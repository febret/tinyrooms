"""Milestone 3 Phase C dispenser, aura, and environment tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import random
import unittest

from server.content.cards import load_card_catalog
from server.content.worlds import AuraDefinition
from server.profiles import ProfileRepository
from server.services.activities import ActivityService
from server.services.auras import AuraService
from server.services.cards import CardService
from server.services.dispensers import DispenserService
from server.services.environment import EnvironmentService
from server.services.rooms import RoomService
from server.services.stats import StatsService
from server.state.migrations import DatabaseHub, ensure_profile_database, ensure_world_database
from server.state.world_state import WorldStateRepository
from tests.common import REPO_ROOT, WORLD_ID, ServiceTestCase, load_test_world
from tests.test_milestone1 import websocket_headers
from tests.test_milestone2_integration import Milestone2IntegrationTestCase


class FakeConnections:
    """Minimal connection registry double that reports no occupants."""

    async def list_room(self, room_id: str) -> list[object]:
        return []


class DispenserTests(ServiceTestCase):
    """Dispensers share one in-memory cooldown and draw weighted contents."""

    def setUp(self) -> None:
        super().setUp()
        self.world = load_test_world(REPO_ROOT / "worlds" / "tutorial", set(self.catalog.cards))
        self.world_state = WorldStateRepository(self.hub)
        self.world_state.initialize_world(self.world)
        self.dispensers = DispenserService(
            self.hub, self.profiles, self.catalog, self.world, rng=random.Random(7)
        )

    def _single_card_world(self, card_id: str):
        prop = replace(
            self.world.rooms["playroom"].props["dollhouse0"],
            content=(card_id,),
            draw_weight={card_id: 1.0},
        )
        room = replace(self.world.rooms["playroom"], props={**self.world.rooms["playroom"].props, "dollhouse0": prop})
        return replace(self.world, rooms={**self.world.rooms, "playroom": room})

    def test_new_prop_is_ready_and_grants_to_inventory(self) -> None:
        account = self.create_account("ada")
        result = self.dispensers.dispense(account, "playroom", "dollhouse0")
        self.assertTrue(result.granted)
        self.assertIn(result.card_id, {"fancy-wallet", "ballet-shoes"})
        inventory = {stack.card_def_id: stack.quantity for stack in self.profiles.list_inventory(account.id, WORLD_ID)}
        self.assertEqual(inventory.get(result.card_id), 1)

    def test_shared_cooldown_across_users(self) -> None:
        ada = self.create_account("ada")
        bea = self.create_account("bea")
        self.assertTrue(self.dispensers.dispense(ada, "playroom", "dollhouse0").granted)
        second = self.dispensers.dispense(bea, "playroom", "dollhouse0")
        self.assertFalse(second.granted)
        self.assertGreater(second.remaining_seconds, 0)
        bea_inventory = {stack.card_def_id for stack in self.profiles.list_inventory(bea.id, WORLD_ID)}
        self.assertNotIn("fancy-wallet", bea_inventory)
        self.assertNotIn("ballet-shoes", bea_inventory)

    def test_grant_stacks_into_existing_stack(self) -> None:
        account = self.create_account("dee")
        stack_id = self.grant_card(account, "plastic-bag", 1)
        world = self._single_card_world("plastic-bag")
        service = DispenserService(
            self.hub, self.profiles, self.catalog, world, rng=random.Random(3)
        )
        self.assertEqual(service.dispense(account, "playroom", "dollhouse0").card_id, "plastic-bag")
        stack = self.profiles.get_inventory_stack(account.id, WORLD_ID, stack_id)
        self.assertEqual(stack.quantity, 2)

    def test_dispensed_card_auto_equips_when_hand_has_space(self) -> None:
        account = self.create_account("eve")
        result = self.dispensers.dispense(account, "playroom", "dollhouse0")
        self.assertTrue(result.granted)
        equipped = [
            stack.card_def_id
            for stack in self.profiles.list_inventory(account.id, WORLD_ID)
            if stack.equipped
        ]
        self.assertEqual(equipped, [result.card_id])

    def test_dispensed_card_stays_unequipped_when_hand_is_full(self) -> None:
        account = self.create_account("frank")
        with self.hub.transaction() as connection:
            for card_id in ("hand-light", "juicy-drink", "tasty-toast", "tomato-sauce", "pooper-scooper"):
                definition = self.catalog.cards[card_id]
                stacks = self.profiles.add_inventory_card(
                    connection,
                    account_id=account.id,
                    world_id=WORLD_ID,
                    card_def_id=card_id,
                    quantity=1,
                    scope="world",
                    stack_limit=definition.stack_limit,
                )
                self.profiles.set_stack_equipped(
                    connection,
                    account_id=account.id,
                    world_id=WORLD_ID,
                    stack_id=stacks[0].stack_id,
                    equipped=True,
                )
        result = self.dispensers.dispense(account, "playroom", "dollhouse0")
        self.assertTrue(result.granted)
        equipped = [
            stack.card_def_id
            for stack in self.profiles.list_inventory(account.id, WORLD_ID)
            if stack.equipped
        ]
        self.assertEqual(len(equipped), 5)
        self.assertNotIn(result.card_id, equipped)


class DispenserRestartTests(unittest.TestCase):
    """The in-memory cooldown resets when the process is restarted."""

    def _build(self, hub: DatabaseHub, world):
        return DispenserService(
            hub, ProfileRepository(hub), load_card_catalog(REPO_ROOT / "data" / "cardsets", REPO_ROOT / "worlds" / WORLD_ID),
            world, rng=random.Random(1),
        )

    def test_cooldown_resets_on_reopen(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = root / "profiles.sqlite3"
            world_path = root / "worldstate.sqlite3"
            ensure_profile_database(profile_path)
            ensure_world_database(world_path)
            catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", REPO_ROOT / "worlds" / WORLD_ID)
            world = load_test_world(REPO_ROOT / "worlds" / "tutorial", set(catalog.cards))
            hub = DatabaseHub(profile_path, world_path)
            profiles = ProfileRepository(hub)
            world_state = WorldStateRepository(hub)
            world_state.initialize_world(world)
            account = profiles.create_account("ada", "password123!", WORLD_ID, "hub")
            service = self._build(hub, world)
            self.assertTrue(service.dispense(account, "playroom", "dollhouse0").granted)
            self.assertFalse(service.dispense(account, "playroom", "dollhouse0").granted)
            hub.close()

            hub = DatabaseHub(profile_path, world_path)
            try:
                reopened = ProfileRepository(hub)
                service = self._build(hub, world)
                self.assertTrue(service.dispense(reopened.get_account_by_id(account.id), "playroom", "dollhouse0").granted)
            finally:
                hub.close()


class AuraTests(ServiceTestCase):
    """Auras never stack and clear on departure without touching other effects."""

    def setUp(self) -> None:
        super().setUp()
        self.world = load_test_world(REPO_ROOT / "worlds" / "tutorial", set(self.catalog.cards))
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)

    def _world_with_aura(self, *aura: AuraDefinition):
        room = replace(self.world.rooms["hub"], aura=tuple(aura))
        return replace(self.world, rooms={**self.world.rooms, "hub": room})

    def test_enter_is_idempotent_and_leave_clears(self) -> None:
        world = self._world_with_aura(AuraDefinition(stat="constitution", delta=1))
        auras = AuraService(self.hub, self.stats, world)
        account = self.create_account("ada")
        auras.enter(account.id, "hub")
        auras.enter(account.id, "hub")
        self.assertEqual(self.stats.view(account.id).effective.stats["constitution"], 2)
        auras.leave(account.id, "hub")
        self.assertEqual(self.stats.view(account.id).effective.stats["constitution"], 1)

    def test_leave_preserves_timed_buffs_and_counters(self) -> None:
        world = self._world_with_aura(
            AuraDefinition(stat="constitution", delta=1),
            AuraDefinition(buff_id="cozy", duration_seconds=600),
        )
        auras = AuraService(self.hub, self.stats, world)
        account = self.create_account("bea")
        auras.enter(account.id, "hub")
        self.stats.mutate(account.id, health_delta=-5)
        auras.leave(account.id, "hub")
        profile = self.profiles.get_user_profile(account.id)
        instance_ids = {entry.get("id") for entry in profile.buffs.get("instances", [])}
        self.assertIn("cozy", instance_ids)
        self.assertEqual(self.stats.view(account.id).health, 45)
        self.assertEqual(self.stats.view(account.id).effective.stats["constitution"], 1)


class EnvironmentTests(ServiceTestCase):
    """Environment state gates the room and expires on schedule."""

    def setUp(self) -> None:
        super().setUp()
        self.world = load_test_world(REPO_ROOT / "worlds" / "tutorial", set(self.catalog.cards))
        self.world_state = WorldStateRepository(self.hub)
        self.world_state.initialize_world(self.world)
        self.environment = EnvironmentService(self.hub, self.world, self.world_state)

    def test_set_get_revision_and_gating(self) -> None:
        update = self.environment.set(
            "hub",
            {
                "lighting": "dark",
                "hidden_props": {"welcome-plant": {"expires_at": None}},
                "disabled_exits": {"exit0": {"expires_at": None}},
                "disabled_actions": {".shop": {"expires_at": None}},
            },
        )
        self.assertEqual(update.revision, 1)
        self.assertEqual(self.environment.get("hub")["lighting"], "dark")
        self.assertFalse(self.environment.is_prop_visible("hub", "welcome-plant"))
        self.assertTrue(self.environment.is_prop_visible("hub", "portal0"))
        self.assertFalse(self.environment.is_exit_enabled("hub", "exit0"))
        self.assertFalse(self.environment.is_action_enabled("hub", ".shop"))
        self.assertEqual(self.environment.lighting("hub"), "dark")

    def test_expiry_clears_entries(self) -> None:
        self.environment.set("hub", {"hidden_props": {"portal0": {"expires_at": "2000-01-01T00:00:00+00:00"}}})
        update = self.environment.expire("hub")
        self.assertIsNotNone(update)
        self.assertNotIn("hidden_props", self.environment.get("hub"))
        self.assertTrue(self.environment.is_prop_visible("hub", "portal0"))

    def test_snapshot_filters_hidden_props_and_exits(self) -> None:
        cards = CardService(self.hub, self.profiles, self.world_state, self.catalog, WORLD_ID, {})
        stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        rooms = RoomService(
            hub=self.hub,
            profiles=self.profiles,
            world_state=self.world_state,
            connections=FakeConnections(),
            card_service=cards,
            activities=ActivityService(SimpleNamespace(features=frozenset())),
            world=self.world,
            stats=stats,
            environment=self.environment,
        )
        self.environment.set(
            "hub",
            {
                "lighting": "dark",
                "hidden_props": {"welcome-plant": {"expires_at": None}},
                "disabled_exits": {"exit0": {"expires_at": None}},
            },
        )
        account = self.create_account("ada")
        snapshot = asyncio.run(rooms.build_snapshot(account, "hub"))
        self.assertNotIn("welcome-plant", {prop["id"] for prop in snapshot["props"]})
        self.assertNotIn("exit0", {exit_definition["id"] for exit_definition in snapshot["exits"]})
        self.assertTrue(snapshot["board"]["dark"])
        self.assertEqual(snapshot["environment"]["lighting"], "dark")
        self.assertEqual(snapshot["environment_revision"], 1)


class PropCommandIntegrationTests(Milestone2IntegrationTestCase):
    """Dispenser and crafting commands work over the WebSocket path."""

    def send_command(self, socket, request_id: str, command: str) -> dict[str, object]:
        socket.send_json({"v": 1, "type": "command", "request_id": request_id, "command": command})
        for _ in range(16):
            message = socket.receive_json()
            if message.get("type") == "result" and message.get("request_id") == request_id:
                return message
        raise AssertionError(f"Never received result for {command!r}.")

    def test_dispense_command_and_cooldown(self) -> None:
        credentials = self.create_ready_account("ada")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            self.assertTrue(self.send_command(socket, "go-1", ".go @way:exit0")["ok"])
            first = self.send_command(socket, "d-1", ".dispense @prop:dollhouse0")
            self.assertTrue(first["ok"], first)
            self.assertIn(first["payload"]["dispense"]["card_id"], {"fancy-wallet", "ballet-shoes"})
            second = self.send_command(socket, "d-2", ".dispense dollhouse0")
            self.assertFalse(second["ok"])
            self.assertIn("recharging", second["message"])

    def test_craft_command_opens_bound_activity_and_crafts(self) -> None:
        credentials = self.create_ready_account("bea")
        account_id = self.account_id(credentials)
        poop_id = self.grant_card(account_id, "poop", 2)
        bag_id = self.grant_card(account_id, "plastic-bag", 1)
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            for index, exit_id in enumerate(("exit0", "exit0", "kitchen")):
                self.assertTrue(self.send_command(socket, f"go-{index}", f".go @way:{exit_id}")["ok"])
            opened = self.send_command(socket, "craft-1", ".craft @prop:workbench0")
            self.assertTrue(opened["ok"], opened)
            self.assertEqual(opened["payload"]["activity"]["kind"], "crafting")
            self.assertEqual(opened["payload"]["activity"]["config"]["prop_instance_id"], "workbench0")
            preview = self.send_command(socket, "preview-1", ".craft_preview bagged-poop")
            self.assertTrue(preview["ok"], preview)
            self.assertEqual(preview["payload"]["preview"]["recipe_id"], "bagged-poop")
            made = self.send_command(socket, "make-1", f".craft_make bagged-poop {poop_id}:1 {bag_id}:1")
            self.assertTrue(made["ok"], made)
            self.assertEqual(made["payload"]["craft"]["outputs"][0]["card_id"], "poop-in-a-bag")


if __name__ == "__main__":
    unittest.main()
