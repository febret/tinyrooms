from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import Mock

from server.content.lighting import (
    LIGHTING_ENVIRONMENTS,
    preset_for,
    serialize_preset,
)
from server.services.lighting import LightingService
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
    def test_presets_have_color_level_and_type(self) -> None:
        for name in LIGHTING_ENVIRONMENTS:
            payload = serialize_preset(preset_for(name))
            self.assertEqual(payload["name"], name)
            self.assertRegex(str(payload["color"]), r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")
            self.assertGreaterEqual(float(payload["level"]), 0.0)
            self.assertLessEqual(float(payload["level"]), 1.0)
            self.assertTrue(str(payload["type"]))


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


class PropLightServiceTests(unittest.TestCase):
    def test_fixtures_default_on_and_toggle(self) -> None:
        service = PropLightService()
        self.assertTrue(service.is_on("room", "lamp"))
        self.assertFalse(service.toggle("room", "lamp"))
        self.assertFalse(service.is_on("room", "lamp"))
        self.assertTrue(service.toggle("room", "lamp"))

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


if __name__ == "__main__":
    unittest.main()
