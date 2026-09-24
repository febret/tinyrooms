"""Card sell pricing and inventory selling rules."""

from __future__ import annotations

import unittest

from server.services.pricing import CardPricingService
from server.services.progression import ProgressionService
from server.services.stats import StatsService
from tests.common import ServiceTestCase, WORLD_ID


class CardPricingTestCase(ServiceTestCase):
    """Provide isolated pricing services and a ready seller account."""

    def setUp(self) -> None:
        super().setUp()
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.progression = ProgressionService(
            self.hub, self.profiles, self.stats, self.catalog, self.content, WORLD_ID
        )
        self.pricing = CardPricingService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.account = self.create_account("Seller")

    def _reload(self):
        return self.reload_account(self.account)


class SellValueTests(CardPricingTestCase):
    """Rarity-based values and sellability."""

    def test_value_by_rarity_and_default(self) -> None:
        cases = {
            "tasty-toast": 1,
            "wave": 1,
            "starlight": 2,
            "spirited": 2,
        }
        for card_id, expected in cases.items():
            with self.subTest(card_id=card_id):
                self.assertEqual(self.pricing.sell_value(self.catalog.cards[card_id]), expected)

    def test_unknown_rarity_falls_back_to_default(self) -> None:
        definition = self.catalog.cards["fancy-wallet"]
        self.assertEqual(self.pricing.sell_value(definition), self.content.card_prices.default)

    def test_sellability_rules(self) -> None:
        self.assertTrue(self.pricing.is_sellable(self.catalog.cards["juicy-drink"]))
        self.assertFalse(self.pricing.is_sellable(self.catalog.cards["house-key"]))
        self.assertFalse(self.pricing.is_sellable(self.catalog.cards["emotes"]))


class SellTransactionTests(CardPricingTestCase):
    """Selling credits Bops and mutates inventory atomically."""

    def test_sell_credits_bops_and_decrements_stack(self) -> None:
        stack_id = self.grant_card(self.account, "juicy-drink", 3)
        before = self._reload().bops
        result = self.pricing.sell(self._reload(), stack_id, 2)
        self.assertEqual(result.bops_gained, 2)
        self.assertEqual(result.account.bops, before + 2)
        stacks = [s for s in self.profiles.list_inventory(self.account.id, WORLD_ID) if s.card_def_id == "juicy-drink"]
        self.assertEqual(sum(stack.quantity for stack in stacks), 1)

    def test_selling_whole_stack_removes_it(self) -> None:
        stack_id = self.grant_card(self.account, "starlight", 2, scope="global")
        result = self.pricing.sell(self._reload(), stack_id, 2)
        self.assertEqual(result.bops_gained, 4)
        stacks = [s for s in self.profiles.list_inventory(self.account.id, WORLD_ID) if s.card_def_id == "starlight"]
        self.assertEqual(stacks, [])

    def test_quest_cards_cannot_be_sold(self) -> None:
        stack_id = self.grant_card(self.account, "house-key", 1)
        with self.assertRaises(ValueError):
            self.pricing.sell(self._reload(), stack_id, 1)

    def test_invalid_quantity_rejected(self) -> None:
        stack_id = self.grant_card(self.account, "juicy-drink", 1)
        with self.assertRaises(ValueError):
            self.pricing.sell(self._reload(), stack_id, 2)

    def test_slotted_skill_copies_cannot_be_sold(self) -> None:
        self.set_progress(self.account, level=1)
        stack_id = self.grant_card(self.account, "sturdy", 1, scope="global")
        self.progression.slot_skill(self._reload(), 0, stack_id)
        with self.assertRaises(ValueError):
            self.pricing.sell(self._reload(), stack_id, 1)


if __name__ == "__main__":
    unittest.main()
