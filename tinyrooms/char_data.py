from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


DATA_ROOT = Path(__file__).parent.parent / "data"
USERS_ROOT = DATA_ROOT / "users"
SUPPORTED_SPRITE_EXTENSIONS = (".png", ".gif")


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


def user_images_dir(username: str) -> Path:
    return user_root(username) / "images"


def user_tmp_dir(username: str) -> Path:
    return user_root(username) / "tmp"


def char_yaml_path(username: str) -> Path:
    return user_root(username) / "char.yaml"


def ensure_user_paths(username: str):
    root = user_root(username)
    sprites = user_sprites_dir(username)
    images = user_images_dir(username)
    tmp = user_tmp_dir(username)
    root.mkdir(parents=True, exist_ok=True)
    sprites.mkdir(parents=True, exist_ok=True)
    images.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    return root, sprites, images, tmp


def _default_char() -> dict[str, Any]:
    return {
        "version": 1,
        "description": "",
        "current_sprite": None,
        "main_image": None,
        "updated_at": _now_iso(),
    }


def read_char(username: str) -> dict[str, Any]:
    path = char_yaml_path(username)
    if not path.exists():
        return _default_char()

    with open(path, "r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    char = _default_char()
    if isinstance(loaded, dict):
        char["version"] = loaded.get("version", 1)
        description = loaded.get("description")
        if isinstance(description, str):
            char["description"] = description
        current_sprite = loaded.get("current_sprite")
        if isinstance(current_sprite, str) and current_sprite.strip():
            char["current_sprite"] = current_sprite
        main_image = loaded.get("main_image")
        if isinstance(main_image, str) and main_image.strip():
            char["main_image"] = main_image
        updated_at = loaded.get("updated_at")
        if isinstance(updated_at, str) and updated_at.strip():
            char["updated_at"] = updated_at
    return char


_UNSET = object()


def write_char(
    username: str,
    description: str | None = None,
    current_sprite: str | None | object = _UNSET,
    main_image: str | None | object = _UNSET,
) -> dict[str, Any]:
    ensure_user_paths(username)
    current = read_char(username)
    new_char = {
        "version": 1,
        "description": str(description if description is not None else current.get("description", "")),
        "current_sprite": current.get("current_sprite"),
        "main_image": current.get("main_image"),
        "updated_at": _now_iso(),
    }
    if current_sprite is not _UNSET:
        new_char["current_sprite"] = current_sprite
    if main_image is not _UNSET:
        new_char["main_image"] = main_image

    path = char_yaml_path(username)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(new_char, handle, sort_keys=False)
    return new_char


def sprite_rel_path(sprite_id: str) -> str:
    if not sprite_id or "/" in sprite_id or "\\" in sprite_id:
        raise ValueError("invalid sprite id")
    return f"sprites/{sprite_id}"


def sprite_url(username: str, rel_path: str) -> str:
    return user_asset_url(username, rel_path)


def user_asset_url(username: str, rel_path: str) -> str:
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
