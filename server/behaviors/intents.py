"""Intent application for behavior scripts.

The dispatcher selects and runs scripts; this mixin owns the typed intent
handlers they queue. Keeping the handlers separate keeps the event-routing
module readable while sharing the dispatcher's service dependencies.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, time as datetime_time, timedelta
import sqlite3

from server.behaviors.context import BehaviorContext, Intent
from server.behaviors.events import BehaviorEvent, PeepRef
from server.commands.outcomes import PendingRoomBroadcast
from server.game.buffs import BuffInstance, DAILY, TIMED, apply_buff as apply_buff_instances
from server.game.decals import clear_decals, decals_payload, upsert_decal
from server.security import utc_now
from server.services.cards import auto_equip_new_stacks, grant_card_to_inventory
from server.services.npc_movement import resolve_npc_move


DEFAULT_HIDE_SECONDS = 3600.0


@dataclass(slots=True)
class BehaviorResult:
    """Outcome of dispatching one behavior event."""

    messages: list[str] = field(default_factory=list)
    private_events: list[dict[str, object]] = field(default_factory=list)
    room_broadcasts: list[PendingRoomBroadcast] = field(default_factory=list)
    rejected: bool = False
    inventory_changed_for: str | None = None
    acted: bool = False


class BehaviorIntentMixin:
    """Apply declarative intents queued by trusted behavior scripts."""

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
        elif kind == "room_feedback":
            self._apply_room_feedback(payload, event, result)
        elif kind == "effect":
            self._apply_effect(payload, context, event, result)
        elif kind == "apply_counter":
            self._apply_counter(connection, payload, context, event, result)
        elif kind == "set_counter":
            self._apply_set_counter(connection, payload, context, event, result)
        elif kind == "apply_buff":
            self._apply_buff(connection, payload, context)
        elif kind in {"apply_decal", "clear_decals"}:
            self._apply_decals(
                connection,
                payload,
                context,
                event,
                result,
                active=kind == "apply_decal",
            )
        elif kind == "grant":
            self._apply_grant(connection, payload, context)
        elif kind == "learn_recipes":
            self._apply_learn_recipes(connection, payload, context, result)
        elif kind == "give_card":
            self._apply_give_card(connection, payload, context, result)
        elif kind == "remove_card":
            self._apply_remove_card(connection, payload, context, result)
        elif kind == "purchase_card":
            self._apply_purchase_card(connection, payload, context, result)
        elif kind == "npc_say":
            self._apply_npc_say(payload, context, event, result)
        elif kind == "start_dialog":
            self._apply_start_dialog(connection, payload, context, result)
        elif kind == "end_dialog":
            self._apply_end_dialog(connection, context, result)
        elif kind == "start_activity":
            self._apply_start_activity(payload, context, event, result)
        elif kind == "cutscene":
            self._apply_cutscene(payload, context, event, result, deferred)
        elif kind in {"start_task", "update_task_progress"}:
            self._apply_task_intent(kind, payload, context, result, deferred)
        elif kind == "request_move":
            self._apply_request_move(connection, payload, context, deferred)
        elif kind == "move_through":
            self._apply_move_through(connection, payload, context, result, deferred)
        elif kind == "move_sprite":
            self._apply_move_sprite(payload, context, event, result, random_position=False)
        elif kind == "move_sprite_random":
            self._apply_move_sprite(payload, context, event, result, random_position=True)
        elif kind == "move_peep_sprite":
            self._apply_move_peep_sprite(payload, event, result)
        elif kind == "move_peep":
            self._apply_move_peep(connection, payload, context, result, deferred)
        elif kind == "set_environment":
            self._apply_set_environment(connection, payload, context, event, result)
        elif kind == "hide_prop":
            self._apply_hide_prop(connection, payload, context, event, result)
        elif kind == "clear_source":
            self._apply_clear_source(payload, event, deferred)
        elif kind == "set_game_state":
            self._apply_game_state(payload, event, result)
        else:
            self._log("behavior.intent.unknown", kind=kind)

    def _apply_cutscene(
        self,
        payload: Mapping[str, object],
        context: BehaviorContext,
        event: BehaviorEvent,
        result: BehaviorResult,
        deferred: list[object],
    ) -> None:
        cutscenes = self._cutscenes
        if cutscenes is None or event.room_id is None:
            self._log("behavior.intent.skipped", kind="cutscene", reason="unavailable")
            return
        account_id = context.actor.account_id
        if account_id is None:
            # A system tick can still announce a room-wide scene. Defer the
            # lookup of a present source account until after the transaction.
            async def launch_for_room() -> None:
                occupants: list[object] = []
                if self._connections is not None:
                    occupants = await self._connections.list_room(event.room_id or "")
                if not occupants:
                    self._log("behavior.intent.skipped", kind="cutscene", reason="empty_room")
                    return
                source_id = getattr(occupants[0], "account_id", None)
                account = self._profiles.get_account_by_id(source_id) if source_id else None
                if account is None:
                    self._log("behavior.intent.skipped", kind="cutscene", reason="no_source_account")
                    return
                self._deliver_cutscene(
                    payload,
                    event,
                    result,
                    account,
                    occupants=[getattr(member, "account_id", "") for member in occupants],
                )

            deferred.append(launch_for_room)
            return
        account = self._profiles.get_account_by_id(account_id)
        if account is None:
            self._log("behavior.intent.skipped", kind="cutscene", reason="no_account")
            return
        self._deliver_cutscene(payload, event, result, account)

    def _deliver_cutscene(
        self,
        payload: Mapping[str, object],
        event: BehaviorEvent,
        result: BehaviorResult,
        account: object,
        *,
        occupants: list[str] | None = None,
    ) -> None:
        cutscenes = self._cutscenes
        if cutscenes is None or event.room_id is None:
            return
        cutscene_id = str(payload.get("cutscene_id", ""))
        try:
            definition = cutscenes.resolve(cutscene_id)
            audience = cutscenes.choose_audience(definition, payload.get("audience"))
            launch = cutscenes.launch(
                definition=definition,
                account=account,
                room_id=event.room_id,
                audience=audience,
                origin="behavior",
                params=payload.get("params") if isinstance(payload.get("params"), dict) else None,
                occupants=occupants,
            )
        except Exception as exc:  # noqa: BLE001 - one bad script must not break the room
            self._log("behavior.intent.skipped", kind="cutscene", error=str(exc))
            return
        if launch.is_room_wide:
            result.room_broadcasts.append(PendingRoomBroadcast(room_id=event.room_id, event=launch.event))
        else:
            result.private_events.append(launch.event)
        result.messages.append(f"{launch.definition.title} played.")

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

    def _apply_room_feedback(
        self,
        payload: Mapping[str, object],
        event: BehaviorEvent,
        result: BehaviorResult,
    ) -> None:
        if event.room_id is None:
            return
        text = str(payload.get("text", ""))
        if not text:
            return
        tone = str(payload.get("style", "info"))
        if tone not in {"info", "success", "error"}:
            tone = "info"
        result.room_broadcasts.append(
            PendingRoomBroadcast(
                room_id=event.room_id,
                event={"type": "toast", "room_id": event.room_id, "tone": tone, "text": text},
            )
        )
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

    def _apply_game_state(
        self,
        payload: Mapping[str, object],
        event: BehaviorEvent,
        result: BehaviorResult,
    ) -> None:
        if event.room_id is None:
            return
        state = payload.get("state")
        if not isinstance(state, dict):
            self._log("behavior.intent.skipped", kind="set_game_state", reason="invalid_state")
            return
        result.room_broadcasts.append(
            PendingRoomBroadcast(
                room_id=event.room_id,
                event={"type": "room.board.state", "room_id": event.room_id, "state": state},
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
                        "cleanliness_delta": delta if counter == "cleanliness" else 0,
                        "health": snapshot.health,
                        "energy": snapshot.energy,
                        "cleanliness": snapshot.cleanliness,
                        "max_health": snapshot.effective.max_health,
                        "max_energy": snapshot.effective.max_energy,
                        "max_cleanliness": snapshot.effective.max_cleanliness,
                        "statuses": list(snapshot.statuses),
                        "decals": decals_payload(list(snapshot.decals)),
                        "source_id": context.actor.account_id,
                    },
                )
            )

    def _apply_set_counter(
        self,
        connection: sqlite3.Connection,
        payload: Mapping[str, object],
        context: BehaviorContext,
        event: BehaviorEvent,
        result: BehaviorResult,
    ) -> None:
        account_id = self._account_for(payload, context)
        if account_id is None:
            self._log("behavior.intent.skipped", kind="set_counter", reason="no_account")
            return
        counter = str(payload.get("counter", ""))
        snapshot = self._stats.reconcile_in_transaction(connection, account_id)
        current = getattr(snapshot, counter, None)
        if current is None:
            self._log("behavior.intent.skipped", kind="set_counter", reason="unknown_counter", counter=counter)
            return
        delta = float(payload.get("value", 0.0)) - float(current)
        kwargs = {
            "health": {"health_delta": delta},
            "cleanliness": {"cleanliness_delta": delta},
            "energy": {"energy_delta": delta},
        }.get(counter)
        if kwargs is None:
            return
        updated = self._stats.apply_in_transaction(connection, account_id, **kwargs)
        if event.room_id is None:
            return
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
                    "cleanliness_delta": delta if counter == "cleanliness" else 0,
                    "health": updated.health,
                    "energy": updated.energy,
                    "cleanliness": updated.cleanliness,
                    "max_health": updated.effective.max_health,
                    "max_energy": updated.effective.max_energy,
                    "max_cleanliness": updated.effective.max_cleanliness,
                    "statuses": list(updated.statuses),
                    "decals": decals_payload(list(updated.decals)),
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

    def _apply_decals(
        self,
        connection: sqlite3.Connection,
        payload: Mapping[str, object],
        context: BehaviorContext,
        event: BehaviorEvent,
        result: BehaviorResult,
        *,
        active: bool,
    ) -> None:
        """Attach, update, or clear persistent cosmetic decals on a peep."""

        account_id = self._account_for(payload, context)
        if account_id is None:
            self._log("behavior.intent.skipped", kind="decals", reason="no_account")
            return
        profile = self._profiles.get_user_profile(account_id)
        if profile is None:
            return
        if active:
            decals = upsert_decal(
                list(profile.decals),
                {
                    "id": str(payload.get("decal_id", "")).strip(),
                    "kind": str(payload.get("kind", "")).strip(),
                    "count": payload.get("count", 1),
                    "color": payload.get("color", ""),
                    "data": payload.get("data") if isinstance(payload.get("data"), dict) else {},
                },
            )
        else:
            raw_kind = payload.get("kind")
            decals = clear_decals(
                list(profile.decals),
                kind=str(raw_kind).strip() if raw_kind else None,
            )
        self._profiles.update_profile_in_transaction(
            connection,
            account_id,
            lambda data: data.__setitem__("decals", list(decals)),
        )
        snapshot = self._stats.reconcile_in_transaction(connection, account_id)
        if event.room_id is None:
            return
        account = self._profiles.get_account_by_id(account_id)
        result.room_broadcasts.append(
            PendingRoomBroadcast(
                room_id=event.room_id,
                event={
                    "type": "counter.updated",
                    "room_id": event.room_id,
                    "target_id": account_id,
                    "target_label": account.username_display if account else "",
                    "health": snapshot.health,
                    "energy": snapshot.energy,
                    "cleanliness": snapshot.cleanliness,
                    "max_health": snapshot.effective.max_health,
                    "max_energy": snapshot.effective.max_energy,
                    "max_cleanliness": snapshot.effective.max_cleanliness,
                    "statuses": list(snapshot.statuses),
                    "decals": decals_payload(list(snapshot.decals)),
                    "source_id": context.actor.account_id,
                },
            )
        )

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
            bops=int(payload.get("bops", 0) or 0),
            cards=tuple(str(card_id) for card_id in cards) if isinstance(cards, list) else (),
            ledger_key=ledger_key,
            kind="behavior",
        )

    def _apply_learn_recipes(
        self,
        connection: sqlite3.Connection,
        payload: Mapping[str, object],
        context: BehaviorContext,
        result: BehaviorResult,
    ) -> None:
        account_id = context.actor.account_id
        if not account_id:
            self._log("behavior.intent.skipped", kind="learn_recipes", reason="no_account")
            return
        recipe_ids = {
            str(recipe_id)
            for recipe_id in payload.get("recipe_ids", [])
            if str(recipe_id)
        }
        source = payload.get("source")
        if isinstance(source, str) and source:
            recipe_ids.update(
                recipe.id
                for recipe in self._world.recipes.values()
                if recipe.source == source
            )
        profile = self._profiles.get_user_profile(account_id)
        known = set(profile.known_recipes) if profile is not None else set()
        learned = sorted(recipe_ids - known)
        if not learned:
            result.private_events.append(
                {"type": "toast", "tone": "info", "text": "You already know these recipes."}
            )
            return
        self._profiles.update_profile_in_transaction(
            connection,
            account_id,
            lambda data: data.update(known_recipes=sorted(known | set(learned))),
        )
        result.private_events.append(
            {
                "type": "toast",
                "tone": "success",
                "text": f"Learned {len(learned)} recipes from the cookbook.",
            }
        )

    def _apply_give_card(
        self,
        connection: sqlite3.Connection,
        payload: Mapping[str, object],
        context: BehaviorContext,
        result: BehaviorResult,
    ) -> None:
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
        self._grant_card_quantity(connection, account_id, definition, quantity)
        result.inventory_changed_for = account_id

    def _grant_card_quantity(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        definition: object,
        quantity: int,
    ) -> None:
        """Grant *quantity* copies of a card and auto-equip a new stack."""

        created_stacks: list = []
        for _ in range(max(0, int(quantity))):
            created_stacks.extend(
                grant_card_to_inventory(
                    self._profiles,
                    connection,
                    account_id=account_id,
                    definition=definition,
                    world_id=self._world.id,
                )
            )
        account = self._profiles.get_account_by_id(account_id)
        cap = DEFAULT_MAX_EQUIPPED
        if account is not None:
            cap = self._equipped_caps.get(account.level, DEFAULT_MAX_EQUIPPED)
        auto_equip_new_stacks(
            self._profiles,
            connection,
            account_id=account_id,
            world_id=self._world.id,
            definition=definition,
            created_stacks=created_stacks,
            equipped_cap=cap,
        )

    def _apply_purchase_card(
        self,
        connection: sqlite3.Connection,
        payload: Mapping[str, object],
        context: BehaviorContext,
        result: BehaviorResult,
    ) -> None:
        """Atomically spend Bops and grant a card for a vending script."""

        account_id = self._account_for(payload, context)
        if account_id is None:
            self._log("behavior.intent.skipped", kind="purchase_card", reason="no_account")
            return
        card_id = str(payload.get("card_id", ""))
        definition = self._catalog.cards.get(card_id)
        if definition is None:
            self._log("behavior.intent.skipped", kind="purchase_card", reason="unknown_card", card_id=card_id)
            return
        quantity = max(0, int(payload.get("quantity", 1) or 0))
        cost = max(0, int(payload.get("bops", 0) or 0))
        account = self._profiles.get_account_by_id(account_id)
        if account is None:
            return
        if account.bops < cost:
            result.rejected = True
            self._apply_feedback(
                {
                    "text": f"You need {cost - account.bops} more Bops.",
                    "style": "error",
                    "target_account_id": account_id,
                },
                result,
            )
            return
        if cost:
            self._profiles.update_progress(connection, account, bops=account.bops - cost)
        self._grant_card_quantity(connection, account_id, definition, quantity)
        result.inventory_changed_for = account_id
        self._apply_feedback(
            {
                "text": f"Purchased {card_id.replace('-', ' ')}.",
                "style": "success",
                "target_account_id": account_id,
            },
            result,
        )

    def _apply_npc_say(
        self,
        payload: Mapping[str, object],
        context: BehaviorContext,
        event: BehaviorEvent,
        result: BehaviorResult,
    ) -> None:
        target = context.target
        peep_id = str(payload.get("peep_id") or "")
        if not peep_id and isinstance(target, PeepRef) and target.peep_id:
            peep_id = target.peep_id
        if not peep_id or event.room_id is None:
            return
        text = str(payload.get("text", ""))
        if not text:
            return
        peep = self._world.peeps.get(peep_id)
        result.room_broadcasts.append(
            PendingRoomBroadcast(
                room_id=event.room_id,
                event={
                    "type": "emote.bubble",
                    "room_id": event.room_id,
                    "source_id": peep_id,
                    "source": peep.label if peep is not None else peep_id,
                    "bubble": {"kind": str(payload.get("style", "expression")), "text": text},
                    "card_id": None,
                },
            )
        )

    def _apply_remove_card(
        self,
        connection: sqlite3.Connection,
        payload: Mapping[str, object],
        context: BehaviorContext,
        result: BehaviorResult,
    ) -> None:
        account_id = self._account_for(payload, context)
        if account_id is None:
            self._log("behavior.intent.skipped", kind="remove_card", reason="no_account")
            return
        card_id = str(payload.get("card_id", ""))
        if not card_id:
            return
        raw_quantity = payload.get("quantity")
        if raw_quantity is None:
            self._profiles.remove_inventory_card_in_transaction(
                connection, account_id, self._world.id, card_id
            )
        else:
            self._remove_card_quantity(connection, account_id, card_id, int(raw_quantity))
        result.inventory_changed_for = account_id

    def _remove_card_quantity(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        card_def_id: str,
        quantity: int,
    ) -> None:
        """Remove up to *quantity* copies of one card, equipped stacks first."""

        remaining = max(0, quantity)
        stacks = sorted(
            self._profiles.list_inventory(account_id, self._world.id),
            key=lambda stack: (not stack.equipped, stack.created_at, stack.stack_id),
        )
        for stack in stacks:
            if remaining <= 0:
                break
            if stack.card_def_id != card_def_id:
                continue
            take = min(remaining, stack.quantity)
            self._profiles.remove_inventory_quantity(
                connection,
                account_id=account_id,
                world_id=self._world.id,
                stack_id=stack.stack_id,
                quantity=take,
            )
            remaining -= take

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
        room_id = context.event.room_id or ""
        if kind == "start_task":

            def start_operation(target_account: str = account_id, target_task: str = task_id) -> None:
                changes = self._tasks.start(target_account, target_task)
                self._emit_task_update(target_account, result)
                result.private_events.extend(self._tasks.feedback_events(target_account, changes, room_id=room_id))

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
            changes = self._tasks.advance_step(target_account, target_task, target_step, target_amount)
            self._emit_task_update(target_account, result)
            result.private_events.extend(self._tasks.feedback_events(target_account, changes, room_id=room_id))

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

    def _apply_move_through(
        self,
        connection: sqlite3.Connection,
        payload: Mapping[str, object],
        context: BehaviorContext,
        result: BehaviorResult,
        deferred: list[object],
    ) -> None:
        actor = context.actor
        target = context.target
        if isinstance(target, PeepRef) and target.kind == "npc" and target.peep_id:
            peep_id = target.peep_id
        elif actor.kind == "npc" and actor.peep_id:
            peep_id = actor.peep_id
        else:
            self._log("behavior.intent.skipped", kind="move_through", reason="not_npc")
            return
        if self._peep_states is None:
            self._log("behavior.intent.skipped", kind="move_through", reason="unavailable")
            return
        peep = self._world.peeps.get(peep_id)
        if peep is None:
            self._log("behavior.intent.skipped", kind="move_through", reason="unknown_peep")
            return
        source_room_id = self._current_peep_room(peep.id) or peep.room_id
        exit_id = str(payload.get("exit_id", ""))
        try:
            move = resolve_npc_move(self._world, peep, source_room_id, exit_id)
        except ValueError as exc:
            self._log("behavior.intent.skipped", kind="move_through", reason=str(exc))
            return
        self._peep_states.set_in_transaction(connection, peep.id, move.destination_room_id)
        if self._sprites is not None:
            self._sprites.forget_npc(peep.id)
        source_room = self._world.rooms[move.source_room_id]
        result.room_broadcasts.append(
            PendingRoomBroadcast(
                room_id=move.source_room_id,
                event=peep_leave_event(
                    peep_id=peep.id,
                    label=peep.label,
                    room_id=move.source_room_id,
                    destination_room_id=move.destination_room_id,
                    direction=move.direction,
                ),
            )
        )
        result.room_broadcasts.append(
            PendingRoomBroadcast(
                room_id=move.destination_room_id,
                event=peep_enter_event(
                    peep_id=peep.id,
                    label=peep.label,
                    room_id=move.destination_room_id,
                    source_room_id=move.source_room_id,
                    source_room_label=source_room.label,
                ),
            )
        )
        target_peep = peep.id
        target_room = move.destination_room_id

        def record_move() -> None:
            self._peep_states.record(target_peep, target_room)

        deferred.append(record_move)

    def _apply_move_sprite(
        self,
        payload: Mapping[str, object],
        context: BehaviorContext,
        event: BehaviorEvent,
        result: BehaviorResult,
        *,
        random_position: bool,
    ) -> None:
        sprite_actions.apply_move_sprite(
            sprites=self._sprites,
            payload=payload,
            context=context,
            event=event,
            result=result,
            random_position=random_position,
            log=self._log,
        )

    def _apply_move_peep_sprite(
        self,
        payload: Mapping[str, object],
        event: BehaviorEvent,
        result: BehaviorResult,
    ) -> None:
        """Move one NPC sprite by id, used by room-game controllers for bots."""

        if self._sprites is None or event.room_id is None:
            return
        peep_id = str(payload.get("peep_id", ""))
        if not peep_id or peep_id not in self._world.peeps:
            return
        try:
            if bool(payload.get("random")):
                position = self._sprites.random_npc_position(peep_id, event.room_id)
            else:
                raw = payload.get("position")
                if not isinstance(raw, list) or len(raw) != 2:
                    return
                position = self._sprites.set_npc_position(
                    peep_id, event.room_id, float(raw[0]), float(raw[1])
                )
        except (TypeError, ValueError) as exc:
            self._log("behavior.intent.skipped", kind="move_peep_sprite", error=str(exc))
            return
        result.room_broadcasts.append(
            PendingRoomBroadcast(
                room_id=event.room_id,
                event={
                    "type": "peep.sprite",
                    "room_id": event.room_id,
                    "peep_id": peep_id,
                    "position": list(position),
                },
            )
        )

    def _apply_move_peep(
        self,
        connection: sqlite3.Connection,
        payload: Mapping[str, object],
        context: BehaviorContext,
        result: BehaviorResult,
        deferred: list[object],
    ) -> None:
        del context
        sprite_actions.apply_move_peep(
            world=self._world,
            peep_states=self._peep_states,
            sprites=self._sprites,
            current_room=self._current_peep_room,
            connection=connection,
            payload=payload,
            result=result,
            deferred=deferred,
            log=self._log,
        )

    def _apply_set_environment(
        self,
        connection: sqlite3.Connection,
        payload: Mapping[str, object],
        context: BehaviorContext,
        event: BehaviorEvent,
        result: BehaviorResult,
    ) -> None:
        if self._environment is None:
            self._log("behavior.intent.skipped", kind="set_environment", reason="no_service")
            return
        room_id = event.room_id
        if not isinstance(room_id, str) or not room_id:
            room_id = payload.get("target_room_id")
        if not isinstance(room_id, str) or not room_id:
            self._log("behavior.intent.skipped", kind="set_environment", reason="no_room")
            return
        key = str(payload.get("key", ""))
        if not key:
            self._log("behavior.intent.skipped", kind="set_environment", reason="no_key")
            return
        try:
            update = self._environment.set_in_transaction(connection, room_id, {key: payload.get("value")})
        except ValueError as exc:
            self._log("behavior.intent.skipped", kind="set_environment", error=str(exc))
            return
        result.room_broadcasts.append(PendingRoomBroadcast(room_id=room_id, event=update.event()))

    def _apply_hide_prop(
        self,
        connection: sqlite3.Connection,
        payload: Mapping[str, object],
        context: BehaviorContext,
        event: BehaviorEvent,
        result: BehaviorResult,
    ) -> None:
        if self._environment is None:
            self._log("behavior.intent.skipped", kind="hide_prop", reason="no_service")
            return
        room_id = event.room_id
        if not isinstance(room_id, str) or not room_id:
            room_id = payload.get("target_room_id")
        if not isinstance(room_id, str) or not room_id:
            self._log("behavior.intent.skipped", kind="hide_prop", reason="no_room")
            return
        instance_id = payload.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            self._log("behavior.intent.skipped", kind="hide_prop", reason="no_instance")
            return
        try:
            seconds = float(payload.get("seconds", DEFAULT_HIDE_SECONDS) or DEFAULT_HIDE_SECONDS)
        except (TypeError, ValueError):
            seconds = DEFAULT_HIDE_SECONDS
        hidden = dict(self._environment.get(room_id).get("hidden_props") or {})
        hidden[instance_id] = {"expires_at": (utc_now() + timedelta(seconds=seconds)).isoformat()}
        try:
            update = self._environment.set_in_transaction(connection, room_id, {"hidden_props": hidden})
        except ValueError as exc:
            self._log("behavior.intent.skipped", kind="hide_prop", error=str(exc))
            return
        result.room_broadcasts.append(PendingRoomBroadcast(room_id=room_id, event=update.event()))

    def _apply_clear_source(
        self,
        payload: Mapping[str, object],
        event: BehaviorEvent,
        deferred: list[object],
    ) -> None:
        room_id = event.room_id
        source = str(payload.get("source", ""))
        if not isinstance(room_id, str) or not room_id or not source:
            self._log("behavior.intent.skipped", kind="clear_source", reason="invalid")
            return

        async def operation(target_room: str = room_id, target_source: str = source) -> None:
            for connection in await self._connections.list_room(target_room):
                self._stats.remove_source(connection.account_id, target_source)

        deferred.append(operation)
