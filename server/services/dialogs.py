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
from server.state.npc_peep_states import NpcPeepStateRepository


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
    task_changes: list[object] = field(default_factory=list)


def dialog_choice_guarded(choice: DialogChoice) -> bool:
    """Return whether a dialog choice needs reward-ledger idempotency.

    Choices carrying material rewards, behavior scripts, or mod settlement
    actions are guarded so their effects apply once. Navigation, vibe-only,
    and pure flavor choices are always reusable.
    """

    if bool(getattr(choice, "repeatable", False)):
        return False
    if choice.grant != 0 or int(getattr(choice, "grant_bops", 0) or 0) != 0:
        return True
    if choice.give_card is not None or choice.start_task is not None:
        return True
    return choice.action is not None or choice.script is not None


class DialogService:
    """Owns active dialog state and declarative side-effect application.

    Reward idempotency and navigation are independent: repeating a choice
    always advances the conversation, while material rewards (Kudos, Bops,
    cards, tasks) are granted once per choice through the reward ledger.
    Vibe adjustments apply once per conversation session.
    """

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
        peep_states: NpcPeepStateRepository | None = None,
        vibes: object | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._stats = stats
        self._catalog = catalog
        self._progression = progression
        self._world = world
        self._tasks = tasks
        self._peep_states = peep_states
        self._vibes = vibes
        self._dispatcher: object | None = None
        self._side_effect_hook: object | None = None
        self._active: dict[str, ActiveDialog] = {}
        self._vibe_used: dict[str, set[str]] = {}

    def attach_dispatcher(self, dispatcher: object) -> None:
        """Wire the behavior dispatcher used for dialog script callbacks."""

        self._dispatcher = dispatcher

    def attach_side_effect_hook(self, hook: object) -> None:
        """Wire an optional hook run after a non-duplicate choice commits.

        The hook receives ``(account, peep_id, choice)`` and lets mods settle
        choice-specific state (such as roommate job claims) outside the dialog
        transaction.
        """

        self._side_effect_hook = hook

    def _current_room(self, account_id: str) -> str:
        profile = self._profiles.get_user_profile(account_id)
        remembered = profile.remembered_room if profile is not None else None
        if remembered in self._world.rooms:
            return remembered
        return self._world.entry_room_id

    def _peep_room(self, peep: object) -> str:
        """Return the peep's current room, falling back to its spawn room."""

        if self._peep_states is not None:
            current = self._peep_states.room_for(peep.id)
            if current in self._world.rooms:
                return current
        return peep.room_id

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
        if self._peep_room(peep) != self._current_room(account.id):
            raise ValueError("That peep is not in this room.")
        target_node = node_id or dialog.start_node_id
        if target_node not in dialog.nodes:
            raise ValueError("That dialog node does not exist.")
        existing = self._active.get(account.id)
        if existing is None or existing.peep_id != peep_id:
            self._vibe_used.pop(account.id, None)
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
        self._vibe_used.pop(account_id, None)

    def sessions_for_peep(self, peep_id: str) -> list[ActiveDialog]:
        """Return every open dialog session currently talking to *peep_id*."""

        return [active for active in self._active.values() if active.peep_id == peep_id]

    def has_open_session(self, peep_id: str) -> bool:
        """Return whether any user currently has a dialog open with *peep_id*."""

        return any(active.peep_id == peep_id for active in self._active.values())

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
                change = self._tasks.start_in_transaction(connection, account.id, choice.start_task)
                if change is not None:
                    result.task_changes.append(change)
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
        """Choose a dialog option, always advancing; rewards stay idempotent."""

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
        if resolved_action_id is None or choice is None:
            raise ValueError("That dialog choice is not available.")
        result = DialogResult(dialog=None, peep_id=active.peep_id, node_id=active.node_id, choice=choice)
        guarded = dialog_choice_guarded(choice)
        ledger_key = f"dialog:{active.peep_id}:{resolved_action_id}" if guarded else None
        already_claimed = False
        with self._hub.transaction() as connection:
            current = self.view(account.id)
            if current is None:
                raise ValueError("That conversation has ended.")
            if current.node_id != active.node_id:
                raise ValueError("That conversation has moved on.")
            counters = self._stats.view(account.id).payload()
            if not self._condition_met(choice.when, counters):
                raise ValueError("That choice is not available right now.")
            if guarded:
                already_claimed = self._progression.has_ledger_entry(
                    connection, account.id, str(ledger_key)
                )
            if not already_claimed:
                self._progression.grant_in_transaction(
                    connection,
                    account.id,
                    kudos=choice.grant,
                    bops=int(getattr(choice, "grant_bops", 0) or 0),
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
        vibe_delta = int(getattr(choice, "vibe_delta", 0) or 0)
        if vibe_delta:
            vibe_key = f"{active.peep_id}:{active.node_id}:{choice.index}"
            used = self._vibe_used.setdefault(account.id, set())
            if vibe_key not in used:
                used.add(vibe_key)
                if self._vibes is not None:
                    adjust = getattr(self._vibes, "adjust", None)
                    if callable(adjust):
                        adjust(active.peep_id, account.id, vibe_delta)
                        adjust(account.id, active.peep_id, vibe_delta)
        if not already_claimed and self._side_effect_hook is not None:
            hook = self._side_effect_hook
            if callable(hook):
                hook(account, active.peep_id, choice)
        result.duplicated = already_claimed
        if not already_claimed and self._dispatcher is not None:
            event = BehaviorEvent(
                type="dialog_action",
                actor=PeepRef(kind="user", peep_id=None, account_id=account.id),
                target=PeepRef(kind="npc", peep_id=active.peep_id, account_id=None),
                room_id=self._peep_room(peep),
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
        if result.task_changes and self._tasks is not None:
            result.events.extend(
                self._tasks.feedback_events(account.id, result.task_changes, room_id=self._peep_room(peep))
            )
        return result
