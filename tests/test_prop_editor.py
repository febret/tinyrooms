"""Prop Editor service and HTTP coverage."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import os
import shutil
from tempfile import TemporaryDirectory
import unittest

import yaml

from server.config import KNOWN_FEATURES, load_config
from server.content.worlds import load_world_definition
from server.mods import load_mods
from server.services.audit import AuditService
from server.services.prop_editor import (
    PropEditorNotFound,
    PropEditorService,
    PropEditorValidationError,
)
from tests.common import (
    REPO_ROOT,
    ServiceTestCase,
    load_world_activities,
)
from tests.test_milestone1 import RuntimeTestCase, auth_cookies, auth_headers


WORLD_COPY_NAME = "tutorial"


def _link_or_copy(source: str, destination: str) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _copy_world(destination: Path) -> Path:
    if not destination.is_dir():
        shutil.copytree(REPO_ROOT / "worlds" / "tutorial", destination, copy_function=_link_or_copy)
    return destination


def _write_propset(root: Path) -> None:
    """Create a small, isolated propset so propset saves never touch the repo."""

    directory = root / "testsuite"
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "worlds" / "tutorial" / "props" / "plant.glb", directory / "plant.glb")
    payload = {
        "CONFIG": {"scale_adjust": 2.0},
        "testsuite-plant": {
            "label": "Testset Plant",
            "description": "A test plant.",
            "model": "plant.glb",
            "decorative": True,
            "editable": True,
            "scale": 1.5,
            "tags": ["plant", "test"],
            "effects": {"idle": ["smoke"]},
            "active_effect": "idle",
        },
    }
    (directory / "props.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


class PropEditorServiceTestCase(ServiceTestCase):
    """Provide an isolated world, propset, mod, and fx tree plus the service."""

    def setUp(self) -> None:
        super().setUp()
        root = Path(self.temporary_directory.name)
        self.world_root = _copy_world(root / WORLD_COPY_NAME)
        self.propsets_root = root / "propsets"
        _write_propset(self.propsets_root)
        self.mods_root = root / "mods"
        shutil.copytree(REPO_ROOT / "mods" / "infinite-bedrooms", self.mods_root / "infinite-bedrooms")
        self.fx_root = root / "fx"
        shutil.copytree(REPO_ROOT / "data" / "fx", self.fx_root)

        self.config = replace(
            load_config(
                env={
                    "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "open-sesame",
                    "TRSERVER_USERS_PATH": str(root / "users"),
                    "TRSERVER_WORLD_PATH": str(self.world_root),
                    "TRSERVER_WORLDSTATE_PATH": str(root / "worldstate.sqlite3"),
                    "TRSERVER_PROPSETS_PATH": str(self.propsets_root),
                    "TRSERVER_FX_PATH": str(self.fx_root),
                    "TRSERVER_FEATURES": "prop-editor",
                    "TRSERVER_MODS": "infinite-bedrooms",
                    "TRSERVER_MODS_PATH": str(self.mods_root),
                    "TRSERVER_TIMEZONE": "UTC",
                },
                repo_root=REPO_ROOT,
            ),
            local_path=root,
            drafts_path=root / "drafts",
            revisions_path=root / "revisions",
        )
        self.loaded_mods = load_mods(self.config)
        self.world = load_world_definition(
            self.world_root,
            set(self.catalog.cards),
            core_activities=load_world_activities(),
            known_features=KNOWN_FEATURES,
            propsets_root=self.propsets_root,
            mod_props=self.loaded_mods.mod_props(),
            enabled_mods=self.loaded_mods.ids,
            fx_root=self.fx_root,
        )
        self.audit = AuditService(self.hub, self.world.id)
        self.service = PropEditorService(self.config, self.loaded_mods, self.audit)

    def props_file(self, kind: str, source: str) -> Path:
        if kind == "world":
            return self.world_root / "props" / "props.yaml"
        if kind == "mod":
            return self.mods_root / source / "props" / "props.yaml"
        return self.propsets_root / source / "props.yaml"

    def read_props(self, kind: str, source: str) -> dict:
        return yaml.safe_load(self.props_file(kind, source).read_text(encoding="utf-8"))


class CatalogTests(PropEditorServiceTestCase):
    """The catalog exposes every source and the effect metadata."""

    def test_catalog_lists_world_mod_and_propset_props(self) -> None:
        catalog = self.service.catalog(self.world)
        by_id = {prop["id"]: prop for prop in catalog["props"]}
        self.assertEqual(by_id["plant"]["source_kind"], "world")
        self.assertEqual(by_id["archway"]["source_kind"], "mod")
        self.assertEqual(by_id["testsuite-plant"]["source_kind"], "propset")
        self.assertEqual(by_id["testsuite-plant"]["source"], "testsuite")
        self.assertIn("smoke", {effect["id"] for effect in catalog["effects"]})
        self.assertIn("plant", catalog["tags"])
        self.assertIn("transform_motions", catalog["enums"])

    def test_catalog_reports_hidden_flag(self) -> None:
        definition = self.world.props["testsuite-plant"]
        world = replace(
            self.world,
            props={**self.world.props, "testsuite-plant": replace(definition, hidden=True)},
        )
        catalog = self.service.catalog(world)
        entry = next(prop for prop in catalog["props"] if prop["id"] == "testsuite-plant")
        self.assertTrue(entry["hidden"])

    def test_source_descriptor_reports_models_and_scale_adjust(self) -> None:
        catalog = self.service.catalog(self.world)
        sources = {(entry["kind"], entry["source"]): entry for entry in catalog["sources"]}
        propset = sources[("propset", "testsuite")]
        self.assertIn("plant.glb", propset["models"])
        self.assertEqual(propset["scale_adjust"], 2.0)
        self.assertEqual(propset["file"], "propset/testsuite/props.yaml")


class PropReadWriteTests(PropEditorServiceTestCase):
    """Prop reads, writes, validation, backups, and isolation."""

    def test_load_prop_returns_raw_definition_and_file_context(self) -> None:
        payload = self.service.load_prop(self.world, "propset", "testsuite", "testsuite-plant")
        raw = payload["prop"]["raw"]
        self.assertEqual(raw["label"], "Testset Plant")
        self.assertEqual(raw["tags"], ["plant", "test"])
        self.assertEqual(payload["prop"]["scale"], 3.0)
        self.assertIn("plant.glb", payload["file"]["models"])
        self.assertEqual(payload["file"]["scale_adjust"], 2.0)

    def test_save_prop_round_trip_preserves_siblings_and_config(self) -> None:
        before = self.read_props("propset", "testsuite")
        raw = dict(before["testsuite-plant"])
        raw["label"] = "Renamed Plant"
        raw["description"] = "Updated."
        result = self.service.save_prop(
            self.world,
            "propset",
            "testsuite",
            "testsuite-plant",
            raw,
            actor_id="test-actor",
        )
        after = self.read_props("propset", "testsuite")
        self.assertEqual(after["testsuite-plant"]["label"], "Renamed Plant")
        self.assertEqual(after["CONFIG"]["scale_adjust"], 2.0)
        self.assertEqual(result["prop"]["raw"]["description"], "Updated.")

    def test_save_world_prop_touches_only_the_world_copy(self) -> None:
        before = (REPO_ROOT / "worlds" / "tutorial" / "props" / "props.yaml").read_bytes()
        raw = self.service.load_prop(self.world, "world", self.world.id, "plant")["prop"]["raw"]
        raw = dict(raw)
        raw["label"] = "World Plant"
        self.service.save_prop(self.world, "world", self.world.id, "plant", raw, actor_id="test-actor")
        self.assertEqual(self.read_props("world", self.world.id)["plant"]["label"], "World Plant")
        self.assertEqual((REPO_ROOT / "worlds" / "tutorial" / "props" / "props.yaml").read_bytes(), before)

    def test_save_prop_rejects_unknown_effect_and_leaves_file_untouched(self) -> None:
        before = self.props_file("propset", "testsuite").read_bytes()
        raw = dict(self.read_props("propset", "testsuite")["testsuite-plant"])
        raw["effects"] = {"idle": ["does-not-exist"]}
        with self.assertRaises(PropEditorValidationError):
            self.service.save_prop(self.world, "propset", "testsuite", "testsuite-plant", raw, actor_id="a")
        self.assertEqual(self.props_file("propset", "testsuite").read_bytes(), before)

    def test_unknown_source_is_rejected(self) -> None:
        with self.assertRaises(PropEditorNotFound):
            self.service.load_prop(self.world, "propset", "nope", "testsuite-plant")
        with self.assertRaises(PropEditorNotFound):
            self.service.load_prop(self.world, "mod", "not-a-mod", "archway")

    def test_scale_adjust_override_rewrites_config(self) -> None:
        raw = dict(self.read_props("propset", "testsuite")["testsuite-plant"])
        result = self.service.save_prop(
            self.world,
            "propset",
            "testsuite",
            "testsuite-plant",
            raw,
            scale_adjust=3.0,
            actor_id="a",
        )
        self.assertEqual(self.read_props("propset", "testsuite")["CONFIG"]["scale_adjust"], 3.0)
        self.assertEqual(result["prop"]["scale"], 4.5)

    def test_save_prop_round_trips_hidden_flag(self) -> None:
        raw = dict(self.read_props("propset", "testsuite")["testsuite-plant"])
        raw["hidden"] = True
        self.service.save_prop(self.world, "propset", "testsuite", "testsuite-plant", raw, actor_id="a")
        self.assertTrue(self.read_props("propset", "testsuite")["testsuite-plant"]["hidden"])


class EffectReadWriteTests(PropEditorServiceTestCase):
    """Effect layer reads, writes, and validation."""

    def test_load_effect_returns_layers_and_enums(self) -> None:
        payload = self.service.load_effect("smoke")
        self.assertEqual(payload["effect"]["id"], "smoke")
        self.assertEqual(payload["effect"]["raw"]["layers"][0]["type"], "particle")
        self.assertIn("smoke-puff.png", payload["enums"]["textures"])

    def test_save_effect_round_trip(self) -> None:
        raw = dict(self.service.load_effect("smoke")["effect"]["raw"])
        raw["label"] = "Heavy Smoke"
        raw["layers"] = [dict(raw["layers"][0])]
        raw["layers"][0]["rate"] = 9
        self.service.save_effect("smoke", raw, actor_id="a")
        after = yaml.safe_load((self.fx_root / "smoke.yaml").read_text(encoding="utf-8"))
        self.assertEqual(after["label"], "Heavy Smoke")
        self.assertEqual(after["layers"][0]["rate"], 9)

    def test_save_effect_rejects_unknown_texture(self) -> None:
        raw = dict(self.service.load_effect("smoke")["effect"]["raw"])
        raw["layers"] = [dict(raw["layers"][0])]
        raw["layers"][0]["texture"] = "missing.png"
        with self.assertRaises(PropEditorValidationError):
            self.service.save_effect("smoke", raw, actor_id="a")

    def test_save_effect_forces_filename_id(self) -> None:
        raw = dict(self.service.load_effect("smoke")["effect"]["raw"])
        raw["id"] = "other"
        self.service.save_effect("smoke", raw, actor_id="a")
        after = yaml.safe_load((self.fx_root / "smoke.yaml").read_text(encoding="utf-8"))
        self.assertEqual(after["id"], "smoke")


class PropEditorHttpTests(RuntimeTestCase):
    """HTTP route gating, round trips, and reload."""

    features = "prop-editor"

    def setUp(self) -> None:
        self._world_directory = TemporaryDirectory()
        self.addCleanup(self._world_directory.cleanup)
        self.world_path = _copy_world(Path(self._world_directory.name) / WORLD_COPY_NAME)
        super().setUp()

    def _runtime(self):
        return self.app.state.runtime

    def _admin(self, username: str = "siteadmin") -> dict[str, str]:
        credentials = self.create_ready_account(username)
        runtime = self._runtime()
        account = runtime.profiles.get_account_by_username(username)
        runtime.powers.grant(account.id, account.id, "admin")
        return credentials

    def test_editor_requires_admin_power(self) -> None:
        credentials = self.create_ready_account("plain")
        cookies = auth_cookies(credentials["session_token"], credentials["csrf_token"])
        self.assertEqual(self.client.get("/api/prop-editor/catalog", cookies=cookies).status_code, 403)
        self.assertEqual(self.client.get("/prop-editor/", cookies=cookies).status_code, 403)

    def test_catalog_prop_round_trip_and_reload(self) -> None:
        credentials = self._admin()
        cookies = auth_cookies(credentials["session_token"], credentials["csrf_token"])
        headers = auth_headers(credentials["csrf_token"])

        catalog = self.client.get("/api/prop-editor/catalog", cookies=cookies)
        self.assertEqual(catalog.status_code, 200, catalog.text)
        props = {prop["id"]: prop for prop in catalog.json()["catalog"]["props"]}
        self.assertIn("plant", props)

        loaded = self.client.get(
            "/api/prop-editor/prop",
            params={"kind": "world", "source": WORLD_COPY_NAME, "prop_id": "plant"},
            cookies=cookies,
        )
        self.assertEqual(loaded.status_code, 200, loaded.text)
        raw = loaded.json()["prop"]["raw"]
        raw["label"] = "HTTP Plant"

        saved = self.client.put(
            "/api/prop-editor/prop",
            json={"kind": "world", "source": WORLD_COPY_NAME, "prop_id": "plant", "prop": raw},
            cookies=cookies,
            headers=headers,
        )
        self.assertEqual(saved.status_code, 200, saved.text)

        reload_response = self.client.post("/api/prop-editor/reload", cookies=cookies, headers=headers)
        self.assertEqual(reload_response.status_code, 200, reload_response.text)
        self.assertEqual(self._runtime().world.props["plant"].label, "HTTP Plant")

    def test_effect_endpoints_are_readable(self) -> None:
        credentials = self._admin("admin3")
        cookies = auth_cookies(credentials["session_token"], credentials["csrf_token"])
        effects = self.client.get("/api/prop-editor/effects", cookies=cookies)
        self.assertEqual(effects.status_code, 200, effects.text)
        self.assertIn("smoke", {effect["id"] for effect in effects.json()["effects"]})
        one = self.client.get("/api/prop-editor/effect", params={"effect_id": "smoke"}, cookies=cookies)
        self.assertEqual(one.status_code, 200, one.text)


if __name__ == "__main__":
    unittest.main()
