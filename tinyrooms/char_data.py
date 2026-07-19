from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


DATA_ROOT = Path(__file__).parent.parent / "data"
USERS_ROOT = DATA_ROOT / "users"
SUPPORTED_SPRITE_EXTENSIONS = (".png", ".gif", ".svg")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_username(username: str) -> str:
    if not username or "/" in username or "\\" in username or ".." in username:
        raise ValueError("invalid username")
    return username


def user_root(username: str) -> Path:
    return USERS_ROOT / _validate_username(username)


def user_sprites_dir(username: str) -> Path:
    return user_root(username) / "sprites"


def user_tmp_dir(username: str) -> Path:
    return user_root(username) / "tmp"


def char_yaml_path(username: str) -> Path:
    return user_root(username) / "char.yaml"


def ensure_user_paths(username: str):
    root = user_root(username)
    sprites = user_sprites_dir(username)
    tmp = user_tmp_dir(username)
    root.mkdir(parents=True, exist_ok=True)
    sprites.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    return root, sprites, tmp


def _default_char(appearance_defaults: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "version": 1,
        "appearance": dict(appearance_defaults or {}),
        "current_sprite": None,
        "updated_at": _now_iso(),
    }


def read_char(username: str, appearance_defaults: dict[str, str] | None = None) -> dict[str, Any]:
    path = char_yaml_path(username)
    if not path.exists():
        return _default_char(appearance_defaults)

    with open(path, "r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    char = _default_char(appearance_defaults)
    if isinstance(loaded, dict):
        char["version"] = loaded.get("version", 1)
        appearance = loaded.get("appearance", {})
        if isinstance(appearance, dict):
            char["appearance"] = {**char["appearance"], **appearance}
        current_sprite = loaded.get("current_sprite")
        if isinstance(current_sprite, str) and current_sprite.strip():
            char["current_sprite"] = current_sprite
        updated_at = loaded.get("updated_at")
        if isinstance(updated_at, str) and updated_at.strip():
            char["updated_at"] = updated_at
    return char


_UNSET = object()


def write_char(
    username: str,
    appearance: dict[str, str] | None = None,
    current_sprite: str | None | object = _UNSET,
    appearance_defaults: dict[str, str] | None = None,
) -> dict[str, Any]:
    ensure_user_paths(username)
    current = read_char(username, appearance_defaults=appearance_defaults)
    new_char = {
        "version": 1,
        "appearance": dict(appearance if appearance is not None else current.get("appearance", {})),
        "current_sprite": current.get("current_sprite"),
        "updated_at": _now_iso(),
    }
    if current_sprite is not _UNSET:
        new_char["current_sprite"] = current_sprite

    path = char_yaml_path(username)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(new_char, handle, sort_keys=False)
    return new_char


def sprite_rel_path(sprite_id: str) -> str:
    if not sprite_id or "/" in sprite_id or "\\" in sprite_id:
        raise ValueError("invalid sprite id")
    return f"sprites/{sprite_id}"


def sprite_url(username: str, rel_path: str) -> str:
    rel = rel_path.replace("\\", "/").lstrip("/")
    return f"/user-assets/{_validate_username(username)}/{rel}"


def list_user_sprites(username: str) -> list[dict[str, str]]:
    sprites_dir = user_sprites_dir(username)
    if not sprites_dir.exists():
        return []
    out: list[dict[str, str]] = []
    sprite_paths = sorted(
        (
            p
            for p in sprites_dir.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_SPRITE_EXTENSIONS
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for sprite_path in sprite_paths:
        sprite_id = sprite_path.name
        rel = sprite_rel_path(sprite_id)
        out.append(
            {
                "sprite_id": sprite_id,
                "sprite_path": rel,
                "sprite_url": sprite_url(username, rel),
            }
        )
    return out
