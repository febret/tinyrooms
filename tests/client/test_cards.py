"""Tests for card selection actions ported from app/js/cards.js."""

from __future__ import annotations

import unittest

from server.client.cards import selection_actions


def selected_state(scope: str, quick_actions: list[dict], pinned: bool = False) -> dict:
    stack = {"stackId": "wallet", "quantity": 2, "pinned": pinned, "quickActions": quick_actions}
    return {
        "room": {
            "roomCards": [stack] if scope == "room" else [],
            "inventory": [stack] if scope == "inventory" else [],
        },
        "selection": {"kind": f"{scope}-card", "id": "wallet"},
    }


class SelectionActionsTests(unittest.TestCase):
    """Quantity-action selection requires a matching server action and respects pinning."""

    def test_pickup_quantity_ui_with_room_scope(self) -> None:
        self._assert_quantity_ui("room", "pickup")

    def test_drop_quantity_ui_with_inventory_scope(self) -> None:
        self._assert_quantity_ui("inventory", "drop")

    def test_pinned_room_stacks_disable_pickup(self) -> None:
        actions = selection_actions(
            selected_state("room", [{"label": "Pick up", "command": ".pickup @card:wallet 1"}], pinned=True)
        )
        pickup = next(action for action in actions if action.get("local", {}).get("intent") == "pickup")
        self.assertTrue(pickup["disabled"])

    def _assert_quantity_ui(self, scope: str, intent: str) -> None:
        look = {"label": "Look", "command": ".look @card:wallet"}
        without_transfer = selection_actions(selected_state(scope, [look]))
        self.assertEqual([action["label"] for action in without_transfer], ["Inspect", "Look"])
        actions = selection_actions(selected_state(scope, [look, {"label": intent, "command": f".{intent} @card:wallet 1"}]))
        self.assertEqual(actions[1]["command"], look["command"])
        self.assertEqual(actions[2]["local"], {"type": "quantity", "stackId": "wallet", "max": 2, "intent": intent})
        self.assertFalse(actions[2]["disabled"])


if __name__ == "__main__":
    unittest.main()