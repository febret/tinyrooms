from __future__ import annotations

import unittest

from server.game.activity_arena import (
    hits_obstacle,
    move_body,
    sweep_hits_obstacle,
)


class ActivityArenaTests(unittest.TestCase):
    def test_circle_collision(self) -> None:
        obstacle = {"id": "rock", "kind": "circle", "x": 20.0, "y": 50.0, "r": 4.0}
        self.assertTrue(hits_obstacle(19.0, 50.0, 1.8, [obstacle]))
        self.assertFalse(hits_obstacle(10.0, 50.0, 1.8, [obstacle]))

    def test_movement_slides_along_obstacles(self) -> None:
        obstacle = {"id": "rock", "kind": "circle", "x": 30.0, "y": 50.0, "r": 5.0}
        x, y = move_body(10.0, 50.0, 15.0, 0.0, 1.8, (100.0, 100.0), [obstacle])
        self.assertLess(x, 30.0)
        self.assertEqual(y, 50.0)

    def test_sweep_collision(self) -> None:
        obstacle = {"id": "rock", "kind": "circle", "x": 20.0, "y": 50.0, "r": 2.0}
        self.assertTrue(sweep_hits_obstacle(10.0, 50.0, 30.0, 50.0, 1.0, [obstacle]))
        self.assertFalse(sweep_hits_obstacle(10.0, 10.0, 30.0, 10.0, 1.0, [obstacle]))
