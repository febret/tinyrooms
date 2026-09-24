"""Server mod system tests: config parsing, discovery, loading, world requirements."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from server.config import ConfigError, load_config, parse_mods
from server.content.worlds import ContentError, load_world_definition
from server.mods import (
    ModAPI,
    discover_mods,
    load_mod_activity_definitions,
    load_mod_module,
    load_mods,
    resolve_mods,
)
from tests.common import REPO_ROOT, load_world_activities, load_world_mod_props, load_world_propsets
from tests.test_milestone1 import RuntimeTestCase


MODS_PATH = REPO_ROOT / "mods"


def _config(**overrides):
    with TemporaryDirectory() as temporary_directory:
        env = {
            "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "invite",
            "TRSERVER_USERS_PATH": str(Path(temporary_directory) / "users"),
            "TRSERVER_WORLDSTATE_PATH": str(Path(temporary_directory) / "world.sqlite3"),
            "TRSERVER_WORLD_PATH": str(REPO_ROOT / "worlds" / "tutorial"),
            "TRSERVER_TIMEZONE": "UTC",
            "TRSERVER_HOST": "127.0.0.1",
            "TRSERVER_PORT": "5000",
        }
        env.update(overrides)
        return load_config(env=env, repo_root=REPO_ROOT)


class ModConfigTests(unittest.TestCase):
    """``TRSERVER_MODS`` parsing and validation."""

    def test_parse_mods_accepts_names_and_wildcard(self) -> None:
        self.assertEqual(parse_mods(""), frozenset())
        self.assertEqual(parse_mods("infinite-bedrooms"), frozenset({"infinite-bedrooms"}))
        self.assertEqual(parse_mods("a, b"), frozenset({"a", "b"}))
        self.assertEqual(parse_mods("*"), frozenset({"*"}))
        with self.assertRaises(ConfigError):
            parse_mods("Bad Name")

    def test_load_config_records_mods_and_path(self) -> None:
        config = _config(TRSERVER_MODS="infinite-bedrooms")
        self.assertEqual(config.mods, frozenset({"infinite-bedrooms"}))
        self.assertEqual(config.mods_path, MODS_PATH.resolve())

    def test_missing_mods_path_is_rejected_when_mods_requested(self) -> None:
        with self.assertRaises(ConfigError):
            _config(TRSERVER_MODS="infinite-bedrooms", TRSERVER_MODS_PATH=str(REPO_ROOT / "nope"))


class ModDiscoveryTests(unittest.TestCase):
    """Manifest discovery, resolution, and Python entrypoint loading."""

    def test_discover_and_resolve_wildcard(self) -> None:
        available = discover_mods(MODS_PATH)
        self.assertIn("infinite-bedrooms", available)
        resolved = resolve_mods(_config(TRSERVER_MODS="*"))
        self.assertEqual({mod.id for mod in resolved}, {"infinite-bedrooms"})

    def test_unknown_mod_is_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            resolve_mods(_config(TRSERVER_MODS="does-not-exist"))

    def test_resolve_pulls_in_transitive_requires(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            mods_path = Path(temporary_directory) / "mods"
            for mod_id, requires in (("alpha", "[beta]"), ("beta", "[]")):
                folder = mods_path / mod_id
                folder.mkdir(parents=True)
                (folder / "mod.yaml").write_text(
                    f"id: {mod_id}\nlabel: {mod_id}\nrequires: {requires}\n",
                    encoding="utf-8",
                )
            with TemporaryDirectory() as other:
                config = load_config(
                    env={
                        "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "invite",
                        "TRSERVER_USERS_PATH": str(Path(other) / "users"),
                        "TRSERVER_WORLDSTATE_PATH": str(Path(other) / "world.sqlite3"),
                        "TRSERVER_WORLD_PATH": str(REPO_ROOT / "worlds" / "tutorial"),
                        "TRSERVER_MODS": "alpha",
                        "TRSERVER_MODS_PATH": str(mods_path),
                        "TRSERVER_TIMEZONE": "UTC",
                        "TRSERVER_HOST": "127.0.0.1",
                        "TRSERVER_PORT": "5000",
                    },
                    repo_root=REPO_ROOT,
                )
            self.assertEqual({mod.id for mod in resolve_mods(config)}, {"alpha", "beta"})

    def test_entrypoint_registers_command_and_state(self) -> None:
        mod = discover_mods(MODS_PATH)["infinite-bedrooms"]
        module = load_mod_module(mod)
        self.assertTrue(callable(getattr(module, "register", None)))
        api = ModAPI(mod)
        module.register(api)
        self.assertEqual([spec["name"] for spec in api.commands], ["door"])
        self.assertEqual(len(api.state_factories), 1)

    def test_mod_activity_definitions_are_exposed(self) -> None:
        definitions = load_mod_activity_definitions(discover_mods(MODS_PATH).values())
        self.assertIn("bedrooms", definitions)
        self.assertTrue(definitions["bedrooms"].room_bound)

    def test_load_mods_returns_definitions_and_apis(self) -> None:
        loaded = load_mods(_config(TRSERVER_MODS="infinite-bedrooms"))
        self.assertEqual({mod.id for mod in loaded.definitions}, {"infinite-bedrooms"})
        self.assertEqual([spec["name"] for spec in loaded.command_specs()], ["door"])
        mod_props = loaded.mod_props()
        self.assertEqual(len(mod_props), 1)
        self.assertEqual(mod_props[0][0], "infinite-bedrooms")
        self.assertTrue((mod_props[0][1] / "props.yaml").is_file())
        self.assertIn("bedrooms", loaded.activity_definitions)


class WorldModRequirementTests(unittest.TestCase):
    """Worlds declare the mods they need through ``requires_mods``."""

    def _load(self, enabled_mods):
        from server.content.cards import load_card_catalog

        catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", REPO_ROOT / "worlds" / "tutorial")
        return load_world_definition(
            REPO_ROOT / "worlds" / "tutorial",
            set(catalog.cards),
            core_activities=load_world_activities(),
            propsets_root=load_world_propsets(),
            mod_props=load_world_mod_props(),
            enabled_mods=enabled_mods,
        )

    def test_tutorial_requires_infinite_bedrooms(self) -> None:
        with self.assertRaises(ContentError):
            self._load(frozenset())
        world = self._load(frozenset({"infinite-bedrooms"}))
        self.assertEqual(world.requires_mods, ("infinite-bedrooms",))


class ModServingTests(RuntimeTestCase):
    """The runtime serves mod activities and mod prop assets."""

    def test_mod_activity_and_assets_are_served(self) -> None:
        index = self.client.get("/activities/bedrooms/")
        self.assertEqual(index.status_code, 200)
        self.assertIn("The Bedrooms", index.text)
        script = self.client.get("/activities/bedrooms/bedrooms.js")
        self.assertEqual(script.status_code, 200)
        asset = self.client.get("/activities/bedrooms/assets/door-panel.svg")
        self.assertEqual(asset.status_code, 200)
        model = self.client.get("/assets/mods/infinite-bedrooms/props/archway.glb")
        self.assertEqual(model.status_code, 200)
