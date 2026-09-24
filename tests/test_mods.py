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


def _mods_path_config(mods_path: Path, mods: str, workspace: Path):
    return load_config(
        env={
            "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "invite",
            "TRSERVER_USERS_PATH": str(workspace / "users"),
            "TRSERVER_WORLDSTATE_PATH": str(workspace / "world.sqlite3"),
            "TRSERVER_WORLD_PATH": str(REPO_ROOT / "worlds" / "tutorial"),
            "TRSERVER_MODS": mods,
            "TRSERVER_MODS_PATH": str(mods_path),
            "TRSERVER_TIMEZONE": "UTC",
            "TRSERVER_HOST": "127.0.0.1",
            "TRSERVER_PORT": "5000",
        },
        repo_root=REPO_ROOT,
    )


class ModConfigTests(unittest.TestCase):
    """``TRSERVER_MODS`` parsing and validation."""

    def test_parse_mods_accepts_names_and_wildcard(self) -> None:
        self.assertEqual(parse_mods("infinite-bedrooms"), frozenset({"infinite-bedrooms"}))
        self.assertEqual(parse_mods("*"), frozenset({"*"}))
        with self.assertRaises(ConfigError):
            parse_mods("Bad Name")

    def test_invalid_mod_configuration_is_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            _config(TRSERVER_MODS="infinite-bedrooms", TRSERVER_MODS_PATH=str(REPO_ROOT / "nope"))
        with self.assertRaises(ConfigError):
            resolve_mods(_config(TRSERVER_MODS="does-not-exist"))


class ModDiscoveryTests(unittest.TestCase):
    """Manifest discovery, resolution, and Python entrypoint loading."""

    def _write_mod(self, mods_path: Path, mod_id: str, manifest: str) -> None:
        folder = mods_path / mod_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "mod.yaml").write_text(manifest, encoding="utf-8")

    def test_discover_and_resolve_wildcard(self) -> None:
        available = discover_mods(MODS_PATH)
        self.assertIn("infinite-bedrooms", available)
        resolved = resolve_mods(_config(TRSERVER_MODS="*"))
        self.assertEqual({mod.id for mod in resolved}, {"infinite-bedrooms"})

    def test_resolve_pulls_in_transitive_requires_in_dependency_order(self) -> None:
        with TemporaryDirectory() as temporary_directory, TemporaryDirectory() as other:
            mods_path = Path(temporary_directory) / "mods"
            self._write_mod(mods_path, "alpha", "id: alpha\nlabel: alpha\nrequires: [beta]\n")
            self._write_mod(mods_path, "beta", "id: beta\nlabel: beta\nrequires: []\n")
            config = _mods_path_config(mods_path, "alpha", Path(other))
            self.assertEqual([mod.id for mod in resolve_mods(config)], ["beta", "alpha"])

    def test_explicit_missing_entrypoint_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory, TemporaryDirectory() as other:
            mods_path = Path(temporary_directory) / "mods"
            self._write_mod(mods_path, "bad", "id: bad\nlabel: bad\nentrypoint: nope.py\n")
            config = _mods_path_config(mods_path, "bad", Path(other))
            with self.assertRaises(ConfigError):
                load_mods(config)

    def test_entrypoint_registers_command_and_state(self) -> None:
        mod = discover_mods(MODS_PATH)["infinite-bedrooms"]
        module = load_mod_module(mod)
        api = ModAPI(mod)
        module.register(api)
        self.assertIn("door", [spec["name"] for spec in api.commands])
        self.assertGreaterEqual(len(api.state_factories), 1)

    def test_command_registry_rejects_duplicate_names(self) -> None:
        from server.commands.registry import CommandRegistry

        async def handler(context, command):
            return None

        registry = CommandRegistry()
        registry.register("go", "first", handler)
        with self.assertRaises(ValueError):
            registry.register("go", "second", handler)

    def test_load_mods_returns_definitions_and_apis(self) -> None:
        loaded = load_mods(_config(TRSERVER_MODS="infinite-bedrooms"))
        self.assertEqual(loaded.ids, frozenset({"infinite-bedrooms"}))
        self.assertIn("door", [spec["name"] for spec in loaded.command_specs()])
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
