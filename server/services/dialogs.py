"""Declarative NPC dialog sessions, validation, and side effects."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import sqlite3

from server.behaviors.events import BehaviorEvent, PeepRef
from server.content.cards import CardCatalog
from server.content.worlds import DialogChoice, DialogDefinition, WorldDefinition
from server.profiles import AccountRecord, ProfileRepository
from server.services.cards import grant_card_to_inventory
from server.state.migrations import DatabaseHub


@dataclass(frozen=True, slots=True)
class ActiveDialog:
    """An in-process active dialog row for one account."""

    account_id: str
    world_id: str
    peep_id: str
    node_id: str
    revision: int


@dataclass(slots=True)
class DialogResult:
    """Outcome of choosing a dialog option."""

    dialog: dict[str, object] | None
    peep_id: str | None
    node_id: str | None
    choice: DialogChoice | None
    duplicated: bool = False
    behavior_result: object | None = None
    events: list[dict[str, object]] = field(default_factory=list)


class DialogService:
    """Owns active dialog state and declarative side-effect application."""

    def __init__(
        self,
        *,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        stats: object,
        catalog: CardCatalog,
        progression: object,
        world: WorldDefinition,
        tasks: object | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._stats = stats
        self._catalog = catalog
        self._progression = progression
        self._world = world
        self._tasks = tasks
        self._dispatcher: object | None = None
        self._active: dict[str, ActiveDialog] = {}

    def attach_dispatcher(self, dispatcher: object) -> None:
        """Wire the behavior dispatcher used for dialog script callbacks."""

        self._dispatcher = dispatcher

    def _current_room(self, account_id: str) -> str:
        profile = self._profiles.get_user_profile(account_id)
        remembered = profile.remembered_room if profile is not None else None
        if remembered in self._world.rooms:
            return remembered
        return self._world.entry_room_id

    def _require_dialog(self, peep_id: str) -> tuple[DialogDefinition, object]:
        peep = self._world.peeps.get(peep_id)
        if peep is None or peep.dialog is None:
            raise ValueError("That peep has nothing to say.")
        return peep.dialog, peep

    def start(self, account: AccountRecord, peep_id: str, node_id: str | None = None) -> ActiveDialog:
        """Open (or refocus) a peep dialog for the account."""

        return self.start_in_transaction(None, account, peep_id, node_id)

    def start_in_transaction(
        self,
        connection: sqlite3.Connection | None,
        account: AccountRecord,
        peep_id: str,
        node_id: str | None = None,
    ) -> ActiveDialog:
        """Open a dialog inside a caller-owned transaction."""

        del connection
        dialog, peep = self._require_dialog(peep_id)
        if peep.room_id != self._current_room(account.id):
            raise ValueError("That peep is not in this room.")
        target_node = node_id or dialog.start_node_id
        if target_node not in dialog.nodes:
            raise ValueError("That dialog node does not exist.")
        existing = self._active.get(account.id)
        revision = existing.revision + 1 if existing is not None else 1
        active = ActiveDialog(
            account_id=account.id,
            world_id=self._world.id,
            peep_id=peep_id,
            node_id=target_node,
            revision=revision,
        )
        self._active[account.id] = active
        return active

    def view(self, account_id: str) -> ActiveDialog | None:
        """Return the account's active dialog, if any."""

        return self._active.get(account_id)

    def end(self, account_id: str, reason: str) -> None:
        """End the account's active dialog."""

        del reason
        self.end_in_transaction(None, account_id)

    def end_in_transaction(self, connection: sqlite3.Connection | None, account_id: str) -> None:
        """Delete the account's active dialog inside a caller-owned transaction."""

        del connection
        self._active.pop(account_id, None)

    def _condition_met(self, condition: object, counters: dict[str, object]) -> bool:
        if condition is None:
            return True
        counter = getattr(condition, "counter", "")
        value = counters.get(counter)
        maximum = counters.get(f"max_{counter}")
        if value is None:
            return False
        return bool(condition.matches(float(value), None if maximum is None else float(maximum)))

    def serialize(self, active: ActiveDialog | None) -> dict[str, object] | None:
        """Serialize an active dialog with per-choice availability."""

        if active is None:
            return None
        dialog, peep = self._require_dialog(active.peep_id)
        node = dialog.nodes.get(active.node_id)
        if node is None:
            return None
        counters = self._stats.view(active.account_id).payload()
        return {
            "peep_id": active.peep_id,
            "peep_label": peep.label,
            "node_id": active.node_id,
            "revision": active.revision,
            "text": node.text,
            "choices": [
                {
                    "label": choice.label,
                    "index": choice.index,
                    "action_id": choice.action_id,
                    "disabled": not self._condition_met(choice.when, counters),
                }
                for choice in node.choices
            ],
        }

    def _resolve_choice(self, node: object, value: object) -> DialogChoice | None:
        choices = getattr(node, "choices", ())
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return choices[value] if 0 <= value < len(choices) else None
        text = str(value)
        if text.isdigit():
            index = int(text)
            return choices[index] if 0 <= index < len(choices) else None
        return next((choice for choice in choices if choice.action_id == text), None)

    def _apply_side_effects(
        self,
        connection: sqlite3.Connection,
        account: AccountRecord,
        choice: DialogChoice,
        result: DialogResult,
    ) -> None:
        if choice.give_card is not None:
            definition = self._catalog.cards.get(choice.give_card)
            if definition is not None:
                grant_card_to_inventory(
                    self._profiles,
                    connection,
                    account_id=account.id,
                    definition=definition,
                    world_id=self._world.id,
                )
        if choice.start_task is not None:
            if self._tasks is not None:
                self._tasks.start_in_transaction(connection, account.id, choice.start_task)
                result.events.append(
                    {"type": "task.updated", "tasks": self._tasks.view_payload(account.id), "account_id": account.id}
                )
            else:
                result.events.append(
                    {"type": "task.started", "task_id": choice.start_task, "account_id": account.id}
                )

    async def choose(
        self,
        account: AccountRecord,
        choice_index_or_action_id: object,
        *,
        action_id: str | None = None,
    ) -> DialogResult:
        """Choose a dialog option with full revalidation and idempotency."""

        active = self.view(account.id)
        if active is None:
            raise ValueError("You are not in a conversation.")
        dialog, peep = self._require_dialog(active.peep_id)
        if peep.room_id != self._current_room(account.id):
            raise ValueError("That peep is no longer here.")
        node = dialog.nodes.get(active.node_id)
        if node is None:
            raise ValueError("That conversation has ended.")
        choice = self._resolve_choice(node, choice_index_or_action_id)
        resolved_action_id = action_id or (choice.action_id if choice is not None else None)
        if resolved_action_id is None:
            raise ValueError("That dialog choice is not available.")
        result = DialogResult(dialog=None, peep_id=active.peep_id, node_id=active.node_id, choice=choice)
        duplicated = False
        with self._hub.transaction() as connection:
            current = self.view(account.id)
            if current is None:
                raise ValueError("That conversation has ended.")
            ledger_key = f"dialog:{active.peep_id}:{resolved_action_id}"
            duplicated = self._progression.has_ledger_entry(connection, account.id, ledger_key)
            if not duplicated:
                if choice is None:
                    raise ValueError("That dialog choice is not available.")
                if current.node_id != active.node_id:
                    raise ValueError("That conversation has moved on.")
                counters = self._stats.view(account.id).payload()
                if not self._condition_met(choice.when, counters):
                    raise ValueError("That choice is not available right now.")
                self._progression.grant_in_transaction(
                    connection,
                    account.id,
                    kudos=choice.grant,
                    ledger_key=ledger_key,
                    kind="dialog",
                )
                self._apply_side_effects(connection, account, choice, result)
                if choice.end:
                    self.end_in_transaction(connection, account.id)
                else:
                    self._active[account.id] = replace(
                        current,
                        node_id=choice.next_node_id,
                        revision=current.revision + 1,
                    )
        result.duplicated = duplicated
        if not duplicated and choice is not None and self._dispatcher is not None:
            event = BehaviorEvent(
                type="dialog_action",
                actor=PeepRef(kind="user", peep_id=None, account_id=account.id),
                target=PeepRef(kind="npc", peep_id=active.peep_id, account_id=None),
                room_id=peep.room_id,
                action=choice.action,
                data={
                    "peep_id": active.peep_id,
                    "node_id": active.node_id,
                    "choice_index": choice.index,
                    "action_id": resolved_action_id,
                    "label": choice.label,
                    "script": choice.script,
                },
            )
            result.behavior_result = await self._dispatcher.dispatch(event)
        refreshed = self.view(account.id)
        result.dialog = self.serialize(refreshed)
        result.node_id = None if refreshed is None else refreshed.node_id
        return result
