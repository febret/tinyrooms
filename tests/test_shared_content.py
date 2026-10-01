"""Shared content roots override version-bundled cards and propsets."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from server.config import KNOWN_FEATURES
from server.content.cards import ContentError, cutscene_card_references, load_card_catalog
from server.content.worlds import load_world_definition
from tests.common import (
    REPO_ROOT,
    load_world_activities,
    load_world_cutscene_roots,
    load_world_cutscenes,
    load_world_mod_props,
)


def _write_card_set(root: Path, cardset: str, card_id: str, label: str) -> None:
    directory = root / cardset
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "art.png").write_bytes(b"png")
    (directory / "cards.yaml").write_text(
        f"{card_id}:\n  label: {label}\n  description: test\n  image: art.png\n",
        encoding="utf-8",
    )


def _write_propset(root: Path, propset: str, prop_id: str, label: str) -> None:
    directory = root / propset
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "model.glb").write_bytes(b"glTF")
    (directory / "props.yaml").write_text(
        f"{prop_id}:\n  label: {label}\n  model: model.glb\n  decorative: true\n",
        encoding="utf-8",
    )


class SharedCardOverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.empty_world = self.root / "empty-world"
        self.empty_world.mkdir()

    def test_shared_root_overrides_bundled(self) -> None:
        bundled = self.root / "bundled"
        shared = self.root / "shared"
        _write_card_set(bundled, "set", "test-card", "Bundled")
        _write_card_set(shared, "set", "test-card", "Shared")
        catalog = load_card_catalog(bundled, self.empty_world, extra_cardsets_roots=(shared,))
        self.assertEqual(catalog.cards["test-card"].label, "Shared")

    def test_duplicate_within_one_root_still_errors(self) -> None:
        bundled = self.root / "bundled"
        _write_card_set(bundled, "set-a", "test-card", "A")
        _write_card_set(bundled, "set-b", "test-card", "B")
        with self.assertRaises(ContentError):
            load_card_catalog(bundled, self.empty_world)


class SharedPropsetOverrideTests(unittest.TestCase):
    def _load(self, bundled: tuple[Path, ...], shared: Path):
        catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", REPO_ROOT / "worlds" / "tutorial")
        return load_world_definition(
            REPO_ROOT / "worlds" / "tutorial",
            set(catalog.cards),
            core_activities=load_world_activities(),
            core_cutscenes=load_world_cutscenes(),
            cutscene_cards=cutscene_card_references(catalog),
            cutscene_roots=load_world_cutscene_roots(),
            known_features=KNOWN_FEATURES,
            propsets_root=bundled,
            shared_propsets_root=shared,
            mod_props=load_world_mod_props(),
        )

    def test_shared_propset_overrides_bundled(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundled = root / "bundled"
            shared = root / "shared"
            _write_propset(bundled, "extra", "shared-test-prop", "Bundled")
            _write_propset(shared, "extra", "shared-test-prop", "Shared")
            world = self._load((REPO_ROOT / "data" / "propsets", bundled), shared)
            self.assertEqual(world.props["shared-test-prop"].label, "Shared")


if __name__ == "__main__":
    unittest.main()
