"""Tests for runtime-minted dynamic cards and stinky-peep drops."""

from __future__ import annotations

import asyncio
import random
import unittest
from dataclasses import replace
from types import SimpleNamespace

from server.commands.admin import _admin_stinky_drop
from server.services import dynamic_cards as dynamic_card_store
from server.services.cards import CardService
from server.services.dynamic_cards import DynamicCardDrops
from server.services.stats import StatsService
from server.services.vibes import VibesService
from server.state.npc_peep_states import NpcPeepStateRepository
from server.state.world_state import WorldStateRepository
from tests.common import REPO_ROOT, ServiceTestCase, WORLD_ID, load_test_world


class DynamicCardTests(ServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.world_state = WorldStateRepository(self.hub)
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.cards = CardService(
            self.hub, self.profiles, self.world_state, self.catalog, WORLD_ID, {}, None, None
        )

    def test_mint_inherits_base_and_applies_overrides(self) -> None:
        account = self.create_account("dyn-minter")
        with self.hub.transaction() as connection:
            definition = dynamic_card_store.mint_dynamic_card(
                self.catalog,
                self.profiles,
                connection,
                base_card_id="poop",
                label="Aldo's poop",
                description="Fresh from Aldo. Do not ask about the journey.",
                rarity="Rare",
                creator_account_id=account.id,
            )
        base = self.catalog.cards["poop"]
        self.assertTrue(definition.id.startswith("dyn_"))
        self.assertEqual(definition.label, "Aldo's poop")
        self.assertEqual(definition.rarity, "Rare")
        self.assertEqual(definition.image_name, base.image_name)
        self.assertEqual(definition.source, base.source)
        self.assertEqual(definition.stack_limit, base.stack_limit)
        self.assertEqual(definition.sounds, base.sounds)

    def test_mint_rejects_bad_input(self) -> None:
        account = self.create_account("dyn-invalid")
        with self.hub.transaction() as connection:
            with self.assertRaises(ValueError):
                dynamic_card_store.mint_dynamic_card(
                    self.catalog,
                    self.profiles,
                    connection,
                    base_card_id="no-such-card",
                    label="x",
                    description="y",
                )
            with self.assertRaises(ValueError):
                dynamic_card_store.mint_dynamic_card(
                    self.catalog,
                    self.profiles,
                    connection,
                    base_card_id="poop",
                    label="   ",
                    description="y",
                )
            with self.assertRaises(ValueError):
                dynamic_card_store.mint_dynamic_card(
                    self.catalog,
                    self.profiles,
                    connection,
                    base_card_id="poop",
                    label="x",
                    description="y",
                    rarity="Mythic",
                )
            with self.assertRaises(ValueError):
                dynamic_card_store.mint_dynamic_card(
                    self.catalog,
                    self.profiles,
                    connection,
                    base_card_id="inventory",
                    label="x",
                    description="y",
                )

    def test_room_drop_pickup_and_drop_roundtrip(self) -> None:
        account = self.create_account("dyn-roundtrip")
        with self.hub.transaction() as connection:
            definition = dynamic_card_store.mint_dynamic_card(
                self.catalog,
                self.profiles,
                connection,
                base_card_id="poop",
                label="Aldo's poop",
                description="A personalized problem.",
                creator_account_id=account.id,
            )
            room_stack = self.world_state.add_room_card(
                connection,
                room_id="hub",
                card_def_id=definition.id,
                quantity=1,
                pos=(10.0, 10.0, 0.0),
            )
        payload = self.cards.serialize_room_stack(room_stack)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["definition"]["label"], "Aldo's poop")

        mutation = self.cards.pickup(account, "hub", room_stack.stack_id, 1)
        self.assertEqual(mutation.room_event["type"], "room.card.removed")
        rows = self.profiles.list_inventory(account.id, WORLD_ID)
        picked = [row for row in rows if row.card_def_id == definition.id]
        self.assertEqual(len(picked), 1)
        # Dynamic pickups stay global so the definition resolves in every world.
        self.assertIsNone(picked[0].world_id)
        self.assertEqual(picked[0].scope, "global")
        foreign = self.profiles.list_inventory(account.id, "some-other-world")
        self.assertIn(definition.id, [row.card_def_id for row in foreign])

        stacks = self.profiles.list_inventory(account.id, WORLD_ID)
        picked_stack = next(row for row in stacks if row.card_def_id == definition.id)
        second = self.cards.drop(account, "hub", picked_stack.stack_id, 1, (20.0, 20.0, 0.0))
        self.assertEqual(second.room_event["type"], "room.card.added")
        self.assertEqual(
            second.room_event["stack"]["definition"]["description"], "A personalized problem."
        )

    def test_dynamic_cards_sell_at_rarity_price(self) -> None:
        from server.services.pricing import CardPricingService

        account = self.create_account("dyn-seller")
        pricing = CardPricingService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        with self.hub.transaction() as connection:
            definition = dynamic_card_store.mint_dynamic_card(
                self.catalog,
                self.profiles,
                connection,
                base_card_id="poop",
                label="Aldo's poop",
                description="Surprisingly liquid asset.",
                rarity="Common",
                creator_account_id=account.id,
            )
            stacks = self.profiles.add_inventory_card(
                connection,
                account_id=account.id,
                world_id=None,
                card_def_id=definition.id,
                quantity=2,
                scope="global",
                stack_limit=definition.stack_limit,
            )
        self.assertTrue(pricing.is_sellable(definition))
        self.assertEqual(
            pricing.sell_value(definition),
            pricing.sell_value(self.catalog.cards["juicy-drink"]),
        )
        before = self.reload_account(account).bops
        result = pricing.sell(self.reload_account(account), stacks[0].stack_id, 1)
        self.assertEqual(result.bops_gained, pricing.sell_value(definition))
        self.assertEqual(result.account.bops, before + result.bops_gained)
        remaining = self.profiles.list_inventory(account.id, WORLD_ID)
        self.assertEqual(
            sum(stack.quantity for stack in remaining if stack.card_def_id == definition.id), 1
        )


