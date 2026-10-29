from __future__ import annotations

from dataclasses import replace
import re
import unittest
from unittest.mock import Mock

from server.content.common import ContentError
from server.content.lighting import (
    DAY_NIGHT_CYCLE_SECONDS,
    LIGHTING_ENVIRONMENTS,
    phase_to_environment,
    preset_for,
    serialize_preset,
    validate_lighting_name,
)
from server.services.lighting import LightingService, prop_light_kind
from server.services.prop_lights import PropLightService
from server.services.rooms import RoomService
from tests.common import REPO_ROOT, load_test_world


def _stub_world() -> object:
    from types import SimpleNamespace

    def room(room_id: str, **overrides: object) -> SimpleNamespace:
        base = {"id": room_id, "dark": False, "environment": None}
        base.update(overrides)
        return SimpleNamespace(**base)

    return SimpleNamespace(
        id="stub",
        global_environment="day",
        rooms={
            "open": room("open"),
            "moody": room("moody", environment="night"),
            "cellar": room("cellar", dark=True),
        },
    )


class LightingContentTests(unittest.TestCase):
    def test_environments_cover_darkness_night_dusk_day_dawn(self) -> None:
        self.assertEqual(
            tuple(LIGHTING_ENVIRONMENTS), ("darkness", "night", "dusk", "day", "dawn", "fluorescent")
        )

    def test_validate_rejects_unknown_environment(self) -> None:
        with self.assertRaises(ContentError):
            validate_lighting_name("midnight", "Room 'hub' environment")
        self.assertIsNone(validate_lighting_name(None, "Room 'hub' environment"))
        self.assertEqual(validate_lighting_name(" Night ", "World 'w' environment"), "night")

    def test_presets_have_color_level_and_type(self) -> None:
        for name in LIGHTING_ENVIRONMENTS:
            payload = serialize_preset(preset_for(name))
            self.assertEqual(payload["name"], name)
            self.assertRegex(str(payload["color"]), r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")
            self.assertGreaterEqual(float(payload["level"]), 0.0)
            self.assertLessEqual(float(payload["level"]), 1.0)
            self.assertTrue(str(payload["type"]))

    def test_darkness_is_fully_black(self) -> None:
        payload = serialize_preset(preset_for("darkness"))
        self.assertEqual(float(payload["level"]), 0.0)

    def test_phase_bands_cover_full_cycle(self) -> None:
        self.assertEqual(phase_to_environment(0.0), "night")
        self.assertEqual(phase_to_environment(0.25), "dawn")
        self.assertEqual(phase_to_environment(0.5), "day")
        self.assertEqual(phase_to_environment(0.75), "dusk")
        self.assertEqual(phase_to_environment(0.95), "night")


class LightingResolutionTests(unittest.TestCase):
    def test_room_falls_back_to_global_environment(self) -> None:
        service = LightingService(_stub_world())
        self.assertEqual(service.snapshot_payload("open")["name"], "day")

    def test_room_override_wins_over_global(self) -> None:
        service = LightingService(_stub_world())
        self.assertEqual(service.snapshot_payload("moody")["name"], "night")

    def test_dark_rooms_always_resolve_to_darkness(self) -> None:
        service = LightingService(_stub_world())
        payload = service.snapshot_payload("cellar")
        self.assertEqual(payload["name"], "darkness")
        self.assertEqual(float(payload["level"]), 0.0)

    def test_apply_cycle_skips_specific_and_dark_rooms(self) -> None:
        service = LightingService(_stub_world())
        expected = service.cycle_environment()
        changed = service.apply_cycle()
        self.assertEqual(changed, {"open": expected})
        self.assertEqual(service.snapshot_payload("moody")["name"], "night")
        self.assertEqual(service.snapshot_payload("cellar")["name"], "darkness")

    def test_snapshot_carries_shared_phase(self) -> None:
        service = LightingService(_stub_world())
        payload = service.snapshot_payload("open")
        self.assertEqual(payload["name"], "day")
        self.assertGreaterEqual(float(payload["time_of_day"]), 0.0)
        self.assertLess(float(payload["time_of_day"]), 1.0)
        self.assertEqual(float(payload["day_cycle_seconds"]), 600.0)
        service.apply_cycle()
        self.assertEqual(
            service.snapshot_payload("open")["name"], service.cycle_environment()
        )

    def test_client_cycle_fallback_matches_server(self) -> None:
        source = (REPO_ROOT / "client" / "app" / "js" / "board" / "board-diorama-daylight.js").read_text()
        match = re.search(r"DIORAMA_CYCLE_SECONDS\s*=\s*([\d.]+)", source)
        self.assertIsNotNone(match, "client cycle fallback")
        self.assertAlmostEqual(float(match.group(1)), float(DAY_NIGHT_CYCLE_SECONDS))

    def test_client_preset_names_match_server(self) -> None:
        source = (REPO_ROOT / "client" / "app" / "js" / "board" / "board-lighting.js").read_text()
        for name in LIGHTING_ENVIRONMENTS:
            self.assertIsNotNone(
                re.search(rf"{name}:\s*\{{", source), f"client preset '{name}'"
            )
        client_names = set(re.findall(r"^\s{2}(\w+):\s*\{$", source, re.MULTILINE))
        self.assertEqual(client_names, set(LIGHTING_ENVIRONMENTS))


class PropLightServiceTests(unittest.TestCase):
    def test_fixtures_default_on_and_toggle(self) -> None:
        service = PropLightService()
        self.assertTrue(service.is_on("room", "lamp"))
        self.assertFalse(service.toggle("room", "lamp"))
        self.assertFalse(service.is_on("room", "lamp"))
        self.assertTrue(service.toggle("room", "lamp"))

    def test_window_and_fixture_classification(self) -> None:
        from types import SimpleNamespace

        self.assertEqual(prop_light_kind(SimpleNamespace(tags=("window", "building"))), "window")
        self.assertEqual(prop_light_kind(SimpleNamespace(tags=("lighting", "lamp"))), "fixture")
        self.assertEqual(prop_light_kind(SimpleNamespace(tags=("lantern",))), "fixture")
        self.assertIsNone(prop_light_kind(SimpleNamespace(tags=("table",))))
        self.assertIsNone(prop_light_kind(SimpleNamespace(tags=())))

    def test_every_tagged_light_and_window_prop_classifies(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        fixtures = [
            definition.id
            for definition in world.props.values()
            if set(definition.tags) & {"lamp", "lighting", "lantern", "sconce"}
        ]
        windows = [
            definition.id
            for definition in world.props.values()
            if "window" in definition.tags
        ]
        self.assertTrue(fixtures, "expected lamp/lighting props in the catalog")
        self.assertTrue(windows, "expected window props in the catalog")
        for prop_id in fixtures:
            self.assertEqual(
                prop_light_kind(world.props[prop_id]), "fixture", f"prop '{prop_id}'"
            )
        for prop_id in windows:
            self.assertEqual(
                prop_light_kind(world.props[prop_id]), "window", f"prop '{prop_id}'"
            )
class FixtureToggleTests(unittest.TestCase):
    @staticmethod
    def _service() -> tuple[RoomService, object, str, str]:
        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        entry = next(iter(world.rooms.values()))
        from server.content.worlds import PropInstanceDefinition

        def instance(instance_id: str, prop_id: str) -> PropInstanceDefinition:
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

        room = replace(
            entry,
            id="lighting-room",
            dark=False,
            environment=None,
            props={
                "lamp-one": instance("lamp-one", "mushroom-table-lamp"),
                "window-one": instance("window-one", "bay-window"),
                "table-one": instance("table-one", "rattan-side-table"),
            },
        )
        world.rooms["lighting-room"] = room
        service = RoomService(
            hub=Mock(),
            profiles=Mock(),
            world_state=Mock(),
            connections=Mock(),
            card_service=Mock(),
            activities=Mock(),
            world=world,
            stats=Mock(),
            command_verbs=frozenset({".toggle"}),
        )
        return service, room, "lamp-one", "window-one", "table-one"

    def test_fixture_toggle_flips_and_broadcasts(self) -> None:
        service, _room, lamp_id, _window_id, _table_id = self._service()
        first = service.toggle_prop_light("lighting-room", lamp_id)
        self.assertEqual(first["type"], "room.prop.updated")
        self.assertFalse(first["prop"]["light"]["on"])
        second = service.toggle_prop_light("lighting-room", lamp_id)
        self.assertTrue(second["prop"]["light"]["on"])

    def test_window_has_no_toggle(self) -> None:
        service, _room, _lamp_id, window_id, _table_id = self._service()
        with self.assertRaises(ValueError):
            service.toggle_prop_light("lighting-room", window_id)

    def test_toggle_command_dispatches_fixture(self) -> None:
        import asyncio
        from types import SimpleNamespace

        from server.commands.outcomes import CommandError
        from server.commands.parser import ParsedCommand
        from server.commands.props import toggle_command

        service, _room, lamp_id, window_id, table_id = self._service()
        context = SimpleNamespace(
            rooms=service,
            connection=SimpleNamespace(room_id="lighting-room"),
            account=Mock(),
        )

        def run(instance_id: str) -> object:
            return asyncio.run(toggle_command(
                context,
                ParsedCommand(kind="normal", name="toggle", args=(f"@prop:{instance_id}",), raw_text=".toggle"),
            ))

        outcome = run(lamp_id)
        self.assertFalse(outcome.payload["light"]["on"])
        self.assertEqual(len(outcome.room_broadcasts), 1)
        self.assertEqual(
            outcome.room_broadcasts[0].event["prop"]["light"]["on"], False
        )
        with self.assertRaises(CommandError):
            run(window_id)
        with self.assertRaises(CommandError):
            run(table_id)

    def test_is_toggleable_matches_fixtures_only(self) -> None:
        from types import SimpleNamespace

        from server.services.lighting import is_toggleable

        self.assertTrue(is_toggleable(SimpleNamespace(tags=("lighting", "lamp"))))
        self.assertFalse(is_toggleable(SimpleNamespace(tags=("window", "building"))))
        self.assertFalse(is_toggleable(SimpleNamespace(tags=("table",))))

    def test_fixture_serializes_light_and_toggle_action(self) -> None:
        service, room, lamp_id, window_id, _table_id = self._service()
        account = Mock()
        lamp = service._serialize_prop(account, room, room.props[lamp_id])
        self.assertEqual(lamp["light"]["kind"], "fixture")
        self.assertTrue(lamp["light"]["on"])
        commands = [action["command"] for action in lamp["quick_actions"]]
        self.assertIn(f".toggle @prop:{lamp_id}", commands)
        window = service._serialize_prop(account, room, room.props[window_id])
        self.assertEqual(window["light"]["kind"], "window")
        self.assertEqual(window["light"]["color"], "#8da7e8")

    def test_tinytown_world_has_day_global_environment(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / "tinytown")
        self.assertEqual(world.global_environment, "day")


if __name__ == "__main__":
    unittest.main()
