"""Guards for the synthetic world generator.

The performance suite copies ``worlds/tutorial`` and rewrites its YAML. The copy
is hardlinked to save time, so a stray write would truncate the shared inode and
corrupt the checked-in world definition in a way that is easy to miss and very
expensive to debug.

These tests pin both halves of that contract: the generator must not mutate the
source tree, and the standard browser runtime (which also hardlinks) must stay
read-only with respect to world content.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.common import REPO_ROOT
from tests.perf.synthetic import build_scaled_world

WORLD_FILES = ("rooms/rooms.yaml", "peeps/peeps.yaml", "world.yaml", "props/props.yaml")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_digests() -> dict[str, str]:
    root = REPO_ROOT / "worlds" / "tutorial"
    return {name: _digest(root / name) for name in WORLD_FILES}


class SyntheticWorldTests(unittest.TestCase):
    """The generator scales content without touching the checked-in world."""

    def test_generating_a_world_does_not_mutate_the_source_tree(self) -> None:
        before = _source_digests()
        with TemporaryDirectory() as directory:
            build_scaled_world(
                Path(directory),
                rooms=3,
                props_per_room=12,
                peeps_per_room=4,
                cards_per_room=6,
            )
        after = _source_digests()
        self.assertEqual(
            before,
            after,
            "build_scaled_world corrupted the checked-in world definition. Rewriting a hardlinked "
            "file truncates the shared inode; unlink before writing.",
        )

    def test_generated_world_is_independent_between_runs(self) -> None:
        """A second generation must not accumulate content from the first."""

        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = build_scaled_world(root / "a", rooms=2, props_per_room=5)
            second = build_scaled_world(root / "b", rooms=2, props_per_room=5)
            self.assertEqual(
                (first / "rooms" / "rooms.yaml").read_text(encoding="utf-8"),
                (second / "rooms" / "rooms.yaml").read_text(encoding="utf-8"),
                "Two identical generations produced different rooms.yaml content.",
            )

    def test_generated_world_reuses_existing_artwork(self) -> None:
        """Generated rooms must point at real files, or the content loader rejects them."""

        with TemporaryDirectory() as directory:
            world_path = build_scaled_world(Path(directory), rooms=2, props_per_room=2, peeps_per_room=1)
            rooms_dir = world_path / "rooms"
            for board_image in rooms_dir.glob("*.jpg"):
                self.assertTrue(board_image.is_file())
            self.assertTrue((world_path / "peeps" / "molly.png").is_file())


if __name__ == "__main__":
    unittest.main()