class StatusDropViaVibesTests(ServiceTestCase):
    """Stinky drops fire through the shared minute tick in VibesService."""

    def setUp(self) -> None:
        super().setUp()
        self.world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        self.world_state = WorldStateRepository(self.hub)
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.cards = CardService(
            self.hub, self.profiles, self.world_state, self.catalog, WORLD_ID, {}, None, None
        )
        self.peep_states = NpcPeepStateRepository(self.hub, self.world)
        self.drops = DynamicCardDrops(
            hub=self.hub,
            profiles=self.profiles,
            world_state=self.world_state,
            cards=self.cards,
            catalog=self.catalog,
            random_func=lambda: 0.0,
            rng=random.Random(7),
        )
        self.vibes = VibesService(
            hub=self.hub,
            world=self.world,
            stats=self.stats,
            peep_states=self.peep_states,
            card_drops=self.drops,
        )

    def _make_stinky(self, username: str):
        account = self.create_account(username)
        with self.hub.transaction() as connection:
            self.profiles.write_counters(connection, account.id, {"health": 50, "cleanliness": 0})
        return account

    def test_solo_stinky_peep_drops_personalized_card(self) -> None:
        account = self._make_stinky("stinky-aldo")
        broadcasts = self.vibes.update_room("hub", [account.id])
        self.assertTrue(any(event.event["type"] == "room.card.added" for event in broadcasts))
        self.assertTrue(any(event.event["type"] == "room.refresh" for event in broadcasts))
        stacks = self.world_state.list_room_cards("hub")
        self.assertEqual(len(stacks), 1)
        definition = self.cards.definition(stacks[0].card_def_id)
        self.assertIn("stinky-aldo", definition.label)
        self.assertIn("stinky-aldo", definition.description)
        self.assertTrue(
            definition.label.endswith("'s pee") or definition.label.endswith("'s poop")
        )
        added = next(event for event in broadcasts if event.event["type"] == "room.card.added")
        self.assertEqual(added.event["stack"]["definition"]["id"], definition.id)

    def test_pair_room_reports_drop_and_single_refresh(self) -> None:
        stinky = self._make_stinky("stinky-aldo")
        friend = self.create_account("clean-friend")
        broadcasts = self.vibes.update_room("hub", [stinky.id, friend.id])
        kinds = [event.event["type"] for event in broadcasts]
        self.assertIn("room.card.added", kinds)
        self.assertEqual(kinds.count("room.refresh"), 1)

    def test_clean_peep_drops_nothing(self) -> None:
        account = self.create_account("clean-beto")
        self.assertEqual(self.vibes.update_room("hub", [account.id]), [])

    def test_drops_throttle_to_one_check_per_minute(self) -> None:
        from datetime import timedelta

        from server.security import utc_now

        account = self._make_stinky("stinky-carla")
        now = utc_now()
        first = self.vibes.update_room("hub", [account.id], now=now)
        self.assertTrue(first)
        self.assertEqual(
            self.vibes.update_room("hub", [account.id], now=now + timedelta(seconds=30)),
            [],
        )
        second = self.vibes.update_room("hub", [account.id], now=now + timedelta(seconds=61))
        self.assertTrue(second)
        self.assertEqual(len(self.world_state.list_room_cards("hub")), 2)

    def test_room_cap_stops_further_drops(self) -> None:
        account = self._make_stinky("stinky-dora")
        with self.hub.transaction() as connection:
            for _ in range(10):
                definition = dynamic_card_store.mint_dynamic_card(
                    self.catalog,
                    self.profiles,
                    connection,
                    base_card_id="poop",
                    label="filler",
                    description="filler",
                    creator_account_id=account.id,
                )
                self.world_state.add_room_card(
                    connection,
                    room_id="hub",
                    card_def_id=definition.id,
                    quantity=1,
                    pos=(1.0, 1.0, 0.0),
                )
        self.assertEqual(self.vibes.update_room("hub", [account.id]), [])


