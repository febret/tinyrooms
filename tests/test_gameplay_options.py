"""Tests for gameplay options loading, overrides, and disabled mechanics."""

from __future__ import annotations

import json
import random
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from server.content.gameplay import load_gameplay_content
from server.gameplay_options import (
    GameplayOptionsError,
    apply_gameplay_options,
    load_gameplay_options,
    parse_gameplay_options,
    write_gameplay_options,
)
from server.services.cards import CardService
from server.services.dynamic_cards import DynamicCardDrops
from server.services.stats import StatsService
from server.state.world_state import WorldStateRepository
from tests.common import REPO_ROOT, ServiceTestCase, WORLD_ID


class GameplayOptionsParsingTests(unittest.TestCase):
    def test_partial_override_merges_with_defaults(self) -> None:
        options = parse_gameplay_options(
            {
                "mechanics": {"energy": False},
                "card_drops": {"cleanliness": False},
                "constants": {"energy_cost_card": 0, "base_max_health": 75},
            }
        )
        self.assertFalse(options.energy_enabled)
        self.assertTrue(options.sickness_enabled)
        self.assertFalse(options.card_drops.cleanliness)
        self.assertTrue(options.card_drops.sickness)
        self.assertEqual(options.constants.energy_cost_card, 0)
        self.assertEqual(options.constants.base_max_health, 75)
        self.assertEqual(options.constants.energy_cost_expression, 1)

    def test_file_round_trip(self) -> None:
        options = parse_gameplay_options({"mechanics": {"cleanliness": False}})
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "options.json"
            write_gameplay_options(path, options)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), options.to_dict())
            self.assertEqual(load_gameplay_options(path), options)
        self.assertIs(load_gameplay_options(None).energy_enabled, True)

    def test_content_overrides_apply_to_existing_values(self) -> None:
        content = load_gameplay_content(REPO_ROOT / "data" / "core")
        options = parse_gameplay_options(
            {
                "constants": {
                    "energy_recharge_rate": 4,
                    "energy_recovery_threshold": 0.25,
                    "base_max_health": 75,
                    "base_max_cleanliness": 150,
                }
            }
        )
        updated = apply_gameplay_options(content, options)
        self.assertEqual(updated.juice.energy_recharge_rate, 4)
        self.assertEqual(updated.juice.recovery_threshold, 0.25)
        self.assertEqual(updated.statuses["tired"].cleared_when.at_or_above_fraction, 0.25)
        self.assertEqual(updated.base_max_health, 75)
        self.assertEqual(updated.base_max_cleanliness, 150)


class ConfiguredStartingStateTests(ServiceTestCase):
    def test_new_accounts_use_configured_starting_values(self) -> None:
        account = self.profiles.create_account(
            "configured",
            "password123!",
            WORLD_ID,
            "hub",
            starting_energy=123,
            starting_counters={"health": 75, "cleanliness": 150},
        )
        profile = self.profiles.get_user_profile(account.id)
        self.assertEqual(account.shared_energy, 123)
        self.assertEqual(profile.counters["health"], 75)
        self.assertEqual(profile.counters["cleanliness"], 150)
        self.assertEqual(profile.counters["max_health"], 50)


class DisabledMechanicsTests(ServiceTestCase):
    def _stats(self, payload: dict[str, object]) -> StatsService:
        options = parse_gameplay_options(payload)
        return StatsService(
            self.hub,
            self.profiles,
            self.catalog,
            apply_gameplay_options(self.content, options),
            WORLD_ID,
            options=options,
        )

    def test_disabled_energy_skips_charges_and_tired(self) -> None:
        stats = self._stats({"mechanics": {"energy": False}})
        account = self.create_account("free-energy")
        snapshot = stats.charge(account, 999)
        self.assertEqual(snapshot.energy, snapshot.effective.max_energy)
        self.assertNotIn("tired", snapshot.statuses)
        with self.hub.transaction() as connection:
            charged = stats.charge_in_transaction(connection, account.id, 5)
        self.assertEqual(charged.energy, charged.effective.max_energy)

    def test_enabled_mechanics_still_apply_statuses(self) -> None:
        stats = self._stats({})
        account = self.create_account("normal")
        snapshot = stats.mutate(account.id, health_delta=-999, cleanliness_delta=-999)
        self.assertEqual(snapshot.health, 0)
        self.assertEqual(snapshot.cleanliness, 0)
        self.assertIn("sick", snapshot.statuses)
        self.assertIn("stinky", snapshot.statuses)


class DisabledDropTests(ServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.world_state = WorldStateRepository(self.hub)
        self.cards = CardService(
            self.hub, self.profiles, self.world_state, self.catalog, WORLD_ID, {}, None, None
        )

    def _dropper(self, payload: dict[str, object]) -> DynamicCardDrops:
        options = parse_gameplay_options(payload)
        return DynamicCardDrops(
            hub=self.hub,
            profiles=self.profiles,
            world_state=self.world_state,
            cards=self.cards,
            catalog=self.catalog,
            rng=random.Random(7),
            random_func=lambda: 0.0,
            options=options,
        )

    def _stinky(self, username: str):
        account = self.create_account(username)
        with self.hub.transaction() as connection:
            self.profiles.write_counters(
                connection, account.id, {"health": 50, "cleanliness": 0}
            )
        return account

    def test_disabled_cleanliness_drops_skip_even_when_forced(self) -> None:
        dropper = self._dropper({"card_drops": {"cleanliness": False}})
        account = self._stinky("no-drop")
        broadcasts = dropper.maybe_drop(
            "hub",
            [account.id],
            force=True,
            statuses_by_account={account.id: {"stinky"}},
        )
        self.assertEqual(broadcasts, [])
        self.assertEqual(self.world_state.list_room_cards("hub"), [])

    def test_enabled_drops_still_mint(self) -> None:
        dropper = self._dropper({})
        account = self._stinky("drop-ok")
        broadcasts = dropper.maybe_drop(
            "hub",
            [account.id],
            force=True,
            statuses_by_account={account.id: {"stinky"}},
        )
        self.assertEqual(len(broadcasts), 1)


if __name__ == "__main__":
    unittest.main()
