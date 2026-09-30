"""Tests for the build-version helpers backed by version.json."""

from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from server.version import BUILD_VERSION, VERSION_FILE, VersionFileError, latest_build_version


class LatestBuildVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.version_file = Path(self._tmp.name) / "version.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, entries: object) -> None:
        self.version_file.write_text(json.dumps(entries), encoding="utf-8")

    def test_picks_highest_semver_regardless_of_order(self) -> None:
        self._write(
            [
                {"major": 0, "minor": 2, "patch": 0},
                {"major": 0, "minor": 10, "patch": 1},
                {"major": 1, "minor": 0, "patch": 0},
            ]
        )
        self.assertEqual(latest_build_version(self.version_file), "1.0.0")

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(VersionFileError):
            latest_build_version(Path(self._tmp.name) / "absent.json")

    def test_empty_list_raises(self) -> None:
        self._write([])
        with self.assertRaises(VersionFileError):
            latest_build_version(self.version_file)

    def test_malformed_json_raises(self) -> None:
        self.version_file.write_text("{not json", encoding="utf-8")
        with self.assertRaises(VersionFileError):
            latest_build_version(self.version_file)

    def test_invalid_entry_raises(self) -> None:
        self._write([{"major": 1, "minor": 0}])
        with self.assertRaises(VersionFileError):
            latest_build_version(self.version_file)


class RealVersionFileTests(unittest.TestCase):
    def test_build_version_matches_repository_version_file(self) -> None:
        self.assertEqual(BUILD_VERSION, latest_build_version(VERSION_FILE))
        self.assertRegex(BUILD_VERSION, re.compile(r"^\d+\.\d+\.\d+$"))


if __name__ == "__main__":
    unittest.main()
