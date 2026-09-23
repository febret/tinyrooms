"""Behavior event dispatch and atomic intent application."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, time as datetime_time, timedelta
import inspect
import json
import logging
import sqlite3
import time

from server.behaviors.context import BehaviorContext, Intent
from server.behaviors.events import BehaviorEvent, PeepRef, PropRef
from server.behaviors.loader import BehaviorAttachment, BehaviorScripts
from server.commands.outcomes import PendingRoomBroadcast
from server.content.cards import CardCatalog
from server.content.worlds import WorldDefinition
from server.game.buffs import BuffInstance, DAILY, TIMED
from server.game.buffs import apply_buff as apply_buff_instances
from server.profiles import ProfileRepository
from server.security import utc_now
from server.services.cards import grant_card_to_inventory
from server.state.migrations import DatabaseHub


SLOW_HANDLER_SECONDS = 0.25


@dataclass(slots=True)
class BehaviorResult:
    """Outcome of dispatching one behavior event."""

    messages: list[str] = field(default_factory=list)
    private_events: list[dict[str, object]] = field(default_factory=list)
    room_broadcasts: list[PendingRoomBroadcast] = field(default_factory=list)
    rejected: bool = False


class BehaviorDispatcher:
    """Selects scripts, runs handlers, and applies their intents atomically."""

    def __init__(
        self,
        *,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        stats: object,
        progression: object,
        activities: object,
        catalog: CardCatalog,
        dialogs: object,
        connections: object,
        scripts: BehaviorScripts,
        world: WorldDefinition,
        tasks: object | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._stats = stats
        self._progression = progression
        self._activities = activities
        self._catalog = catalog
        self._dialogs = dialogs
        self._connections = connections
        self._scripts = scripts
        self._world = world
        self._tasks = tasks
        self._logger = logger or logging.getLogger("tinyrooms.behaviors")
        self.erroring: set[str] = set()
        self._lock: asyncio.Lock | None = None
        self._world_view_cache: dict[str, object] = self._build_world_view()
        self._room_view_cache: dict[str, dict[str, object]] = {}

    def _log(self, event: str, **fields: object) -> None:
        self._logger.info(json.dumps({"event": event, **fields}, separators=(",", ":"), default=str))

    def _event_task_trigger(self, event: BehaviorEvent) -> tuple[str, dict[str, object]] | None:
        if event.type == "enter":
            return "enter_room", {
                "room_id": event.room_id or "",
                "source_room_id": event.data.get("source_room_id") or "",
            }
        if event.type in {"card_play", "dialog_action", "activity_result"}:
            return event.type, dict(event.data)
        if event.type == "quick_action" and isinstance(event.target, PropRef):
            return "prop_action", {
                "prop_id": event.target.prop_id,
                "instance_id": event.target.instance_id,
                "room_id": event.room_id or "",
                "action": event.action or "",
            }
        return None

    def _record_task_event(self, event: BehaviorEvent) -> None:
        if self._tasks is None:
            return
        account_id = event.actor.account_id
        if not account_id:
            return
        mapping = self._event_task_trigger(event)
        if mapping is None:
            return
        trigger, fields = mapping
        try:
            self._tasks.record(account_id, trigger, fields)
        except Exception as exc:  # noqa: BLE001 - task recording must never break rooms
            self._log("behavior.task.error", event_type=event.type, error=str(exc))

    def _attachments_for(self, event: BehaviorEvent) -> list[BehaviorAttachment]:
        if event.type in {"tick", "enter", "leave"}:
            return list(self._scripts.room_attachments.get(event.room_id or "", ()))
        if event.type in {"quick_action", "card_play"}:
            target = event.target
            if isinstance(target, PeepRef) and target.peep_id:
                attachment = self._scripts.peep_attachments.get(target.peep_id)
                return [attachment] if attachment is not None else []
            if isinstance(target, PropRef):
                attachment = self._scripts.prop_attachments.get(target.instance_id)
                return [attachment] if attachment is not None else []
            return []
        if event.type == "dialog_action":
            attachments: list[BehaviorAttachment] = []
            seen: set[str] = set()
            peep_id = event.data.get("peep_id")
            if isinstance(peep_id, str) and peep_id in self._scripts.peep_attachments:
                attachment = self._scripts.peep_attachments[peep_id]
                attachments.append(attachment)
                seen.add(attachment.script_id)
            for script_id, script in self._scripts.scripts.items():
                if script_id not in seen and hasattr(script.module, "on_dialog_action"):
                    attachments.append(BehaviorAttachment(script_id=script_id, namespace="script", instance_id=script_id, ref=None))
            return attachments
        if event.type == "activity_result":
            return [
                BehaviorAttachment(script_id=script_id, namespace="script", instance_id=script_id, ref=None)
                for script_id, script in self._scripts.scripts.items()
                if hasattr(script.module, "on_activity_result")
            ]
        return []

    def _load_state(self, namespace: str, instance_id: str) -> dict[str, object]:
        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT state_json FROM world.behavior_state WHERE namespace = ? AND instance_id = ?",
                (namespace, instance_id),
            ).fetchone()
        if row is None:
            return {}
        try:
            raw = json.loads(row["state_json"])
        except (TypeError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save_state(self, connection: sqlite3.Connection, attachment: BehaviorAttachment, state: dict[str, object]) -> None:
        connection.execute(
            """
            INSERT INTO world.behavior_state (namespace, instance_id, state_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace, instance_id) DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at
            """,
            (attachment.namespace, attachment.instance_id, json.dumps(state), utc_now().isoformat()),
        )

    def _room_view(self, room_id: str | None) -> dict[str, object]:
        key = room_id or ""
        cached = self._room_view_cache.get(key)
        if cached is not None:
            return cached
        room = self._world.rooms.get(key)
        if room is None:
            view: dict[str, object] = {"id": room_id, "label": "", "props": [], "peeps": [], "exits": []}
        else:
            view = {
                "id": room.id,
                "label": room.label,
                "props": [
                    {
                        "id": prop.id,
                        "prop_id": prop.prop_id,
                        "behavior": prop.behavior,
                        "label": self._world.props[prop.prop_id].label,
                    }
                    for prop in room.props.values()
                ],
                "peeps": [
                    {"id": peep.id, "label": peep.label}
                    for peep in self._world.peeps.values()
                    if peep.room_id == room.id
                ],
                "exits": [
                    {"id": exit_definition.id, "label": exit_definition.label, "target_room_id": exit_definition.target_room_id}
                    for exit_definition in room.exits.values()
                ],
            }
        self._room_view_cache[key] = view
        return view

    def _build_world_view(self) -> dict[str, object]:
        return {"id": self._world.id, "label": self._world.label}

    def _world_view(self) -> dict[str, object]:
        return self._world_view_cache

    def _account_for(self, payload: Mapping[str, object], context: BehaviorContext) -> str | None:
        account_id = payload.get("target_account_id")
        if isinstance(account_id, str) and account_id:
            return account_id
        if context.actor.kind == "user":
            return context.actor.account_id
        return None

    async def dispatch(self, event: BehaviorEvent, *, extra: Mapping[str, object] | None = None) -> BehaviorResult:
        """Deliver *event* to its scripts and apply the resulting intents.

        Dispatches are serialized so a handler that awaits can never interleave
        with another event mutating the same per-instance behavior state.
        """

        del extra
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            return await self._dispatch(event)

    async def _dispatch(self, event: BehaviorEvent) -> BehaviorResult:
        result = BehaviorResult()
        self._record_task_event(event)
        contexts: list[tuple[BehaviorAttachment, BehaviorContext]] = []
        for attachment in self._attachments_for(event):
            script = self._scripts.scripts.get(attachment.script_id)
            if script is None:
                continue
            handler = getattr(script.module, f"on_{event.type}", None)
            if handler is None:
                continue
            context = BehaviorContext(
                event=event,
                actor=event.actor,
                target=attachment.ref if attachment.ref is not None else event.target,
                room=self._room_view(event.room_id),
                world=self._world_view(),
                state=self._load_state(attachment.namespace, attachment.instance_id),
                now=utc_now(),
            )
            contexts.append((attachment, context))
            try:
                started = time.perf_counter()
                outcome = handler(context, event)
                if inspect.isawaitable(outcome):
                    await outcome
                elapsed = time.perf_counter() - started
                if elapsed > SLOW_HANDLER_SECONDS:
                    self._log("behavior.slow", script=attachment.script_id, event_type=event.type, duration_ms=round(elapsed * 1000, 2))
            except Exception as exc:  # noqa: BLE001 - one script must never break the room loop
                self.erroring.add(attachment.script_id)
                self._log("behavior.error", script=attachment.script_id, event_type=event.type, error=str(exc))
                return BehaviorResult(rejected=True)
        if not contexts:
            return result
        try:
            await self._apply(contexts, event, result)
        except Exception as exc:  # noqa: BLE001 - intent application failures roll back cleanly
            self._log("behavior.error", script="intents", event_type=event.type, error=str(exc))
            return BehaviorResult(rejected=True)
        return result

    async def _apply(
        self,
        contexts: list[tuple[BehaviorAttachment, BehaviorContext]],
        event: BehaviorEvent,
        result: BehaviorResult,
    ) -> None:
        deferred: list[object] = []
        with self._hub.transaction() as connection:
            for attachment, context in contexts:
                for intent in context.intents:
                    self._apply_intent(connection, intent, context, event, result, deferred)
                self._save_state(connection, attachment, context.state)
        for operation in deferred:
            outcome = operation()
            if inspect.isawaitable(outcome):
                await outcome

    def _apply_intent(
        self,
        connection: sqlite3.Connection,
        intent: Intent,
        context: BehaviorContext,
        event: BehaviorEvent,
        result: BehaviorResult,
        deferred: list[object],
    ) -> None:
        kind = intent.kind
        payload = intent.payload
        if kind == "feedback":
            self._apply_feedback(payload, result)
        elif kind == "effect":
            self._apply_effect(payload, context, event, result)
        elif kind == "apply_counter":
            self._apply_counter(connection, payload, context, event, result)
        elif kind == "apply_buff":
            self._apply_buff(connection, payload, context)
        elif kind == "grant":
            self._apply_grant(connection, payload, context)
        elif kind == "give_card":
            self._apply_give_card(connection, payload, context)
        elif kind == "start_dialog":
            self._apply_start_dialog(connection, payload, context, result)
        elif kind == "end_dialog":
            self._apply_end_dialog(connection, context, result)
        elif kind == "start_activity":
            self._apply_start_activity(payload, context, event, result)
        elif kind in {"start_task", "update_task_progress"}:
            self._apply_task_intent(kind, payload, context, result, deferred)
        elif kind == "request_move":
            self._apply_request_move(connection, payload, context, deferred)
        elif kind == "set_environment":
            self._apply_set_environment(connection, payload)
        else:
            self._log("behavior.intent.unknown", kind=kind)

    def _apply_feedback(self, payload: Mapping[str, object], result: BehaviorResult) -> None:
        text = str(payload.get("text", ""))
        style = str(payload.get("style", "toast"))
        tone = style if style in {"info", "success", "error"} else "info"
        event: dict[str, object] = {"type": "toast", "tone": tone, "text": text}
        account_id = payload.get("target_account_id")
        if isinstance(account_id, str) and account_id:
            event["account_id"] = account_id
        result.private_events.append(event)
        if text:
            result.messages.append(text)

    def _apply_effect(
        self,
        payload: Mapping[str, object],
        context: BehaviorContext,
        event: BehaviorEvent,
        result: BehaviorResult,
    ) -> None:
        if event.room_id is None:
            return
        result.room_broadcasts.append(
            PendingRoomBroadcast(
                room_id=event.room_id,
                event={
                    "type": "effect.queued",
                    "room_id": event.room_id,
                    "effect": str(payload.get("effect_id", "")),
                    "source_id": context.actor.account_id,
                },
            )
        )

    def _apply_counter(
        self,
        connection: sqlite3.Connection,
        payload: Mapping[str, object],
        context: BehaviorContext,
        event: BehaviorEvent,
        result: BehaviorResult,
    ) -> None:
        account_id = self._account_for(payload, context)
        if account_id is None:
            self._log("behavior.intent.skipped", kind="apply_counter", reason="no_account")
            return
        counter = str(payload.get("counter", ""))
        delta = float(payload.get("delta", 0.0))
        kwargs = {
            "health": {"health_delta": delta},
            "cleanliness": {"cleanliness_delta": delta},
            "energy": {"energy_delta": delta},
        }.get(counter)
        if kwargs is None:
            self._log("behavior.intent.skipped", kind="apply_counter", reason="unknown_counter", counter=counter)
            return
        snapshot = self._stats.apply_in_transaction(connection, account_id, **kwargs)
        if event.room_id is not None:
            account = self._profiles.get_account_by_id(account_id)
            result.room_broadcasts.append(
                PendingRoomBroadcast(
                    room_id=event.room_id,
                    event={
                        "type": "counter.updated",
                        "room_id": event.room_id,
                        "target_id": account_id,
                        "target_label": account.username_display if account else "",
                        "health_delta": delta if counter == "health" else 0,
                        "energy_delta": delta if counter == "energy" else 0,
                        "health": snapshot.health,
                        "energy": snapshot.energy,
                        "max_health": snapshot.effective.max_health,
                        "max_energy": snapshot.effective.max_energy,
                        "statuses": list(snapshot.statuses),
                        "source_id": context.actor.account_id,
                    },
                )
            )

    def _apply_buff(self, connection: sqlite3.Connection, payload: Mapping[str, object], context: BehaviorContext) -> None:
        account_id = self._account_for(payload, context)
        if account_id is None:
            self._log("behavior.intent.skipped", kind="apply_buff", reason="no_account")
            return
        profile = self._profiles.get_user_profile(account_id)
        if profile is None:
            return
        raw = profile.buffs.get("instances") if isinstance(profile.buffs, dict) else None
        instances: list[BuffInstance] = []
        for entry in raw or []:
            if isinstance(entry, dict) and entry.get("expires_at"):
                try:
                    instances.append(BuffInstance.from_payload(entry))
                except (KeyError, ValueError):
                    continue
        now = context.now
        duration_seconds = payload.get("duration_seconds")
        if bool(payload.get("daily")):
            expires = datetime.combine((now + timedelta(days=1)).date(), datetime_time.min, tzinfo=now.tzinfo)
        elif duration_seconds is not None:
            expires = now + timedelta(seconds=float(duration_seconds))
        else:
            expires = now
        incoming = BuffInstance(
            id=str(payload.get("buff_id", "")),
            label=str(payload.get("buff_id", "")),
            kind=DAILY if bool(payload.get("daily")) else TIMED,
            expires_at=expires,
        )
        updated = apply_buff_instances(instances, incoming, now)
        self._profiles.write_buffs(connection, account_id, [item.to_payload() for item in updated])

    def _apply_grant(self, connection: sqlite3.Connection, payload: Mapping[str, object], context: BehaviorContext) -> None:
        account_id = self._account_for(payload, context)
        if account_id is None:
            self._log("behavior.intent.skipped", kind="grant", reason="no_account")
            return
        raw_key = payload.get("ledger_key")
        ledger_key = str(raw_key) if isinstance(raw_key, str) and raw_key else None
        cards = payload.get("cards") or []
        self._progression.grant_in_transaction(
            connection,
            account_id,
            kudos=int(payload.get("kudos", 0) or 0),
            cards=tuple(str(card_id) for card_id in cards) if isinstance(cards, list) else (),
            ledger_key=ledger_key,
            kind="behavior",
        )

    def _apply_give_card(self, connection: sqlite3.Connection, payload: Mapping[str, object], context: BehaviorContext) -> None:
        account_id = self._account_for(payload, context)
        if account_id is None:
            self._log("behavior.intent.skipped", kind="give_card", reason="no_account")
            return
        card_id = str(payload.get("card_id", ""))
        definition = self._catalog.cards.get(card_id)
        if definition is None:
            self._log("behavior.intent.skipped", kind="give_card", reason="unknown_card", card_id=card_id)
            return
        quantity = max(0, int(payload.get("quantity", 1) or 0))
        for _ in range(quantity):
            grant_card_to_inventory(
                self._profiles,
                connection,
                account_id=account_id,
                definition=definition,
                world_id=self._world.id,
            )

    def _apply_start_dialog(
        self,
        connection: sqlite3.Connection,
        payload: Mapping[str, object],
        context: BehaviorContext,
        result: BehaviorResult,
    ) -> None:
        account_id = context.actor.account_id
        if account_id is None:
            self._log("behavior.intent.skipped", kind="start_dialog", reason="no_account")
            return
        account = self._profiles.get_account_by_id(account_id)
        if account is None:
            return
        peep_id = str(payload.get("peep_id", ""))
        node_id = payload.get("node_id")
        try:
            active = self._dialogs.start_in_transaction(connection, account, peep_id, node_id if isinstance(node_id, str) else None)
        except ValueError as exc:
            self._log("behavior.intent.skipped", kind="start_dialog", error=str(exc))
            return
        result.private_events.append({"type": "dialog.updated", "dialog": self._dialogs.serialize(active), "account_id": account_id})

    def _apply_end_dialog(self, connection: sqlite3.Connection, context: BehaviorContext, result: BehaviorResult) -> None:
        account_id = context.actor.account_id
        if account_id is None:
            return
        self._dialogs.end_in_transaction(connection, account_id)
        result.private_events.append({"type": "dialog.updated", "dialog": None, "account_id": account_id})

    def _apply_start_activity(
        self,
        payload: Mapping[str, object],
        context: BehaviorContext,
        event: BehaviorEvent,
        result: BehaviorResult,
    ) -> None:
        account_id = context.actor.account_id
        if account_id is None:
            self._log("behavior.intent.skipped", kind="start_activity", reason="no_account")
            return
        kind = str(payload.get("kind", ""))
        title = payload.get("title")
        try:
            session, _replaced = self._activities.start(
                account_id=account_id,
                kind=kind,
                title=str(title) if isinstance(title, str) and title else kind.replace("-", " ").title(),
                room_bound=True,
                room_id=event.room_id,
                replace_existing=True,
            )
        except ValueError as exc:
            self._log("behavior.intent.skipped", kind="start_activity", error=str(exc))
            return
        result.private_events.append(
            {"type": "activity.started", "activity": self._activities.serialize(session), "account_id": account_id}
        )

    def _apply_task_intent(
        self,
        kind: str,
        payload: Mapping[str, object],
        context: BehaviorContext,
        result: BehaviorResult,
        deferred: list[object],
    ) -> None:
        account_id = context.actor.account_id
        if account_id is None:
            self._log("behavior.intent.skipped", kind=kind, reason="no_account")
            return
        if self._tasks is None:
            event: dict[str, object] = {
                "type": "task.started" if kind == "start_task" else "task.progress",
                **payload,
            }
            event["account_id"] = account_id
            result.private_events.append(event)
            return
        task_id = str(payload.get("task_id", ""))
        if kind == "start_task":

            def start_operation(target_account: str = account_id, target_task: str = task_id) -> None:
                self._tasks.start(target_account, target_task)
                self._emit_task_update(target_account, result)

            deferred.append(start_operation)
            return
        raw_step = payload.get("step_id")
        step_id = str(raw_step) if isinstance(raw_step, str) and raw_step else None
        amount = max(1, int(payload.get("amount", 1) or 1))

        def advance_operation(
            target_account: str = account_id,
            target_task: str = task_id,
            target_step: str | None = step_id,
            target_amount: int = amount,
        ) -> None:
            self._tasks.advance_step(target_account, target_task, target_step, target_amount)
            self._emit_task_update(target_account, result)

        deferred.append(advance_operation)

    def _emit_task_update(self, account_id: str, result: BehaviorResult) -> None:
        try:
            payload = self._tasks.view_payload(account_id)
        except Exception as exc:  # noqa: BLE001 - a view failure must not break the room loop
            self._log("behavior.task.error", reason="view", error=str(exc))
            return
        result.private_events.append({"type": "task.updated", "tasks": payload, "account_id": account_id})

    def _apply_request_move(
        self,
        connection: sqlite3.Connection,
        payload: Mapping[str, object],
        context: BehaviorContext,
        deferred: list[object],
    ) -> None:
        account_id = context.actor.account_id
        room_id = str(payload.get("room_id", ""))
        if account_id is None or room_id not in self._world.rooms:
            self._log("behavior.intent.skipped", kind="request_move", reason="invalid")
            return
        self._profiles.set_remembered_room(connection, account_id, self._world.id, room_id)
        deferred.append(lambda: self._connections.set_room(account_id, room_id))

    def _apply_set_environment(self, connection: sqlite3.Connection, payload: Mapping[str, object]) -> None:
        instance_id = payload.get("target_instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            self._log("behavior.intent.skipped", kind="set_environment", reason="no_target")
            return
        row = connection.execute(
            "SELECT state_json FROM world.behavior_state WHERE namespace = 'prop' AND instance_id = ?",
            (instance_id,),
        ).fetchone()
        state: dict[str, object] = {}
        if row is not None:
            try:
                loaded = json.loads(row["state_json"])
                if isinstance(loaded, dict):
                    state = loaded
            except (TypeError, ValueError):
                state = {}
        environment = state.get("environment")
        if not isinstance(environment, dict):
            environment = {}
            state["environment"] = environment
        environment[str(payload.get("key", ""))] = payload.get("value")
        self._save_state(
            connection,
            BehaviorAttachment(script_id="environment", namespace="prop", instance_id=instance_id, ref=None),
            state,
        )
