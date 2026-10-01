"""NPC movement must not strand room-scoped peep interactions."""

from __future__ import annotations

import asyncio
import unittest

from tests.test_milestone1 import RuntimeTestCase, websocket_headers


class WanderingPeepRoutingTests(RuntimeTestCase):
    """A peep that wandered out of its spawn room still supports its actions."""

    def _move_molly_to_foyer(self) -> None:
        runtime = self.app.state.runtime
        asyncio.run(runtime.rooms.move_npc("molly", "exit0"))

    def _travel_to_foyer(self, socket) -> dict[str, object]:
        for index, command in enumerate((".go @way:exit0", ".go @way:exit0")):
            result = self.command(socket, f"go-{index}", command)
            self.assertTrue(result["ok"], result)
            snapshot = socket.receive_json()
        self.assertEqual(snapshot["room"]["id"], "foyer")
        return snapshot

    def _connect(self, username: str):
        credentials = self.create_ready_account(username)
        return self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(credentials["session_token"], credentials["csrf_token"]),
        )

    def test_play_follows_the_peep_to_its_current_room(self) -> None:
        self._move_molly_to_foyer()
        with self._connect("playwander") as socket:
            socket.receive_json()
            snapshot = self._travel_to_foyer(socket)
            self.assertIn("molly", [npc["id"] for npc in snapshot["room"]["npcs"]])
            result = self.command(socket, "play-1", ".play molly")
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["payload"]["activity"]["kind"], "lazor-rush")

    def test_talk_follows_the_peep_to_its_current_room(self) -> None:
        self._move_molly_to_foyer()
        with self._connect("talkwander") as socket:
            socket.receive_json()
            self._travel_to_foyer(socket)
            result = self.command(socket, "talk-1", ".talk molly")
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["payload"]["dialog"]["peep_id"], "molly")


if __name__ == "__main__":
    unittest.main()
