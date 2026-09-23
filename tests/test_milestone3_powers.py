"""Milestone 3 Phase D power, audit, and moderation tests."""

from __future__ import annotations

from dataclasses import replace

from starlette.websockets import WebSocketDisconnect

from server.services.audit import AuditService
from server.services.ownership import OwnershipService
from server.services.powers import PowersService
from server.state.world_state import WorldStateRepository
from tests.common import REPO_ROOT, WORLD_ID, ServiceTestCase, load_test_world
from tests.test_milestone1 import websocket_headers
from tests.test_milestone2_integration import Milestone2IntegrationTestCase


class PowerServiceTests(ServiceTestCase):
    """Powers combine world, bootstrap, and DB sources and are audited."""

    def setUp(self) -> None:
        super().setUp()
        self.world = load_test_world(REPO_ROOT / "worlds" / "tutorial", set(self.catalog.cards))
        self.world_state = WorldStateRepository(self.hub)
        self.audit = AuditService(self.hub, WORLD_ID)
        self.powers = PowersService(self.hub, self.profiles, self.world, frozenset(), self.audit)

    def test_world_yaml_bootstrap_and_db_powers_combine(self) -> None:
        world = replace(self.world, powers={"ada": ("realtor",)})
        powers = PowersService(self.hub, self.profiles, world, frozenset({"bea"}), self.audit)
        ada = self.create_account("ada")
        bea = self.create_account("bea")
        cam = self.create_account("cam")
        self.assertIn("realtor", powers.effective(ada))
        self.assertIn("admin", powers.effective(bea))
        self.assertEqual(powers.effective(cam), frozenset())
        powers.grant(cam.id, cam.id, "builder")
        self.assertIn("builder", powers.effective(cam))
        powers.revoke(cam.id, cam.id, "builder")
        self.assertNotIn("builder", powers.effective(cam))

    def test_unknown_power_is_rejected(self) -> None:
        account = self.create_account("dee")
        with self.assertRaises(ValueError):
            self.powers.grant(account.id, account.id, "wizard")

    def test_grant_and_revoke_are_audited(self) -> None:
        actor = self.create_account("eva")
        target = self.create_account("finn")
        self.powers.grant(actor.id, target.id, "moderator")
        self.powers.revoke(actor.id, target.id, "moderator")
        actions = [entry["action"] for entry in self.audit.entries()]
        self.assertIn("power.grant.moderator", actions)
        self.assertIn("power.revoke.moderator", actions)

    def test_mute_expires_and_is_audited(self) -> None:
        actor = self.create_account("gus")
        target = self.create_account("hana")
        self.powers.mute(actor.id, target.id, 30)
        self.assertTrue(self.powers.is_muted(target.id))
        with self.hub.transaction() as connection:
            connection.execute(
                "UPDATE accounts SET muted_until = ? WHERE id = ?",
                ("2000-01-01T00:00:00+00:00", target.id),
            )
        self.assertFalse(self.powers.is_muted(target.id))
        self.assertIn("moderation.mute", [entry["action"] for entry in self.audit.entries()])

    def test_ownership_can_edit_uses_builder_power(self) -> None:
        account = self.create_account("iris")
        ownership = OwnershipService(self.hub, self.profiles, self.world_state, self.world, self.powers.has_power)
        self.assertFalse(ownership.can_edit(account, "hub"))
        ownership.grant("hub", account.id)
        self.assertEqual(ownership.owner_of("hub"), account.id)
        self.assertTrue(ownership.can_edit(account, "hub"))
        self.assertIn("hub", self.profiles.get_user_profile(account.id).owned_rooms)


class BootstrapAdminTests(Milestone2IntegrationTestCase):
    """TRSERVER_ADMINS grants admin without inferring it from creation order."""

    def setUp(self) -> None:
        super().setUp()
        self.config = replace(self.config, bootstrap_admins=frozenset({"root"}))
        self.restart()

    def test_bootstrap_admin_env_grants_admin(self) -> None:
        root = self.bootstrap(self.create_ready_account("root"))
        other = self.bootstrap(self.create_ready_account("plain"))
        self.assertIn("admin", root["powers"])
        self.assertEqual(other["powers"], [])


