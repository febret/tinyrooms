"""Audio chat presence, signaling relay, and ICE configuration coverage."""

from __future__ import annotations

import json
import unittest

from server.config import ConfigError, parse_ice_urls
from server.protocol import (
    ClientRtcPresenceEnvelope,
    ClientRtcSignalEnvelope,
    ProtocolError,
    parse_client_message,
)
from tests.test_milestone1 import (
    RuntimeTestCase,
    auth_cookies,
    websocket_headers,
)


class RtcProtocolTests(unittest.TestCase):
    """Validate the rtc.presence and rtc.signal envelopes in isolation."""

    def test_presence_round_trip(self) -> None:
        kind, payload = parse_client_message(
            json.dumps({"v": 1, "type": "rtc.presence", "enabled": True})
        )
        self.assertEqual(kind, "rtc.presence")
        self.assertIsInstance(payload, ClientRtcPresenceEnvelope)
        self.assertTrue(payload.enabled)

    def test_signal_offer_round_trip(self) -> None:
        kind, payload = parse_client_message(
            json.dumps(
                {
                    "v": 1,
                    "type": "rtc.signal",
                    "to": "account-1",
                    "signal": {"kind": "offer", "sdp": "v=0"},
                }
            )
        )
        self.assertEqual(kind, "rtc.signal")
        self.assertIsInstance(payload, ClientRtcSignalEnvelope)
        self.assertEqual(payload.to, "account-1")
        self.assertEqual(payload.signal["kind"], "offer")

    def test_candidate_round_trip_normalizes_fields(self) -> None:
        _, payload = parse_client_message(
            json.dumps(
                {
                    "v": 1,
                    "type": "rtc.signal",
                    "to": "account-1",
                    "signal": {
                        "kind": "candidate",
                        "candidate": "candidate:1 1 udp",
                        "sdp_mid": "0",
                        "sdp_m_line_index": 3,
                    },
                }
            )
        )
        self.assertEqual(payload.signal["sdp_mid"], "0")
        self.assertEqual(payload.signal["sdp_m_line_index"], 3)

    def test_invalid_envelopes_are_rejected(self) -> None:
        bad_enabled = {"v": 1, "type": "rtc.presence", "enabled": "yes"}
        with self.assertRaises(ProtocolError):
            parse_client_message(json.dumps(bad_enabled))
        bad_kind = {
            "v": 1,
            "type": "rtc.signal",
            "to": "account-1",
            "signal": {"kind": "nope"},
        }
        with self.assertRaises(ProtocolError):
            parse_client_message(json.dumps(bad_kind))
        missing_target = {
            "v": 1,
            "type": "rtc.signal",
            "signal": {"kind": "bye"},
        }
        with self.assertRaises(ProtocolError):
            parse_client_message(json.dumps(missing_target))

    def test_oversized_signal_is_rejected(self) -> None:
        huge = {"v": 1, "type": "rtc.signal", "to": "a", "signal": {"kind": "bye"}, "pad": "x" * 70000}
        with self.assertRaises(ProtocolError):
            parse_client_message(json.dumps(huge))

    def test_ice_urls_validation(self) -> None:
        self.assertEqual(
            parse_ice_urls("stun:example.org, turn:relay.example.org"),
            ("stun:example.org", "turn:relay.example.org"),
        )
        with self.assertRaises(ConfigError):
            parse_ice_urls("http://example.org")


