"""Prop definition ownership: behavior, activity, content, cooldown, recipes."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from server.content.common import ContentError
from server.content.prop_definitions import load_prop_definition
from tests.common import REPO_ROOT, load_test_world, load_world_activities


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
            "one_per_room": True,
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


class PropDefinitionFieldTests(unittest.TestCase):
    def test_definition_fields_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            props_file = Path(tmp) / "props.yaml"
            (Path(tmp) / "widget.glb").write_bytes(b"")
            definition = load_prop_definition(
                "widget",
                {
                    "label": "Widget",
                    "model": "widget.glb",
                    "behavior": "dispenser",
                    "activity": "whiteboard",
                    "content": ["market-bandage"],
                    "cooldown": 60,
                    "recipes": ["supper"],
                    "one_per_room": True,
                },
                props_file=props_file,
                source="probe",
            )
        self.assertEqual(definition.behavior, "dispenser")
        self.assertEqual(definition.activity, "whiteboard")
        self.assertEqual(definition.content, ("market-bandage",))
        self.assertEqual(definition.cooldown, 60)
        self.assertEqual(definition.recipes, ("supper",))
        self.assertTrue(definition.one_per_room)

    def test_text_render_kind_needs_no_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            props_file = Path(tmp) / "props.yaml"
            definition = load_prop_definition(
                "ticker",
                {"label": "Ticker", "render_kind": "text", "behavior": "chess"},
                props_file=props_file,
                source="probe",
            )
        self.assertEqual(definition.render_kind, "text")
        self.assertIsNone(definition.model_name)
        self.assertEqual(definition.behavior, "chess")


class PropGameplayMigrationTests(unittest.TestCase):
    def test_shared_dispenser_lives_on_the_definition(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        definition = world.props["medicine-cabinet"]
        self.assertFalse(definition.decorative)
        self.assertEqual(definition.behavior, "dispenser")
        self.assertIn("market-bandage", definition.content)
        self.assertEqual(definition.cooldown, 60)
        self.assertTrue(definition.one_per_room)
        instance = world.rooms["bathroom"].props["medicine0"]
        self.assertFalse(hasattr(instance, "behavior"))
        self.assertFalse(hasattr(instance, "content"))

    def test_chess_controller_is_a_dedicated_text_prop(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / "tiny-arcade")
        definition = world.props["chess-controller"]
        self.assertEqual(definition.render_kind, "text")
        self.assertEqual(definition.behavior, "chess")
        instance = world.rooms["chess"].props["chess-controller"]
        self.assertEqual(instance.text, {"content": "CHESS", "font_id": "serif", "color": "#ffd166"})

    def test_classroom_door_activity_lives_on_the_definition(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / "scammon-academia")
        definition = world.props["classroom-oak-panel-door"]
        self.assertEqual(definition.activity, "classrooms")
        instance = world.rooms["hall"].props["classroom-door0"]
        self.assertFalse(hasattr(instance, "activity"))
        self.assertTrue(instance.actions)

    def test_whiteboard_keeps_its_default_activity(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        self.assertEqual(world.props["builtin:whiteboard"].activity, "whiteboard")


class PropInstanceValidationTests(unittest.TestCase):
    def test_moved_instance_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            world_path = _minimal_world(Path(tmp), {
                "hub": {
                    "label": "Hub",
                    "board_image": "hub.png",
                    "props": {"widget0": {"prop": "widget", "behavior": "dispenser"}},
                },
            })
            with self.assertRaises(ContentError) as raised:
                _load_probe(world_path)
        self.assertIn("define them on the prop instead", str(raised.exception))

    def test_instance_label_override_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            world_path = _minimal_world(Path(tmp), {
                "hub": {
                    "label": "Hub",
                    "board_image": "hub.png",
                    "props": {"widget0": {"prop": "widget", "label": "Lobby Widget"}},
                },
            })
            world = _load_probe(world_path)
        self.assertEqual(world.rooms["hub"].props["widget0"].label, "Lobby Widget")

    def test_one_per_room_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            world_path = _minimal_world(Path(tmp), {
                "hub": {
                    "label": "Hub",
                    "board_image": "hub.png",
                    "props": {
                        "sole": {"prop": "widget"},
                        "twin": {"prop": "widget"},
                    },
                },
            })
            with self.assertRaises(ContentError) as raised:
                _load_probe(world_path)
        self.assertIn("only one", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
