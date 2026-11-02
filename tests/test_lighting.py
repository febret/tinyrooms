from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import Mock

from server.content.lighting import LIGHTING_ENVIRONMENTS, phase_to_environment
from server.services.lighting import LightingService
from server.services.prop_lights import PropLightService
from server.services.rooms import RoomService
from tests.common import REPO_ROOT, load_test_world


def _stub_world(**world_overrides: object) -> object:
    from types import SimpleNamespace

    def room(room_id: str, **overrides: object) -> SimpleNamespace:
        base = {"id": room_id, "dark": False, "environment": None, "board_type": "basic"}
        base.update(overrides)
        return SimpleNamespace(**base)

    base_world = {
        "id": "stub",
        "environment": None,
        "rooms": {
            "open": room("open"),
            "moody": room("moody", environment="night"),
            "cellar": room("cellar", dark=True),
            "diorama": room("diorama", board_type="diorama"),
        },
    }
    base_world.update(world_overrides)
    return SimpleNamespace(**base_world)


def _cycled(service: LightingService, name: str) -> LightingService:
    """Pin a service's live cycle bucket for deterministic assertions."""

    service.cycle_environment = lambda: name  # type: ignore[method-assign]
    return service


class LightingContentTests(unittest.TestCase):
    def test_cycle_buckets_cover_the_known_environments(self) -> None:
        phases = [0.0, 0.25, 0.5, 0.8]
        self.assertEqual(
            [phase_to_environment(phase) for phase in phases],
            ["night", "dawn", "day", "dusk"],
        )
        for environment in ("night", "dawn", "day", "dusk"):
            self.assertIn(environment, LIGHTING_ENVIRONMENTS)


class LightingResolutionTests(unittest.TestCase):
    def test_room_without_override_follows_live_cycle(self) -> None:
        service = _cycled(LightingService(_stub_world()), "dusk")
        self.assertEqual(service.snapshot_payload("open")["name"], "dusk")

    def test_world_override_freezes_cycle(self) -> None:
        service = _cycled(
            LightingService(_stub_world(environment="night")),
            "dusk",
        )
        self.assertEqual(service.snapshot_payload("open")["name"], "night")
        self.assertFalse(service.follows_cycle("open"))

    def test_room_override_wins_over_cycle_and_world(self) -> None:
        cycle = _cycled(LightingService(_stub_world()), "dusk")
        self.assertEqual(cycle.snapshot_payload("moody")["name"], "night")
        world = _cycled(
            LightingService(_stub_world(environment="night")),
            "dusk",
        )
        self.assertEqual(world.snapshot_payload("moody")["name"], "night")

    def test_dark_rooms_always_resolve_to_darkness(self) -> None:
        service = _cycled(
            LightingService(_stub_world(environment="night")),
            "dusk",
        )
        payload = service.snapshot_payload("cellar")
        self.assertEqual(payload["name"], "darkness")
        self.assertTrue(payload["dark"])

    def test_runtime_dark_override_wins_over_yaml(self) -> None:
        service = _cycled(LightingService(_stub_world()), "dusk")
        self.assertEqual(service.snapshot_payload("moody", dark=True)["name"], "darkness")

    def test_follows_cycle_only_for_inheriting_basic_rooms(self) -> None:
        service = LightingService(_stub_world())
        self.assertTrue(service.follows_cycle("open"))
        self.assertFalse(service.follows_cycle("moody"))
        self.assertFalse(service.follows_cycle("cellar"))
        self.assertFalse(service.follows_cycle("diorama"))
        self.assertFalse(service.follows_cycle("missing"))

    def test_poll_cycle_change_arms_then_reports_followers(self) -> None:
        service = LightingService(_stub_world())
        buckets = iter(["dusk", "dusk", "dawn", "dawn"])
        service.cycle_environment = lambda: next(buckets)  # type: ignore[method-assign]
        self.assertIsNone(service.poll_cycle_change())
        self.assertIsNone(service.poll_cycle_change())
        self.assertEqual(service.poll_cycle_change(), ["open"])
        self.assertIsNone(service.poll_cycle_change())


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