class AudioChatTests(RuntimeTestCase):
    """Exercise the room-scoped signaling relay over the WebSocket loop."""

    def account_id(self, credentials: dict[str, str]) -> str:
        response = self.client.get(
            "/api/bootstrap",
            cookies=auth_cookies(credentials["session_token"], credentials["csrf_token"]),
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["user"]["id"]

    def send_presence(self, socket, enabled: bool) -> None:
        socket.send_json({"v": 1, "type": "rtc.presence", "enabled": enabled})

    def send_signal(self, socket, target_id: str, signal: dict[str, object]) -> None:
        socket.send_json(
            {"v": 1, "type": "rtc.signal", "to": target_id, "signal": signal}
        )

    def test_bootstrap_exposes_ice_servers(self) -> None:
        alice = self.create_ready_account("alice")
        response = self.client.get(
            "/api/bootstrap",
            cookies=auth_cookies(alice["session_token"], alice["csrf_token"]),
        )
        self.assertEqual(response.status_code, 200)
        ice_servers = response.json()["rtc"]["ice_servers"]
        self.assertTrue(ice_servers)
        self.assertTrue(ice_servers[0]["urls"][0].startswith("stun:"))

    def test_presence_broadcasts_and_snapshot_flag(self) -> None:
        alice = self.create_ready_account("alice")
        bob = self.create_ready_account("bob")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as alice_socket:
            alice_socket.receive_json()
            with self.client.websocket_connect(
                "/ws", headers=websocket_headers(bob["session_token"], bob["csrf_token"])
            ) as bob_socket:
                bob_socket.receive_json()
                self.assertEqual(alice_socket.receive_json()["event"]["type"], "presence.enter")
                self.send_presence(alice_socket, True)
                alice_event = alice_socket.receive_json()
                bob_event = bob_socket.receive_json()
                self.assertEqual(alice_event["event"]["type"], "presence.audio")
                self.assertTrue(alice_event["event"]["enabled"])
                self.assertTrue(bob_event["event"]["enabled"])
                bob_socket.send_json({"v": 1, "type": "snapshot.request"})
                snapshot = bob_socket.receive_json()
                self.assertEqual(snapshot["type"], "room.snapshot")
                occupant = next(
                    entry
                    for entry in snapshot["room"]["occupants"]
                    if entry["username"] == "alice"
                )
                self.assertTrue(occupant["audio_enabled"])

    def test_signal_relays_between_audio_peers(self) -> None:
        alice = self.create_ready_account("alice")
        bob = self.create_ready_account("bob")
        bob_id = self.account_id(bob)
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as alice_socket:
            alice_socket.receive_json()
            with self.client.websocket_connect(
                "/ws", headers=websocket_headers(bob["session_token"], bob["csrf_token"])
            ) as bob_socket:
                bob_socket.receive_json()
                alice_socket.receive_json()
                self.send_presence(alice_socket, True)
                alice_socket.receive_json()
                bob_socket.receive_json()
                self.send_presence(bob_socket, True)
                bob_socket.receive_json()
                alice_socket.receive_json()
                self.send_signal(alice_socket, bob_id, {"kind": "offer", "sdp": "v=0"})
                relayed = bob_socket.receive_json()
                self.assertEqual(relayed["type"], "rtc.signal")
                self.assertEqual(relayed["signal"]["kind"], "offer")
                self.assertEqual(relayed["from_username"], "alice")

    def test_signal_rejected_when_receiver_disabled(self) -> None:
        alice = self.create_ready_account("alice")
        bob = self.create_ready_account("bob")
        bob_id = self.account_id(bob)
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as alice_socket:
            alice_socket.receive_json()
            with self.client.websocket_connect(
                "/ws", headers=websocket_headers(bob["session_token"], bob["csrf_token"])
            ) as bob_socket:
                bob_socket.receive_json()
                alice_socket.receive_json()
                self.send_presence(alice_socket, True)
                alice_socket.receive_json()
                bob_socket.receive_json()
                self.send_signal(alice_socket, bob_id, {"kind": "bye"})
                rejected = alice_socket.receive_json()
                self.assertEqual(rejected["type"], "error")
                self.assertEqual(rejected["code"], "rtc_rejected")

    def test_signal_rejected_without_enabling(self) -> None:
        alice = self.create_ready_account("alice")
        bob = self.create_ready_account("bob")
        bob_id = self.account_id(bob)
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as alice_socket:
            alice_socket.receive_json()
            with self.client.websocket_connect(
                "/ws", headers=websocket_headers(bob["session_token"], bob["csrf_token"])
            ) as bob_socket:
                bob_socket.receive_json()
                alice_socket.receive_json()
                self.send_signal(alice_socket, bob_id, {"kind": "bye"})
                rejected = alice_socket.receive_json()
                self.assertEqual(rejected["type"], "error")
                self.assertEqual(rejected["code"], "rtc_rejected")

    def test_room_change_keeps_audio_enabled(self) -> None:
        alice = self.create_ready_account("alice")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as alice_socket:
            alice_socket.receive_json()
            self.send_presence(alice_socket, True)
            self.assertEqual(alice_socket.receive_json()["event"]["type"], "presence.audio")
            result = self.command(alice_socket, "move-1", ".go @way:exit0")
            self.assertTrue(result["ok"])
            snapshot = alice_socket.receive_json()
            self.assertEqual(snapshot["type"], "room.snapshot")
            self.assertEqual(snapshot["room"]["id"], "playroom")
            occupant = next(
                entry
                for entry in snapshot["room"]["occupants"]
                if entry["id"] == self.account_id(alice)
            )
            self.assertTrue(occupant["audio_enabled"])

    def test_new_session_resets_audio(self) -> None:
        alice = self.create_ready_account("alice")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as alice_socket:
            alice_socket.receive_json()
            self.send_presence(alice_socket, True)
            self.assertEqual(alice_socket.receive_json()["event"]["type"], "presence.audio")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as reconnect_socket:
            snapshot = reconnect_socket.receive_json()
            occupant = next(
                entry
                for entry in snapshot["room"]["occupants"]
                if entry["id"] == self.account_id(alice)
            )
            self.assertFalse(occupant["audio_enabled"])


if __name__ == "__main__":
    unittest.main()