class CrossWorldDropTests(ServiceTestCase):
    """Drops must resolve in worlds that lack the tutorial bases."""

    def setUp(self) -> None:
        super().setUp()
        self.world_state = WorldStateRepository(self.hub)
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)

    def _dropper_for(self, catalog, **kwargs):
        cards = CardService(
            self.hub, self.profiles, self.world_state, catalog, WORLD_ID, {}, None, None
        )
        return (
            DynamicCardDrops(
                hub=self.hub,
                profiles=self.profiles,
                world_state=self.world_state,
                cards=cards,
                catalog=catalog,
                random_func=kwargs.get("random_func", lambda: 0.0),
                rng=kwargs.get("rng", random.Random(11)),
            ),
            cards,
        )

    def test_global_bases_cover_worlds_without_tutorial_cards(self) -> None:
        from server.content.cards import load_card_catalog

        remote_catalog = load_card_catalog(
            REPO_ROOT / "data" / "cardsets", REPO_ROOT / "worlds" / "scammon-academia"
        )
        for base in ("poop", "poop-in-a-bag", "juicy-drink", "tasty-toast", "tomato-sauce"):
            self.assertNotIn(base, remote_catalog.cards)
        dropper, cards = self._dropper_for(remote_catalog)
        broadcasts = dropper.maybe_drop("some-room", ["ghost-id"], force=True)
        added = [event for event in broadcasts if event.event["type"] == "room.card.added"]
        self.assertEqual(len(added), 1)
        definition = cards.definition(added[0].event["stack"]["definition"]["id"])
        self.assertIn(definition.image_name, ("stinky-pee.png", "stinky-poop.png"))
        self.assertEqual(definition.source, "stinky")

    def test_variant_fallback_when_first_choice_has_no_base(self) -> None:
        catalog = replace(
            self.catalog,
            cards={
                card_id: definition
                for card_id, definition in self.catalog.cards.items()
                if card_id not in {"stinky-pee", "poop", "poop-in-a-bag", "juicy-drink", "tasty-toast", "tomato-sauce"}
            },
        )
        self.assertIn("stinky-poop", catalog.cards)
        dropper, cards = self._dropper_for(catalog)
        broadcasts = dropper.maybe_drop("some-room", ["ghost-id"], force=True)
        added = [event for event in broadcasts if event.event["type"] == "room.card.added"]
        self.assertEqual(len(added), 1)
        definition = cards.definition(added[0].event["stack"]["definition"]["id"])
        self.assertTrue(definition.label.endswith("'s poop"))
        self.assertEqual(definition.image_name, "stinky-poop.png")

    def test_force_bypasses_dice(self) -> None:
        dropper, _ = self._dropper_for(
            self.catalog, random_func=lambda: 0.99, rng=random.Random(3)
        )
        self.assertEqual(dropper.maybe_drop("some-room", ["ghost-id"]), [])
        forced = dropper.maybe_drop("other-room", ["ghost-id"], force=True)
        self.assertTrue(any(event.event["type"] == "room.card.added" for event in forced))

    def test_room_cap_logs_warning(self) -> None:
        account = self.create_account("cap-watcher")
        with self.hub.transaction() as connection:
            for _ in range(10):
                definition = dynamic_card_store.mint_dynamic_card(
                    self.catalog,
                    self.profiles,
                    connection,
                    base_card_id="stinky-poop",
                    label="filler",
                    description="filler",
                    creator_account_id=account.id,
                )
                self.world_state.add_room_card(
                    connection,
                    room_id="hub",
                    card_def_id=definition.id,
                    quantity=1,
                    pos=(1.0, 1.0, 0.0),
                )
        dropper, _ = self._dropper_for(self.catalog)
        with self.assertLogs("server.services.dynamic_cards", level="WARNING") as captured:
            self.assertEqual(dropper.maybe_drop("hub", [account.id], force=True), [])
        self.assertTrue(
            any("already holds" in message for message in captured.output),
            captured.output,
        )


