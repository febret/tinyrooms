"""Build, protocol, and schema version helpers shared across servers."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from server.protocol import PROTOCOL_VERSION
from server.state.migrations import PROFILE_SCHEMA_VERSION, WORLD_SCHEMA_VERSION


REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / "version.json"


class VersionFileError(RuntimeError):
    """Raised when the build version cannot be read from ``version.json``."""


def latest_build_version(version_file: Path = VERSION_FILE) -> str:
    """Return the highest ``major.minor.patch`` label recorded in *version_file*."""

    try:
        entries = json.loads(version_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise VersionFileError(f"Unable to read build version from {version_file}: {error}") from error
    if not isinstance(entries, list) or not entries:
        raise VersionFileError(f"{version_file} contains no version entries.")
    try:
        latest = max(entries, key=lambda entry: (int(entry["major"]), int(entry["minor"]), int(entry["patch"])))
    except (KeyError, TypeError, ValueError) as error:
        raise VersionFileError(f"{version_file} contains an invalid version entry: {error}") from error
    return f"{int(latest['major'])}.{int(latest['minor'])}.{int(latest['patch'])}"


def _load_build_version() -> str:
    """Return the recorded build version, falling back when it is unavailable.

    A missing or malformed ``version.json`` must not prevent the server from
    importing; deployments that ship without the file still boot, reporting an
    unknown ``0.0.0`` build.
    """

    try:
        return latest_build_version()
    except VersionFileError:
        return "0.0.0"


BUILD_VERSION = _load_build_version()


def schema_versions() -> dict[str, int]:
    """Return the profile and world schema versions supported by this build."""

    return {"profile": PROFILE_SCHEMA_VERSION, "world": WORLD_SCHEMA_VERSION}


def git_describe(path: Path) -> str | None:
    """Return ``git describe`` output for *path*, or None when unavailable."""

    try:
        result = subprocess.run(
            ["git", "-C", str(path), "describe", "--tags", "--always", "--dirty"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = result.stdout.strip()
    return text or None


def version_info(path: Path) -> dict[str, object]:
    """Return build/protocol/schema/commit metadata for a checkout or package.

    The build label is read from *path*'s own ``version.json`` when present so
    that additional installed checkouts report their own version rather than the
    running build.
    """

    try:
        build = latest_build_version(path / "version.json")
    except VersionFileError:
        build = BUILD_VERSION
    return {
        "build": build,
        "protocol": PROTOCOL_VERSION,
        "commit": git_describe(path),
        "schema": schema_versions(),
    }
