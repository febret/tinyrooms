"""Prop effect catalog loading, parsing, and serialization tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from server.content.common import ContentError
from server.content.fx import load_effect_catalog
from server.content.worlds import load_propset
from server.services.activities import ActivityService
from server.services.cards import CardService
from server.services.prop_shop import serialize_prop_entry
from server.services.room_effects import RoomEffectService
from server.services.rooms import RoomService
from server.services.stats import StatsService
from server.state.world_state import WorldStateRepository
from tests.common import REPO_ROOT, WORLD_ID, ServiceTestCase, load_world_fx, load_test_world


class FakeConnections:
    """Minimal connection registry double that reports no occupants."""

    async def list_room(self, room_id: str) -> list[object]:
        return []


def _write_propset(root: Path, props_body: str) -> Path:
    propset = root / "testset"
    propset.mkdir(parents=True)
    (propset / "model.glb").write_bytes(b"")
    (propset / "props.yaml").write_text(props_body, encoding="utf-8")
    return propset


class EffectCatalogTests(unittest.TestCase):
    """The effect catalog loader accepts valid definitions and rejects bad ones."""

    def test_core_catalog_loads_smoke_fire_and_sparks(self) -> None:
        effects = load_effect_catalog(REPO_ROOT / "data" / "fx")
        self.assertEqual({"smoke", "fire", "sparks"} <= set(effects), True)
        fire = effects["fire"].serialize()
        self.assertEqual(fire["id"], "fire")
        particle = fire["layers"][0]
        self.assertEqual(particle["type"], "particle")
        self.assertEqual(particle["preset"], "fire")
        self.assertEqual(particle["texture_url"], "/assets/fx/fire-puff.png")
        self.assertEqual(particle["anchor"], "top")

    def test_missing_catalog_directory_is_empty(self) -> None:
        with TemporaryDirectory() as temporary:
            self.assertEqual(load_effect_catalog(Path(temporary) / "nope"), {})

    def test_duplicate_or_mismatched_ids_are_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "smoke.yaml").write_text("id: other\nlayers: []\n", encoding="utf-8")
            with self.assertRaises(ContentError):
                load_effect_catalog(root)

    def test_unknown_layer_type_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "weird.yaml").write_text(
                "id: weird\nlayers:\n  - type: hologram\n", encoding="utf-8"
            )
            with self.assertRaises(ContentError):
                load_effect_catalog(root)

    def test_particle_requires_an_existing_texture(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "ghost.yaml").write_text(
                "id: ghost\nlayers:\n  - type: particle\n    preset: smoke\n    texture: missing.png\n",
                encoding="utf-8",
            )
            with self.assertRaises(ContentError):
                load_effect_catalog(root)

    def test_bad_transform_motion_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "wobble.yaml").write_text(
                "id: wobble\nlayers:\n  - type: transform\n    motion: wiggle\n",
                encoding="utf-8",
            )
            with self.assertRaises(ContentError):
                load_effect_catalog(root)


class PropEffectBindingTests(ServiceTestCase):
    """Props declare named effect sets and reference known effects."""

    def test_prop_definition_parses_named_sets_and_default(self) -> None:
        with TemporaryDirectory() as temporary:
            propset = _write_propset(
                Path(temporary),
                "lamp:\n  label: Lamp\n  model: model.glb\n"
                "  effects:\n    lit: [fire, ember-glow]\n    smoking: [smoke]\n"
                "  active_effect: lit\n",
            )
            lamp = load_propset(propset, effects=load_world_fx())["lamp"]
            self.assertEqual(lamp.effect_sets["lit"], ("fire", "ember-glow"))
            self.assertEqual(lamp.effect_sets["smoking"], ("smoke",))
            self.assertEqual(lamp.active_effect, "lit")

    def test_effects_list_shorthand_becomes_default_set(self) -> None:
        with TemporaryDirectory() as temporary:
            propset = _write_propset(
                Path(temporary),
                "thing:\n  label: Thing\n  model: model.glb\n  effects: [smoke]\n",
            )
            props = load_propset(propset, effects=load_world_fx())
            self.assertEqual(props["thing"].effect_sets, {"default": ("smoke",)})
            self.assertEqual(props["thing"].active_effect, "default")

    def test_unknown_effect_reference_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            propset = _write_propset(
                Path(temporary),
                "thing:\n  label: Thing\n  model: model.glb\n  effects:\n    idle: [not-a-thing]\n",
            )
            with self.assertRaises(ContentError):
                load_propset(propset, effects=load_world_fx())

    def test_active_effect_must_name_a_declared_set(self) -> None:
        with TemporaryDirectory() as temporary:
            propset = _write_propset(
                Path(temporary),
                "thing:\n  label: Thing\n  model: model.glb\n"
                "  effects:\n    idle: [smoke]\n  active_effect: active\n",
            )
            with self.assertRaises(ContentError):
                load_propset(propset, effects=load_world_fx())

    def test_serialize_prop_entry_resolves_effect_descriptors(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        definition = next(entry for entry in world.props.values() if entry.effect_sets)
        payload = serialize_prop_entry(world, definition)
        self.assertTrue(payload["effect_sets"])
        self.assertIn(payload["active_effect"], payload["effect_sets"])
        particle_layers = [
            layer
            for effects in payload["effect_sets"].values()
            for effect in effects
            for layer in effect["layers"]
            if layer.get("type") == "particle"
        ]
        self.assertTrue(particle_layers)
        for layer in particle_layers:
            self.assertTrue(layer["texture_url"].startswith("/assets/fx/"))


class RoomEffectServiceTests(unittest.TestCase):
    """Runtime active-set overrides are tracked per instance and reset on clear."""

    def test_override_and_default(self) -> None:
        service = RoomEffectService()
        self.assertEqual(service.active_for("hub", "portal0", "idle"), "idle")
        service.set("hub", "portal0", "active")
        self.assertEqual(service.active_for("hub", "portal0", "idle"), "active")
        service.clear_room("hub")
        self.assertEqual(service.active_for("hub", "portal0", "idle"), "idle")


class PropEffectSnapshotTests(ServiceTestCase):
    """Room snapshots carry resolved effects and reflect runtime switches."""

    def setUp(self) -> None:
        super().setUp()
        self.world = load_test_world(REPO_ROOT / "worlds" / "tutorial", set(self.catalog.cards))
        self.world_state = WorldStateRepository(self.hub)
        self.world_state.initialize_world(self.world)
        self.room_effects = RoomEffectService()
        cards = CardService(self.hub, self.profiles, self.world_state, self.catalog, WORLD_ID, {})
        stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.rooms = RoomService(
            hub=self.hub,
            profiles=self.profiles,
            world_state=self.world_state,
            connections=FakeConnections(),
            card_service=cards,
            activities=ActivityService(SimpleNamespace(features=frozenset())),
            world=self.world,
            stats=stats,
            room_effects=self.room_effects,
        )

    def _portal(self, account) -> dict[str, object]:
        snapshot = asyncio.run(self.rooms.build_snapshot(account, "hub"))
        return next(entry for entry in snapshot["props"] if entry["id"] == "portal0")

    def test_snapshot_carries_effects_and_runtime_switch(self) -> None:
        account = self.create_account("ada")
        definition = self.world.props["portal"]
        default = definition.active_effect
        other = next(name for name in definition.effect_sets if name != default)
        portal = self._portal(account)
        self.assertEqual(portal["active_effect"], default)
        self.assertTrue(portal["effect_sets"][default])
        self.assertTrue(portal["effect_sets"][other])

        event = self.rooms.set_prop_active_effect("hub", "portal0", other)
        self.assertEqual(event["type"], "room.prop.updated")
        self.assertEqual(event["prop"], {"id": "portal0", "active_effect": other})
        self.assertEqual(self._portal(account)["active_effect"], other)

        with self.assertRaises(ValueError):
            self.rooms.set_prop_active_effect("hub", "portal0", "missing")
        with self.assertRaises(ValueError):
            self.rooms.set_prop_active_effect("hub", "welcome-plant", "idle")


if __name__ == "__main__":
    unittest.main()
