"""Build, protocol, and schema version helpers shared across servers."""

from __future__ import annotations

from pathlib import Path
import subprocess

from server.protocol import PROTOCOL_VERSION
from server.state.migrations import PROFILE_SCHEMA_VERSION, WORLD_SCHEMA_VERSION


BUILD_VERSION = "1.0.0"


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
    """Return build/protocol/schema/commit metadata for a checkout or package."""

    return {
        "build": BUILD_VERSION,
        "protocol": PROTOCOL_VERSION,
        "commit": git_describe(path),
        "schema": schema_versions(),
    }
