"""Milestone 2 progression and inventory rules tests."""

from __future__ import annotations

import unittest

from server.services.inventory import InventoryService
from server.services.progression import ProgressionService
from server.services.stats import StatsService
from tests.common import ServiceTestCase, WORLD_ID


class ProgressionTestCase(ServiceTestCase):
    """Provide isolated progression services and a ready account."""

    def setUp(self) -> None:
        super().setUp()
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.inventory = InventoryService(
            self.hub, self.profiles, self.stats, self.catalog, self.content.levels, WORLD_ID
        )
        self.progression = ProgressionService(
            self.hub, self.profiles, self.stats, self.catalog, self.content, WORLD_ID
        )
        self.account = self.create_account("Tester")

    def _reload(self):
        return self.reload_account(self.account)


class LevelUpTests(ProgressionTestCase):
    """Explicit level transitions and Kudos spending."""

    def test_level_up_spends_only_required_kudos_and_retains_surplus(self) -> None:
        self.set_progress(self.account, kudos=10)
        result = self.progression.level_up(self._reload())
        self.assertEqual(result.spent, 1)
        self.assertEqual(result.account.level, 1)
        self.assertEqual(result.account.kudos, 9)

    def test_level_up_rejected_without_enough_kudos(self) -> None:
        self.set_progress(self.account, kudos=0)
        with self.assertRaises(ValueError):
            self.progression.level_up(self._reload())

    def test_level_up_stops_at_cap_but_kudos_still_accrue(self) -> None:
        self.set_progress(self.account, level=15, kudos=0)
        with self.assertRaises(ValueError):
            self.progression.level_up(self._reload())
        self.progression.reward_once(self.account.id, "test:bonus", kudos=5)
        self.assertEqual(self._reload().kudos, 5)


class DailyBopsTests(ProgressionTestCase):
    """Once-per-game-day Bops claiming."""

    def test_claim_grants_level_allowance_and_is_once_per_day(self) -> None:
        amount, updated = self.progression.claim_daily_bops(self._reload())
        self.assertEqual(amount, 1)
        self.assertEqual(updated.bops, 11)
        with self.assertRaises(ValueError):
            self.progression.claim_daily_bops(self._reload())

    def test_claim_uses_level_at_claim_time(self) -> None:
        self.set_progress(self.account, level=2)
        amount, _ = self.progression.claim_daily_bops(self._reload())
        self.assertEqual(amount, 10)


class RewardLedgerTests(ProgressionTestCase):
    """Idempotent reward granting."""

    def test_reward_once_grants_kudos_exactly_once(self) -> None:
        self.assertTrue(self.progression.reward_once(self.account.id, "task:portal", kudos=3))
        self.assertFalse(self.progression.reward_once(self.account.id, "task:portal", kudos=3))
        self.assertEqual(self._reload().kudos, 3)

    def test_reward_once_grants_cards_exactly_once(self) -> None:
        self.assertTrue(self.progression.reward_once(self.account.id, "task:sturdy", cards=["sturdy"]))
        self.assertFalse(self.progression.reward_once(self.account.id, "task:sturdy", cards=["sturdy"]))
        stacks = [s for s in self.profiles.list_inventory(self.account.id, WORLD_ID) if s.card_def_id == "sturdy"]
        self.assertEqual(sum(stack.quantity for stack in stacks), 1)


