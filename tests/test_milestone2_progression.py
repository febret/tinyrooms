"""Milestone 2 progression and inventory rules tests."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from server.content.cards import load_card_catalog
from server.content.gameplay import load_gameplay_content
from server.profiles import ProfileRepository
from server.services.inventory import InventoryService
from server.services.progression import MAX_SKILL_SLOTS, ProgressionService
from server.services.stats import StatsService
from server.state.migrations import DatabaseHub, ensure_profile_database, ensure_world_database
from tests.common import REPO_ROOT

WORLD_ID = "tutorial"


class ProgressionTestCase(unittest.TestCase):
    """Provide isolated services for progression and inventory tests."""

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
        self.inventory = InventoryService(
            self.hub, self.profiles, self.stats, self.catalog, self.content.levels, WORLD_ID
        )
        self.progression = ProgressionService(
            self.hub, self.profiles, self.stats, self.catalog, self.content, WORLD_ID
        )
        self.account = self.profiles.create_account("Tester", "password123!", WORLD_ID, "hub")

    def _reload(self):
        return self.profiles.get_account_by_id(self.account.id)

    def _add(self, card_id: str, quantity: int = 1, *, scope: str = "world"):
        with self.hub.transaction() as connection:
            stacks = self.profiles.add_inventory_card(
                connection,
                account_id=self.account.id,
                world_id=WORLD_ID if scope == "world" else None,
                card_def_id=card_id,
                quantity=quantity,
                scope=scope,
                stack_limit=self.catalog.cards[card_id].stack_limit,
            )
        return stacks[0].stack_id

    def _set_kudos(self, kudos: int) -> None:
        with self.hub.transaction() as connection:
            account = self.profiles.get_account_by_id(self.account.id)
            self.profiles.update_account_progress(
                connection,
                account.id,
                level=account.level,
                kudos=kudos,
                bops=account.bops,
                energy=account.shared_energy,
                last_energy_at=account.last_energy_at,
                last_daily_claim=account.last_daily_claim,
            )


class LevelUpTests(ProgressionTestCase):
    """Explicit level transitions and Kudos spending."""

    def test_level_up_spends_only_required_kudos_and_retains_surplus(self) -> None:
        self._set_kudos(10)
        result = self.progression.level_up(self._reload())
        self.assertEqual(result.spent, 1)
        self.assertEqual(result.account.level, 1)
        self.assertEqual(result.account.kudos, 9)

    def test_level_up_rejected_without_enough_kudos(self) -> None:
        self._set_kudos(0)
        with self.assertRaises(ValueError):
            self.progression.level_up(self._reload())

    def test_level_up_stops_at_cap_and_kudos_keep_accruing(self) -> None:
        with self.hub.transaction() as connection:
            account = self.profiles.get_account_by_id(self.account.id)
            self.profiles.update_account_progress(
                connection,
                account.id,
                level=15,
                kudos=0,
                bops=account.bops,
                energy=account.shared_energy,
                last_energy_at=account.last_energy_at,
                last_daily_claim=account.last_daily_claim,
            )
        with self.assertRaises(ValueError):
            self.progression.level_up(self._reload())
        self.progression.grant_kudos(self.account.id, 5)
        self.assertEqual(self._reload().kudos, 5)

    def test_level_up_surplus_retained_at_higher_cost(self) -> None:
        with self.hub.transaction() as connection:
            account = self.profiles.get_account_by_id(self.account.id)
            self.profiles.update_account_progress(
                connection,
                account.id,
                level=1,
                kudos=10,
                bops=account.bops,
                energy=account.shared_energy,
                last_energy_at=account.last_energy_at,
                last_daily_claim=account.last_daily_claim,
            )
        result = self.progression.level_up(self._reload())
        self.assertEqual(result.spent, 3)
        self.assertEqual(result.account.level, 2)
        self.assertEqual(result.account.kudos, 7)


class DailyBopsTests(ProgressionTestCase):
    """Once-per-game-day Bops claiming."""

    def test_claim_grants_level_allowance_and_is_once_per_day(self) -> None:
        amount, updated = self.progression.claim_daily_bops(self._reload())
        self.assertEqual(amount, 1)
        self.assertEqual(updated.bops, 11)
        with self.assertRaises(ValueError):
            self.progression.claim_daily_bops(self._reload())

    def test_claim_uses_level_at_claim_time(self) -> None:
        with self.hub.transaction() as connection:
            account = self.profiles.get_account_by_id(self.account.id)
            self.profiles.update_account_progress(
                connection,
                account.id,
                level=2,
                kudos=account.kudos,
                bops=account.bops,
                energy=account.shared_energy,
                last_energy_at=account.last_energy_at,
                last_daily_claim=account.last_daily_claim,
            )
        amount, _ = self.progression.claim_daily_bops(self._reload())
        self.assertEqual(amount, 10)


class RewardLedgerTests(ProgressionTestCase):
    """Idempotent reward granting."""

    def test_reward_once_grants_kudos_exactly_once(self) -> None:
        self.assertTrue(self.progression.reward_once(self.account.id, "task:portal", kudos=3))
        self.assertFalse(self.progression.reward_once(self.account.id, "task:portal", kudos=3))
        self.assertEqual(self._reload().kudos, 3)

    def test_reward_once_grants_cards_exactly_once(self) -> None:
        self.assertTrue(
            self.progression.reward_once(self.account.id, "task:sturdy", cards=["sturdy"])
        )
        self.assertFalse(
            self.progression.reward_once(self.account.id, "task:sturdy", cards=["sturdy"])
        )
        stacks = [s for s in self.profiles.list_inventory(self.account.id, WORLD_ID) if s.card_def_id == "sturdy"]
        self.assertEqual(sum(stack.quantity for stack in stacks), 1)


class SkillSlotTests(ProgressionTestCase):
    """Skill-grid unlock, rank, and ownership rules."""

    def _skill_stack(self, card_id: str, quantity: int = 1) -> str:
        with self.hub.transaction() as connection:
            stacks = self.profiles.add_inventory_card(
                connection,
                account_id=self.account.id,
                world_id=None,
                card_def_id=card_id,
                quantity=quantity,
                scope="global",
                stack_limit=1,
            )
        return stacks[0].stack_id

    def _level_to(self, level: int) -> None:
        with self.hub.transaction() as connection:
            account = self.profiles.get_account_by_id(self.account.id)
            self.profiles.update_account_progress(
                connection,
                account.id,
                level=level,
                kudos=account.kudos,
                bops=account.bops,
                energy=account.shared_energy,
                last_energy_at=account.last_energy_at,
                last_daily_claim=account.last_daily_claim,
            )

    def test_slots_are_locked_below_level(self) -> None:
        self._level_to(1)
        stack_id = self._skill_stack("sturdy")
        with self.assertRaises(ValueError):
            self.progression.slot_skill(self._reload(), 1, stack_id)
        snapshot = self.progression.slot_skill(self._reload(), 0, stack_id)
        self.assertEqual(snapshot.effective.stats["constitution"], 2)

    def test_locked_slot_rejected(self) -> None:
        stack_id = self._skill_stack("sturdy")
        with self.assertRaises(ValueError):
            self.progression.slot_skill(self._reload(), 0, stack_id)

    def test_rank_eligibility_allows_card_in_higher_rank_slot(self) -> None:
        self._level_to(15)
        spirited = self._skill_stack("spirited")
        snapshot = self.progression.slot_skill(self._reload(), 7, spirited)
        self.assertEqual(snapshot.effective.max_energy, 340)

    def test_slotted_skill_bonus_and_removal(self) -> None:
        self._level_to(1)
        stack_id = self._skill_stack("sturdy")
        snapshot = self.progression.slot_skill(self._reload(), 0, stack_id)
        self.assertEqual(snapshot.effective.stats["constitution"], 2)
        snapshot = self.progression.remove_skill(self._reload(), 0)
        self.assertEqual(snapshot.effective.stats["constitution"], 1)

    def test_one_copy_cannot_fill_two_slots(self) -> None:
        self._level_to(2)
        stack_id = self._skill_stack("sturdy")
        self.progression.slot_skill(self._reload(), 0, stack_id)
        with self.assertRaises(ValueError):
            self.progression.slot_skill(self._reload(), 1, stack_id)

    def test_two_copies_fill_two_slots(self) -> None:
        self._level_to(2)
        stack_id = self._skill_stack("sturdy")
        self.progression.slot_skill(self._reload(), 0, stack_id)
        with self.hub.transaction() as connection:
            self.profiles.set_stack_quantity(
                connection, account_id=self.account.id, stack_id=stack_id, quantity=2
            )
        snapshot = self.progression.slot_skill(self._reload(), 1, stack_id)
        self.assertEqual(snapshot.effective.stats["constitution"], 3)


class InventoryRuleTests(ProgressionTestCase):
    """Stack fill, split, merge, equip, and slot-cap invariants."""

    def test_acquisition_fills_existing_then_creates_new(self) -> None:
        self._add("juicy-drink", 8)
        self._add("juicy-drink", 5)
        stacks = [s for s in self.profiles.list_inventory(self.account.id, WORLD_ID) if s.card_def_id == "juicy-drink"]
        self.assertEqual(sorted(s.quantity for s in stacks), [3, 10])

    def test_split_creates_unequipped_stack(self) -> None:
        stack_id = self._add("juicy-drink", 5)
        self.inventory.equip(self._reload(), stack_id)
        self.inventory.split(self._reload(), stack_id, 2)
        stacks = [s for s in self.profiles.list_inventory(self.account.id, WORLD_ID) if s.card_def_id == "juicy-drink"]
        equipped = [s for s in stacks if s.equipped]
        self.assertEqual(len(equipped), 1)
        self.assertEqual(equipped[0].quantity, 3)
        self.assertEqual(sorted(s.quantity for s in stacks), [2, 3])

    def test_merge_respects_destination_limit(self) -> None:
        first = self._add("juicy-drink", 8)
        with self.hub.transaction() as connection:
            second = self.profiles.create_inventory_stack(
                connection,
                account_id=self.account.id,
                world_id=WORLD_ID,
                card_def_id="juicy-drink",
                quantity=5,
                scope="world",
            )
        self.inventory.merge(self._reload(), second.stack_id, first)
        stacks = [s for s in self.profiles.list_inventory(self.account.id, WORLD_ID) if s.card_def_id == "juicy-drink"]
        self.assertEqual(sorted(s.quantity for s in stacks), [3, 10])

    def test_equip_cap_counts_stacks(self) -> None:
        stack_ids = []
        for _ in range(6):
            with self.hub.transaction() as connection:
                stack = self.profiles.create_inventory_stack(
                    connection,
                    account_id=self.account.id,
                    world_id=WORLD_ID,
                    card_def_id="juicy-drink",
                    quantity=1,
                    scope="world",
                )
            stack_ids.append(stack.stack_id)
        account = self._reload()
        for stack_id in stack_ids[:5]:
            self.inventory.equip(account, stack_id)
        with self.assertRaises(ValueError):
            self.inventory.equip(self._reload(), stack_ids[5])

    def test_non_equippable_types_rejected(self) -> None:
        emote = self._add("smile", scope="global")
        with self.assertRaises(ValueError):
            self.inventory.equip(self._reload(), emote)

    def test_equip_updates_passive_bonuses_and_unequip_reverts(self) -> None:
        stack_id = self._add("ballet-shoes")
        snapshot = self.inventory.equip(self._reload(), stack_id).snapshot
        self.assertEqual(snapshot.effective.stats["fanciness"], 3)
        snapshot = self.inventory.unequip(self._reload(), stack_id).snapshot
        self.assertEqual(snapshot.effective.stats["fanciness"], 1)


if __name__ == "__main__":
    unittest.main()
