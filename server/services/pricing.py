"""Card sell pricing and the inventory sell transaction."""

from __future__ import annotations

from dataclasses import dataclass

from server.content.cards import CardCatalog, CardDefinition
from server.content.gameplay import GameplayContent
from server.profiles import AccountRecord, InventoryStack, ProfileRepository
from server.state.migrations import DatabaseHub


@dataclass(frozen=True, slots=True)
class SaleResult:
    """Outcome of selling a quantity from an owned card stack."""

    definition: CardDefinition
    quantity: int
    bops_gained: int
    stacks: tuple[InventoryStack, ...]
    account: AccountRecord


class CardPricingService:
    """Owns runtime sell values and the sell transaction.

    Sell values currently derive from a card's rarity. Keeping the lookup behind
    ``sell_value`` leaves room for richer pricing rules later.
    """

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        catalog: CardCatalog,
        content: GameplayContent,
        world_id: str,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._catalog = catalog
        self._content = content
        self._world_id = world_id

    def sell_value(self, definition: CardDefinition) -> int:
        """Return the Bops value of one copy of a card."""

        return self._content.card_prices.value_for(definition.rarity)

    def is_sellable(self, definition: CardDefinition) -> bool:
        """Return whether a card can be sold from an inventory."""

        return definition.collectible and not definition.quest

    def _slotted_count(self, account_id: str, stack_id: str) -> int:
        profile = self._profiles.get_user_profile(account_id)
        if profile is None:
            return 0
        return sum(1 for entry in profile.skills if entry == stack_id)

    def sell(self, account: AccountRecord, stack_id: str, quantity: int = 1) -> SaleResult:
        """Sell copies of an owned card stack for Bops in one transaction."""

        with self._hub.transaction() as connection:
            stack = self._profiles.get_inventory_stack(account.id, self._world_id, stack_id)
            if stack is None:
                raise ValueError("That card stack is not in your inventory.")
            definition = self._catalog.cards.get(stack.card_def_id)
            if definition is None:
                raise ValueError("That card is not available.")
            if not self.is_sellable(definition):
                raise ValueError(f"{definition.label} cannot be sold.")
            if quantity < 1 or quantity > stack.quantity:
                raise ValueError("Invalid quantity for that card stack.")
            if definition.type == "skill" and self._slotted_count(account.id, stack_id) > stack.quantity - quantity:
                raise ValueError("Remove slotted skill copies before selling them.")
            current = self._profiles.get_account_by_id(account.id)
            if current is None:
                raise ValueError("Unknown account.")
            value = self.sell_value(definition)
            self._profiles.remove_inventory_quantity(
                connection,
                account_id=account.id,
                world_id=self._world_id,
                stack_id=stack_id,
                quantity=quantity,
            )
            updated = self._profiles.update_progress(
                connection,
                current,
                bops=current.bops + value * quantity,
            )
            stacks = tuple(self._profiles.list_inventory(account.id, self._world_id))
        return SaleResult(
            definition=definition,
            quantity=quantity,
            bops_gained=value * quantity,
            stacks=stacks,
            account=updated,
        )
