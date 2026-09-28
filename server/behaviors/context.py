"""Typed behavior context and declarative intents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from server.behaviors.events import BehaviorEvent, PeepRef, PropRef


@dataclass(frozen=True, slots=True)
class Intent:
    """A declarative mutation requested by a behavior script."""

    kind: str
    payload: dict[str, object]


def _target_payload(target: PeepRef | PropRef | None) -> dict[str, object]:
    if isinstance(target, PeepRef):
        return {"target_kind": target.kind, "target_peep_id": target.peep_id, "target_account_id": target.account_id}
    if isinstance(target, PropRef):
        return {"target_instance_id": target.instance_id, "target_prop_id": target.prop_id, "target_room_id": target.room_id}
    return {}


class BehaviorContext:
    """Narrow, typed facade handed to trusted scripts.

    Scripts never touch live services directly; every method appends an
    :class:`Intent` that the dispatcher revalidates and applies atomically.
    """

    def __init__(
        self,
        *,
        event: BehaviorEvent,
        actor: PeepRef,
        target: PeepRef | PropRef | None,
        room: Mapping[str, object],
        world: Mapping[str, object],
        state: dict[str, object],
        now: datetime,
        statuses: tuple[str, ...] = (),
        counters: Mapping[str, object] | None = None,
        card_ids: tuple[str, ...] = (),
        equipped_ids: tuple[str, ...] = (),
        environment: object | None = None,
    ) -> None:
        self.event = event
        self.actor = actor
        self.target = target
        self.room = room
        self.world = world
        self.state = state
        self.now = now
        self.statuses = statuses
        self.counters = dict(counters or {})
        self._card_ids = frozenset(card_ids)
        self._equipped_ids = frozenset(equipped_ids)
        self._environment = environment
        self.intents: list[Intent] = []

    def has_status(self, status_id: str) -> bool:
        """Return whether the acting peep currently has *status_id*."""

        return status_id in self.statuses

    def counter(self, name: str, default: float = 0.0) -> float:
        """Return one of the acting peep's counter values."""

        try:
            return float(self.counters.get(name, default))
        except (TypeError, ValueError):
            return default

    def has_card(self, card_id: str) -> bool:
        """Return whether the acting peep owns at least one copy of a card."""

        return card_id in self._card_ids

    def has_equipped_card(self, card_id: str) -> bool:
        """Return whether the acting peep has a copy of a card equipped."""

        return card_id in self._equipped_ids

    def room_lighting(self) -> str:
        """Return the acting room's lighting mode."""

        if self._environment is None or self.event.room_id is None:
            return "normal"
        return str(self._environment.lighting(self.event.room_id))

    def prop_visible(self, instance_id: str) -> bool:
        """Return whether a prop instance is currently visible in the room."""

        if self._environment is None or self.event.room_id is None:
            return True
        return bool(self._environment.is_prop_visible(self.event.room_id, instance_id))

    def _resolve(self, target: PeepRef | PropRef | None) -> PeepRef | PropRef | None:
        return self.actor if target is None else target

    def _append(self, kind: str, payload: dict[str, object]) -> None:
        self.intents.append(Intent(kind=kind, payload=payload))

    def feedback(self, text: str, style: str = "toast", *, target: PeepRef | PropRef | None = None) -> None:
        """Queue a private feedback message for the acting peep."""

        payload: dict[str, object] = {"text": str(text), "style": str(style)}
        payload.update(_target_payload(self._resolve(target)))
        self._append("feedback", payload)

    def effect(self, effect_id: str, *, target: PeepRef | PropRef | None = None) -> None:
        """Queue a visible room effect."""

        payload: dict[str, object] = {"effect_id": str(effect_id)}
        payload.update(_target_payload(self._resolve(target)))
        self._append("effect", payload)

    def apply_counter(self, counter: str, delta: float, *, target: PeepRef | PropRef | None = None) -> None:
        """Queue a counter delta on a peep."""

        payload: dict[str, object] = {"counter": str(counter), "delta": float(delta)}
        payload.update(_target_payload(self._resolve(target)))
        self._append("apply_counter", payload)

    def set_counter(self, counter: str, value: float, *, target: PeepRef | PropRef | None = None) -> None:
        """Queue an absolute counter value on a peep."""

        payload: dict[str, object] = {"counter": str(counter), "value": float(value)}
        payload.update(_target_payload(self._resolve(target)))
        self._append("set_counter", payload)

    def apply_buff(
        self,
        buff_id: str,
        duration_seconds: float | None = None,
        *,
        daily: bool = False,
        source: str | None = None,
        target: PeepRef | PropRef | None = None,
    ) -> None:
        """Queue a buff application on a peep."""

        payload: dict[str, object] = {
            "buff_id": str(buff_id),
            "duration_seconds": None if duration_seconds is None else float(duration_seconds),
            "daily": bool(daily),
            "source": source,
        }
        payload.update(_target_payload(self._resolve(target)))
        self._append("apply_buff", payload)

    def grant(
        self,
        *,
        kudos: int = 0,
        cards: tuple[str, ...] | list[str] = (),
        ledger_key: str | None = None,
        target: PeepRef | PropRef | None = None,
    ) -> None:
        """Queue an idempotent Kudos and/or card grant."""

        payload: dict[str, object] = {
            "kudos": int(kudos),
            "cards": [str(card_id) for card_id in cards],
            "ledger_key": ledger_key,
        }
        payload.update(_target_payload(self._resolve(target)))
        self._append("grant", payload)

    def give_card(self, card_id: str, quantity: int = 1, *, target: PeepRef | PropRef | None = None) -> None:
        """Queue a direct inventory card grant."""

        payload: dict[str, object] = {"card_id": str(card_id), "quantity": int(quantity)}
        payload.update(_target_payload(self._resolve(target)))
        self._append("give_card", payload)

    def remove_card(self, card_id: str, *, target: PeepRef | PropRef | None = None) -> None:
        """Queue removal of every copy of a card from the target's inventory."""

        payload: dict[str, object] = {"card_id": str(card_id)}
        payload.update(_target_payload(self._resolve(target)))
        self._append("remove_card", payload)

    def npc_say(self, text: str, style: str = "expression") -> None:
        """Queue a speech bubble spoken by the attached NPC peep."""

        self._append("npc_say", {"text": str(text), "style": str(style)})

    def start_dialog(self, peep_id: str, node_id: str | None = None) -> None:
        """Queue opening (or refocusing) an NPC dialog."""

        self._append("start_dialog", {"peep_id": str(peep_id), "node_id": node_id})

    def end_dialog(self) -> None:
        """Queue closing the acting peep's active dialog."""

        self._append("end_dialog", {})

    def start_activity(self, kind: str, title: str | None = None) -> None:
        """Queue opening an activity for the acting peep."""

        self._append("start_activity", {"kind": str(kind), "title": title})

    def cutscene(
        self,
        cutscene_id: str,
        *,
        audience: str | None = None,
        params: Mapping[str, object] | None = None,
    ) -> None:
        """Queue playing a cutscene for the acting peep, or for the whole room.

        The default ``private`` audience reaches only the account whose action
        triggered this event, because the dispatcher routes the play event by
        ``account_id``.
        """

        self._append(
            "cutscene",
            {
                "cutscene_id": str(cutscene_id),
                "audience": str(audience) if audience else None,
                "params": dict(params or {}),
            },
        )

    def start_task(self, task_id: str) -> None:
        """Queue starting a task (task storage lands in Phase B)."""

        self._append("start_task", {"task_id": str(task_id)})

    def update_task_progress(self, task_id: str, step_id: str | None = None, amount: int = 1) -> None:
        """Queue advancing a task step (task storage lands in Phase B)."""

        self._append("update_task_progress", {"task_id": str(task_id), "step_id": step_id, "amount": int(amount)})

    def request_move(self, room_id: str) -> None:
        """Queue moving the acting peep to another room."""

        self._append("request_move", {"room_id": str(room_id)})

    def move_through(self, exit_id: str) -> None:
        """Queue moving the acting peep through an exit in its current room."""

        self._append("move_through", {"exit_id": str(exit_id)})

    def set_environment(self, key: str, value: object, *, target: PropRef | None = None) -> None:
        """Queue a persistent prop environment update (Phase C stub)."""

        resolved = target if target is not None else self.target
        payload: dict[str, object] = {"key": str(key), "value": value}
        if isinstance(resolved, PropRef):
            payload.update(_target_payload(resolved))
        self._append("set_environment", payload)

    def prop_state(self, key: str, default: object = None) -> object:
        """Read a key from this instance's persisted behavior state."""

        return self.state.get(key, default)
