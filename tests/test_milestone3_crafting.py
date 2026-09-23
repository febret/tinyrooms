"""Milestone 3 Phase C crafting tests."""

from __future__ import annotations

from dataclasses import replace
import threading
import unittest

from server.content.recipes import Ingredient, RecipeDefinition
from server.services.crafting import CraftingService
from server.services.inventory import InventoryService
from server.services.progression import ProgressionService
from server.services.stats import StatsService
from tests.common import REPO_ROOT, WORLD_ID, ServiceTestCase, load_test_world


class CraftingTestCase(ServiceTestCase):
    """Shared crafting fixtures built on the tutorial world."""

    def setUp(self) -> None:
        super().setUp()
        self.world = load_test_world(REPO_ROOT / "worlds" / "tutorial", set(self.catalog.cards))
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.inventory = InventoryService(self.hub, self.profiles, self.stats, self.catalog, self.content.levels, WORLD_ID)
        self.crafting = self._service(self.world)

    def _service(self, world) -> CraftingService:
        return CraftingService(
            self.hub, self.profiles, self.inventory, self.stats, self.catalog, self.content, world, world.recipes
        )

    def _world_with_recipe(self, recipe: RecipeDefinition):
        prop = replace(self.world.rooms["kitchen"].props["workbench0"], recipes=(recipe.id,))
        room = replace(self.world.rooms["kitchen"], props={**self.world.rooms["kitchen"].props, "workbench0": prop})
        return replace(
            self.world,
            rooms={**self.world.rooms, "kitchen": room},
            recipes={**self.world.recipes, recipe.id: recipe},
        )


class CraftPreviewTests(CraftingTestCase):
    """Previews show recipes, outputs, and eligible source stacks."""

    def test_preview_lists_ingredients_and_stacks(self) -> None:
        account = self.create_account("ada")
        self.grant_card(account, "poop", 2)
        self.grant_card(account, "plastic-bag", 1)
        preview = self.crafting.preview(account, "kitchen", "workbench0", "bagged-poop")
        self.assertEqual(preview.recipe_id, "bagged-poop")
        self.assertEqual({item.card_id for item in preview.output}, {"poop-in-a-bag"})
        ingredients = {item.card_id: item for item in preview.ingredients}
        self.assertEqual(ingredients["poop"].quantity, 1)
        self.assertEqual(sum(stack.quantity for stack in ingredients["poop"].stacks), 2)
        self.assertEqual(len(ingredients["plastic-bag"].stacks), 1)

    def test_equipped_stack_is_shown(self) -> None:
        recipe = RecipeDefinition(
            id="test-wallet",
            label="Walletcraft",
            description="",
            ingredients=(Ingredient("fancy-wallet", 1),),
            output=(Ingredient("poop", 1),),
        )
        crafting = self._service(self._world_with_recipe(recipe))
        account = self.create_account("bea")
        stack_id = self.grant_card(account, "fancy-wallet", 1)
        self.inventory.equip(account, stack_id)
        preview = crafting.preview(account, "kitchen", "workbench0", "test-wallet")
        stacks = preview.ingredients[0].stacks
        self.assertEqual(len(stacks), 1)
        self.assertTrue(stacks[0].equipped)

    def test_slotted_skill_stack_is_excluded(self) -> None:
        recipe = RecipeDefinition(
            id="test-skill",
            label="Skillcraft",
            description="",
            ingredients=(Ingredient("sturdy", 1),),
            output=(Ingredient("poop", 1),),
        )
        crafting = self._service(self._world_with_recipe(recipe))
        account = self.create_account("cam")
        stack_id = self.grant_card(account, "sturdy", 1)
        progression = ProgressionService(self.hub, self.profiles, self.stats, self.catalog, self.content, WORLD_ID)
        account = self.set_progress(account, level=1)
        progression.slot_skill(account, 0, stack_id)
        preview = crafting.preview(account, "kitchen", "workbench0", "test-skill")
        self.assertEqual(preview.ingredients[0].stacks, ())


class CraftExecutionTests(CraftingTestCase):
    """Crafts consume, grant, and record atomically and idempotently."""

    def test_craft_consumes_and_grants(self) -> None:
        account = self.create_account("dee")
        poop_id = self.grant_card(account, "poop", 2)
        bag_id = self.grant_card(account, "plastic-bag", 1)
        self.crafting.craft(account, "kitchen", "workbench0", "bagged-poop", {poop_id: 1, bag_id: 1})
        inventory = {stack.card_def_id: stack for stack in self.profiles.list_inventory(account.id, WORLD_ID)}
        self.assertEqual(inventory["poop"].quantity, 1)
        self.assertNotIn("plastic-bag", inventory)
        self.assertEqual(inventory["poop-in-a-bag"].quantity, 1)

    def test_invalid_selection_consumes_nothing(self) -> None:
        account = self.create_account("eva")
        poop_id = self.grant_card(account, "poop", 2)
        self.grant_card(account, "plastic-bag", 1)
        with self.assertRaises(ValueError):
            self.crafting.craft(account, "kitchen", "workbench0", "bagged-poop", {poop_id: 1})
        inventory = {stack.card_def_id: stack.quantity for stack in self.profiles.list_inventory(account.id, WORLD_ID)}
        self.assertEqual(inventory["poop"], 2)
        self.assertEqual(inventory["plastic-bag"], 1)
        self.assertNotIn("poop-in-a-bag", inventory)

    def test_equipped_bonus_updates_on_consume(self) -> None:
        recipe = RecipeDefinition(
            id="test-shoes",
            label="Shoecraft",
            description="",
            ingredients=(Ingredient("ballet-shoes", 1),),
            output=(Ingredient("poop", 1),),
        )
        crafting = self._service(self._world_with_recipe(recipe))
        account = self.create_account("gus")
        stack_id = self.grant_card(account, "ballet-shoes", 1)
        self.inventory.equip(account, stack_id)
        self.assertEqual(self.stats.view(account.id).effective.stats["charisma"], 2)
        crafting.craft(account, "kitchen", "workbench0", "test-shoes", {stack_id: 1})
        snapshot = self.stats.view(account.id)
        self.assertEqual(snapshot.effective.stats["charisma"], 1)
        self.assertEqual(snapshot.effective.stats["fanciness"], 1)

    def test_concurrent_crafts_do_not_double_consume(self) -> None:
        recipe = RecipeDefinition(
            id="test-solo",
            label="Solocraft",
            description="",
            ingredients=(Ingredient("fancy-wallet", 1),),
            output=(Ingredient("poop", 1),),
        )
        crafting = self._service(self._world_with_recipe(recipe))
        account = self.create_account("hana")
        stack_id = self.grant_card(account, "fancy-wallet", 1)
        results: list[object] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                results.append(crafting.craft(account, "kitchen", "workbench0", "test-solo", {stack_id: 1}))
            except Exception as exc:  # noqa: BLE001 - test captures the rejected craft
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        inventory = {stack.card_def_id: stack.quantity for stack in self.profiles.list_inventory(account.id, WORLD_ID)}
        self.assertEqual(inventory["poop"], 1)


if __name__ == "__main__":
    unittest.main()
