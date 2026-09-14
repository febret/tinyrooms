"""Tests for the client state store ported from app/js/state.js."""

from __future__ import annotations

import unittest

from server.client.state import create_store, normalize_room

ROOM = {
    "id": "hub",
    "label": "The Hub",
    "occupants": [],
    "npcs": [],
    "props": [],
    "exits": [],
    "inventory": [],
    "favorites": ["room"],
    "room_cards": [{"stack_id": "wallet", "quantity": 2, "definition": {"id": "wallet", "label": "Wallet"}}],
}


class StateStoreTests(unittest.TestCase):
    """State normalization, snapshot merging, selection, and toast behavior."""

    def test_normalization_retains_quantities_and_favorites(self) -> None:
        normalized = normalize_room(ROOM)
        self.assertEqual(normalized["roomCards"][0]["quantity"], 2)
        self.assertEqual(normalized["favorites"], ["room"])

    def test_remote_removal_invalidates_selection_and_inspection(self) -> None:
        store = create_store()
        store["dispatch"]({"type": "snapshot", "room": ROOM})
        store["dispatch"]({"type": "open-view", "view": "room"})
        store["dispatch"]({"type": "select", "selection": {"kind": "room-card", "id": "wallet"}})
        store["dispatch"]({"type": "open-details", "stackId": "wallet"})
        store["dispatch"]({"type": "snapshot", "room": {**ROOM, "room_cards": []}})
        self.assertIsNone(store["getState"]()["views"]["details"])
        self.assertNotEqual(store["getState"]()["selection"]["kind"], "room-card")

    def test_room_navigation_and_logout_clear_state(self) -> None:
        store = create_store()
        store["dispatch"]({"type": "session", "loggedIn": True, "user": {"id": "sunbeam", "remembered_room": "hub"}})
        store["dispatch"]({"type": "snapshot", "room": ROOM})
        store["dispatch"]({"type": "open-view", "view": "inventory"})
        store["dispatch"]({"type": "open-details", "stackId": "wallet"})
        store["dispatch"]({"type": "snapshot", "room": {**ROOM, "id": "playroom"}})
        self.assertIsNone(store["getState"]()["views"]["main"])
        self.assertIsNone(store["getState"]()["views"]["details"])
        self.assertEqual(store["getState"]()["selection"], {"kind": "room", "id": "playroom"})
        self.assertEqual(store["getState"]()["user"]["rememberedRoom"], "playroom")
        store["dispatch"]({"type": "session", "loggedIn": False})
        self.assertIsNone(store["getState"]()["room"])
        self.assertEqual(store["getState"]()["activities"], [])
        self.assertTrue(store["getState"]()["views"]["auth"])

    def test_same_room_snapshots_preserve_selection_and_bubbles(self) -> None:
        occupied = {**ROOM, "occupants": [{"id": "sunbeam", "username": "sunbeam"}]}
        store = create_store()
        store["dispatch"]({"type": "snapshot", "room": occupied})
        store["dispatch"]({"type": "open-view", "view": "room"})
        store["dispatch"]({"type": "select", "selection": {"kind": "room-card", "id": "wallet"}})
        store["dispatch"]({"type": "open-details", "stackId": "wallet"})
        store["dispatch"]({
            "type": "room-event",
            "event": {"type": "chat.message", "speaker_id": "sunbeam", "speaker": "sunbeam", "text": "Hello", "style": "normal"},
        })
        store["dispatch"]({"type": "snapshot", "room": occupied})
        self.assertEqual(store["getState"]()["selection"], {"kind": "room-card", "id": "wallet"})
        self.assertEqual(store["getState"]()["views"]["main"], "room")
        self.assertEqual(store["getState"]()["views"]["details"], "wallet")
        self.assertEqual(store["getState"]()["room"]["occupants"][0]["bubble"]["text"], "Hello")
        store["dispatch"]({"type": "dismiss-bubble", "id": "sunbeam"})
        store["dispatch"]({"type": "snapshot", "room": occupied})
        self.assertTrue(store["getState"]()["room"]["occupants"][0]["bubbleDismissed"])

    def test_command_catalog_becomes_chat_commands(self) -> None:
        store = create_store()
        store["dispatch"]({
            "type": "result",
            "ok": True,
            "payload": {
                "commands": [
                    {"name": "look", "summary": "Look around"},
                    {"name": "pickup", "summary": "Pick up a card"},
                    {"name": ".help", "summary": "Help"},
                    {"name": "\\help", "summary": "Help alias"},
                ]
            },
        })
        names = [item["name"] for item in store["getState"]()["commandCatalog"]]
        self.assertEqual(names, [".look", ".pickup", ".help", "\\help"])

    def test_core_view_selection_and_detail_clearing(self) -> None:
        store = create_store()
        store["dispatch"]({"type": "snapshot", "room": ROOM})
        store["dispatch"]({"type": "open-view", "view": "room"})
        self.assertEqual(store["getState"]()["selection"], {"kind": "core", "id": "room"})
        store["dispatch"]({"type": "open-details", "stackId": "missing"})
        store["dispatch"]({"type": "snapshot", "room": ROOM})
        self.assertIsNone(store["getState"]()["views"]["details"])
        self.assertEqual(store["getState"]()["selection"], {"kind": "core", "id": "room"})

    def test_command_result_logs_survive_same_room_refresh(self) -> None:
        chat = [{"speaker_id": "sunbeam", "speaker": "sunbeam", "text": "Hello", "style": "normal"}]
        snapshot = {**ROOM, "chat_history": chat}
        store = create_store()
        store["dispatch"]({"type": "snapshot", "room": snapshot})
        store["dispatch"]({"type": "result", "ok": True, "message": "Looked around."})
        self.assertEqual(store["getState"]()["room"]["chatHistory"][-1]["text"], "Looked around.")
        history = store["getState"]()["room"]["chatHistory"]
        store["dispatch"]({"type": "snapshot", "room": snapshot})
        self.assertEqual(store["getState"]()["room"]["chatHistory"], history)

    def test_quiet_commands_are_logged_without_toasts(self) -> None:
        for command in ['.say "Hello"', ".help", ".look @card:wallet", ".settings action-log on"]:
            store = create_store()
            store["dispatch"]({"type": "snapshot", "room": ROOM})
            store["dispatch"]({"type": "result", "ok": True, "command": command, "message": "Acknowledged."})
            self.assertEqual(store["getState"]()["room"]["chatHistory"][-1]["text"], "Acknowledged.", command)
            self.assertEqual(store["getState"]()["ui"]["toasts"], [], command)

    def test_quiet_command_errors_deduplicated(self) -> None:
        for command in [".say", ".help", ".look", ".settings"]:
            store = create_store()
            store["dispatch"]({"type": "snapshot", "room": ROOM})
            result = {"type": "result", "ok": False, "command": command, "message": "Command rejected."}
            store["dispatch"](result)
            store["dispatch"](result)
            toasts = store["getState"]()["ui"]["toasts"]
            self.assertEqual(len(toasts), 1, command)
            self.assertEqual(toasts[0]["tone"], "error", command)
            self.assertEqual(toasts[0]["message"], result["message"], command)
            self.assertEqual(store["getState"]()["room"]["chatHistory"][-1]["text"], result["message"], command)

    def test_non_quiet_commands_produce_success_toasts(self) -> None:
        for command in [".pickup @card:wallet 1", ".drop @card:wallet 1", ".favorite @card:journal", ".lookalike"]:
            store = create_store()
            store["dispatch"]({"type": "snapshot", "room": ROOM})
            store["dispatch"]({"type": "result", "ok": True, "command": command, "message": "Done."})
            toasts = store["getState"]()["ui"]["toasts"]
            self.assertEqual(len(toasts), 1, command)
            self.assertEqual(toasts[0]["tone"], "success", command)


if __name__ == "__main__":
    unittest.main()