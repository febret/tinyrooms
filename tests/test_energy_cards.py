"""Energy-refill cards convert unused Energy into Health."""

from __future__ import annotations

import unittest

from server.services.actions import ActionsService
from server.services.stats import StatsService
from tests.common import ServiceTestCase, WORLD_ID


class EnergyCardOverflowTests(ServiceTestCase):
    """Unused Energy-refill amounts recover half their value as Health."""

    def setUp(self) -> None:
        super().setUp()
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.actions = ActionsService(self.hub, self.profiles, self.stats, self.catalog, WORLD_ID)
        self.account = self.create_account("snacker")

    def _set_state(self, energy: float, health: float):
        account = self.set_energy(self.reload_account(self.account), energy)
        with self.hub.transaction() as connection:
            self.profiles.write_vitals(
                connection, account.id, health, 100
            )
        return self.reload_account(account)

    def _inventory_quantity(self, account_id: str, card_id: str = "juicy-drink") -> int:
        stacks = self.profiles.list_inventory(account_id, WORLD_ID)
        return sum(stack.quantity for stack in stacks if stack.card_def_id == card_id)

    def test_overflow_splits_and_clamps_to_max_health(self) -> None:
        maxima = self.stats.snapshot(self.account.id).effective
        account = self._set_state(maxima.max_energy - 5, maxima.max_health - 5)
        stack_id = self.grant_card(account, "juicy-drink", 1)

        result = self.actions.use_card(self.reload_account(account), stack_id=stack_id)

        self.assertAlmostEqual(result.effects[0].energy_delta, 5.0)
        self.assertAlmostEqual(result.effects[0].health_delta, 5.0)
        self.assertAlmostEqual(result.actor.energy, maxima.max_energy)
        self.assertAlmostEqual(result.actor.health, maxima.max_health)
        self.assertIn("Energy", result.message)
        self.assertIn("Health", result.message)

        account = self._set_state(maxima.max_energy, maxima.max_health - 5)
        stack_id = self.grant_card(account, "juicy-drink", 1)

        result = self.actions.use_card(self.reload_account(account), stack_id=stack_id)

        self.assertAlmostEqual(result.effects[0].energy_delta, 0.0)
        self.assertAlmostEqual(result.effects[0].health_delta, 5.0)
        self.assertAlmostEqual(result.actor.health, maxima.max_health)
        self.assertNotIn("Energy", result.message)
        self.assertIn("Health", result.message)

    def test_full_energy_and_health_rejects_without_consuming(self) -> None:
        maxima = self.stats.snapshot(self.account.id).effective
        account = self._set_state(maxima.max_energy, maxima.max_health)
        stack_id = self.grant_card(account, "juicy-drink", 1)

        with self.assertRaises(ValueError):
            self.actions.use_card(self.reload_account(account), stack_id=stack_id)

        self.assertEqual(self._inventory_quantity(account.id), 1)


if __name__ == "__main__":
    unittest.main()
