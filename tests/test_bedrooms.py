"""Per-player bedroom door tests: catalog, mod props, service, commands, migration."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import shutil
import sqlite3
import unittest

from server.content.worlds import ContentError, prop_model_url
from server.mods import discover_mods, load_mod_module
from server.services.ownership import OwnershipService
from server.state.migrations import WORLD_SCHEMA_VERSION, ensure_world_database
from server.state.world_state import WorldStateRepository
from tests.common import REPO_ROOT, ServiceTestCase, WORLD_ID, load_test_world, load_world_activities, load_world_mod_props
from tests.test_milestone1 import websocket_headers
from tests.test_milestone2_integration import Milestone2IntegrationTestCase


MOD = load_mod_module(discover_mods(REPO_ROOT / "mods")["infinite-bedrooms"])
load_door_catalog = MOD.load_door_catalog
BedroomService = MOD.BedroomService
DOORS_PATH = REPO_ROOT / "mods" / "infinite-bedrooms" / "content" / "doors.yaml"


class DoorCatalogTests(unittest.TestCase):
    """The door customization catalog loads and validates styles."""

    def test_catalog_exposes_five_dimensions_and_defaults(self) -> None:
        catalog = load_door_catalog(DOORS_PATH)
        self.assertEqual(catalog.cost, 10)
        self.assertEqual(
            [dimension.id for dimension in catalog.dimensions],
            ["color", "material", "handle", "tag_color", "tag_text"],
        )
        for dimension in catalog.dimensions:
            if dimension.kind == "choice":
                self.assertEqual(len(dimension.options), 5)
        defaults = catalog.default_style()
        self.assertEqual(defaults["color"], "crimson")
        self.assertEqual(defaults["tag_text"], "")

    def test_validate_patch_rejects_unknown_and_invalid_values(self) -> None:
        catalog = load_door_catalog(DOORS_PATH)
        with self.assertRaises(ValueError):
            catalog.validate_patch({"bogus": "x"})
        with self.assertRaises(ValueError):
            catalog.validate_patch({"color": "chartreuse"})
        with self.assertRaises(ValueError):
            catalog.validate_patch({"tag_text": "x" * 17})
        with self.assertRaises(ValueError):
            catalog.validate_patch({"tag_text": "bad<tag>"})
        normalized = catalog.validate_patch({"material": "wood", "tag_text": "My Room"})
        self.assertEqual(normalized, {"material": "wood", "tag_text": "My Room"})


class ModPropLoaderTests(unittest.TestCase):
    """Mod props merge into the tutorial world's prop catalog like world props."""

    def test_mod_prop_resolves_and_urls(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / WORLD_ID)
        archway = world.props["archway"]
        self.assertEqual(archway.source, "infinite-bedrooms")
        self.assertEqual(archway.source_kind, "mod")
        self.assertEqual(
            prop_model_url(world.id, archway),
            "/assets/mods/infinite-bedrooms/props/archway.glb",
        )
        self.assertEqual(prop_model_url(world.id, world.props["portal"]), "/assets/world/tutorial/props/portal.glb")
        self.assertIn("archway0", world.rooms["hub"].props)

    def test_duplicate_prop_id_between_mod_and_world_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "tutorial"
            shutil.copytree(REPO_ROOT / "worlds" / "tutorial", target)
            props_file = target / "props" / "props.yaml"
            props_file.write_text(
                props_file.read_text(encoding="utf-8")
                + "\narchway:\n  label: Duplicate\n  description: Duplicate.\n"
                + "  model: portal.glb\n  scale: 1.0\n",
                encoding="utf-8",
            )
            with self.assertRaises(ContentError):
                load_test_world(target)

    def test_missing_propset_model_is_rejected(self) -> None:
        from server.content.cards import load_card_catalog
        from server.content.worlds import load_world_definition

        with TemporaryDirectory() as temporary_directory:
            propsets = Path(temporary_directory) / "propsets"
            (propsets / "base").mkdir(parents=True)
            (propsets / "base" / "props.yaml").write_text(
                "ghost:\n  label: Ghost\n  description: Missing.\n  model: ghost.glb\n  scale: 1.0\n",
                encoding="utf-8",
            )
            catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", REPO_ROOT / "worlds" / WORLD_ID)
            with self.assertRaises(ContentError):
                load_world_definition(
                    REPO_ROOT / "worlds" / WORLD_ID,
                    set(catalog.cards),
                    core_activities=load_world_activities(),
                    propsets_root=propsets,
                    mod_props=load_world_mod_props(),
                )