class SkillSlotTests(ProgressionTestCase):
    """Skill-grid unlock, rank, and ownership rules."""

    def _skill_stack(self, card_id: str, quantity: int = 1) -> str:
        return self.grant_card(self.account, card_id, quantity, scope="global")

    def test_slots_are_locked_below_level(self) -> None:
        self.set_progress(self.account, level=1)
        stack_id = self._skill_stack("sturdy")
        with self.assertRaises(ValueError):
            self.progression.slot_skill(self._reload(), 1, stack_id)
        snapshot = self.progression.slot_skill(self._reload(), 0, stack_id)
        self.assertEqual(snapshot.effective.stats["constitution"], 2)

    def test_rank_eligibility_allows_card_in_higher_rank_slot(self) -> None:
        self.set_progress(self.account, level=15)
        spirited = self._skill_stack("spirited")
        snapshot = self.progression.slot_skill(self._reload(), 7, spirited)
        self.assertEqual(snapshot.effective.max_energy, 340)

    def test_slotted_skill_bonus_and_removal(self) -> None:
        self.set_progress(self.account, level=1)
        stack_id = self._skill_stack("sturdy")
        snapshot = self.progression.slot_skill(self._reload(), 0, stack_id)
        self.assertEqual(snapshot.effective.stats["constitution"], 2)
        snapshot = self.progression.remove_skill(self._reload(), 0)
        self.assertEqual(snapshot.effective.stats["constitution"], 1)

    def test_one_copy_cannot_fill_two_slots(self) -> None:
        self.set_progress(self.account, level=2)
        stack_id = self._skill_stack("sturdy")
        self.progression.slot_skill(self._reload(), 0, stack_id)
        with self.assertRaises(ValueError):
            self.progression.slot_skill(self._reload(), 1, stack_id)

    def test_two_copies_fill_two_slots(self) -> None:
        self.set_progress(self.account, level=2)
        stack_id = self._skill_stack("sturdy")
        self.progression.slot_skill(self._reload(), 0, stack_id)
        with self.hub.transaction() as connection:
            self.profiles.set_stack_quantity(
                connection, account_id=self.account.id, stack_id=stack_id, quantity=2
            )
        snapshot = self.progression.slot_skill(self._reload(), 1, stack_id)
        self.assertEqual(snapshot.effective.stats["constitution"], 3)


class InventoryRuleTests(ProgressionTestCase):
    """Stack fill, split, equip, and slot-cap invariants."""

    def test_acquisition_fills_existing_then_creates_new(self) -> None:
        self.grant_card(self.account, "juicy-drink", 8)
        self.grant_card(self.account, "juicy-drink", 5)
        stacks = [s for s in self.profiles.list_inventory(self.account.id, WORLD_ID) if s.card_def_id == "juicy-drink"]
        self.assertEqual(sorted(s.quantity for s in stacks), [3, 10])

    def test_split_creates_unequipped_stack(self) -> None:
        stack_id = self.grant_card(self.account, "juicy-drink", 5)
        self.inventory.equip(self._reload(), stack_id)
        self.inventory.split(self._reload(), stack_id, 2)
        stacks = [s for s in self.profiles.list_inventory(self.account.id, WORLD_ID) if s.card_def_id == "juicy-drink"]
        equipped = [s for s in stacks if s.equipped]
        self.assertEqual(len(equipped), 1)
        self.assertEqual(equipped[0].quantity, 3)
        self.assertEqual(sorted(s.quantity for s in stacks), [2, 3])

    def test_equip_cap_counts_stacks(self) -> None:
        stack_ids = [self.create_stack(self.account, "juicy-drink").stack_id for _ in range(6)]
        account = self._reload()
        for stack_id in stack_ids[:5]:
            self.inventory.equip(account, stack_id)
        with self.assertRaises(ValueError):
            self.inventory.equip(self._reload(), stack_ids[5])

    def test_non_equippable_types_rejected(self) -> None:
        emote = self.grant_card(self.account, "smile", scope="global")
        with self.assertRaises(ValueError):
            self.inventory.equip(self._reload(), emote)

    def test_equip_updates_passive_bonuses_and_unequip_reverts(self) -> None:
        stack_id = self.grant_card(self.account, "ballet-shoes")
        snapshot = self.inventory.equip(self._reload(), stack_id).snapshot
        self.assertEqual(snapshot.effective.stats["fanciness"], 3)
        snapshot = self.inventory.unequip(self._reload(), stack_id).snapshot
        self.assertEqual(snapshot.effective.stats["fanciness"], 1)


if __name__ == "__main__":
    unittest.main()
