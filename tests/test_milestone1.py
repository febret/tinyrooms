"""Milestone 1 unit and integration coverage using the standard library."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import threading
import unittest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server.app import create_app
from server.commands.parser import CommandParseError, parse_command, parse_target
from server.config import ConfigError, ensure_contained, load_config
from server.content.cards import ContentError, load_card_catalog
from server.content.worlds import load_world_definition
from server.profiles import ProfileRepository, STARTING_WORLD_COUNTERS
from server.security import hash_password, normalize_username, verify_password
from server.services.cards import CardService
from server.state.migrations import DatabaseHub, ensure_profile_database, ensure_world_database
from tests.common import REPO_ROOT

TEST_ORIGIN = "https://testserver:5000"
TEST_PASSWORD = "password123!"


def auth_headers(csrf_token: str) -> dict[str, str]:
    """Build authenticated request headers."""

    return {"origin": TEST_ORIGIN, "x-csrf-token": csrf_token}


def auth_cookies(session_token: str, csrf_token: str) -> dict[str, str]:
    """Build authenticated request cookies."""

    return {"tr_session": session_token, "tr_csrf": csrf_token}


def websocket_headers(session_token: str, csrf_token: str) -> dict[str, str]:
    """Build authenticated WebSocket headers."""

    return {
        "cookie": f"tr_session={session_token}; tr_csrf={csrf_token}",
        "origin": TEST_ORIGIN,
    }


class RuntimeTestCase(unittest.TestCase):
    """Provide an isolated app, profile directory, and world-state database."""

    features = "dev_sample_activity"

    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.runtime_path = Path(self.temporary_directory.name)
        self.config = load_config(
            env={
                "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "open-sesame",
                "TRSERVER_USERS_PATH": str(self.runtime_path / "users"),
                "TRSERVER_WORLD_PATH": str(REPO_ROOT / "worlds" / "tutorial"),
                "TRSERVER_WORLDSTATE_PATH": str(self.runtime_path / "worldstate.sqlite3"),
                "TRSERVER_FEATURES": self.features,
                "TRSERVER_TIMEZONE": "UTC",
                "TRSERVER_HOST": "testserver",
                "TRSERVER_PORT": "5000",
            },
            repo_root=REPO_ROOT,
        )
        self._open_client()

    def tearDown(self) -> None:
        self._close_client()
        self.temporary_directory.cleanup()

    def _open_client(self) -> None:
        self.app = create_app(self.config)
        self.client_context = TestClient(self.app, base_url=TEST_ORIGIN)
        self.client = self.client_context.__enter__()

    def _close_client(self) -> None:
        if hasattr(self, "client_context"):
            self.client_context.__exit__(None, None, None)
            del self.client_context

    def restart(self) -> None:
        """Restart the application while retaining disposable databases."""

        self._close_client()
        self._open_client()

    def create_account(
        self,
        username: str,
        password: str = TEST_PASSWORD,
    ) -> dict[str, str]:
        """Create an account and return its session credentials."""

        response = self.client.post(
            "/api/auth/create",
            json={
                "username": username,
                "password": password,
                "passphrase": "open-sesame",
            },
            headers={"origin": TEST_ORIGIN},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {
            "session_token": response.cookies["tr_session"],
            "csrf_token": response.cookies["tr_csrf"],
        }

    def create_ready_account(self, username: str) -> dict[str, str]:
        """Create an account and confirm its initial sticker."""

        credentials = self.create_account(username)
        self.confirm_sticker(credentials)
        return credentials

    def confirm_sticker(
        self,
        credentials: dict[str, str],
        sticker: str = "s1.png",
    ) -> dict[str, object]:
        """Confirm an initial sticker for an account."""

        response = self.client.post(
            "/api/stickers/confirm",
            json={"sticker": sticker},
            headers=auth_headers(credentials["csrf_token"]),
            cookies=auth_cookies(
                credentials["session_token"],
                credentials["csrf_token"],
            ),
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def command(
        self,
        socket,
        request_id: str,
        command: str,
    ) -> dict[str, object]:
        """Send a command and return its private result."""

        socket.send_json(
            {
                "v": 1,
                "type": "command",
                "request_id": request_id,
                "command": command,
            }
        )
        result = socket.receive_json()
        self.assertEqual(result["type"], "result")
        self.assertEqual(result["request_id"], request_id)
        return result


class ConfigSecurityParserTests(unittest.TestCase):
    """Cover configuration, password, username, and command contracts."""

    def test_invalid_timezone_and_path_escape_are_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            contained = root / "contained"
            contained.mkdir()
            with self.assertRaises(ConfigError):
                ensure_contained(root, contained, "test")
            with self.assertRaises(ConfigError):
                load_config(
                    env={
                        "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "invite",
                        "TRSERVER_USERS_PATH": str(root / "users"),
                        "TRSERVER_WORLD_PATH": str(REPO_ROOT / "worlds" / "tutorial"),
                        "TRSERVER_WORLDSTATE_PATH": str(root / "world.sqlite3"),
                        "TRSERVER_FEATURES": "",
                        "TRSERVER_TIMEZONE": "Mars/Phobos",
                        "TRSERVER_HOST": "127.0.0.1",
                        "TRSERVER_PORT": "5000",
                    },
                    repo_root=REPO_ROOT,
                )

    def test_password_and_username_security(self) -> None:
        digest = hash_password(TEST_PASSWORD)
        self.assertTrue(verify_password(TEST_PASSWORD, digest))
        self.assertFalse(verify_password("wrong-password", digest))
        display, key = normalize_username("Alice_One")
        self.assertEqual(display, "Alice_One")
        self.assertEqual(key, "alice_one")

    def test_command_quoting_targets_and_malformed_input(self) -> None:
        parsed = parse_command('.pickup "@card:room:stack" 2')
        self.assertEqual(parsed.name, "pickup")
        self.assertEqual(parsed.args, ("@card:room:stack", "2"))
        target = parse_target("@way:portal")
        self.assertEqual((target.kind, target.value), ("way", "portal"))
        self.assertEqual(parse_command("hello room").name, "say")
        with self.assertRaises(CommandParseError):
            parse_command(".")


class ContentPersistenceTests(unittest.TestCase):
    """Cover strict content validation and persistent stack invariants."""

    def test_world_loader_rejects_dangling_exit(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "tutorial"
            shutil.copytree(REPO_ROOT / "worlds" / "tutorial", target)
            rooms_file = target / "rooms" / "rooms.yaml"
            text = rooms_file.read_text(encoding="utf-8")
            rooms_file.write_text(
                text.replace("target: playroom", "target: nowhere", 1),
                encoding="utf-8",
            )
            catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", target)
            with self.assertRaises(ContentError):
                load_world_definition(target, set(catalog.cards))

    def test_prop_animation_loader_defaults_and_validation(self) -> None:
        catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", REPO_ROOT / "worlds" / "tutorial")
        world = load_world_definition(REPO_ROOT / "worlds" / "tutorial", set(catalog.cards))
        self.assertEqual(world.props["portal"].animation, "auto")
        self.assertIsNone(world.rooms["hub"].props["portal0"].animation)
        self.assertIsNone(world.props["plant"].animation)
        self.assertIsNone(world.rooms["hub"].props["welcome-plant"].animation)

    def test_board_image_style_loader_validation(self) -> None:
        catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", REPO_ROOT / "worlds" / "tutorial")
        world = load_world_definition(REPO_ROOT / "worlds" / "tutorial", set(catalog.cards))
        self.assertEqual(world.rooms["hub"].board_image_style, "stretch")
        self.assertEqual(world.rooms["playroom"].board_image_style, "tile")
        with TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "tutorial"
            shutil.copytree(REPO_ROOT / "worlds" / "tutorial", target)
            rooms_file = target / "rooms" / "rooms.yaml"
            text = rooms_file.read_text(encoding="utf-8")
            rooms_file.write_text(
                text.replace("board_image_style: tile", "board_image_style: bogus", 1),
                encoding="utf-8",
            )
            with self.assertRaises(ContentError):
                load_world_definition(target, set(catalog.cards))

    def test_core_card_order_is_loaded_and_sorted(self) -> None:
        catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", REPO_ROOT / "worlds" / "tutorial")
        order_defined = {card_id: definition.order for card_id, definition in catalog.cards.items() if definition.order is not None}
        self.assertEqual(
            order_defined,
            {"emotes": 2, "inventory": 3, "journal": 5},
        )
        service = CardService(None, None, None, catalog, "tutorial")
        serialized = service.serialize_core_cards()
        self.assertEqual(
            [card["id"] for card in serialized],
            ["emotes", "inventory", "journal"],
        )
        self.assertTrue(all(card["type"] == "core" for card in serialized))
        self.assertTrue(all(card["image_url"].startswith("/assets/base/") for card in serialized))
        self.assertFalse(any(card["id"] in {"self", "friends", "edit-room", "arrow-left", "arrow-right"} for card in serialized))

    def test_inventory_stack_limit_and_world_defaults(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            profile_db = root / "profiles.sqlite3"
            world_db = root / "world.sqlite3"
            ensure_profile_database(profile_db)
            ensure_world_database(world_db)
            hub = DatabaseHub(profile_db, world_db)
            try:
                profiles = ProfileRepository(hub)
                account = profiles.create_account(
                    "StackUser",
                    TEST_PASSWORD,
                    "tutorial",
                    "hub",
                )
                user_profile = profiles.get_user_profile(account.id)
                self.assertEqual(user_profile.counters, STARTING_WORLD_COUNTERS)
                self.assertEqual(user_profile.last_world_id, "tutorial")
                self.assertEqual(user_profile.remembered_room, "hub")
                self.assertFalse(user_profile.show_activity_log)
                self.assertEqual(user_profile.owned_rooms, ())
                self.assertEqual(replace(user_profile, ownership={"rooms": ["bedroom"]}).owned_rooms, ("bedroom",))
                with hub.transaction() as connection:
                    created = profiles.add_inventory_card(
                        connection,
                        account_id=account.id,
                        world_id="tutorial",
                        card_def_id="juicy-drink",
                        quantity=25,
                        scope="world",
                        stack_limit=10,
                    )
                self.assertEqual(
                    sorted(stack.quantity for stack in created),
                    [5, 10, 10],
                )
                ensured = profiles.ensure_user_profile(account.id, "other-world", "hub")
                self.assertEqual(ensured.last_world_id, "other-world")
                with hub.locked() as connection:
                    rows = connection.execute(
                        "SELECT COUNT(*) FROM user_profiles WHERE account_id = ?",
                        (account.id,),
                    ).fetchone()
                self.assertEqual(int(rows[0]), 1)
                shown = profiles.set_show_activity_log(account.id, True)
                self.assertTrue(shown.show_activity_log)
            finally:
                hub.close()


class AccountLifecycleTests(RuntimeTestCase):
    """Cover account gating, sessions, CSRF, and sticker completion."""

    def test_passphrase_casefold_uniqueness_and_csrf_failures(self) -> None:
        missing_origin = self.client.post(
            "/api/auth/create",
            json={
                "username": "originless",
                "password": TEST_PASSWORD,
                "passphrase": "open-sesame",
            },
        )
        self.assertEqual(missing_origin.status_code, 403)
        wrong = self.client.post(
            "/api/auth/create",
            json={
                "username": "alice",
                "password": TEST_PASSWORD,
                "passphrase": "wrong",
            },
            headers={"origin": TEST_ORIGIN},
        )
        self.assertEqual(wrong.status_code, 401)
        alice = self.create_account("Alice")
        duplicate = self.client.post(
            "/api/auth/create",
            json={
                "username": "alice",
                "password": TEST_PASSWORD,
                "passphrase": "open-sesame",
            },
            headers={"origin": TEST_ORIGIN},
        )
        self.assertEqual(duplicate.status_code, 409)
        missing_csrf = self.client.post(
            "/api/auth/logout",
            headers={"origin": TEST_ORIGIN},
            cookies=auth_cookies(alice["session_token"], alice["csrf_token"]),
        )
        self.assertEqual(missing_csrf.status_code, 403)

    def test_logout_immediately_revokes_open_websocket(self) -> None:
        alice = self.create_ready_account("alice")
        with self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(
                alice["session_token"],
                alice["csrf_token"],
            ),
        ) as socket:
            socket.receive_json()
            logout = self.client.post(
                "/api/auth/logout",
                headers=auth_headers(alice["csrf_token"]),
                cookies=auth_cookies(
                    alice["session_token"],
                    alice["csrf_token"],
                ),
            )
            self.assertEqual(logout.status_code, 200)
            revoked = socket.receive_json()
            self.assertEqual(revoked["type"], "session.replaced")
            self.assertEqual(revoked["message"], "You signed out.")

    def test_interrupted_and_idempotent_sticker_flow(self) -> None:
        alice = self.create_account("alice")
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                "/ws",
                headers={
                    "cookie": (
                        f"tr_session={alice['session_token']}; "
                        f"tr_csrf={alice['csrf_token']}"
                    )
                },
            ):
                pass
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                "/ws",
                headers=websocket_headers(
                    alice["session_token"],
                    alice["csrf_token"],
                ),
            ):
                pass
        first = self.confirm_sticker(alice)
        second = self.confirm_sticker(alice)
        self.assertTrue(first["user"]["initial_sticker_complete"])
        self.assertEqual(second["user"]["sticker"], "s1.png")

    def test_second_login_replaces_first_without_removing_new_connection(self) -> None:
        alice = self.create_ready_account("alice")
        with self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(
                alice["session_token"],
                alice["csrf_token"],
            ),
        ) as first_socket:
            first_socket.receive_json()
            login = self.client.post(
                "/api/auth/login",
                json={"username": "alice", "password": TEST_PASSWORD},
                headers={"origin": TEST_ORIGIN},
            )
            self.assertEqual(login.status_code, 200)
            replacement = first_socket.receive_json()
            self.assertEqual(replacement["type"], "session.replaced")
            second = {
                "session_token": login.cookies["tr_session"],
                "csrf_token": login.cookies["tr_csrf"],
            }
            with self.client.websocket_connect(
                "/ws",
                headers=websocket_headers(
                    second["session_token"],
                    second["csrf_token"],
                ),
            ) as second_socket:
                self.assertEqual(
                    second_socket.receive_json()["type"],
                    "room.snapshot",
                )
                result = self.command(second_socket, "look-1", ".look")
                self.assertTrue(result["ok"])


class MultiplayerGameplayTests(RuntimeTestCase):
    """Cover presence, chat, navigation, cards, activities, and settings."""

    def test_hub_snapshot_includes_portal_animation(self) -> None:
        alice = self.create_ready_account("alice")
        with self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(
                alice["session_token"],
                alice["csrf_token"],
            ),
        ) as socket:
            room = socket.receive_json()["room"]
            self.assertEqual(room["id"], "hub")
            portal = next(entry for entry in room["props"] if entry["id"] == "portal0")
            self.assertEqual(portal["animation"], "auto")
            plant = next(entry for entry in room["props"] if entry["id"] == "welcome-plant")
            self.assertIsNone(plant["animation"])

    def test_two_clients_chat_and_navigate(self) -> None:
        alice = self.create_ready_account("alice")
        bob = self.create_ready_account("bob")
        with self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(
                alice["session_token"],
                alice["csrf_token"],
            ),
        ) as alice_socket:
            alice_snapshot = alice_socket.receive_json()
            self.assertEqual(alice_snapshot["type"], "room.snapshot")
            with self.client.websocket_connect(
                "/ws",
                headers=websocket_headers(
                    bob["session_token"],
                    bob["csrf_token"],
                ),
            ) as bob_socket:
                bob_snapshot = bob_socket.receive_json()
                self.assertEqual(bob_snapshot["type"], "room.snapshot")
                self.assertEqual(bob_snapshot["room"]["id"], "hub")
                joined = alice_socket.receive_json()
                self.assertEqual(joined["type"], "room.event")
                self.assertEqual(joined["event"]["type"], "presence.enter")
                self.assertTrue(
                    self.command(
                        alice_socket,
                        "chat-1",
                        "(!) hello hub",
                    )["ok"]
                )
                alice_chat = alice_socket.receive_json()
                bob_chat = bob_socket.receive_json()
                self.assertEqual(alice_chat["event"]["style"], "spiky")
                self.assertEqual(bob_chat["event"]["text"], "hello hub")
                self.assertTrue(
                    self.command(
                        alice_socket,
                        "go-1",
                        ".go @way:exit0",
                    )["ok"]
                )
                self.assertEqual(
                    alice_socket.receive_json()["room"]["id"],
                    "playroom",
                )
                self.assertEqual(
                    bob_socket.receive_json()["event"]["type"],
                    "presence.leave",
                )

    def test_strict_room_scope_card_transfer_and_restart(self) -> None:
        dana = self.create_ready_account("dana")
        with self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(
                dana["session_token"],
                dana["csrf_token"],
            ),
        ) as socket:
            hub = socket.receive_json()["room"]
            self.assertIn(
                "playroom",
                {exit_entry["target_room_id"] for exit_entry in hub["exits"]},
            )
            self.command(socket, "go-1", ".go @way:exit0")
            playroom = socket.receive_json()["room"]
            self.assertEqual(
                {exit_entry["target_room_id"] for exit_entry in playroom["exits"]},
                {"hub", "foyer"},
            )
            room_card = playroom["room_cards"][0]
            pickup = self.command(
                socket,
                "pickup-1",
                f".pickup @card:{room_card['stack_id']} 1",
            )
            self.assertTrue(pickup["ok"])
            socket.receive_json()
        self.restart()
        login = self.client.post(
            "/api/auth/login",
            json={"username": "dana", "password": TEST_PASSWORD},
            headers={"origin": TEST_ORIGIN},
        )
        credentials = {
            "session_token": login.cookies["tr_session"],
            "csrf_token": login.cookies["tr_csrf"],
        }
        with self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(
                credentials["session_token"],
                credentials["csrf_token"],
            ),
        ) as socket:
            snapshot = socket.receive_json()["room"]
            self.assertEqual(snapshot["id"], "playroom")
            inventory_ids = {
                stack["definition"]["id"] for stack in snapshot["inventory"]
            }
            self.assertEqual(
                room_card["definition"]["id"],
                "fancy-wallet",
            )
            self.assertIn("fancy-wallet", inventory_ids)
            picked = next(
                stack for stack in snapshot["inventory"]
                if stack["definition"]["id"] == "fancy-wallet"
            )
            self.assertTrue(picked["equipped"])
            self.assertFalse(
                any(
                    stack["stack_id"] == room_card["stack_id"]
                    for stack in snapshot["room_cards"]
                )
            )

    def test_atomic_pickup_has_one_winner(self) -> None:
        runtime = self.client.app.state.runtime
        account = runtime.profiles.create_account(
            "Picker",
            TEST_PASSWORD,
            runtime.world.id,
            runtime.world.entry_room_id,
        )
        stack = runtime.world_state.list_room_cards("playroom")[0]
        self.assertEqual(len(stack.position), 3)
        serialized = runtime.cards.serialize_room_stack(stack)
        self.assertEqual(list(serialized["position"]), list(stack.position))
        barrier = threading.Barrier(2)
        results: list[str] = []

        def worker() -> None:
            barrier.wait()
            try:
                runtime.cards.pickup(
                    account,
                    "playroom",
                    stack.stack_id,
                    1,
                )
                results.append("ok")
            except ValueError:
                results.append("fail")

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), ["fail", "ok"])

    def test_drop_uses_requested_position_and_clamps_coordinates(self) -> None:
        player = self.create_ready_account("planter")
        runtime = self.client.app.state.runtime
        with self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(
                player["session_token"],
                player["csrf_token"],
            ),
        ) as socket:
            socket.receive_json()
            self.assertTrue(self.command(socket, "go-1", ".go @way:exit0")["ok"])
            playroom = socket.receive_json()["room"]
            room_card = playroom["room_cards"][0]
            pickup = self.command(
                socket,
                "pickup-1",
                f".pickup @card:{room_card['stack_id']} 1",
            )
            self.assertTrue(pickup["ok"])
            socket.receive_json()
            picked_stack_id = next(
                stack["stack_id"]
                for stack in pickup["payload"]["inventory"]
                if stack["definition"]["id"] == room_card["definition"]["id"]
            )
            dropped = self.command(
                socket,
                "drop-1",
                f".drop @card:{picked_stack_id} 1 23.5 67.25 0",
            )
            self.assertTrue(dropped["ok"])
            added = socket.receive_json()
            self.assertEqual(added["event"]["type"], "room.card.added")
            self.assertEqual(
                added["event"]["stack"]["position"],
                [23.5, 67.25, 0.0],
            )
            persisted = next(
                stack
                for stack in runtime.world_state.list_room_cards("playroom")
                if stack.stack_id == added["event"]["stack"]["stack_id"]
            )
            self.assertEqual(tuple(persisted.position), (23.5, 67.25, 0.0))
            smile_stack_id = next(
                stack["stack_id"]
                for stack in playroom["inventory"]
                if stack["definition"]["id"] == "smile"
            )
            clamped = self.command(
                socket,
                "drop-2",
                f".drop @card:{smile_stack_id} 1 250 -10 999",
            )
            self.assertTrue(clamped["ok"])
            clamped_added = socket.receive_json()
            self.assertEqual(
                clamped_added["event"]["stack"]["position"],
                [100.0, 0.0, 50.0],
            )

    def test_reset_room_restores_definition_seed_cards(self) -> None:
        runtime = self.client.app.state.runtime
        seed_ids = {
            f"room:{card.initial_key}"
            for card in runtime.world.rooms["playroom"].initial_cards
        }
        player = self.create_ready_account("resetter")
        with self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(
                player["session_token"],
                player["csrf_token"],
            ),
        ) as socket:
            socket.receive_json()
            self.assertTrue(self.command(socket, "go-1", ".go @way:exit0")["ok"])
            playroom = socket.receive_json()["room"]
            dropped_id = playroom["inventory"][0]["stack_id"]
            self.assertTrue(
                self.command(socket, "drop-1", f".drop @card:{dropped_id} 1")["ok"]
            )
            added = socket.receive_json()
            self.assertEqual(added["type"], "room.event")
            self.assertEqual(added["event"]["type"], "room.card.added")
            self.assertNotIn(added["event"]["stack"]["stack_id"], seed_ids)
            reset = self.command(socket, "reset-1", ".reset_room")
            self.assertTrue(reset["ok"])
            snapshot = socket.receive_json()
            self.assertEqual(snapshot["type"], "room.snapshot")
            self.assertEqual(
                {stack["stack_id"] for stack in snapshot["room"]["room_cards"]},
                seed_ids,
            )
            broadcast = socket.receive_json()
            self.assertEqual(broadcast["type"], "room.event")
            self.assertEqual(broadcast["event"]["type"], "room.cards.reset")
            self.assertEqual(
                {stack["stack_id"] for stack in broadcast["event"]["stacks"]},
                seed_ids,
            )

    def test_activity_replacement_disconnect_and_persisted_setting(self) -> None:
        carol = self.create_ready_account("carol")
        with self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(
                carol["session_token"],
                carol["csrf_token"],
            ),
        ) as socket:
            socket.receive_json()
            opened = self.command(socket, "play-1", ".play sample")
            self.assertTrue(opened["ok"])
            rejected = self.command(socket, "play-2", ".play sample-other")
            self.assertFalse(rejected["ok"])
            replaced = self.command(
                socket,
                "play-3",
                ".play sample replace",
            )
            self.assertTrue(replaced["ok"])
            self.assertTrue(
                any(
                    event["type"] == "activity.closed"
                    for event in replaced["events"]
                )
            )
            setting = self.command(
                socket,
                "setting-1",
                ".settings action-log on",
            )
            self.assertTrue(setting["payload"]["show_activity_log"])
        self.assertIsNone(self.client.app.state.runtime.activities.get(
            self.client.app.state.runtime.profiles.get_account_by_username(
                "carol"
            ).id
        ))
        session = self.client.get(
            "/api/session",
            cookies=auth_cookies(
                carol["session_token"],
                carol["csrf_token"],
            ),
        )
        self.assertTrue(session.json()["user"]["show_activity_log"])

    def test_static_app_and_activity_assets_are_explicitly_served(self) -> None:
        index = self.client.get("/")
        module = self.client.get("/app/js/ui.js")
        shared_css = self.client.get("/activities/shared.css")
        private_file = self.client.get("/assets/stickers/../../users/profiles.sqlite3")
        self.assertEqual(index.status_code, 200)
        self.assertIn("/app/js/ui.js", index.text)
        self.assertEqual(module.status_code, 200)
        self.assertEqual(shared_css.status_code, 200)
        self.assertIn("text/css", shared_css.headers["content-type"])
        self.assertEqual(private_file.status_code, 404)


class PickupAutoEquipTests(RuntimeTestCase):
    """Picked-up cards occupy an equipped slot while the hand has space."""

    def test_pickup_equips_item_when_hand_has_space(self) -> None:
        runtime = self.client.app.state.runtime
        account = runtime.profiles.create_account(
            "Equipper",
            TEST_PASSWORD,
            runtime.world.id,
            runtime.world.entry_room_id,
        )
        stack = runtime.world_state.list_room_cards("playroom")[0]
        result = runtime.cards.pickup(account, "playroom", stack.stack_id, 1)
        picked = [
            item for item in result.inventory
            if item["definition"]["id"] == stack.card_def_id
        ]
        self.assertEqual(len(picked), 1)
        self.assertTrue(picked[0]["equipped"])

    def test_pickup_leaves_cards_unequipped_when_hand_is_full(self) -> None:
        runtime = self.client.app.state.runtime
        account = runtime.profiles.create_account(
            "FullHand",
            TEST_PASSWORD,
            runtime.world.id,
            runtime.world.entry_room_id,
        )
        with runtime.hub.transaction() as connection:
            for card_id in (
                "tasty-toast", "tomato-sauce", "juicy-drink", "plastic-bag", "pooper-scooper"
            ):
                created = runtime.profiles.add_inventory_card(
                    connection,
                    account_id=account.id,
                    world_id=runtime.world.id,
                    card_def_id=card_id,
                    quantity=1,
                    scope="world",
                    stack_limit=10,
                )
                runtime.profiles.set_stack_equipped(
                    connection,
                    account_id=account.id,
                    world_id=runtime.world.id,
                    stack_id=created[0].stack_id,
                    equipped=True,
                )
        stack = runtime.world_state.list_room_cards("playroom")[0]
        result = runtime.cards.pickup(account, "playroom", stack.stack_id, 1)
        picked = [
            item for item in result.inventory
            if item["definition"]["id"] == stack.card_def_id
        ]
        self.assertEqual(len(picked), 1)
        self.assertFalse(picked[0]["equipped"])
        self.assertEqual(sum(1 for item in result.inventory if item["equipped"]), 5)


if __name__ == "__main__":
    unittest.main()