class BedroomServiceTestCase(ServiceTestCase):
    """Shared service wiring for the player bedroom tests."""

    def setUp(self) -> None:
        super().setUp()
        self.world = load_test_world(REPO_ROOT / "worlds" / WORLD_ID)
        self.world_state = WorldStateRepository(self.hub)
        self.ownership = OwnershipService(self.hub, self.profiles, self.world_state, self.world)
        self.door_catalog = load_door_catalog(DOORS_PATH)
        self.bedrooms = BedroomService(
            self.hub,
            self.profiles,
            self.world_state,
            self.ownership,
            self.world,
            self.door_catalog,
        )
        self.bedrooms.prepare()
        self.world_state.initialize_world(self.world)


class BedroomServiceTests(BedroomServiceTestCase):
    """Door purchase, materialization, locking, and design rules."""

    def test_purchase_charges_bops_and_materializes_owned_room(self) -> None:
        account = self.create_account("alice")
        view = self.bedrooms.purchase(account)
        room_id = BedroomService.room_id_for(account.id)
        self.assertEqual(view.room_id, room_id)
        self.assertEqual(view.owner_username, "alice")
        self.assertIn("alice", view.label)
        self.assertEqual(self.reload_account(account).bops, 0)
        self.assertIn(room_id, self.world.rooms)
        self.assertEqual(self.world.rooms[room_id].label, view.label)
        self.assertEqual(self.ownership.owner_of(room_id), account.id)
        profile = self.profiles.user_profile_for(account.id, WORLD_ID, "hub")
        self.assertIn(room_id, profile.owned_rooms)
        self.assertIsNotNone(self.world_state.get_player_room(room_id))

    def test_second_purchase_is_rejected_without_double_charge(self) -> None:
        account = self.create_account("alice")
        self.bedrooms.purchase(account)
        with self.assertRaises(ValueError):
            self.bedrooms.purchase(self.reload_account(account))
        self.assertEqual(self.reload_account(account).bops, 0)

    def test_purchase_requires_bops_and_leaves_no_room(self) -> None:
        account = self.create_account("alice")
        self.set_progress(account, bops=5)
        with self.assertRaises(ValueError):
            self.bedrooms.purchase(self.reload_account(account))
        self.assertEqual(self.reload_account(account).bops, 5)
        self.assertIsNone(self.world_state.get_player_room_for_account(account.id))

    def test_locked_door_blocks_others_but_not_owner(self) -> None:
        owner = self.create_account("alice")
        other = self.create_account("bob")
        self.bedrooms.purchase(owner)
        room_id = BedroomService.room_id_for(owner.id)
        self.assertIsNotNone(self.bedrooms.require_entry(other, room_id))
        self.bedrooms.set_locked(owner, True)
        with self.assertRaises(ValueError):
            self.bedrooms.require_entry(other, room_id)
        self.assertIsNotNone(self.bedrooms.require_entry(owner, room_id))
        self.bedrooms.set_locked(owner, False)
        self.assertIsNotNone(self.bedrooms.require_entry(other, room_id))

    def test_design_validates_and_persists(self) -> None:
        account = self.create_account("alice")
        self.bedrooms.purchase(account)
        view = self.bedrooms.design(account, {"color": "cobalt", "handle": "ring", "tag_text": "Home"})
        self.assertEqual(view.style["color"], "cobalt")
        self.assertEqual(view.style["handle"], "ring")
        self.assertEqual(view.style["tag_text"], "Home")
        with self.assertRaises(ValueError):
            self.bedrooms.design(account, {"color": "bogus"})
        with self.assertRaises(ValueError):
            self.bedrooms.design(account, {"tag_text": "x" * 40})
        with self.assertRaises(ValueError):
            self.bedrooms.design(account, {"material": "bogus"})

    def test_list_doors_marks_the_viewer(self) -> None:
        owner = self.create_account("alice")
        other = self.create_account("bob")
        self.bedrooms.purchase(owner)
        doors = self.bedrooms.list_doors(viewer_id=owner.id)
        self.assertEqual(len(doors), 1)
        self.assertTrue(doors[0]["is_owner"])
        self.assertFalse(self.bedrooms.list_doors(viewer_id=other.id)[0]["is_owner"])

    def test_world_schema_uses_room_states_for_player_rooms(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "world.sqlite3"
            ensure_world_database(path)
            connection = sqlite3.connect(path)
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            columns = [row[1] for row in connection.execute("PRAGMA table_info(room_states)")]
            connection.close()
        self.assertEqual(version, WORLD_SCHEMA_VERSION)
        self.assertNotIn("player_rooms", tables)
        self.assertIn("door_json", columns)

    def test_v9_player_rooms_migrate_into_room_states(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "world.sqlite3"
            ensure_world_database(path)
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                BEGIN;
                ALTER TABLE room_states DROP COLUMN door_json;
                CREATE TABLE player_rooms (
                    room_id TEXT PRIMARY KEY,
                    owner_account_id TEXT NOT NULL UNIQUE,
                    template_room_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    locked INTEGER NOT NULL DEFAULT 0 CHECK (locked IN (0, 1)),
                    door_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(door_json)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO room_states (room_id, initialized, owner_account_id, props_json, environment_json, layout_revision)
                VALUES ('bedroom:alice', 1, 'alice', '{}', '{}', 0);
                INSERT INTO player_rooms (room_id, owner_account_id, template_room_id, label, locked, door_json, created_at, updated_at)
                VALUES ('bedroom:alice', 'alice', 'player-bedroom', 'alice''s Bedroom', 1, '{"color":"cobalt"}', 't', 't');
                PRAGMA user_version = 9;
                COMMIT;
                """
            )
            connection.close()

            ensure_world_database(path)

            connection = sqlite3.connect(path)
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            door = connection.execute(
                "SELECT door_json FROM room_states WHERE room_id = 'bedroom:alice'"
            ).fetchone()[0]
            connection.close()
        self.assertEqual(version, WORLD_SCHEMA_VERSION)
        self.assertNotIn("player_rooms", tables)
        self.assertEqual(json.loads(door), {"style": {"color": "cobalt"}, "locked": 1})


class DoorCommandIntegrationTests(Milestone2IntegrationTestCase):
    """The .door command family over the live WebSocket protocol."""

    def test_play_bedrooms_opens_activity_in_hub(self) -> None:
        credentials = self.create_ready_account("ada")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            result = self.command(socket, "play-1", ".play bedrooms")
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["payload"]["activity"]["kind"], "bedrooms")

    def test_archway_gains_go_to_bedroom_action_once_owned(self) -> None:
        credentials = self.create_ready_account("alice")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            initial = socket.receive_json()
            self.assertEqual(initial["type"], "room.snapshot")
            archway = next(prop for prop in initial["room"]["props"] if prop["id"] == "archway0")
            self.assertNotIn("Go to Bedroom", [action["label"] for action in archway["quick_actions"]])

            purchase = self.command(socket, "buy-1", ".door buy")
            self.assertTrue(purchase["ok"], purchase)
            room_id = purchase["payload"]["door"]["room_id"]

            socket.send_json({"v": 1, "type": "snapshot.request"})
            refreshed = socket.receive_json()
            self.assertEqual(refreshed["type"], "room.snapshot")
            archway = next(prop for prop in refreshed["room"]["props"] if prop["id"] == "archway0")
            actions = {action["label"]: action["command"] for action in archway["quick_actions"]}
            self.assertEqual(actions.get("Go to Bedroom"), f".door enter {room_id}")

    def test_buy_enter_and_lock_flow(self) -> None:
        owner = self.create_ready_account("alice")
        other = self.create_ready_account("bob")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(owner["session_token"], owner["csrf_token"])
        ) as owner_socket:
            owner_socket.receive_json()
            listing = self.command(owner_socket, "list-1", ".door list")
            self.assertTrue(listing["ok"], listing)
            self.assertEqual(listing["payload"]["cost"], 10)
            self.assertEqual(len(listing["payload"]["catalog"]["dimensions"]), 5)

            purchase = self.command(owner_socket, "buy-1", ".door buy")
            self.assertTrue(purchase["ok"], purchase)
            self.assertEqual(purchase["payload"]["user"]["bops"], 0)
            room_id = purchase["payload"]["door"]["room_id"]

            design = self.command(owner_socket, "design-1", ".door design color cobalt tag_text Home")
            self.assertTrue(design["ok"], design)
            self.assertEqual(design["payload"]["door"]["style"]["color"], "cobalt")

            enter = self.command(owner_socket, "enter-1", f".door enter {room_id}")
            self.assertTrue(enter["ok"], enter)
            snapshot = owner_socket.receive_json()
            self.assertEqual(snapshot["type"], "room.snapshot")
            self.assertEqual(snapshot["room"]["id"], room_id)
            self.assertTrue(snapshot["room"]["can_edit_room"])

            lock = self.command(owner_socket, "lock-1", ".door lock on")
            self.assertTrue(lock["ok"], lock)

        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(other["session_token"], other["csrf_token"])
        ) as other_socket:
            other_socket.receive_json()
            blocked = self.command(other_socket, "enter-2", f".door enter {room_id}")
            self.assertFalse(blocked["ok"])
            self.assertIn("locked", blocked["message"].lower())
