"""Milestone 2 stats, Energy, and status persistence tests."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from server.content.cards import load_card_catalog
from server.content.gameplay import load_gameplay_content
from server.profiles import ProfileRepository
from server.security import utc_now
from server.services.stats import StatsService
from server.state.migrations import DatabaseHub, ensure_profile_database, ensure_world_database
from tests.common import REPO_ROOT

WORLD_ID = "tutorial"
ENTRY_ROOM = "hub"


class StatsServiceTestCase(unittest.TestCase):
    """Provide an isolated database and stats service."""

    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        profile_path = root / "profiles.sqlite3"
        world_path = root / "worldstate.sqlite3"
        ensure_profile_database(profile_path)
        ensure_world_database(world_path)
        self.hub = DatabaseHub(profile_path, world_path)
        self.addCleanup(self.hub.close)
        self.profiles = ProfileRepository(self.hub)
        self.content = load_gameplay_content(REPO_ROOT / "data" / "core")
        self.catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", REPO_ROOT / "worlds" / WORLD_ID)
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.account = self.profiles.create_account("Tester", "password123!", WORLD_ID, ENTRY_ROOM)

    def _set_energy(self, energy: float, *, minutes_ago: float = 0.0) -> None:
        with self.hub.transaction() as connection:
            self.profiles.update_account_progress(
                connection,
                self.account.id,
                level=self.account.level,
                kudos=self.account.kudos,
                bops=self.account.bops,
                energy=energy,
                last_energy_at=(utc_now() - timedelta(minutes=minutes_ago)).isoformat(),
                last_daily_claim=self.account.last_daily_claim,
            )


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
    """Offline recovery, Tired threshold, and no-cost failures."""

    def test_offline_recovery_accrues_one_per_minute(self) -> None:
        self._set_energy(0, minutes_ago=30)
        snapshot = self.stats.reconcile(self.account.id)
        self.assertAlmostEqual(snapshot.energy, 30, delta=0.5)

    def test_recovery_caps_at_maximum(self) -> None:
        self._set_energy(0, minutes_ago=1000)
        snapshot = self.stats.reconcile(self.account.id)
        self.assertEqual(snapshot.energy, 80)

    def test_tired_applies_at_zero_and_clears_above_threshold(self) -> None:
        self._set_energy(0, minutes_ago=0)
        snapshot = self.stats.reconcile(self.account.id)
        self.assertIn("tired", snapshot.statuses)
        self._set_energy(10, minutes_ago=0)
        snapshot = self.stats.reconcile(self.account.id)
        self.assertNotIn("tired", snapshot.statuses)

    def test_spend_rejects_without_cost_when_insufficient(self) -> None:
        self._set_energy(1, minutes_ago=0)
        with self.assertRaises(ValueError):
            self.stats.spend_energy(self.account.id, 5)
        snapshot = self.stats.reconcile(self.account.id)
        self.assertAlmostEqual(snapshot.energy, 1, delta=0.2)

    def test_spend_rejects_while_tired(self) -> None:
        self._set_energy(0, minutes_ago=0)
        with self.assertRaises(ValueError):
            self.stats.spend_energy(self.account.id, 0)
        # A refill-style action may explicitly run while Tired.
        snapshot = self.stats.spend_energy(self.account.id, 0, allow_while_tired=True)
        self.assertIn("tired", snapshot.statuses)

    def test_spend_energy_deducts_and_can_apply_tired(self) -> None:
        self._set_energy(5, minutes_ago=0)
        snapshot = self.stats.spend_energy(self.account.id, 5)
        self.assertAlmostEqual(snapshot.energy, 0, delta=0.2)
        self.assertIn("tired", snapshot.statuses)

    def test_charge_more_than_available_rejected(self) -> None:
        self._set_energy(3, minutes_ago=0)
        with self.assertRaises(ValueError):
            with self.hub.transaction() as connection:
                self.stats.charge_in_transaction(connection, self.account.id, 10)


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

    def test_max_health_increase_does_not_refill(self) -> None:
        self.stats.mutate(self.account.id, health_delta=-20)
        damaged = self.stats.reconcile(self.account.id)
        self.assertEqual(damaged.health, 30)


class EquipmentAndSkillModifierTests(StatsServiceTestCase):
    """Equipment and slotted-skill bonuses feed effective state."""

    def _add_and_equip(self, card_id: str, quantity: int = 1) -> str:
        with self.hub.transaction() as connection:
            stacks = self.profiles.add_inventory_card(
                connection,
                account_id=self.account.id,
                world_id=WORLD_ID,
                card_def_id=card_id,
                quantity=quantity,
                scope="world",
                stack_limit=10,
            )
            self.profiles.set_stack_equipped(
                connection,
                account_id=self.account.id,
                world_id=WORLD_ID,
                stack_id=stacks[0].stack_id,
                equipped=True,
            )
        return stacks[0].stack_id

    def test_ballet_shoes_passive_bonuses(self) -> None:
        self._add_and_equip("ballet-shoes")
        snapshot = self.stats.reconcile(self.account.id)
        self.assertEqual(snapshot.effective.stats["charisma"], 2)
        self.assertEqual(snapshot.effective.stats["fanciness"], 3)

    def test_slotted_skill_bonus(self) -> None:
        with self.hub.transaction() as connection:
            stacks = self.profiles.add_inventory_card(
                connection,
                account_id=self.account.id,
                world_id=None,
                card_def_id="sturdy",
                quantity=1,
                scope="global",
                stack_limit=1,
            )
        stack_id = stacks[0].stack_id
        self.profiles.update_profile(
            self.account.id, lambda data: data.__setitem__("skills", [stack_id])
        )
        snapshot = self.stats.reconcile(self.account.id)
        self.assertEqual(snapshot.effective.stats["constitution"], 2)
        self.assertEqual(snapshot.effective.max_health, 100)

    def test_double_slotted_skill_requires_two_copies(self) -> None:
        with self.hub.transaction() as connection:
            stacks = self.profiles.add_inventory_card(
                connection,
                account_id=self.account.id,
                world_id=None,
                card_def_id="sturdy",
                quantity=1,
                scope="global",
                stack_limit=1,
            )
        stack_id = stacks[0].stack_id
        self.profiles.update_profile(
            self.account.id, lambda data: data.__setitem__("skills", [stack_id, stack_id])
        )
        snapshot = self.stats.reconcile(self.account.id)
        # One owned copy cannot fill two slots, so only the first slot counts.
        self.assertEqual(snapshot.effective.stats["constitution"], 2)


if __name__ == "__main__":
    unittest.main()
