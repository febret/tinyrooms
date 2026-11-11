"""One-off recovery of version-local custom sticker PNGs into shared storage."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from server.mission_control.config import MCConfig
from server.services.stickers import CUSTOM_STICKER_PREFIX

LOGGER = logging.getLogger("tinyrooms.mc")


def legacy_candidate_dirs(config: MCConfig) -> list[Path]:
    """Return version-local sticker directories that predate shared storage."""

    candidates = [config.repo_root / ".local" / "stickers"]
    try:
        entries = list(config.versions_path.iterdir())
    except OSError:
        entries = []
    for child in entries:
        try:
            if child.is_dir():
                candidates.append(child / ".local" / "stickers")
        except OSError:
            continue
    seen: list[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.append(candidate)
    return seen


def _custom_users_dirs(config: MCConfig) -> list[Path]:
    """Return distinct non-shared users directories referenced by saved instances."""

    try:
        shared = config.users_path.resolve()
    except OSError:
        shared = config.users_path
    found: list[Path] = []
    try:
        identities = list(config.instances_path.glob("*/instance.json"))
    except OSError:
        return found
    for path in identities:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        spawn = data.get("spawn_config") if isinstance(data, dict) else None
        if not isinstance(spawn, dict):
            continue
        raw = spawn.get("users_path")
        if not raw:
            continue
        candidate = Path(str(raw)).expanduser()
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved == shared or candidate in found:
            continue
        if any(existing.resolve() == resolved for existing in found if existing.exists()):
            continue
        found.append(candidate)
    return found


def _copy_missing(sources: list[Path], dest: Path) -> int:
    copied = 0
    dest.mkdir(parents=True, exist_ok=True)
    for source in sources:
        try:
            if not source.is_dir() or source.resolve() == dest.resolve():
                continue
            files = sorted(source.glob(f"{CUSTOM_STICKER_PREFIX}*.png"))
        except OSError:
            continue
        for candidate in files:
            try:
                if not candidate.is_file():
                    continue
                target = dest / candidate.name
                if target.exists():
                    continue
                shutil.copy2(candidate, target)
                copied += 1
            except OSError:
                continue
    return copied


def migrate_legacy_custom_stickers(config: MCConfig) -> dict[str, int]:
    """Copy version-local ``custom-*.png`` files into shared storage.

    Existing files are never overwritten. Returns ``{"copied": n,
    "destinations": m}``. Failures are skipped so startup never blocks on
    this best-effort recovery.
    """

    sources = legacy_candidate_dirs(config)
    shared_dest = config.custom_stickers_path
    copied = _copy_missing(sources, shared_dest)
    destinations = 1
    for users_dir in _custom_users_dirs(config):
        target = users_dir / "stickers"
        try:
            if target.resolve() == shared_dest.resolve():
                continue
        except OSError:
            pass
        copied += _copy_missing([*sources, shared_dest], target)
        destinations += 1
    if copied:
        LOGGER.info(
            json.dumps({
                "event": "mc.stickers_migrated",
                "copied": copied,
                "destinations": destinations,
            })
        )
    return {"copied": copied, "destinations": destinations}
