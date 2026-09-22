"""Card action execution, targeting, affordability, and emote presentation."""

from __future__ import annotations

from dataclasses import dataclass, field

from server.content.cards import CardCatalog, CardDefinition
from server.profiles import AccountRecord, InventoryStack, ProfileRepository
from server.services.stats import PeepSnapshot, StatsService
from server.state.migrations import DatabaseHub

DEFAULT_CARD_ENERGY_COST = 2
EMOTE_COSTS = {"Expression": 1, "Animation": 3, "Effects": 5}
HEALTH_EFFECT = "health"
ENERGY_EFFECT = "energy"
SUPPORTED_EFFECTS = frozenset({HEALTH_EFFECT, ENERGY_EFFECT})
PASSIVE_FLAGS = frozenset({"passive", "decorative"})


@dataclass(frozen=True, slots=True)
class ActionEffect:
    """A resolved counter or status change on one peep."""

    target_account_id: str
    target_label: str
    health_delta: float = 0.0
    energy_delta: float = 0.0
    statuses: tuple[str, ...] = ()
    health: float = 0.0
    energy: float = 0.0
    max_health: int = 0
    max_energy: int = 0


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Outcome of a card action or emote."""

    actor: PeepSnapshot
    card_id: str
    card_label: str
    message: str
    consumed: bool
    effects: tuple[ActionEffect, ...] = ()
    room_effect: str | None = None
    bubble: dict[str, object] | None = None
    inventory: tuple[InventoryStack, ...] = field(default_factory=tuple)


class ActionsService:
    """Owns card use, emotes, and transactional charging."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        stats: StatsService,
        catalog: CardCatalog,
        world_id: str,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._stats = stats
        self._catalog = catalog
        self._world_id = world_id

    def _definition(self, card_def_id: str) -> CardDefinition:
        definition = self._catalog.cards.get(card_def_id)
        if definition is None:
            raise ValueError(f"Unknown card '{card_def_id}'.")
        return definition

    def _stack(self, account_id: str, stack_id: str) -> InventoryStack:
        stack = self._profiles.get_inventory_stack(account_id, self._world_id, stack_id)
        if stack is None:
            raise ValueError("That card stack is not in your inventory.")
        return stack

    def energy_cost(self, definition: CardDefinition) -> int:
        """Return the Energy cost of playing a card."""

        if definition.energy_cost is not None:
            return int(definition.energy_cost)
        if definition.type == "emote":
            return EMOTE_COSTS.get(definition.category or "Expression", 0)
        return DEFAULT_CARD_ENERGY_COST

    def can_use(self, definition: CardDefinition) -> bool:
        """Return whether a card has an active Use action in this milestone."""

        if definition.type in {"core", "emote", "skill"}:
            return False
        if definition.passive or definition.decorative:
            return False
        if definition.effect not in SUPPORTED_EFFECTS:
            return False
        return True

    def use_card(
        self,
        account: AccountRecord,
        *,
        stack_id: str,
        target_account_id: str | None = None,
        target_label: str | None = None,
        target_is_npc: bool = False,
    ) -> ActionResult:
        """Use one copy of an equipped item/action card."""

        with self._hub.transaction() as connection:
            stack = self._stack(account.id, stack_id)
            definition = self._definition(stack.card_def_id)
            if not self.can_use(definition):
                if definition.passive:
                    raise ValueError(f"{definition.label} works automatically while equipped.")
                if definition.decorative:
                    raise ValueError(f"{definition.label} is a decorative keepsake.")
                raise ValueError(f"{definition.label} has no Use action.")
            if not stack.equipped:
                raise ValueError(f"Equip {definition.label} before using it.")

            resolved_target = target_account_id or account.id
            resolved_label = target_label or account.username_display
            effects: list[ActionEffect] = []
            message: str

            if definition.effect == ENERGY_EFFECT:
                if target_account_id is not None and target_account_id != account.id:
                    raise ValueError(f"{definition.label} can only be used on yourself.")
                amount = float(definition.amount or 0)
                before = self._stats.reconcile_in_transaction(connection, account.id)
                if before.energy >= before.effective.max_energy:
                    raise ValueError("Your Energy is already full.")
                snapshot = self._stats.apply_in_transaction(connection, account.id, energy_delta=amount)
                gained = snapshot.energy - before.energy
                effects.append(
                    ActionEffect(
                        target_account_id=account.id,
                        target_label=account.username_display,
                        energy_delta=gained,
                        statuses=snapshot.statuses,
                        health=snapshot.health,
                        energy=snapshot.energy,
                        max_health=snapshot.effective.max_health,
                        max_energy=snapshot.effective.max_energy,
                    )
                )
                message = f"{account.username_display} drank a {definition.label} (+{gained:.0f} Energy)."
                actor = snapshot
            elif definition.effect == HEALTH_EFFECT:
                if target_is_npc:
                    raise ValueError(f"{target_label or 'That peep'} does not accept that right now.")
                target_id = resolved_target
                before = self._stats.reconcile_in_transaction(connection, target_id)
                if before.health >= before.effective.max_health:
                    raise ValueError(f"{resolved_label} is already at full Health.")
                amount = float(definition.amount or 0)
                snapshot = self._stats.apply_in_transaction(connection, target_id, health_delta=amount)
                healed = snapshot.health - before.health
                effects.append(
                    ActionEffect(
                        target_account_id=target_id,
                        target_label=resolved_label,
                        health_delta=healed,
                        statuses=snapshot.statuses,
                        health=snapshot.health,
                        energy=snapshot.energy,
                        max_health=snapshot.effective.max_health,
                        max_energy=snapshot.effective.max_energy,
                    )
                )
                if target_id == account.id:
                    message = f"You used {definition.label} (+{healed:.0f} Health)."
                    actor = snapshot
                else:
                    actor = self._stats.reconcile_in_transaction(connection, account.id)
                    message = f"You gave {resolved_label} {definition.label} (+{healed:.0f} Health)."
            else:
                raise ValueError(f"{definition.label} has no effect yet.")

            cost = self.energy_cost(definition)
            allow_while_tired = definition.effect == ENERGY_EFFECT
            if cost:
                actor = self._stats.charge_in_transaction(
                    connection, account.id, cost, allow_while_tired=allow_while_tired
                )
            else:
                actor = self._stats.reconcile_in_transaction(connection, account.id)

            consumed = False
            if definition.one_use:
                self._profiles.remove_inventory_quantity(
                    connection,
                    account_id=account.id,
                    world_id=self._world_id,
                    stack_id=stack_id,
                    quantity=1,
                )
                consumed = True
            inventory = tuple(self._profiles.list_inventory(account.id, self._world_id))
            return ActionResult(
                actor=actor,
                card_id=definition.id,
                card_label=definition.label,
                message=message,
                consumed=consumed,
                effects=tuple(effects),
                inventory=inventory,
            )

    def use_emote(self, account: AccountRecord, *, stack_id: str) -> ActionResult:
        """Play an owned emote, charging its configured Energy cost."""

        with self._hub.transaction() as connection:
            stack = self._stack(account.id, stack_id)
            definition = self._definition(stack.card_def_id)
            if definition.type != "emote":
                raise ValueError(f"{definition.label} is not an emote.")
            cost = self.energy_cost(definition)
            if cost:
                actor = self._stats.charge_in_transaction(connection, account.id, cost)
            else:
                actor = self._stats.reconcile_in_transaction(connection, account.id)
            category = definition.category or "Expression"
            if category == "Effects":
                return ActionResult(
                    actor=actor,
                    card_id=definition.id,
                    card_label=definition.label,
                    message=f"{account.username_display} used {definition.label}.",
                    consumed=False,
                    room_effect=definition.effect or definition.id,
                    inventory=tuple(self._profiles.list_inventory(account.id, self._world_id)),
                )
            bubble = {
                "kind": "animation" if category == "Animation" else "expression",
                "text": definition.label,
                "image_url": self._emote_image_url(definition),
            }
            return ActionResult(
                actor=actor,
                card_id=definition.id,
                card_label=definition.label,
                message=f"{account.username_display} used {definition.label}.",
                consumed=False,
                bubble=bubble,
                inventory=tuple(self._profiles.list_inventory(account.id, self._world_id)),
            )

    def _emote_image_url(self, definition: CardDefinition) -> str:
        asset_kind = "base" if definition.source != self._world_id else f"world/{self._world_id}/cards"
        return f"/assets/{asset_kind}/{definition.image_name}"
