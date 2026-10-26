"""Prop definition ownership: behavior, activity, content, cooldown, recipes."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from server.content.common import ContentError
from server.content.prop_definitions import load_prop_definition
from tests.common import REPO_ROOT, ServiceTestCase, load_test_world, load_world_activities


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
        world = load_test_world(REPO_ROOT / "worlds" / "tiny-arcade", allow_legacy_whiteboards=True)
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
        self.assertEqual(instance.actions, ())
        self.assertEqual(
            [(action.label, action.command) for action in definition.default_actions],
            [("Enter the classroom", ".play classrooms")],
        )

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


class PropDefaultActionTests(unittest.TestCase):
    def test_self_placeholder_targets_the_placed_instance(self) -> None:
        from server.content.prop_definitions import resolve_default_prop_actions

        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        resolved = resolve_default_prop_actions(world.props["medicine-cabinet"], "custom:abc")
        self.assertEqual(
            [(action.label, action.command) for action in resolved],
            [("Take medicine", ".dispense @prop:custom:abc")],
        )

    def test_behavior_actions_moved_off_authored_instances(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        self.assertEqual(world.rooms["bathroom"].props["medicine0"].actions, ())
        definition = world.props["medicine-cabinet"]
        self.assertTrue(definition.default_actions)

    def test_placed_dispenser_serializes_an_execute_action(self) -> None:
        from unittest.mock import Mock

        from server.content.worlds import PropInstanceDefinition
        from server.services.rooms import RoomService

        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        placed = PropInstanceDefinition(
            id="custom:placed",
            prop_id="medicine-cabinet",
            pos=(50.0, 50.0, 0.0),
            rot=(0.0, 0.0, 0.0),
            scale=1.0,
            actions=(),
            personal=False,
            animation=None,
        )
        room = world.rooms["bathroom"]
        service = RoomService(
            hub=Mock(),
            profiles=Mock(),
            world_state=Mock(),
            connections=Mock(),
            card_service=Mock(),
            activities=Mock(),
            world=world,
            stats=Mock(),
            command_verbs=frozenset({".dispense", ".craft", ".act", ".play"}),
        )
        payload = service._serialize_prop(Mock(), room, placed)
        commands = [action["command"] for action in payload["quick_actions"]]
        self.assertIn(".dispense @prop:custom:placed", commands)

    def test_authored_dispenser_keeps_a_single_dispense_action(self) -> None:
        from unittest.mock import Mock

        from server.services.rooms import RoomService

        world = load_test_world(REPO_ROOT / "worlds" / "scammon-academia")
        room = world.rooms["teachers-lounge"]
        service = RoomService(
            hub=Mock(),
            profiles=Mock(),
            world_state=Mock(),
            connections=Mock(),
            card_service=Mock(),
            activities=Mock(),
            world=world,
            stats=Mock(),
            command_verbs=frozenset({".dispense", ".craft", ".act", ".play"}),
        )
        payload = service._serialize_prop(Mock(), room, room.props["pantry0"])
        commands = [action["command"] for action in payload["quick_actions"]]
        self.assertEqual(commands.count(".dispense @prop:pantry0"), 1)


class PlacedPropBehaviorTests(ServiceTestCase):
    """Player-placed behavior props must work like authored instances."""

    def _placed(self, instance_id: str, prop_id: str):
        from server.content.worlds import PropInstanceDefinition

        return PropInstanceDefinition(
            id=instance_id,
            prop_id=prop_id,
            pos=(50.0, 50.0, 0.0),
            rot=(0.0, 0.0, 0.0),
            scale=1.0,
            actions=(),
            personal=False,
            animation=None,
        )

    def test_placed_dispenser_dispenses(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import Mock

        from server.services.dispensers import DispenserService

        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        account = self.create_account("placed-dispense")
        placed = self._placed("custom:placed", "medicine-cabinet")
        layout = SimpleNamespace(effective_props=lambda room_id: [placed])
        service = DispenserService(
            self.hub, self.profiles, self.catalog, world, layout=layout
        )
        result = service.dispense(account, "bathroom", "custom:placed")
        self.assertTrue(result.granted)
        self.assertIn(result.card_id, world.props["medicine-cabinet"].content)

    def test_placed_crafting_station_resolves(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import Mock

        from server.services.crafting import CraftingService

        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        account = self.create_account("placed-craft")
        placed = self._placed("custom:station", "kitchen-counter")
        layout = SimpleNamespace(effective_props=lambda room_id: [placed])
        service = CraftingService(
            self.hub,
            self.profiles,
            Mock(),
            Mock(),
            self.catalog,
            self.content,
            world,
            world.recipes,
            layout=layout,
        )
        recipes = service.station_recipes(account, "kitchen", "custom:station")
        self.assertIsInstance(recipes, tuple)

    def test_authored_lookup_still_works_without_layout(self) -> None:
        from server.services.dispensers import DispenserService

        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        service = DispenserService(self.hub, self.profiles, self.catalog, world)
        prop = service._prop("bathroom", "medicine0")
        self.assertEqual(prop.prop_id, "medicine-cabinet")


if __name__ == "__main__":
    unittest.main()
