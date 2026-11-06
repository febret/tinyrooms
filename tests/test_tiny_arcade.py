from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from server.behaviors.loader import BehaviorLoader
from tests.common import REPO_ROOT, load_test_world

WORLD_PATH = REPO_ROOT / "worlds" / "tiny-arcade"
CHESS_PATH = WORLD_PATH / "props" / "chess.py"
PAINTBALL_PATH = WORLD_PATH / "props" / "paintball.py"


class TinyArcadeContentTests(unittest.TestCase):
    def test_world_loads_and_activity_envelopes_resolve(self) -> None:
        world = load_test_world(WORLD_PATH, allow_legacy_whiteboards=True)
        self.assertIn("chess", world.activities)
        self.assertIn("paintball", world.activities)
        self.assertNotIn("chess", world.rooms)
        self.assertNotIn("paintball", world.rooms)
        activities = world.rooms["lobby"].activities
        self.assertEqual(set(activities), {"chess", "paintball"})
        self.assertEqual(activities["chess"].kind, "chess")
        self.assertEqual(activities["chess"].controller, "chess-cabinet")
        self.assertEqual(activities["paintball"].kind, "paintball")
        self.assertEqual(activities["paintball"].controller, "paintball-vending")
        self.assertIn("chess-cabinet", world.rooms["lobby"].props)
        self.assertIn("paintball-vending", world.rooms["lobby"].props)
        self.assertEqual(world.props["chess-cabinet"].activity, "chess")
        self.assertEqual(world.props["paintball-vending"].activity, "paintball")
        self.assertEqual(set(world.activities["chess"].rooms), {"lobby"})
        self.assertEqual(set(world.activities["paintball"].rooms), {"lobby"})
        self.assertEqual(world.activities["paintball"].start_cost, 20)

    def test_arcade_side_rooms_and_snack_dispensers_resolve(self) -> None:
        world = load_test_world(WORLD_PATH, allow_legacy_whiteboards=True)
        self.assertEqual(world.rooms["lobby"].grid, (0, 0, 0))
        self.assertEqual(world.rooms["restroom"].grid, (1, 0, 0))
        self.assertEqual(world.rooms["snack-bar"].grid, (-1, 0, 0))
        self.assertEqual(set(world.rooms["lobby"].exits), {"west", "east"})
        self.assertEqual(world.rooms["lobby"].exits["west"].target_room_id, "restroom")
        self.assertEqual(world.rooms["lobby"].exits["east"].target_room_id, "snack-bar")
        self.assertEqual(world.rooms["restroom"].exits["east"].target_room_id, "lobby")
        self.assertEqual(world.rooms["snack-bar"].exits["west"].target_room_id, "lobby")
        restroom_props = {prop.prop_id for prop in world.rooms["restroom"].props.values()}
        self.assertIn("cottage-toilet", restroom_props)
        self.assertIn("medicine-cabinet", restroom_props)
        self.assertIn("apothecary-cabinet", restroom_props)
        self.assertNotIn("arcade-medicine-cabinet", restroom_props)
        for prop_id in ("arcade-snack-dresser", "arcade-drink-cooler", "arcade-sweet-shelf"):
            definition = world.props[prop_id]
            self.assertEqual(definition.behavior, "dispenser")
            self.assertTrue(definition.content)
            self.assertTrue(all(card_id.startswith("market-") for card_id in definition.content))

    def test_prop_behavior_scripts_resolve(self) -> None:
        world = load_test_world(WORLD_PATH, allow_legacy_whiteboards=True)
        scripts = BehaviorLoader().load_world(world)
        self.assertIn("builtin:dispenser", scripts.scripts)
        self.assertTrue(any(script.startswith("behavior:") for script in scripts.scripts))

    def test_paintball_config_preserves_gameplay_values(self) -> None:
        world = load_test_world(WORLD_PATH, allow_legacy_whiteboards=True)
        config = world.rooms["lobby"].activities["paintball"].config
        self.assertEqual(config["round_seconds"], 120)
        self.assertEqual(config["intermission_seconds"], 30)
        self.assertEqual(config["tick_hz"], 15)
        self.assertEqual(list(config["rewards"]), [100, 50, 20])
        self.assertNotIn("shot_energy_cost", config)
        self.assertNotIn("max_range", config)
        self.assertNotIn("peep_radius", config)
        bots = config["bots"]
        self.assertEqual(bots["target_players"], 4)
        self.assertNotIn("home_room", bots)
        self.assertNotIn("dismiss_seconds", bots)


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


class PaintballArenaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.paintball = BehaviorLoader().import_script(PAINTBALL_PATH).module

    def test_input_parsing_accepts_normalized_vectors(self) -> None:
        parsed = self.paintball._parse_input("input:1000:0:0:-1000:1")
        self.assertEqual(parsed, (1.0, 0.0, 0.0, -1.0, True))

    def test_obstacles_are_circles_clear_of_spawn_slots(self) -> None:
        obstacles = self.paintball._generate_obstacles(1234, {}, (100.0, 100.0))
        self.assertTrue(3 <= len(obstacles) <= 5)
        for obstacle in obstacles:
            self.assertEqual(obstacle["kind"], "circle")
        for slot in self.paintball._spawn_slots((100.0, 100.0)):
            for obstacle in obstacles:
                self.assertGreaterEqual(
                    ((slot[0] - obstacle["x"]) ** 2 + (slot[1] - obstacle["y"]) ** 2) ** 0.5,
                    self.paintball.DEFAULT_PLAYER_RADIUS + 3.0 + obstacle["r"],
                )

    def test_paintball_round_transitions_emit_no_room_toasts(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0)

        class SilentContext:
            def __init__(self) -> None:
                self.room = {"activities": {"paintball": {"reset_powers": [], "config": {}}}}
                self.grants = []

            def grant(self, **payload) -> None:
                self.grants.append(payload)

            def room_feedback(self, *args, **kwargs) -> None:
                raise AssertionError("paintball must not broadcast room toasts")

        context = SilentContext()
        state = {
            "version": 2,
            "phase": "active",
            "round": 4,
            "round_started_at": now.isoformat(),
            "scores": {"u1": {"name": "Human", "hits": 2, "shots": 3}},
            "records": {"games": 0, "best_hits": 0, "best_name": ""},
        }
        self.paintball._finish_round(context, state, now)
        self.assertEqual(len(context.grants), 1)

    def test_activity_scripts_have_no_room_broadcast_toasts(self) -> None:
        for script in (CHESS_PATH, PAINTBALL_PATH):
            self.assertNotIn("room_feedback(", script.read_text(encoding="utf-8"))