class PowerIntegrationTests(Milestone2IntegrationTestCase):
    """Power boundaries hold through the WebSocket command path."""

    def send_command(self, socket, request_id: str, command: str) -> dict[str, object]:
        """Send a command and drain interleaved room events until its result."""

        socket.send_json({"v": 1, "type": "command", "request_id": request_id, "command": command})
        for _ in range(16):
            message = socket.receive_json()
            if message.get("type") == "result" and message.get("request_id") == request_id:
                return message
        raise AssertionError(f"Never received result for {command!r}.")

    def test_bootstrap_exposes_powers(self) -> None:
        credentials = self.create_ready_account("ada")
        user = self.bootstrap(credentials)
        self.assertEqual(user["powers"], [])

    def test_realtor_command_requires_power_then_takes_effect(self) -> None:
        alice = self.create_ready_account("alice")
        bob = self.create_ready_account("bob")
        alice_id = self.account_id(alice)
        bob_id = self.account_id(bob)
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            rejected = self.send_command(socket, "own-1", ".own show hub")
            self.assertFalse(rejected["ok"])
            rejected_entry = next(
                entry for entry in self.runtime().audit.entries() if entry["action"] == "command.own"
            )
            self.assertEqual(rejected_entry["result"], "rejected")
            self.assertEqual(rejected_entry["actor_account_id"], alice_id)
            self.runtime().powers.grant(alice_id, alice_id, "realtor")
            granted = self.send_command(socket, "own-2", ".own grant hub @bob")
            self.assertTrue(granted["ok"], granted)
            self.assertEqual(granted["payload"]["owner_account_id"], bob_id)
            self.assertEqual(self.runtime().ownership.owner_of("hub"), bob_id)

    def test_admin_console_blocks_r_and_k_and_audits(self) -> None:
        alice = self.create_ready_account("alice")
        alice_id = self.account_id(alice)
        self.runtime().powers.grant(alice_id, alice_id, "admin")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            self.assertTrue(self.send_command(socket, "admin-1", "\\status")["ok"])
            blocked_r = self.send_command(socket, "admin-2", "\\r")
            self.assertFalse(blocked_r["ok"])
            self.assertIn("not available", blocked_r["message"])
            blocked_k = self.send_command(socket, "admin-3", "\\k")
            self.assertFalse(blocked_k["ok"])
            unknown = self.send_command(socket, "admin-4", "\\random")
            self.assertFalse(unknown["ok"])
            self.assertIn("Unknown admin command", unknown["message"])
        actions = [entry["action"] for entry in self.runtime().audit.entries()]
        self.assertIn("admin.status", actions)
        results = {entry["action"]: entry["result"] for entry in self.runtime().audit.entries()}
        self.assertEqual(results.get("admin.console"), "rejected")

    def test_non_admin_backslash_is_rejected(self) -> None:
        alice = self.create_ready_account("alice")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            result = self.send_command(socket, "admin-1", "\\status")
            self.assertFalse(result["ok"])
            self.assertIn("admin power", result["message"])

    def test_mute_blocks_say_but_not_other_commands(self) -> None:
        alice = self.create_ready_account("alice")
        bob = self.create_ready_account("bob")
        alice_id = self.account_id(alice)
        bob_id = self.account_id(bob)
        self.runtime().powers.grant(alice_id, alice_id, "moderator")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as mod_socket:
            mod_socket.receive_json()
            muted = self.send_command(mod_socket, "mute-1", ".mute @bob 30")
            self.assertTrue(muted["ok"], muted)
            with self.client.websocket_connect(
                "/ws", headers=websocket_headers(bob["session_token"], bob["csrf_token"])
            ) as bob_socket:
                bob_socket.receive_json()
                blocked = self.send_command(bob_socket, "bob-say", ".say hello")
                self.assertFalse(blocked["ok"])
                self.assertIn("muted", blocked["message"])
                looked = self.send_command(bob_socket, "bob-look", ".look")
                self.assertTrue(looked["ok"], looked)
            self.runtime().powers.unmute(alice_id, bob_id)
        self.assertFalse(self.runtime().powers.is_muted(bob_id))

    def test_kick_closes_target_socket(self) -> None:
        alice = self.create_ready_account("alice")
        bob = self.create_ready_account("bob")
        alice_id = self.account_id(alice)
        self.runtime().powers.grant(alice_id, alice_id, "moderator")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as mod_socket:
            mod_socket.receive_json()
            with self.client.websocket_connect(
                "/ws", headers=websocket_headers(bob["session_token"], bob["csrf_token"])
            ) as bob_socket:
                bob_socket.receive_json()
                kicked = self.send_command(mod_socket, "kick-1", ".kick @bob removed")
                self.assertTrue(kicked["ok"], kicked)
                envelope = bob_socket.receive_json()
                self.assertEqual(envelope["type"], "session.replaced")
                self.assertIn("removed", envelope["message"])
                with self.assertRaises(WebSocketDisconnect):
                    bob_socket.receive_json()

    def test_gm_commands_apply_and_audit(self) -> None:
        alice = self.create_ready_account("alice")
        bob = self.create_ready_account("bob")
        alice_id = self.account_id(alice)
        bob_id = self.account_id(bob)
        self.runtime().powers.grant(alice_id, alice_id, "game-master")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            gave = self.send_command(socket, "gm-1", ".gm give @bob @card:sturdy 2")
            self.assertTrue(gave["ok"], gave)
            setcounter = self.send_command(socket, "gm-2", ".gm setcounter @bob health 10")
            self.assertTrue(setcounter["ok"], setcounter)
            self.assertEqual(setcounter["payload"]["value"], 10)
            buffed = self.send_command(socket, "gm-3", ".gm buff @bob stinky 300")
            self.assertTrue(buffed["ok"], buffed)
            kudos = self.send_command(socket, "gm-4", ".gm kudos @bob 5")
            self.assertTrue(kudos["ok"], kudos)
            environment = self.send_command(socket, "gm-5", '.gm environment hub hidden_props {\\"prop0\\":{}}')
            self.assertTrue(environment["ok"], environment)
            self.assertEqual(environment["payload"]["revision"], 1)
        bob_inventory = {stack.card_def_id for stack in self.runtime().profiles.list_inventory(bob_id, WORLD_ID)}
        self.assertIn("sturdy", bob_inventory)
        self.assertEqual(self.runtime().stats.view(bob_id).health, 10)
        actions = [entry["action"] for entry in self.runtime().audit.entries()]
        self.assertIn("gm.give", actions)
        self.assertIn("gm.setcounter", actions)
        self.assertIn("gm.buff", actions)
        self.assertIn("gm.kudos", actions)
        self.assertIn("gm.environment", actions)

    def test_help_payload_includes_usage_power_and_help(self) -> None:
        alice = self.create_ready_account("alice")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            result = self.send_command(socket, "help-1", ".help")
            self.assertTrue(result["ok"])
            commands = {entry["name"]: entry for entry in result["payload"]["commands"]}
            self.assertIn("usage", commands["look"])
            self.assertTrue(commands["look"]["help"])
            self.assertEqual(commands["gm"]["power"], "game-master")
            self.assertFalse(commands["gm"]["allowed"])
            self.assertIn("own", commands)


if __name__ == "__main__":
    import unittest

    unittest.main()
