"""Shared per-container card storage: deposits, opens, and takes."""

from __future__ import annotations

import unittest

from server.services.cards import CardService
from server.services.containers import ContainerService
from server.state.world_state import WorldStateRepository
from tests.common import (
    REPO_ROOT,
    IntegrationTestCase,
    ServiceTestCase,
    WORLD_ID,
    load_test_world,
    websocket_headers,
)


class ContainerBehaviorTests(ServiceTestCase):
    def test_container_tag_rule(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        self.assertEqual(world.props["saari-cabinet"].behavior, "container")
        self.assertEqual(world.props["galvanized-trashcan"].behavior, "container")
        self.assertEqual(world.props["floral-nightstand"].behavior, "container")
        actions = {
            action.command for action in world.props["saari-cabinet"].default_actions
        }
        self.assertIn(".open @self", actions)

    def test_existing_behaviors_and_shelves_are_untouched(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        self.assertEqual(world.props["medicine-cabinet"].behavior, "dispenser")
        self.assertEqual(world.props["kitchen-dresser"].behavior, "dispenser")
        self.assertEqual(world.props["city-trashcan"].behavior, "trashcan")
        self.assertIsNone(world.props["kuusi-wall-shelf"].behavior)


class ContainerServiceTests(ServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        self.world_state = WorldStateRepository(self.hub)
        self.cards = CardService(
            self.hub, self.profiles, self.world_state, self.catalog, WORLD_ID, {}, None, None
        )
        self.containers = ContainerService(
            self.hub, self.profiles, self.world_state, self.catalog, self.cards, self.world
        )

    def _instance_id(self, room_id: str, prop_id: str) -> str:
        return next(
            prop.id
            for prop in self.world.rooms[room_id].props.values()
            if prop.prop_id == prop_id
        )

    def test_deposit_open_take_roundtrip_is_shared(self) -> None:
        first = self.create_account("container-first")
        second = self.create_account("container-second")
        instance_id = self._instance_id("bathroom", "saari-cabinet")
        stack_id = self.grant_card(first, "poop", 3)
        before_energy = self.reload_account(first).shared_energy

        deposit = self.containers.deposit(first, "bathroom", instance_id, stack_id)
        self.assertEqual(deposit.card_id, "poop")
        remaining = [
            row for row in self.profiles.list_inventory(first.id, WORLD_ID)
            if row.card_def_id == "poop"
        ]
        self.assertEqual(sum(row.quantity for row in remaining), 2)
        self.assertEqual(self.reload_account(first).shared_energy, before_energy)

        contents = self.containers.contents("bathroom", instance_id)
        self.assertEqual(
            [(card["definition"]["id"], card["quantity"]) for card in contents["cards"]],
            [("poop", 1)],
        )
        peer_contents = self.containers.contents("bathroom", instance_id)
        self.assertEqual(
            [(card["definition"]["id"], card["quantity"]) for card in peer_contents["cards"]],
            [("poop", 1)],
        )

        container_stack_id = contents["cards"][0]["stack_id"]
        take = self.containers.take(second, "bathroom", instance_id, container_stack_id)
        self.assertEqual((take.card_id, take.quantity), ("poop", 1))
        taken = [
            row for row in self.profiles.list_inventory(second.id, WORLD_ID)
            if row.card_def_id == "poop"
        ]
        self.assertEqual(sum(row.quantity for row in taken), 1)
        self.assertEqual(self.containers.contents("bathroom", instance_id)["cards"], [])

    def test_one_use_cards_are_stored_not_consumed(self) -> None:
        account = self.create_account("container-keeper")
        instance_id = self._instance_id("bathroom", "saari-cabinet")
        stack_id = self.grant_card(account, "juicy-drink", 2)
        before_energy = self.reload_account(account).shared_energy

        self.containers.deposit(account, "bathroom", instance_id, stack_id)
        contents = self.containers.contents("bathroom", instance_id)
        self.assertEqual(
            [(card["definition"]["id"], card["quantity"]) for card in contents["cards"]],
            [("juicy-drink", 1)],
        )
        remaining = [
            row for row in self.profiles.list_inventory(account.id, WORLD_ID)
            if row.card_def_id == "juicy-drink"
        ]
        self.assertEqual(sum(row.quantity for row in remaining), 1)
        self.assertEqual(self.reload_account(account).shared_energy, before_energy)

    def test_rejects_non_containers_and_over_takes(self) -> None:
        account = self.create_account("container-reject")
        instance_id = self._instance_id("bathroom", "saari-cabinet")
        stack_id = self.grant_card(account, "poop", 1)
        shower_id = self._instance_id("bathroom", "shower")
        with self.assertRaises(ValueError):
            self.containers.deposit(account, "bathroom", shower_id, stack_id)
        with self.assertRaises(ValueError):
            self.containers.contents("bathroom", shower_id)
        with self.assertRaises(ValueError):
            self.containers.take(account, "bathroom", instance_id, "container:nope")
        self.containers.deposit(account, "bathroom", instance_id, stack_id)
        container_stack_id = self.containers.contents("bathroom", instance_id)["cards"][0]["stack_id"]
        with self.assertRaises(ValueError):
            self.containers.take(account, "bathroom", instance_id, container_stack_id, 2)

    def test_room_reset_clears_containers(self) -> None:
        account = self.create_account("container-reset")
        instance_id = self._instance_id("bathroom", "saari-cabinet")
        stack_id = self.grant_card(account, "poop", 1)
        self.containers.deposit(account, "bathroom", instance_id, stack_id)
        self.assertEqual(len(self.containers.contents("bathroom", instance_id)["cards"]), 1)
        self.world_state.reset_room_state(self.world, "bathroom")
        self.assertEqual(self.containers.contents("bathroom", instance_id)["cards"], [])


class ContainerCommandTests(IntegrationTestCase):
    def test_use_open_take_commands(self) -> None:
        credentials = self.create_ready_account("container-user")
        runtime = self.runtime()
        account_id = self.account_id(credentials)
        stack_id = self.grant_card(account_id, "tasty-toast")
        before_energy = runtime.profiles.get_account_by_id(account_id).shared_energy
        with runtime.hub.transaction() as connection:
            runtime.profiles.set_remembered_room(
                connection, account_id, runtime.world.id, "bathroom"
            )
        instance_id = next(
            prop.id
            for prop in runtime.world.rooms["bathroom"].props.values()
            if prop.prop_id == "saari-cabinet"
        )
        with self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(credentials["session_token"], credentials["csrf_token"]),
        ) as socket:
            socket.receive_json()
            stored = self.command(socket, "c-store", f".use @card:{stack_id} @prop:{instance_id}")
            self.assertTrue(stored["ok"], stored)
            self.assertIn("Stored", stored["message"])
            self.assertEqual(
                runtime.profiles.get_account_by_id(account_id).shared_energy, before_energy
            )

            opened = self.command(socket, "c-open", f".open @prop:{instance_id}")
            self.assertTrue(opened["ok"], opened)
            self.assertTrue(opened["payload"]["container_open"])
            cards = opened["payload"]["container"]["cards"]
            self.assertEqual(
                [(card["definition"]["id"], card["quantity"]) for card in cards],
                [("tasty-toast", 1)],
            )

            taken = self.command(
                socket, "c-take", f".take @prop:{instance_id} @card:{cards[0]['stack_id']}"
            )
            self.assertTrue(taken["ok"], taken)
            self.assertIn("Took", taken["message"])
            self.assertEqual(taken["payload"]["container"]["cards"], [])

    def test_drop_onto_container_stores(self) -> None:
        credentials = self.create_ready_account("container-dropper")
        runtime = self.runtime()
        account_id = self.account_id(credentials)
        stack_id = self.grant_card(account_id, "poop", 3)
        with runtime.hub.transaction() as connection:
            runtime.profiles.set_remembered_room(
                connection, account_id, runtime.world.id, "bathroom"
            )
        room = runtime.world.rooms["bathroom"]
        instance_id = next(
            prop.id for prop in room.props.values() if prop.prop_id == "saari-cabinet"
        )
        shower_id = next(
            prop.id for prop in room.props.values() if prop.prop_id == "shower"
        )
        with self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(credentials["session_token"], credentials["csrf_token"]),
        ) as socket:
            socket.receive_json()
            dropped = self.command(socket, "c-drop", f".drop @card:{stack_id} 2 @prop:{instance_id}")
            self.assertTrue(dropped["ok"], dropped)
            self.assertIn("Stored", dropped["message"])

            opened = self.command(socket, "c-open", f".open @prop:{instance_id}")
            self.assertTrue(opened["ok"], opened)
            cards = opened["payload"]["container"]["cards"]
            self.assertEqual(
                [(card["definition"]["id"], card["quantity"]) for card in cards],
                [("poop", 2)],
            )

            rejected = self.command(socket, "c-drop-bad", f".drop @card:{stack_id} @prop:{shower_id}")
            self.assertFalse(rejected["ok"])
            self.assertIn("container", rejected["message"])


if __name__ == "__main__":
    unittest.main()