class AdminStinkyDropTests(ServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        self.world_state = WorldStateRepository(self.hub)
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.cards = CardService(
            self.hub, self.profiles, self.world_state, self.catalog, WORLD_ID, {}, None, None
        )
        self.dropper = DynamicCardDrops(
            hub=self.hub,
            profiles=self.profiles,
            world_state=self.world_state,
            cards=self.cards,
            catalog=self.catalog,
            random_func=lambda: 0.99,
            rng=random.Random(5),
        )

    def _context_for(self, account, room_id="hub", occupants=()):
        async def list_room(_room_id):
            self.assertEqual(_room_id, room_id)
            return [SimpleNamespace(account_id=user_id) for user_id in occupants]

        audit_calls = []

        return SimpleNamespace(
            account=account,
            connection=SimpleNamespace(room_id=room_id),
            rooms=SimpleNamespace(world=self.world),
            stats=self.stats,
            card_drops=self.dropper,
            connections=SimpleNamespace(list_room=list_room),
            audit=SimpleNamespace(
                safe_record=lambda *args: audit_calls.append(args),
            ),
            _audit_calls=audit_calls,
        )

    def _make_stinky(self, username):
        account = self.create_account(username)
        with self.hub.transaction() as connection:
            self.profiles.write_counters(connection, account.id, {"health": 50, "cleanliness": 0})
        return account

    def test_force_drop_mints_for_stinky_occupant(self) -> None:
        admin = self.create_account("admin-ana")
        stinky = self._make_stinky("stinky-eli")
        context = self._context_for(admin, occupants=[stinky.id])
        outcome = asyncio.run(_admin_stinky_drop(context, []))
        self.assertIn("Dropped 1 card(s)", outcome.message)
        kinds = [event.event["type"] for event in outcome.room_broadcasts]
        self.assertIn("room.card.added", kinds)
        stacks = self.world_state.list_room_cards("hub")
        self.assertEqual(len(stacks), 1)
        definition = self.cards.definition(stacks[0].card_def_id)
        self.assertIn("stinky-eli", definition.label)
        self.assertTrue(context._audit_calls)

    def test_no_stinky_means_no_drop(self) -> None:
        admin = self.create_account("admin-ana")
        clean = self.create_account("clean-finn")
        context = self._context_for(admin, occupants=[clean.id])
        outcome = asyncio.run(_admin_stinky_drop(context, []))
        self.assertIn("nothing dropped", outcome.message)
        self.assertEqual(outcome.room_broadcasts, [])
        self.assertEqual(self.world_state.list_room_cards("hub"), [])

    def test_unknown_room_rejected(self) -> None:
        from server.commands.outcomes import CommandError

        admin = self.create_account("admin-ana")
        context = self._context_for(admin, room_id="nope", occupants=[])
        with self.assertRaises(CommandError):
            asyncio.run(_admin_stinky_drop(context, ["nope"]))


if __name__ == "__main__":
    unittest.main()
