from __future__ import annotations

import unittest

from server.behaviors.loader import BehaviorLoader
from tests.common import REPO_ROOT, load_test_world

WORLD_PATH = REPO_ROOT / "worlds" / "tiny-arcade"
CHESS_PATH = WORLD_PATH / "props" / "chess.py"


class TinyArcadeContentTests(unittest.TestCase):
    def test_world_loads_and_game_envelopes_resolve(self) -> None:
        world = load_test_world(WORLD_PATH)
        games = {
            room_id: room.game
            for room_id, room in world.rooms.items()
            if room.game is not None
        }
        self.assertEqual(set(games), {"chess", "paintball"})
        self.assertEqual(games["chess"].kind, "chess")
        self.assertEqual(games["chess"].controller, "chess-controller")
        self.assertEqual(games["paintball"].kind, "paintball")
        self.assertEqual(games["paintball"].controller, "paintball-vending")


class ChessCastlingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chess = BehaviorLoader().import_script(CHESS_PATH).module

    def test_pawn_attack_prevents_kingside_castling(self) -> None:
        board = [None] * 64
        board[self.chess._index("e1")] = {"id": "wK", "code": "wK"}
        board[self.chess._index("h1")] = {"id": "wR", "code": "wR"}
        board[self.chess._index("e8")] = {"id": "bK", "code": "bK"}
        board[self.chess._index("e2")] = {"id": "bP", "code": "bP"}
        state = {
            "board": board,
            "turn": "w",
            "castling": {"wK": True, "wQ": True, "bK": True, "bQ": True},
            "en_passant": "",
        }

        self.assertTrue(self.chess._is_attacked(board, self.chess._index("f1"), "b"))
        self.assertFalse(self.chess._is_attacked(board, self.chess._index("e1"), "b"))
        moves = self.chess._legal_moves(board, state)
        self.assertFalse(any(move["castle"] == "K" for move in moves))
