"""3D room-grid positions, adjacency exits, and dynamic placement."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from server.content.common import ContentError
from server.content.room_grid import (
    allocate_grid_block,
    direction_between,
    extend_grid_cluster,
    parse_room_grid,
)
from server.content.worlds import ExitDefinition, RoomDefinition, apply_room_grid
from tests.common import IntegrationTestCase, REPO_ROOT


def _room(
    room_id: str,
    grid: tuple[int, int, int] | None,
    exits: dict[str, ExitDefinition] | None = None,
    *,
    template: bool = False,
) -> RoomDefinition:
    return RoomDefinition(
        id=room_id,
        label=room_id,
        description="",
        board_type="basic",
        board_image_name="room.png",
        board_image_path=Path("room.png"),
        board_image_style="stretch",
        palette=(),
        dark=False,
        props={},
        exits=dict(exits or {}),
        initial_cards=(),
        grid=grid,
        template=template,
    )


def _exit(exit_id: str, target: str = "", **overrides) -> ExitDefinition:
    values = {
        "id": exit_id,
        "label": "",
        "target_room_id": target,
        "locked": False,
        "requires_card_id": None,
        "npc_barrier": False,
        "target_world_id": None,
        "transition": "crossfade",
        "transition_explicit": False,
    }
    values.update(overrides)
    return ExitDefinition(**values)


class RoomGridValidationTests(unittest.TestCase):
    def test_grid_requires_three_int32_coordinates(self) -> None:
        self.assertEqual(parse_room_grid([1, -2, 3], "hub"), (1, -2, 3))
        self.assertIsNone(parse_room_grid(None, "hub"))
        for bad in ([1, 2], [1, 2, 3, 4], [1.5, 0, 0], [True, 0, 0], "north"):
            with self.subTest(value=bad):
                with self.assertRaises(ContentError):
                    parse_room_grid(bad, "hub")
        with self.assertRaises(ContentError):
            parse_room_grid([2**31, 0, 0], "hub")

    def test_duplicate_positions_are_rejected(self) -> None:
        rooms = {
            "one": _room("one", (0, 0, 0)),
            "two": _room("two", (0, 0, 0)),
        }
        with self.assertRaises(ContentError):
            apply_room_grid(rooms)

    def test_templates_do_not_participate_in_the_grid(self) -> None:
        rooms = {
            "blueprint": _room("blueprint", None, template=True),
            "live": _room("live", (4, 5, 6)),
        }
        apply_room_grid(rooms)
        self.assertEqual(rooms["live"].exits, {})

    def test_legacy_worlds_without_positions_are_untouched(self) -> None:
        rooms = {"one": _room("one", None), "two": _room("two", None)}
        apply_room_grid(rooms)
        self.assertEqual(rooms["one"].exits, {})

    def test_direction_between_uses_only_orthogonal_neighbors(self) -> None:
        self.assertEqual(direction_between((0, 0, 0), (0, 1, 0)), "south")
        self.assertEqual(direction_between((0, 0, 0), (0, 0, -1)), "up")
        self.assertIsNone(direction_between((0, 0, 0), (1, 1, 0)))
        self.assertIsNone(direction_between((0, 0, 0), None))


class GridExitLinkingTests(unittest.TestCase):
    def test_missing_neighbors_get_open_bidirectional_exits(self) -> None:
        rooms = {
            "here": _room("here", (0, 0, 0)),
            "side": _room("side", (1, 0, 0)),
            "below": _room("below", (0, 0, 1)),
        }
        apply_room_grid(rooms)
        self.assertEqual(rooms["here"].exits["west"].target_room_id, "side")
        self.assertEqual(rooms["here"].exits["west"].label, "West")
        self.assertEqual(rooms["here"].exits["west"].transition, "swipe-west")
        self.assertEqual(rooms["side"].exits["east"].target_room_id, "here")
        self.assertEqual(rooms["below"].exits["up"].target_room_id, "here")
        self.assertNotIn("north", rooms["here"].exits)

    def test_an_existing_link_to_a_neighbor_prevents_a_duplicate(self) -> None:
        rooms = {
            "here": _room("here", (0, 0, 0), {"door": _exit("door", "side", label="Oak door")}),
            "side": _room("side", (1, 0, 0)),
        }
        apply_room_grid(rooms)
        self.assertEqual(set(rooms["here"].exits), {"door"})
        self.assertEqual(rooms["here"].exits["door"].transition, "swipe-west")
        self.assertEqual(rooms["side"].exits["east"].target_room_id, "here")
        self.assertEqual(rooms["side"].exits["east"].label, "East")

    def test_explicit_transitions_are_preserved(self) -> None:
        rooms = {
            "west": _room(
                "west",
                (0, 0, 0),
                {"door": _exit("door", "east", transition_explicit=True)},
            ),
            "east": _room("east", (1, 0, 0)),
        }
        apply_room_grid(rooms)
        self.assertEqual(rooms["west"].exits["door"].transition, "crossfade")

    def test_directional_details_use_the_adjacent_target(self) -> None:
        rooms = {
            "here": _room(
                "here",
                (0, 0, 0),
                {
                    "west": _exit(
                        "west",
                        "",
                        label="Garden gate",
                        locked=True,
                        transition="swipe-west",
                    )
                },
            ),
            "side": _room("side", (1, 0, 0)),
        }
        apply_room_grid(rooms, pending_directional_targets={"here": ["west"]})
        resolved = rooms["here"].exits["west"]
        self.assertEqual(resolved.target_room_id, "side")
        self.assertEqual(resolved.label, "Garden gate")
        self.assertTrue(resolved.locked)
        self.assertEqual(resolved.transition, "swipe-west")
        self.assertEqual(rooms["side"].exits["east"].target_room_id, "here")

    def test_mismatched_directional_targets_are_rejected(self) -> None:
        rooms = {
            "here": _room("here", (0, 0, 0), {"west": _exit("west", "far")}),
            "side": _room("side", (1, 0, 0)),
            "far": _room("far", (9, 9, 9)),
        }
        with self.assertRaises(ContentError):
            apply_room_grid(rooms)


class GridAllocationTests(unittest.TestCase):
    def test_allocation_returns_connected_free_space(self) -> None:
        rooms = {"town": _room("town", (0, 0, 0))}
        block = allocate_grid_block(rooms, 4, origin=(64, 64, 0), columns=2)
        self.assertEqual(len(block), 4)
        self.assertNotIn((0, 0, 0), block)
        self.assertEqual(len(set(block)), 4)

    def test_allocation_keeps_separate_blocks_apart(self) -> None:
        rooms = {"town": _room("town", (0, 0, 0))}
        first = allocate_grid_block(rooms, 2, origin=(64, 64, 0), columns=2)
        rooms.update({f"old-{index}": _room(f"old-{index}", point) for index, point in enumerate(first)})
        second = allocate_grid_block(rooms, 2, origin=(64, 64, 0), columns=2)
        closest = min(
            max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))
            for a in first
            for b in second
        )
        self.assertGreater(closest, 1)

    def test_extension_grows_the_existing_cluster(self) -> None:
        rooms = {
            "one": _room("one", (0, 0, 0)),
            "two": _room("two", (1, 0, 0)),
            "far": _room("far", (10, 10, 0)),
        }
        grown = extend_grid_cluster(rooms, [(0, 0, 0), (1, 0, 0)], 2)
        self.assertEqual(len(grown), 2)
        for point in grown:
            self.assertNotIn(point, {(0, 0, 0), (1, 0, 0), (10, 10, 0)})
            touched = [
                seed
                for seed in ((0, 0, 0), (1, 0, 0))
                if max(abs(point[index] - seed[index]) for index in range(3)) == 1
                and sum(point[index] != seed[index] for index in range(3)) == 1
            ]
            self.assertTrue(touched, f"{point} is not adjacent to the cluster")


class TutorialGridSnapshotTests(IntegrationTestCase):
    def test_grid_room_snapshot_carries_minimap_and_directions(self) -> None:
        credentials = self.create_ready_account("grid-scout")
        account = self.runtime().profiles.get_account_by_id(self.account_id(credentials))
        snapshot = asyncio.run(self.runtime().rooms.build_snapshot(account, "foyer"))
        self.assertEqual(snapshot["grid"], [0, 0, 0])
        self.assertEqual(snapshot["minimap"]["position"], [0, 0, 0])
        self.assertEqual(snapshot["minimap"]["radius"], 2)
        tiles = {tile["id"]: tile for tile in snapshot["minimap"]["rooms"]}
        self.assertIn("kitchen", tiles)
        self.assertTrue(tiles["kitchen"]["image_url"].endswith("/rooms/kitchen.png"))
        directions = {
            exit_definition["direction"]: exit_definition["target_room_id"]
            for exit_definition in snapshot["exits"]
            if exit_definition["direction"]
        }
        self.assertEqual(
            directions,
            {"west": "kitchen", "north": "bedroom", "east": "garden", "up": "hub"},
        )
        transitions = {
            exit_definition["direction"]: exit_definition["transition"]
            for exit_definition in snapshot["exits"]
            if exit_definition["direction"]
        }
        self.assertEqual(
            transitions,
            {
                "west": "swipe-west",
                "north": "swipe-north",
                "east": "swipe-east",
                "up": "swipe-up",
            },
        )


class TinytownGridPlacementTests(IntegrationTestCase):
    world_path = REPO_ROOT / "worlds" / "tinytown"
    mods = "tinytown"

    def test_purchased_houses_form_connected_free_clusters(self) -> None:
        credentials = self.create_ready_account("grid-buyer")
        account_id = self.account_id(credentials)
        self.set_bops(account_id, 5000)
        runtime = self.runtime()
        account = runtime.profiles.get_account_by_id(account_id)
        housing = runtime.mods["tinytown"].housing
        first = housing.purchase(account, "micro-loft")
        second = housing.purchase(account, "brick-studio")

        for record in (first, second):
            rooms = [runtime.world.rooms[room_id] for room_id in record.room_ids.values()]
            positions = [room.grid for room in rooms]
            self.assertTrue(all(position is not None for position in positions))
            self.assertEqual(len(set(positions)), len(positions))
            self.assertEqual({position[2] for position in positions}, {positions[0][2]})
            reachable = {record.room_ids[housing.template_for(record).entry_key]}
            frontier = list(reachable)
            while frontier:
                room = runtime.world.rooms[frontier.pop()]
                for exit_definition in room.exits.values():
                    if exit_definition.target_world_id is None and exit_definition.target_room_id in record.room_ids.values():
                        if exit_definition.target_room_id not in reachable:
                            reachable.add(exit_definition.target_room_id)
                            frontier.append(exit_definition.target_room_id)
            self.assertEqual(reachable, set(record.room_ids.values()))

        first_positions = [runtime.world.rooms[room_id].grid for room_id in first.room_ids.values()]
        second_positions = [runtime.world.rooms[room_id].grid for room_id in second.room_ids.values()]
        closest = min(
            max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))
            for a in first_positions
            for b in second_positions
        )
        self.assertGreater(closest, 1)

        before = {
            room_id: runtime.world.rooms[room_id].grid
            for room_id in (*first.room_ids.values(), *second.room_ids.values())
        }
        self.restart()
        after = {
            room_id: self.runtime().world.rooms[room_id].grid
            for room_id in (*first.room_ids.values(), *second.room_ids.values())
        }
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
