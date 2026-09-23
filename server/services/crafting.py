"""Validate-before-consume crafting."""

from __future__ import annotations

from dataclasses import dataclass, field
import sqlite3

from server.content.cards import CardCatalog
from server.content.gameplay import GameplayContent
from server.content.recipes import RecipeDefinition
from server.content.worlds import PropInstanceDefinition, WorldDefinition
from server.profiles import AccountRecord, InventoryStack, ProfileRepository
from server.services.cards import grant_card_to_inventory
from server.services.inventory import InventoryService
from server.services.stats import PeepSnapshot, StatsService
from server.state.migrations import DatabaseHub


@dataclass(frozen=True, slots=True)
class StackOption:
    """One inventory stack the user may draw an ingredient from."""

    stack_id: str
    quantity: int
    equipped: bool


@dataclass(frozen=True, slots=True)
class IngredientPreview:
    """A recipe ingredient and the user's eligible source stacks."""

    card_id: str
    label: str
    quantity: int
    stacks: tuple[StackOption, ...] = ()


@dataclass(frozen=True, slots=True)
class OutputPreview:
    """A recipe output card and quantity."""

    card_id: str
    label: str
    quantity: int


@dataclass(frozen=True, slots=True)
class CraftPreview:
    """A crafting station recipe preview."""

    recipe_id: str
    label: str
    description: str
    energy_cost: int
    ingredients: tuple[IngredientPreview, ...]
    output: tuple[OutputPreview, ...]


@dataclass(frozen=True, slots=True)
class CraftResult:
    """Outcome of a crafting attempt."""

    recipe_id: str
    label: str
    outputs: tuple[OutputPreview, ...]
    stacks: tuple[InventoryStack, ...] = field(default_factory=tuple)
    snapshot: PeepSnapshot | None = None


class CraftingService:
    """Owns recipe validation, stack selection, and atomic crafting."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        inventory: InventoryService,
        stats: StatsService,
        catalog: CardCatalog,
        content: GameplayContent,
        world: WorldDefinition,
        recipes: dict[str, RecipeDefinition],
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._inventory = inventory
        self._stats = stats
        self._catalog = catalog
        self._content = content
        self._world = world
        self._recipes = recipes
        self._world_id = world.id

    def _prop(self, room_id: str, prop_instance_id: str) -> PropInstanceDefinition:
        room = self._world.rooms.get(room_id)
        if room is None:
            raise ValueError("That room does not exist.")
        prop = room.props.get(prop_instance_id)
        if prop is None:
            raise ValueError("That crafting station is not in this room.")
        if prop.behavior != "crafting":
            raise ValueError("That prop is not a crafting station.")
        return prop

    def _require_recipe(self, prop: PropInstanceDefinition, recipe_id: str) -> RecipeDefinition:
        if recipe_id not in prop.recipes:
            raise ValueError("That crafting station does not offer that recipe.")
        recipe = self._recipes.get(recipe_id)
        if recipe is None:
            raise ValueError("That recipe is not defined.")
        return recipe

    def _slotted(self, account_id: str) -> set[str]:
        profile = self._profiles.get_user_profile(account_id)
        if profile is None:
            return set()
        return {stack_id for stack_id in profile.skills if stack_id}

    def _eligible_stacks(self, account_id: str, card_id: str, slotted: set[str]) -> tuple[StackOption, ...]:
        return tuple(
            StackOption(stack_id=stack.stack_id, quantity=stack.quantity, equipped=stack.equipped)
            for stack in self._profiles.list_inventory(account_id, self._world_id)
            if stack.card_def_id == card_id and stack.stack_id not in slotted
        )

    def preview(self, account: AccountRecord, room_id: str, prop_instance_id: str, recipe_id: str) -> CraftPreview:
        """Preview a recipe with the account's eligible source stacks."""

        prop = self._prop(room_id, prop_instance_id)
        recipe = self._require_recipe(prop, recipe_id)
        slotted = self._slotted(account.id)
        ingredients = tuple(
            IngredientPreview(
                card_id=ingredient.card_id,
                label=self._catalog.cards[ingredient.card_id].label,
                quantity=ingredient.quantity,
                stacks=self._eligible_stacks(account.id, ingredient.card_id, slotted),
            )
            for ingredient in recipe.ingredients
        )
        output = tuple(
            OutputPreview(
                card_id=item.card_id,
                label=self._catalog.cards[item.card_id].label,
                quantity=item.quantity,
            )
            for item in recipe.output
        )
        return CraftPreview(
            recipe_id=recipe.id,
            label=recipe.label,
            description=recipe.description,
            energy_cost=recipe.energy_cost,
            ingredients=ingredients,
            output=output,
        )

    def craft(
        self,
        account: AccountRecord,
        room_id: str,
        prop_instance_id: str,
        recipe_id: str,
        selections: dict[str, int],
    ) -> CraftResult:
        """Craft one recipe atomically."""

        prop = self._prop(room_id, prop_instance_id)
        recipe = self._require_recipe(prop, recipe_id)
        with self._hub.transaction() as connection:
            self._consume(connection, account, recipe, selections)
            for item in recipe.output:
                grant_card_to_inventory(
                    self._profiles,
                    connection,
                    account_id=account.id,
                    definition=self._catalog.cards[item.card_id],
                    world_id=self._world_id,
                )
            if recipe.energy_cost:
                snapshot = self._stats.charge_in_transaction(connection, account.id, recipe.energy_cost)
            else:
                snapshot = self._stats.reconcile_in_transaction(connection, account.id)
            outputs = tuple(
                OutputPreview(
                    card_id=item.card_id,
                    label=self._catalog.cards[item.card_id].label,
                    quantity=item.quantity,
                )
                for item in recipe.output
            )
            stacks = tuple(self._profiles.list_inventory(account.id, self._world_id))
        return CraftResult(recipe_id=recipe.id, label=recipe.label, outputs=outputs, stacks=stacks, snapshot=snapshot)

    def _consume(
        self,
        connection: sqlite3.Connection,
        account: AccountRecord,
        recipe: RecipeDefinition,
        selections: dict[str, int],
    ) -> None:
        if not selections:
            raise ValueError("Choose the ingredient stacks to use.")
        slotted = self._slotted(account.id)
        inventory = {
            stack.stack_id: stack
            for stack in self._profiles.list_inventory(account.id, self._world_id)
        }
        required = {ingredient.card_id: ingredient.quantity for ingredient in recipe.ingredients}
        selected: dict[str, int] = {}
        for stack_id, quantity in selections.items():
            stack = inventory.get(stack_id)
            if stack is None:
                raise ValueError("One of the selected stacks is not in your inventory.")
            if stack_id in slotted:
                raise ValueError("Remove slotted skill copies before using them as ingredients.")
            if stack.card_def_id not in required:
                raise ValueError("One of the selected stacks is not an ingredient in this recipe.")
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
                raise ValueError("Ingredient quantities must be positive integers.")
            if quantity > stack.quantity:
                raise ValueError("You do not have that many copies in the selected stack.")
            selected[stack.card_def_id] = selected.get(stack.card_def_id, 0) + quantity
        if selected != required:
            raise ValueError("Select exactly the required ingredients for this recipe.")
        for stack_id, quantity in selections.items():
            self._profiles.remove_inventory_quantity(
                connection,
                account_id=account.id,
                world_id=self._world_id,
                stack_id=stack_id,
                quantity=quantity,
            )
