"""Milestone 2 stats, Energy, and status persistence tests."""

from __future__ import annotations

from datetime import timedelta
import unittest

from server.game.buffs import TIMED, BuffInstance
from server.game.modifiers import Modifier
from server.security import utc_now
from server.services.progression import ProgressionService
from server.services.stats import StatsService
from tests.common import ServiceTestCase, WORLD_ID


class StatsServiceTestCase(ServiceTestCase):
    """Provide a stats service and a ready account."""

    def setUp(self) -> None:
        super().setUp()
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.progression = ProgressionService(
            self.hub, self.profiles, self.stats, self.catalog, self.content, WORLD_ID
        )
        self.account = self.create_account("Tester")


class InitialStateTests(StatsServiceTestCase):
    """Fresh accounts start at full counters and base stats."""

    def test_new_account_full_counters(self) -> None:
        snapshot = self.stats.reconcile(self.account.id)
        self.assertEqual(snapshot.health, 50)
        self.assertEqual(snapshot.cleanliness, 100)
        self.assertAlmostEqual(snapshot.energy, 80, places=1)
        self.assertEqual(snapshot.effective.stats["constitution"], 1)
        self.assertEqual(snapshot.statuses, ())


class EnergyRecoveryTests(StatsServiceTestCase):
    """Offline recovery, Tired threshold, and charge failures."""

    def test_offline_recovery_accrues_one_per_minute(self) -> None:
        self.set_energy(self.account, 0, minutes_ago=30)
        snapshot = self.stats.reconcile(self.account.id)
        self.assertAlmostEqual(snapshot.energy, 30, delta=0.5)

    def test_recovery_caps_at_maximum(self) -> None:
        self.set_energy(self.account, 0, minutes_ago=1000)
        snapshot = self.stats.reconcile(self.account.id)
        self.assertEqual(snapshot.energy, 80)

    def test_active_play_preserves_recharge_remainder(self) -> None:
        self.set_energy(self.account, 10, minutes_ago=0.5)
        before = self.reload_account(self.account).last_energy_at
        with self.hub.transaction() as connection:
            self.stats.charge_in_transaction(connection, self.account.id, 0)
        self.assertEqual(self.reload_account(self.account).last_energy_at, before)

    def test_tired_applies_at_zero_and_clears_above_threshold(self) -> None:
        self.set_energy(self.account, 0, minutes_ago=0)
        snapshot = self.stats.reconcile(self.account.id)
        self.assertIn("tired", snapshot.statuses)
        self.set_energy(self.account, 10, minutes_ago=0)
        snapshot = self.stats.reconcile(self.account.id)
        self.assertNotIn("tired", snapshot.statuses)

    def test_charge_rejects_when_insufficient(self) -> None:
        self.set_energy(self.account, 1, minutes_ago=0)
        with self.assertRaises(ValueError):
            with self.hub.transaction() as connection:
                self.stats.charge_in_transaction(connection, self.account.id, 5)
        self.assertAlmostEqual(self.stats.reconcile(self.account.id).energy, 1, delta=0.2)

    def test_charge_blocked_while_tired_unless_allowed(self) -> None:
        self.set_energy(self.account, 0, minutes_ago=0)
        with self.assertRaises(ValueError):
            with self.hub.transaction() as connection:
                self.stats.charge_in_transaction(connection, self.account.id, 0)
        with self.hub.transaction() as connection:
            snapshot = self.stats.charge_in_transaction(
                connection, self.account.id, 0, allow_while_tired=True
            )
        self.assertIn("tired", snapshot.statuses)


class CounterMutationTests(StatsServiceTestCase):
    """Health and Cleanliness clamp and status transitions."""

    def test_health_damage_applies_sick_and_clamps(self) -> None:
        snapshot = self.stats.mutate(self.account.id, health_delta=-999)
        self.assertEqual(snapshot.health, 0)
        self.assertIn("sick", snapshot.statuses)

    def test_healing_clears_sick_and_discards_overflow(self) -> None:
        self.stats.mutate(self.account.id, health_delta=-999)
        snapshot = self.stats.mutate(self.account.id, health_delta=999)
        self.assertEqual(snapshot.health, 50)
        self.assertNotIn("sick", snapshot.statuses)

    def test_cleanliness_drop_applies_stinky(self) -> None:
        snapshot = self.stats.mutate(self.account.id, cleanliness_delta=-999)
        self.assertEqual(snapshot.cleanliness, 0)
        self.assertIn("stinky", snapshot.statuses)


class ModifierSourceTests(StatsServiceTestCase):
    """Equipment, slotted skills, and buffs feed effective state."""

    def test_ballet_shoes_passive_bonuses(self) -> None:
        stack_id = self.grant_card(self.account, "ballet-shoes")
        with self.hub.transaction() as connection:
            self.profiles.set_stack_equipped(
                connection,
                account_id=self.account.id,
                world_id=WORLD_ID,
                stack_id=stack_id,
                equipped=True,
            )
        snapshot = self.stats.reconcile(self.account.id)
        self.assertEqual(snapshot.effective.stats["charisma"], 2)
        self.assertEqual(snapshot.effective.stats["fanciness"], 3)

    def test_slotted_skill_bonus(self) -> None:
        self.set_progress(self.account, level=1)
        stack_id = self.grant_card(self.account, "sturdy", scope="global")
        snapshot = self.progression.slot_skill(self.reload_account(self.account), 0, stack_id)
        self.assertEqual(snapshot.effective.stats["constitution"], 2)
        self.assertEqual(snapshot.effective.max_health, 100)

    def test_buff_modifiers_feed_effective_state(self) -> None:
        self.stats.add_buff(
            self.account.id,
            BuffInstance(
                id="test-glow",
                label="Test Glow",
                kind=TIMED,
                expires_at=utc_now() + timedelta(minutes=5),
                modifiers=(Modifier(target="constitution", flat=1),),
            ),
        )
        snapshot = self.stats.reconcile(self.account.id)
        self.assertEqual(snapshot.effective.stats["constitution"], 2)


if __name__ == "__main__":
    unittest.main()
