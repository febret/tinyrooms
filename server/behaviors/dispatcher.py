"""Behavior event dispatch and atomic intent application."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import inspect
import json
import logging
import sqlite3
import time

from server.behaviors.context import BehaviorContext, CardView
from server.behaviors.events import BehaviorEvent, PeepRef, PropRef
from server.behaviors.intents import BehaviorIntentMixin, BehaviorResult
from server.behaviors.loader import BehaviorAttachment, BehaviorScripts
from server.content.cards import CardCatalog
from server.content.levels import DEFAULT_MAX_EQUIPPED
from server.content.worlds import WorldDefinition
from server.profiles import ProfileRepository
from server.protocol import peep_enter_event, peep_leave_event
from server.security import utc_now
from server.services.sprite_rooms import SpriteService
from server.state.migrations import DatabaseHub, read_behavior_state
from server.state.npc_peep_states import NpcPeepStateRepository


SLOW_HANDLER_SECONDS = 0.25


class BehaviorDispatcher(BehaviorIntentMixin):
    """Selects scripts, runs handlers, and applies their intents atomically."""

    def __init__(
        self,
        *,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        stats: object,
        progression: object,
        activities: object,
        cutscenes: object | None = None,
        catalog: CardCatalog,
        dialogs: object,
        connections: object,
        scripts: BehaviorScripts,
        world: WorldDefinition,
        tasks: object | None = None,
        environment: object | None = None,
        peep_states: NpcPeepStateRepository | None = None,
        sprites: SpriteService | None = None,
        equipped_caps: dict[int, int] | None = None,
        loader: object | None = None,
        powers: object | None = None,
        vibes: object | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._stats = stats
        self._progression = progression
        self._activities = activities
        self._cutscenes = cutscenes
        self._catalog = catalog
        self._dialogs = dialogs
        self._connections = connections
        self._scripts = scripts
        self._world = world
        self._tasks = tasks
        self._environment = environment
        self._peep_states = peep_states
        self._sprites = sprites
        self._equipped_caps = equipped_caps or {}
        self._loader = loader
        self._powers = powers
        self._vibes = vibes
        self._logger = logger or logging.getLogger("tinyrooms.behaviors")
        self.erroring: set[str] = set()
        self._lock: asyncio.Lock | None = None
        self._world_view_cache: dict[str, object] = self._build_world_view()
        self._room_view_cache: dict[str, dict[str, object]] = {}

    def _log(self, event: str, **fields: object) -> None:
        self._logger.info(json.dumps({"event": event, **fields}, separators=(",", ":"), default=str))

    def register_peep(self, peep_id: str, script_path) -> None:
        """Attach a shared behavior script to a runtime-registered NPC peep.

        Used by mods that materialize NPCs after world load (for example, the
        classrooms mod's generated students). The script is imported through the
        loader used at startup so module identity stays stable.
        """

        loader = self._loader
        if loader is None or not hasattr(loader, "import_script"):
            raise RuntimeError("Runtime peep registration requires a behavior loader.")
        script = loader.import_script(script_path)
        self._scripts.scripts[script.script_id] = script
        self._scripts.peep_attachments[peep_id] = BehaviorAttachment(
            script_id=script.script_id,
            namespace="peep",
            instance_id=peep_id,
            ref=PeepRef(kind="npc", peep_id=peep_id, account_id=None),
        )

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

    def _record_task_event(self, event: BehaviorEvent, result: BehaviorResult) -> None:
        if self._tasks is None:
            return
        account_id = event.actor.account_id
        if not account_id:
            return
        mapping = self._event_task_trigger(event)
        if mapping is None:
            return
        trigger, fields = mapping
        changes = self._tasks.record(account_id, trigger, fields)
        if not changes:
            return
        self._emit_task_update(account_id, result)
        result.private_events.extend(self._tasks.feedback_events(account_id, changes, room_id=event.room_id or ""))

    def _current_peep_room(self, peep_id: str) -> str | None:
        if self._peep_states is not None:
            current = self._peep_states.room_for(peep_id)
            if current in self._world.rooms:
                return current
        peep = self._world.peeps.get(peep_id)
        return peep.room_id if peep is not None else None

    def _room_attachments_for(self, room_id: str) -> list[BehaviorAttachment]:
        attachments = [
            attachment
            for attachment in self._scripts.room_attachments.get(room_id, ())
            if attachment.namespace != "peep"
        ]
        seen = {(attachment.script_id, attachment.instance_id) for attachment in attachments}
        for attachment in self._scripts.peep_attachments.values():
            identity = (attachment.script_id, attachment.instance_id)
            if identity in seen or self._current_peep_room(attachment.instance_id) != room_id:
                continue
            attachments.append(attachment)
        return attachments

    def _attachments_for(self, event: BehaviorEvent) -> list[BehaviorAttachment]:
        if event.type in {"tick", "enter", "leave"}:
            return self._room_attachments_for(event.room_id or "")
        if event.type in {"quick_action", "card_play"}:
            target = event.target
            if isinstance(target, PeepRef) and target.peep_id:
                attachment = self._scripts.peep_attachments.get(target.peep_id)
                if attachment is not None:
                    return [attachment]
                if event.type == "card_play":
                    room = self._world.rooms.get(event.room_id or "")
                    if room is not None and room.game is not None:
                        # Game-room NPCs (for example paintbots) have no script
                        # of their own; the room controller owns card resolution.
                        return self._room_attachments_for(event.room_id or "")
                return []
            if isinstance(target, PeepRef) and event.type == "card_play":
                # A card used on another user has no peep attachment, so every
                # script in the room observes it (only those with on_card_play
                # react). This is how world games resolve user-targeted cards.
                return self._room_attachments_for(event.room_id or "")
            if isinstance(target, PropRef):
                attachment = self._scripts.prop_attachments.get(target.instance_id)
                return [attachment] if attachment is not None else []
            if event.type == "card_play" and target is None:
                # A card used with no target is a room-level action: every script
                # in the room observes it (for example, each student reacts).
                return self._room_attachments_for(event.room_id or "")
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

    def _actor_view(self, event: BehaviorEvent) -> dict[str, object]:
        """Return the acting user's statuses, counters, and inventory for scripts."""

        empty: dict[str, object] = {
            "statuses": (),
            "counters": {},
            "card_ids": (),
            "equipped_ids": (),
            "username": "",
            "bops": 0,
            "powers": frozenset(),
        }
        account_id = event.actor.account_id if event.actor.kind == "user" else None
        if not account_id:
            return empty
        try:
            payload = self._stats.view(account_id).payload()
        except Exception as exc:  # noqa: BLE001 - a status read must not break the room loop
            self._log("behavior.status.error", error=str(exc))
            return empty
        try:
            stacks = self._profiles.list_inventory(account_id, self._world.id)
        except Exception as exc:  # noqa: BLE001 - an inventory read must not break the room loop
            self._log("behavior.inventory.error", error=str(exc))
            stacks = []
        account = self._profiles.get_account_by_id(account_id)
        powers: frozenset[str] = frozenset()
        if self._powers is not None and account is not None:
            try:
                powers = frozenset(self._powers.effective(account))
            except Exception as exc:  # noqa: BLE001 - a power read must not break the room loop
                self._log("behavior.powers.error", error=str(exc))
        return {
            "statuses": tuple(payload.get("statuses") or ()),
            "counters": payload,
            "card_ids": tuple(stack.card_def_id for stack in stacks),
            "equipped_ids": tuple(stack.card_def_id for stack in stacks if stack.equipped),
            "username": account.username_display if account is not None else "",
            "bops": account.bops if account is not None else 0,
            "powers": powers,
        }

    def _card_view(self, event: BehaviorEvent) -> CardView | None:
        """Return a read-only view of the card that triggered *event*, if any."""

        card_id = event.data.get("card_id")
        if not isinstance(card_id, str) or not card_id:
            return None
        definition = self._catalog.cards.get(card_id)
        if definition is None:
            return None
        return CardView(
            id=definition.id,
            tags=definition.tags,
            consume_card=definition.consume_card,
            quality=definition.quality,
        )

    def _load_state(self, namespace: str, instance_id: str) -> dict[str, object]:
        with self._hub.locked() as connection:
            return read_behavior_state(connection, namespace, instance_id) or {}

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
        static = self._room_view_cache.get(key)
        room = self._world.rooms.get(key)
        if static is None:
            if room is None:
                static = {
                    "id": room_id,
                    "label": "",
                    "sprites_enabled": False,
                    "game": None,
                    "props": [],
                    "peeps": [],
                    "exits": [],
                }
            else:
                static = {
                    "id": room.id,
                    "label": room.label,
                    "sprites_enabled": room.sprites_enabled,
                    "game": None if room.game is None else {
                        "kind": room.game.kind,
                        "controller": room.game.controller,
                        "renderer": room.game.renderer,
                        "config": dict(room.game.config),
                        "reset_powers": list(room.game.reset_powers),
                        "assets": sorted(room.game.assets),
                        "models": {name: model.prop_id for name, model in room.game.models.items()},
                        "effect_sets": sorted(room.game.effect_sets),
                    },
                    "props": [
                        {
                            "id": prop.id,
                            "prop_id": prop.prop_id,
                            "behavior": prop.behavior,
                            "label": self._world.props[prop.prop_id].label,
                        }
                        for prop in room.props.values()
                    ],
                    "peeps": [],
                    "exits": [
                        {
                            "id": exit_definition.id,
                            "label": exit_definition.label,
                            "target_room_id": exit_definition.target_room_id,
                            "locked": exit_definition.locked,
                            "npc_barrier": exit_definition.npc_barrier,
                            "requires_card_id": exit_definition.requires_card_id,
                        }
                        for exit_definition in room.exits.values()
                    ],
                }
            self._room_view_cache[key] = static
        return {**static, "peeps": self._peeps_in_view(key)}

    def _peeps_in_view(self, room_id: str) -> list[dict[str, object]]:
        """Return lightweight NPC references for a room, including absent states."""

        peeps: list[dict[str, object]] = []
        for peep in self._world.peeps.values():
            if self._current_peep_room(peep.id) != room_id:
                continue
            position = self._sprites.ensure_npc(peep.id, room_id) if self._sprites is not None else None
            peeps.append(
                {
                    "id": peep.id,
                    "label": peep.label,
                    "position": [float(position[0]), float(position[1])] if position is not None else None,
                }
            )
        return peeps

    async def _room_users_view(self, room_id: str) -> list[dict[str, object]]:
        """Return live user occupants with sprite positions and effective stats.

        Scripts call this for server-authoritative positional rules (for example
        a raycast). It is only built on demand so idle ticks stay cheap.
        """

        if self._connections is None:
            return []
        members = await self._connections.list_room(room_id)
        account_ids = [member.account_id for member in members]
        if not account_ids:
            return []
        try:
            snapshots = self._stats.views(account_ids)
        except Exception as exc:  # noqa: BLE001 - a read must not break the room loop
            self._log("behavior.room_users.error", error=str(exc))
            return []
        users: list[dict[str, object]] = []
        for account_id in account_ids:
            account = self._profiles.get_account_by_id(account_id)
            snapshot = snapshots.get(account_id)
            if account is None or snapshot is None:
                continue
            position = None
            if self._sprites is not None:
                stored = self._sprites.ensure_user(account_id, room_id)
                if stored is not None:
                    position = [float(stored[0]), float(stored[1])]
            users.append(
                {
                    "id": account.id,
                    "name": account.username_display,
                    "position": position,
                    "dexterity": snapshot.effective.stat("dexterity"),
                    "health": snapshot.health,
                    "cleanliness": snapshot.cleanliness,
                    "max_cleanliness": snapshot.effective.max_cleanliness,
                }
            )
        return users

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
        if (
            self._environment is not None
            and event.actor.kind == "user"
            and event.type in {"quick_action", "card_play"}
            and isinstance(event.target, PropRef)
        ):
            self._environment.require_prop_target(
                event.target.room_id, event.target.instance_id, event.target.prop_id
            )
        self._record_task_event(event, result)
        contexts: list[tuple[BehaviorAttachment, BehaviorContext]] = []
        actor_view: dict[str, object] | None = None
        for attachment in self._attachments_for(event):
            script = self._scripts.scripts.get(attachment.script_id)
            if script is None:
                continue
            handler = getattr(script.module, f"on_{event.type}", None)
            if handler is None:
                continue
            if actor_view is None:
                actor_view = self._actor_view(event)
            # A user-targeted card play routes to room scripts; keep the user as
            # the script's target instead of the attachment's own prop ref.
            user_target = (
                event.target
                if event.type == "card_play"
                and isinstance(event.target, PeepRef)
                and event.target.kind == "user"
                else None
            )
            source_id = (
                attachment.ref.peep_id
                if isinstance(attachment.ref, PeepRef) and attachment.ref.peep_id
                else event.actor.account_id
            )
            vibe_toward = (
                (lambda target, source=source_id: self._vibes.get(source, target))
                if source_id and self._vibes is not None
                else None
            )
            context = BehaviorContext(
                event=event,
                actor=event.actor,
                target=user_target if user_target is not None else (attachment.ref if attachment.ref is not None else event.target),
                room=self._room_view(event.room_id),
                world=self._world_view(),
                state=self._load_state(attachment.namespace, attachment.instance_id),
                now=utc_now(),
                statuses=actor_view["statuses"],
                counters=actor_view["counters"],
                card_ids=actor_view["card_ids"],
                equipped_ids=actor_view["equipped_ids"],
                environment=self._environment,
                actor_username=str(actor_view.get("username") or ""),
                card=self._card_view(event),
                peeps_in=self._peeps_in_view,
                room_users=self._room_users_view,
                bops=int(actor_view.get("bops") or 0),
                powers=actor_view.get("powers") or frozenset(),
                vibe_toward=vibe_toward,
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
        result.acted = any(context.intents for _, context in contexts) and not result.rejected
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
