"""Milestone 2 card action, emote, and affordability tests."""

from __future__ import annotations

import unittest

from server.services.actions import ActionsService
from server.services.inventory import InventoryService
from server.services.stats import StatsService
from tests.common import ServiceTestCase, WORLD_ID


class ActionsTestCase(ServiceTestCase):
    """Provide isolated action services and ready accounts."""

    def setUp(self) -> None:
        super().setUp()
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.inventory = InventoryService(
            self.hub, self.profiles, self.stats, self.catalog, self.content.levels, WORLD_ID
        )
        self.actions = ActionsService(self.hub, self.profiles, self.stats, self.catalog, WORLD_ID)
        self.alice = self.create_account("Alice")
        self.bob = self.create_account("Bob")

    def _equipped(self, account, card_id: str, quantity: int = 1) -> str:
        stack_id = self.grant_card(account, card_id, quantity)
        self.inventory.equip(self.reload_account(account), stack_id)
        return stack_id


class HealingActionTests(ActionsTestCase):
    """Tasty Toast and Tomato Sauce healing rules."""

    def test_tomato_sauce_heals_self_for_25(self) -> None:
        stack_id = self._equipped(self.alice, "tomato-sauce")
        self.stats.mutate(self.alice.id, health_delta=-30)
        result = self.actions.use_card(self.reload_account(self.alice), stack_id=stack_id)
        self.assertEqual(result.actor.health, 45)
        self.assertTrue(result.consumed)

    def test_healing_another_peep(self) -> None:
        stack_id = self._equipped(self.alice, "tomato-sauce")
        self.stats.mutate(self.bob.id, health_delta=-30)
        result = self.actions.use_card(
            self.reload_account(self.alice),
            stack_id=stack_id,
            target_account_id=self.bob.id,
            target_label="Bob",
        )
        self.assertEqual(result.actor.health, 50)
        self.assertEqual(self.stats.reconcile(self.bob.id).health, 45)

    def test_full_health_rejected_without_cost(self) -> None:
        stack_id = self._equipped(self.alice, "tasty-toast")
        with self.assertRaises(ValueError):
            self.actions.use_card(self.reload_account(self.alice), stack_id=stack_id)
        stacks = [s for s in self.profiles.list_inventory(self.alice.id, WORLD_ID) if s.card_def_id == "tasty-toast"]
        self.assertEqual(sum(stack.quantity for stack in stacks), 1)

    def test_npc_rejects_healing(self) -> None:
        stack_id = self._equipped(self.alice, "tasty-toast")
        self.stats.mutate(self.alice.id, health_delta=-20)
        with self.assertRaises(ValueError):
            self.actions.use_card(
                self.reload_account(self.alice),
                stack_id=stack_id,
                target_account_id=None,
                target_label="Molly",
                target_is_npc=True,
            )

    def test_requires_equipment(self) -> None:
        stack_id = self.grant_card(self.alice, "tasty-toast")
        self.stats.mutate(self.alice.id, health_delta=-20)
        with self.assertRaises(ValueError):
            self.actions.use_card(self.reload_account(self.alice), stack_id=stack_id)


class EnergyActionTests(ActionsTestCase):
    """Juicy Drink refill rules."""

    def test_juicy_drink_restores_25_and_costs_no_energy(self) -> None:
        stack_id = self._equipped(self.alice, "juicy-drink")
        self.set_energy(self.alice, 10)
        before = self.stats.reconcile(self.alice.id)
        result = self.actions.use_card(self.reload_account(self.alice), stack_id=stack_id)
        self.assertAlmostEqual(result.actor.energy, 35, delta=0.5)
        self.assertAlmostEqual(result.actor.energy - before.energy, 25, delta=0.5)

    def test_juicy_drink_works_while_tired(self) -> None:
        stack_id = self._equipped(self.alice, "juicy-drink")
        self.set_energy(self.alice, 0)
        self.stats.reconcile(self.alice.id)
        result = self.actions.use_card(self.reload_account(self.alice), stack_id=stack_id)
        self.assertGreater(result.actor.energy, 0)

    def test_one_use_consumes_single_copy(self) -> None:
        stack_id = self._equipped(self.alice, "juicy-drink", quantity=3)
        self.set_energy(self.alice, 10)
        self.actions.use_card(self.reload_account(self.alice), stack_id=stack_id)
        stacks = [s for s in self.profiles.list_inventory(self.alice.id, WORLD_ID) if s.card_def_id == "juicy-drink"]
        self.assertEqual(sum(stack.quantity for stack in stacks), 2)


class PassiveAndDecorativeTests(ActionsTestCase):
    """Passive equipment and decorative collectibles have no Use action."""

    def test_passive_and_decorative_have_no_use(self) -> None:
        for card_id in ("ballet-shoes", "lucille"):
            with self.subTest(card_id=card_id):
                stack_id = self._equipped(self.alice, card_id)
                with self.assertRaises(ValueError):
                    self.actions.use_card(self.reload_account(self.alice), stack_id=stack_id)


class EmoteTests(ActionsTestCase):
    """Expression, Animation, and Effects emote costs and presentation."""

    def test_emote_costs_by_category(self) -> None:
        for card_id, cost in (("smile", 1), ("wave", 3), ("starlight", 5)):
            with self.subTest(card_id=card_id):
                account = self.create_account(f"Emote-{card_id}")
                stack_id = self.grant_card(account, card_id, scope="global")
                self.set_energy(account, 20)
                result = self.actions.use_emote(self.reload_account(account), stack_id=stack_id)
                self.assertAlmostEqual(result.actor.energy, 20 - cost, delta=0.2)

    def test_effects_enter_room_queue(self) -> None:
        stack_id = self.grant_card(self.alice, "starlight", scope="global")
        self.set_energy(self.alice, 20)
        result = self.actions.use_emote(self.reload_account(self.alice), stack_id=stack_id)
        self.assertIsNotNone(result.room_effect)

    def test_emote_blocked_while_tired(self) -> None:
        stack_id = self.grant_card(self.alice, "smile", scope="global")
        self.set_energy(self.alice, 0)
        self.stats.reconcile(self.alice.id)
        with self.assertRaises(ValueError):
            self.actions.use_emote(self.reload_account(self.alice), stack_id=stack_id)


if __name__ == "__main__":
    unittest.main()
