"""Milestone 2 card action, emote, and affordability tests."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from server.content.cards import load_card_catalog
from server.content.gameplay import load_gameplay_content
from server.profiles import ProfileRepository
from server.services.actions import ActionsService
from server.services.inventory import InventoryService
from server.services.stats import StatsService
from server.state.migrations import DatabaseHub, ensure_profile_database, ensure_world_database
from tests.common import REPO_ROOT

WORLD_ID = "tutorial"


class ActionsTestCase(unittest.TestCase):
    """Provide isolated services and a helper for granting cards."""

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
        self.actions = ActionsService(self.hub, self.profiles, self.stats, self.catalog, WORLD_ID)
        self.alice = self.profiles.create_account("Alice", "password123!", WORLD_ID, "hub")
        self.bob = self.profiles.create_account("Bob", "password123!", WORLD_ID, "hub")

    def _reload(self, account=None):
        return self.profiles.get_account_by_id((account or self.alice).id)

    def _add(self, account, card_id: str, quantity: int = 1, scope: str = "world"):
        with self.hub.transaction() as connection:
            stacks = self.profiles.add_inventory_card(
                connection,
                account_id=account.id,
                world_id=WORLD_ID if scope == "world" else None,
                card_def_id=card_id,
                quantity=quantity,
                scope=scope,
                stack_limit=self.catalog.cards[card_id].stack_limit,
            )
        return stacks[0].stack_id

    def _equipped(self, account, card_id: str, quantity: int = 1) -> str:
        stack_id = self._add(account, card_id, quantity)
        self.inventory.equip(self._reload(account), stack_id)
        return stack_id

    def _damage(self, account, amount: float):
        self.stats.mutate(account.id, health_delta=-amount)

    def _set_energy(self, account, energy: float):
        with self.hub.transaction() as connection:
            current = self.profiles.get_account_by_id(account.id)
            self.profiles.update_account_progress(
                connection,
                account.id,
                level=current.level,
                kudos=current.kudos,
                bops=current.bops,
                energy=energy,
                last_energy_at=current.last_energy_at,
                last_daily_claim=current.last_daily_claim,
            )


class HealingActionTests(ActionsTestCase):
    """Tasty Toast and Tomato Sauce healing rules."""

    def test_tomato_sauce_heals_self_for_25(self) -> None:
        stack_id = self._equipped(self.alice, "tomato-sauce")
        self._damage(self.alice, 30)
        result = self.actions.use_card(self._reload(), stack_id=stack_id)
        self.assertEqual(result.actor.health, 45)
        self.assertTrue(result.consumed)

    def test_healing_another_peep(self) -> None:
        stack_id = self._equipped(self.alice, "tomato-sauce")
        self._damage(self.bob, 30)
        result = self.actions.use_card(
            self._reload(),
            stack_id=stack_id,
            target_account_id=self.bob.id,
            target_label="Bob",
        )
        self.assertEqual(result.actor.health, 50)
        bob = self._reload(self.bob)
        self.assertEqual(bob.shared_energy, self.bob.shared_energy)
        snapshot = self.stats.reconcile(self.bob.id)
        self.assertEqual(snapshot.health, 45)

    def test_full_health_rejected_without_cost(self) -> None:
        stack_id = self._equipped(self.alice, "tasty-toast")
        with self.assertRaises(ValueError):
            self.actions.use_card(self._reload(), stack_id=stack_id)
        stacks = [s for s in self.profiles.list_inventory(self.alice.id, WORLD_ID) if s.card_def_id == "tasty-toast"]
        self.assertEqual(sum(stack.quantity for stack in stacks), 1)

    def test_npc_rejects_healing(self) -> None:
        stack_id = self._equipped(self.alice, "tasty-toast")
        self._damage(self.alice, 20)
        with self.assertRaises(ValueError):
            self.actions.use_card(
                self._reload(),
                stack_id=stack_id,
                target_account_id=None,
                target_label="Molly",
                target_is_npc=True,
            )

    def test_requires_equipment(self) -> None:
        stack_id = self._add(self.alice, "tasty-toast")
        self._damage(self.alice, 20)
        with self.assertRaises(ValueError):
            self.actions.use_card(self._reload(), stack_id=stack_id)


class EnergyActionTests(ActionsTestCase):
    """Juicy Drink refill rules."""

    def test_juicy_drink_restores_25_and_costs_no_energy(self) -> None:
        stack_id = self._equipped(self.alice, "juicy-drink")
        self._set_energy(self.alice, 10)
        before = self.stats.reconcile(self.alice.id)
        result = self.actions.use_card(self._reload(), stack_id=stack_id)
        self.assertAlmostEqual(result.actor.energy, 35, delta=0.5)
        self.assertAlmostEqual(result.actor.energy - before.energy, 25, delta=0.5)

    def test_juicy_drink_works_while_tired(self) -> None:
        stack_id = self._equipped(self.alice, "juicy-drink")
        self._set_energy(self.alice, 0)
        self.stats.reconcile(self.alice.id)
        result = self.actions.use_card(self._reload(), stack_id=stack_id)
        self.assertGreater(result.actor.energy, 0)

    def test_juicy_drink_rejected_at_full_energy_without_consumption(self) -> None:
        stack_id = self._equipped(self.alice, "juicy-drink")
        self._set_energy(self.alice, 80)
        with self.assertRaises(ValueError):
            self.actions.use_card(self._reload(), stack_id=stack_id)
        stacks = [s for s in self.profiles.list_inventory(self.alice.id, WORLD_ID) if s.card_def_id == "juicy-drink"]
        self.assertEqual(sum(stack.quantity for stack in stacks), 1)

    def test_one_use_consumes_single_copy(self) -> None:
        stack_id = self._equipped(self.alice, "juicy-drink", quantity=3)
        self._set_energy(self.alice, 10)
        self.actions.use_card(self._reload(), stack_id=stack_id)
        stacks = [s for s in self.profiles.list_inventory(self.alice.id, WORLD_ID) if s.card_def_id == "juicy-drink"]
        self.assertEqual(sum(stack.quantity for stack in stacks), 2)


class PassiveAndDecorativeTests(ActionsTestCase):
    """Passive equipment and decorative collectibles have no Use action."""

    def test_ballet_shoes_is_passive(self) -> None:
        stack_id = self._equipped(self.alice, "ballet-shoes")
        with self.assertRaises(ValueError):
            self.actions.use_card(self._reload(), stack_id=stack_id)

    def test_lucille_is_decorative(self) -> None:
        stack_id = self._equipped(self.alice, "lucille")
        with self.assertRaises(ValueError):
            self.actions.use_card(self._reload(), stack_id=stack_id)


class EmoteTests(ActionsTestCase):
    """Expression, Animation, and Effects emote costs and presentation."""

    def test_expression_costs_one_energy(self) -> None:
        stack_id = self._add(self.alice, "smile", scope="global")
        self._set_energy(self.alice, 20)
        result = self.actions.use_emote(self._reload(), stack_id=stack_id)
        self.assertAlmostEqual(result.actor.energy, 19, delta=0.2)
        self.assertIsNotNone(result.bubble)

    def test_animation_costs_three_energy(self) -> None:
        stack_id = self._add(self.alice, "wave", scope="global")
        self._set_energy(self.alice, 20)
        result = self.actions.use_emote(self._reload(), stack_id=stack_id)
        self.assertAlmostEqual(result.actor.energy, 17, delta=0.2)

    def test_effects_enter_room_queue(self) -> None:
        stack_id = self._add(self.alice, "starlight", scope="global")
        self._set_energy(self.alice, 20)
        result = self.actions.use_emote(self._reload(), stack_id=stack_id)
        self.assertAlmostEqual(result.actor.energy, 15, delta=0.2)
        self.assertIsNotNone(result.room_effect)

    def test_emote_blocked_while_tired(self) -> None:
        stack_id = self._add(self.alice, "smile", scope="global")
        self._set_energy(self.alice, 0)
        self.stats.reconcile(self.alice.id)
        with self.assertRaises(ValueError):
            self.actions.use_emote(self._reload(), stack_id=stack_id)


if __name__ == "__main__":
    unittest.main()
