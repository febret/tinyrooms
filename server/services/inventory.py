"""Inventory and equipment rules: fill, split, merge, equip, and drop."""

from __future__ import annotations

from dataclasses import dataclass

from server.content.cards import CardCatalog
from server.content.gameplay import LevelTable
from server.profiles import AccountRecord, InventoryStack, ProfileRepository
from server.services.stats import PeepSnapshot, StatsService
from server.state.migrations import DatabaseHub

NON_EQUIP_TYPES = frozenset({"emote", "core", "skill"})


@dataclass(frozen=True, slots=True)
class InventoryMutation:
    """Outcome of an inventory or equipment mutation."""

    stacks: list[InventoryStack]
    snapshot: PeepSnapshot


class InventoryService:
    """Owns equipment-slot limits and stack reorganization invariants."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        stats: StatsService,
        catalog: CardCatalog,
        levels: LevelTable,
        world_id: str,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._stats = stats
        self._catalog = catalog
        self._levels = levels
        self._world_id = world_id

    def _definition(self, card_def_id: str):
        definition = self._catalog.cards.get(card_def_id)
        if definition is None:
            raise ValueError(f"Unknown card '{card_def_id}'.")
        return definition

    def _equipped_count(self, account_id: str) -> int:
        return sum(
            1 for stack in self._profiles.list_inventory(account_id, self._world_id) if stack.equipped
        )

    def _stack(self, account_id: str, stack_id: str) -> InventoryStack:
        stack = self._profiles.get_inventory_stack(account_id, self._world_id, stack_id)
        if stack is None:
            raise ValueError("That card stack is not in your inventory.")
        return stack

    def equip(self, account: AccountRecord, stack_id: str) -> InventoryMutation:
        """Equip an item/action stack when a slot is free."""

        with self._hub.transaction() as connection:
            stack = self._stack(account.id, stack_id)
            definition = self._definition(stack.card_def_id)
            if definition.type in NON_EQUIP_TYPES:
                raise ValueError(f"{definition.label} cannot be equipped.")
            if stack.equipped:
                return self._finish(connection, account.id)
            cap = self._levels.equipped_cap(account.level)
            if self._equipped_count(account.id) >= cap:
                raise ValueError("No free equipment slots. Unequip something first.")
            self._profiles.set_stack_equipped(
                connection,
                account_id=account.id,
                world_id=self._world_id,
                stack_id=stack_id,
                equipped=True,
            )
            return self._finish(connection, account.id)

    def unequip(self, account: AccountRecord, stack_id: str) -> InventoryMutation:
        """Unequip an owned stack for free."""

        with self._hub.transaction() as connection:
            stack = self._stack(account.id, stack_id)
            if stack.equipped:
                self._profiles.set_stack_equipped(
                    connection,
                    account_id=account.id,
                    world_id=self._world_id,
                    stack_id=stack_id,
                    equipped=False,
                )
            return self._finish(connection, account.id)

    def split(self, account: AccountRecord, stack_id: str, quantity: int) -> InventoryMutation:
        """Split copies into a new, unequipped stack preserving the source state."""

        with self._hub.transaction() as connection:
            stack = self._stack(account.id, stack_id)
            definition = self._definition(stack.card_def_id)
            if definition.stack_limit <= 1:
                raise ValueError(f"{definition.label} cannot be split.")
            if quantity < 1 or quantity >= stack.quantity:
                raise ValueError("Choose a quantity smaller than the stack.")
            self._profiles.set_stack_quantity(
                connection,
                account_id=account.id,
                stack_id=stack_id,
                quantity=stack.quantity - quantity,
            )
            self._profiles.create_inventory_stack(
                connection,
                account_id=account.id,
                world_id=stack.world_id,
                card_def_id=stack.card_def_id,
                quantity=quantity,
                scope=stack.scope,
                equipped=False,
            )
            return self._finish(connection, account.id)

    def merge(
        self,
        account: AccountRecord,
        source_id: str,
        destination_id: str,
        quantity: int | None = None,
    ) -> InventoryMutation:
        """Move copies into another stack of the same card up to its limit."""

        if source_id == destination_id:
            raise ValueError("Choose two different stacks to merge.")
        with self._hub.transaction() as connection:
            source = self._stack(account.id, source_id)
            destination = self._stack(account.id, destination_id)
            if source.card_def_id != destination.card_def_id:
                raise ValueError("Only stacks of the same card can be merged.")
            if source.world_id != destination.world_id or source.scope != destination.scope:
                raise ValueError("Those stacks cannot be merged.")
            definition = self._definition(source.card_def_id)
            free_space = definition.stack_limit - destination.quantity
            if free_space <= 0:
                raise ValueError("The destination stack is already full.")
            movable = min(source.quantity, free_space)
            if quantity is not None:
                if quantity < 1 or quantity > movable:
                    raise ValueError("Invalid merge quantity.")
                movable = quantity
            self._profiles.set_stack_quantity(
                connection,
                account_id=account.id,
                stack_id=destination_id,
                quantity=destination.quantity + movable,
            )
            self._profiles.set_stack_quantity(
                connection,
                account_id=account.id,
                stack_id=source_id,
                quantity=source.quantity - movable,
            )
            return self._finish(connection, account.id)

    def _finish(self, connection, account_id: str) -> InventoryMutation:
        stacks = self._profiles.list_inventory(account_id, self._world_id)
        snapshot = self._stats.reconcile_in_transaction(connection, account_id)
        return InventoryMutation(stacks=stacks, snapshot=snapshot)
