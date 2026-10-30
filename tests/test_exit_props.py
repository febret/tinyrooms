"""Prop exit markers: the exit_to instance property and built-in exit props."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import yaml

from server.services.rooms import RoomService
from tests.common import (
    REPO_ROOT,
    IntegrationTestCase,
    ServiceTestCase,
    load_test_world,
    load_world_activities,
)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _minimal_world(root: Path, rooms: dict) -> Path:
    world_path = root / "probe"
    _write_text(world_path / "world.yaml", yaml.safe_dump({"id": "probe", "entry_room": "hub"}))
    _write_text(world_path / "rooms" / "rooms.yaml", yaml.safe_dump(rooms))
    _write_text(world_path / "rooms" / "hub.png", "")
    _write_text(world_path / "peeps" / "peeps.yaml", yaml.safe_dump({}))
    _write_text(world_path / "props" / "props.yaml", yaml.safe_dump({
        "widget": {
            "label": "Widget",
            "model": "widget.glb",
            "decorative": False,
        },
    }))
    _write_text(world_path / "props" / "widget.glb", "")
    return world_path


def _load_probe(world_path: Path):
    from server.content.worlds import load_world_definition

    return load_world_definition(
        world_path,
        {"market-bandage"},
        core_activities=load_world_activities(),
        propsets_root=(),
        fx_root=None,
    )


def _exit_ids(command: str) -> str | None:
    match = re.match(r"^\.go\s+(?:@way:)?(\S+)", command.strip())
    return match.group(1) if match else None


def _covered_exits(room) -> set[str]:
    covered = {instance.exit_to for instance in room.props.values() if instance.exit_to}
    for instance in room.props.values():
        for action in instance.actions:
            exit_id = _exit_ids(action.command)
            if exit_id is not None:
                covered.add(exit_id)
    return covered


class ExitToLoaderTests(unittest.TestCase):
    def test_exit_to_loads_on_a_prop_instance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            world_path = _minimal_world(Path(tmp), {
                "hub": {
                    "label": "Hub",
                    "board_image": "hub.png",
                    "props": {"door0": {"prop": "builtin:door", "exit_to": "out"}},
                    "exits": {"out": {"label": "Out", "target": "hub"}},
                },
            })
            world = _load_probe(world_path)
        self.assertEqual(world.rooms["hub"].props["door0"].exit_to, "out")


class ExitToActionTests(ServiceTestCase):
    def test_exit_to_serializes_a_go_quick_action(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        room = world.rooms["foyer"]
        service = RoomService(
            hub=Mock(),
            profiles=Mock(),
            world_state=Mock(),
            connections=Mock(),
            card_service=Mock(),
            activities=Mock(),
            world=world,
            stats=Mock(),
            command_verbs=frozenset({".go", ".look"}),
        )
        payload = service._serialize_prop(Mock(), room, room.props["hub-door0"])
        commands = [action["command"] for action in payload["quick_actions"]]
        self.assertIn(".go @way:hub", commands)
        action = next(item for item in payload["quick_actions"] if item["command"] == ".go @way:hub")
        self.assertEqual(action["label"], "Out of the dollhouse")
        self.assertTrue(action.get("default"))


class ExitStyleLoaderTests(unittest.TestCase):
    def _world_with_style(self, tmp: str, recipe: object, prop: str = "builtin:door") -> object:
        world_path = _minimal_world(Path(tmp), {
            "hub": {
                "label": "Hub",
                "board_image": "hub.png",
                "props": {"door0": {"prop": prop, **({"exit_style": recipe} if recipe is not None else {})}},
            },
        })
        return _load_probe(world_path)

    def test_exit_style_loads_on_an_exit_prop(self) -> None:
        recipe = {"style": "arch", "main": "#b07a4a", "accent": "#6b4a2f", "texture": "wood"}
        with tempfile.TemporaryDirectory() as tmp:
            world = self._world_with_style(tmp, recipe)
        self.assertEqual(world.rooms["hub"].props["door0"].exit_style, recipe)

    def test_exit_style_serializes_with_defaults_when_absent(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / "tiny-arcade", allow_legacy_whiteboards=True)
        room = world.rooms["chess"]
        service = RoomService(
            hub=Mock(),
            profiles=Mock(),
            world_state=Mock(),
            connections=Mock(),
            card_service=Mock(),
            activities=Mock(),
            world=world,
            stats=Mock(),
            command_verbs=frozenset({".go", ".look"}),
        )
        payload = service._serialize_prop(Mock(), room, room.props["lobby-door0"])
        self.assertEqual(
            payload["exit_style"],
            {"style": "panel", "main": "#b07a4a", "accent": "#6b4a2f", "texture": "plain"},
        )
        foyer = load_test_world(REPO_ROOT / "worlds" / "tutorial").rooms["foyer"]
        styled = service._serialize_prop(Mock(), foyer, foyer.props["hub-door0"])
        self.assertEqual(styled["exit_style"]["style"], "arch")
        self.assertEqual(styled["exit_style"]["texture"], "wood")


class BakedExitTextureTests(unittest.TestCase):
    def test_every_textured_finish_has_a_baked_grayscale_texture(self) -> None:
        from PIL import Image

        from server.content.exit_props import EXIT_TEXTURE_FILES

        for texture_id, filename in EXIT_TEXTURE_FILES.items():
            with self.subTest(texture=texture_id):
                path = REPO_ROOT / "client" / "app" / "assets" / "textures" / filename
                self.assertTrue(path.is_file(), f"Missing baked texture {filename}.")
                image = Image.open(path).convert("RGB")
                self.assertEqual(image.size, (512, 512))
                pixels = list(image.getdata())
                saturation = sum(abs(red - green) + abs(green - blue) for red, green, blue in pixels) / len(pixels)
                self.assertLess(saturation, 12.0, f"{filename} must stay near grayscale so colors tint cleanly.")


class RoomLayoutExitStyleTests(IntegrationTestCase):
    """In-game exit finish edits must persist and win over authored finishes."""

    def setUp(self) -> None:
        super().setUp()
        runtime = self.runtime()
        self.account = runtime.profiles.create_account(
            "exit-owner",
            "password123!",
            runtime.world.id,
            runtime.world.entry_room_id,
        )
        self.room_id = "foyer"
        runtime.ownership.grant(self.room_id, self.account.id)

    def _save(self, props: list[dict]) -> object:
        runtime = self.runtime()
        layout = runtime.world_state.read_room_layout(self.room_id)
        return runtime.layout.save(
            self.account,
            self.room_id,
            int(layout["revision"]),
            {"props": props},
        )

    def _stored(self) -> dict[str, dict]:
        runtime = self.runtime()
        entries = runtime.world_state.read_room_layout(self.room_id)["props"] or []
        return {str(entry.get("id")): entry for entry in entries}

    def test_live_finish_wins_over_the_authored_finish(self) -> None:
        runtime = self.runtime()
        patch = [dict(entry) for entry in (runtime.world_state.read_room_layout(self.room_id)["props"] or [])]
        patch.append({
            "id": "hub-door0",
            "prop_id": "builtin:door",
            "position": [0, 45, 0],
            "rotation": [0, 90, 0],
            "scale": 1.1,
            "locked": False,
            "exit_style": {"style": "slab", "main": "#4ea8ff", "accent": "#0d0b15", "texture": "metal"},
        })
        updated = self._save(patch)
        serialized = {prop["id"]: prop for prop in updated.props}
        self.assertEqual(serialized["hub-door0"]["exit_style"]["style"], "slab")
        self.assertEqual(self._stored()["hub-door0"]["exit_style"]["texture"], "metal")
        effective = runtime.layout.effective_props(self.room_id)
        instance = next(prop for prop in effective if prop.id == "hub-door0")
        self.assertEqual(
            instance.exit_style,
            {"style": "slab", "main": "#4ea8ff", "accent": "#0d0b15", "texture": "metal"},
        )


class ShippedExitCoverageTests(unittest.TestCase):
    def test_every_authored_exit_is_reachable_through_a_prop(self) -> None:
        worlds = ("tutorial", "tiny-arcade", "tinytown")
        for world_name in worlds:
            world_root = REPO_ROOT / "worlds"
            world = load_test_world(
                world_root / world_name,
                allow_legacy_whiteboards=world_name == "tiny-arcade",
            )
            for room_id, room in world.rooms.items():
                missing = sorted(set(room.exits) - _covered_exits(room))
                self.assertEqual(
                    missing, [],
                    f"World '{world_name}' room '{room_id}' has exits without a prop quick action.",
                )


if __name__ == "__main__":
    unittest.main()
