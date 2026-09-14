"""Tests for board helper math ported from app/js/board-helpers.js (pure functions only)."""

from __future__ import annotations

import unittest

from server.client.board_helpers import board_position, board_signature


class BoardHelperTests(unittest.TestCase):
    """Board positioning and layout signature computation."""

    def test_board_position_maps_axes_correctly(self) -> None:
        self.assertEqual(board_position(), [0, 0, 0])
        self.assertEqual(board_position([100, 100, 10]), [5.25, 1, 4.25])
        self.assertEqual(board_position([0, 0, -10]), [-5.25, -1, -4.25])

    def test_board_signature_ignores_non_visual_changes(self) -> None:
        room = {
            "id": "hub",
            "label": "The Hub",
            "board": {"imageUrl": "/floor.png"},
            "props": [{"id": "plant", "position": [10, 20, 0], "modelUrl": "/plant.glb"}],
            "roomCards": [{"stackId": "wallet", "quantity": 1, "definition": {"imageUrl": "/wallet.webp"}}],
        }
        changed_quantity = {
            **room,
            "occupants": [{"id": "new-peep"}],
            "roomCards": [{**room["roomCards"][0], "quantity": 5, "quickActions": [{"label": "Pick up"}]}],
        }
        changed_model = {**room, "props": [{**room["props"][0], "modelUrl": "/changed.glb"}]}
        self.assertEqual(board_signature(room), board_signature(changed_quantity))
        self.assertNotEqual(board_signature(room), board_signature(changed_model))


if __name__ == "__main__":
    unittest.main()