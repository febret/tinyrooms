"""Presence deltas and revision-gated snapshots (A + B)."""

from __future__ import annotations

import json
import unittest

from server.protocol import (
    parse_client_message,
    peep_enter_event,
    presence_enter_event,
)
from tests.common import IntegrationTestCase, websocket_headers


class SnapshotRequestParsingTests(unittest.TestCase):
    """The gateway must accept optional client revision tokens."""

    def test_bare_request_means_no_cache(self) -> None:
        envelope_type, payload = parse_client_message('{"v": 1, "type": "snapshot.request"}')
        self.assertEqual(envelope_type, "snapshot.request")
        self.assertIsNone(payload.layout_revision)
        self.assertIsNone(payload.environment_revision)

    def test_request_carries_revisions(self) -> None:
        envelope_type, payload = parse_client_message(
            '{"v": 1, "type": "snapshot.request", "layout_revision": 4, "environment_revision": 7}'
        )
        self.assertEqual(envelope_type, "snapshot.request")
        self.assertEqual(payload.layout_revision, 4)
        self.assertEqual(payload.environment_revision, 7)

    def test_non_integer_revision_is_rejected(self) -> None:
        from server.protocol import ProtocolError

        with self.assertRaises(ProtocolError):
            parse_client_message('{"v": 1, "type": "snapshot.request", "layout_revision": "fresh"}')


class PresenceDeltaEventTests(unittest.TestCase):
    """Enter events can carry the payload needed to skip a refetch."""

    def test_presence_enter_carries_occupant(self) -> None:
        occupant = {"id": "a1", "username": "Ada"}
        event = presence_enter_event(
            account_id="a1", username="Ada", room_id="hub", occupant=occupant
        )
        self.assertEqual(event["occupant"], occupant)

    def test_presence_enter_omits_occupant_by_default(self) -> None:
        event = presence_enter_event(account_id="a1", username="Ada", room_id="hub")
        self.assertNotIn("occupant", event)

    def test_peep_enter_carries_npc(self) -> None:
        npc = {"id": "peep-1", "label": "Molly"}
        event = peep_enter_event(
            peep_id="peep-1", label="Molly", room_id="hub", source_room_id="hall", npc=npc
        )
        self.assertEqual(event["npc"], npc)


class SnapshotGatingTests(IntegrationTestCase):
    """Matching revisions omit layout sections; anything else sends them."""

    def _snapshot(self, account_id: str, **known):
        runtime = self.runtime()
        account = runtime.profiles.get_account_by_id(account_id)
        import asyncio

        return asyncio.run(
            runtime.rooms.build_snapshot(account, "hub", **known)
        )

    def test_matching_revisions_omit_props_and_exits(self) -> None:
        credentials = self.create_ready_account("gated-ada")
        account_id = self.account_id(credentials)
        full = self._snapshot(account_id)
        self.assertIn("props", full)
        self.assertIn("exits", full)
        gated = self._snapshot(
            account_id,
            known_layout_revision=full["layout_revision"],
            known_environment_revision=full["environment_revision"],
        )
        self.assertNotIn("props", gated)
        self.assertNotIn("exits", gated)
        self.assertTrue(gated.get("props_unchanged"))
        self.assertTrue(gated.get("exits_unchanged"))
        # Dynamic sections are always present.
        for key in ("occupants", "npcs", "room_cards", "chat_history", "board", "grid", "minimap"):
            self.assertIn(key, gated)
        self.assertEqual(
            json.dumps(gated["board"], sort_keys=True, default=str),
            json.dumps(full["board"], sort_keys=True, default=str),
        )

    def test_stale_revision_returns_full_snapshot(self) -> None:
        credentials = self.create_ready_account("gated-bo")
        account_id = self.account_id(credentials)
        full = self._snapshot(account_id)
        stale = self._snapshot(
            account_id,
            known_layout_revision=int(full["layout_revision"]) + 1,
            known_environment_revision=int(full["environment_revision"]) + 1,
        )
        self.assertIn("props", stale)
        self.assertIn("exits", stale)
        self.assertNotIn("props_unchanged", stale)


class PresenceDeltaLiveTests(IntegrationTestCase):
    """A join broadcast carries the occupant so others skip snapshot.request."""

    def test_join_broadcast_carries_occupant_payload(self) -> None:
        host = self.create_ready_account("delta-host")
        guest = self.create_ready_account("delta-guest")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(host["session_token"], host["csrf_token"])
        ) as host_socket:
            host_socket.receive_json()  # host snapshot
            with self.client.websocket_connect(
                "/ws",
                headers=websocket_headers(guest["session_token"], guest["csrf_token"]),
            ) as guest_socket:
                guest_socket.receive_json()  # guest snapshot
                event = self.drain_until(host_socket, "presence.enter")
                self.assertIn("occupant", event)
                self.assertEqual(event["occupant"]["id"], self.account_id(guest))
                self.assertEqual(event["occupant"]["username"], event["username"])


if __name__ == "__main__":
    unittest.main()
