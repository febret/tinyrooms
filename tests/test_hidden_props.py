"""Hidden prop flag: loading, filtering, and preservation across services."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import os
import shutil
import unittest

import yaml

from server.content.worlds import load_propset
from server.routes.world_editor import _catalog_payload
from server.services.environment import EnvironmentService
from server.services.ownership import OwnershipService
from server.services.prop_shop import PropShopService
from server.services.room_layout import RoomLayoutService
from server.state.world_state import WorldStateRepository
from tests.common import REPO_ROOT, ServiceTestCase, load_test_world


def _link_or_copy(source: str, destination: str) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _hidden(world, prop_id: str):
    """Return *world* with one prop definition flagged hidden."""

    props = dict(world.props)
    props[prop_id] = replace(props[prop_id], hidden=True)
    return replace(world, props=props)


class HiddenPropLoaderTests(ServiceTestCase):
    """The optional hidden flag parses and defaults to false."""

    def test_hidden_flag_parses_and_defaults(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            shutil.copy2(REPO_ROOT / "worlds" / "tutorial" / "props" / "plant.glb", root / "plant.glb")
            (root / "props.yaml").write_text(
                yaml.safe_dump(
                    {
                        "secret": {"label": "Secret", "model": "plant.glb", "hidden": True},
                        "visible": {"label": "Visible", "model": "plant.glb"},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            props = load_propset(root)
        self.assertTrue(props["secret"].hidden)
        self.assertFalse(props["visible"].hidden)


class HiddenRoomLayoutTests(ServiceTestCase):
    """Hidden props vanish from the room editor but survive layout saves."""

    def setUp(self) -> None:
        super().setUp()
        base = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        self.world = _hidden(base, "plant")
        self.world_state = WorldStateRepository(self.hub)
        self.world_state.initialize_world(self.world)
        self.ownership = OwnershipService(self.hub, self.profiles, self.world_state, self.world)
        self.environment = EnvironmentService(self.hub, self.world, self.world_state)
        self.prop_shop = PropShopService(self.hub, self.profiles, self.world)
        self.layout = RoomLayoutService(
            self.hub,
            self.world,
            self.world_state,
            self.ownership,
            self.environment,
            self.prop_shop,
        )
        self.owner = self.create_account("alice", room="hub")
        self.ownership.grant("hub", self.owner.id)

    def test_hidden_prop_is_absent_from_editor_library_and_instances(self) -> None:
        view = self.layout.view(self.owner, "hub")
        self.assertNotIn("plant", {entry["prop_id"] for entry in view["library"]})
        self.assertNotIn("welcome-plant", {entry["id"] for entry in view["props"]})
        self.assertNotIn("welcome-plant", {prop.id for prop in self.layout.effective_props("hub")})

    def test_saving_visible_layout_preserves_hidden_instances(self) -> None:
        base = self.layout.view(self.owner, "hub")["revision"]
        self.layout.save(self.owner, "hub", base, {"props": []})
        stored = self.world_state.read_room_layout("hub")["props"] or []
        self.assertIn("welcome-plant", {entry["id"] for entry in stored})


class HiddenPropShopTests(ServiceTestCase):
    """Hidden props are neither listed nor purchasable."""

    def setUp(self) -> None:
        super().setUp()
        self.world = _hidden(load_test_world(REPO_ROOT / "worlds" / "tutorial"), "mustard-armchair")
        self.shop = PropShopService(self.hub, self.profiles, self.world)

    def test_catalog_excludes_hidden_props(self) -> None:
        self.assertNotIn("mustard-armchair", {definition.id for definition in self.shop.catalog()})

    def test_purchase_rejects_hidden_props(self) -> None:
        account = self.create_account("buyer")
        with self.assertRaises(ValueError):
            self.shop.purchase(account, "mustard-armchair")


class HiddenWorldEditorTests(ServiceTestCase):
    """The World Editor prop catalog omits hidden props."""

    def test_catalog_payload_omits_hidden_props(self) -> None:
        world = _hidden(load_test_world(REPO_ROOT / "worlds" / "tutorial"), "plant")
        runtime = SimpleNamespace(
            world=world,
            cards=SimpleNamespace(serialize_definition=lambda definition: {"id": definition.id}),
            catalog=SimpleNamespace(cards={}),
        )
        payload = _catalog_payload(runtime)
        self.assertNotIn("plant", {prop["id"] for prop in payload["props"]})
        self.assertIn("dollhouse", {prop["id"] for prop in payload["props"]})


if __name__ == "__main__":
    unittest.main()
