from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import threading

import yaml
from werkzeug.security import generate_password_hash, check_password_hash


DATA_ROOT = Path(__file__).parent.parent / "data"
USERS_ROOT = DATA_ROOT / "users"
SUPPORTED_SPRITE_EXTENSIONS = (".png", ".gif")

DEFAULT_WORLD_ID = "home"
DEFAULT_SPAWN_X = 32
DEFAULT_SPAWN_Y = 32


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


# ---------------------------------------------------------------------------
# User profile (auth + game state + powers) stored in profile.yaml
# ---------------------------------------------------------------------------

def profile_yaml_path(username: str) -> Path:
    return user_root(username) / "profile.yaml"


def _default_profile() -> dict[str, Any]:
    return {
        "version": 1,
        "password_hash": "",
        "skin": "base",
        "last_world_id": DEFAULT_WORLD_ID,
        "last_room_id": "",
        "last_x": DEFAULT_SPAWN_X,
        "last_y": DEFAULT_SPAWN_Y,
        "powers": [],
        "updated_at": _now_iso(),
    }


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def read_profile(username: str) -> dict[str, Any] | None:
    """Read profile from disk."""
    path = profile_yaml_path(username)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    profile = _default_profile()
    if isinstance(loaded, dict):
        for key in ("password_hash", "skin", "last_world_id", "last_room_id", "updated_at"):
            if key in loaded and isinstance(loaded[key], str):
                profile[key] = loaded[key]
        for key in ("last_x", "last_y"):
            if key in loaded:
                profile[key] = _coerce_int(loaded[key], profile[key])
        if "powers" in loaded and isinstance(loaded["powers"], list):
            profile["powers"] = [str(p) for p in loaded["powers"]]
        if "version" in loaded:
            profile["version"] = loaded["version"]
    return profile


def write_profile(
    username: str,
    password_hash: str | None = None,
    skin: str | None = None,
    last_world_id: str | None = None,
    last_room_id: str | None = None,
    last_x: int | None = None,
    last_y: int | None = None,
    powers: list[str] | None = None,
) -> dict[str, Any]:
    """Create or update a user profile.  Returns the final profile dict."""
    ensure_user_paths(username)
    current = read_profile(username) or _default_profile()
    if password_hash is not None:
        current["password_hash"] = password_hash
    if skin is not None:
        current["skin"] = skin
    if last_world_id is not None:
        current["last_world_id"] = last_world_id
    if last_room_id is not None:
        current["last_room_id"] = last_room_id
    if last_x is not None:
        current["last_x"] = int(last_x)
    if last_y is not None:
        current["last_y"] = int(last_y)
    if powers is not None:
        current["powers"] = list(powers)
    current["updated_at"] = _now_iso()
    path = profile_yaml_path(username)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(current, handle, sort_keys=False)
    return current


def create_user_profile(username: str, password_plain: str) -> bool:
    """Create a user profile with a hashed password.  Returns False if already exists."""
    if read_profile(username) is not None:
        return False
    password_hash = generate_password_hash(password_plain)
    write_profile(username, password_hash=password_hash)
    return True


def check_user_password(username: str, password_plain: str) -> bool:
    """Return True when the given password matches the stored hash."""
    profile = read_profile(username)
    if profile is None:
        return False
    return check_password_hash(profile.get("password_hash", ""), password_plain)


def save_user_state(user_obj: Any) -> None:
    """Persist a connected User's current state to their profile.yaml."""
    from_room = getattr(user_obj, "room", None)
    from_peep = getattr(user_obj, "peep", None)
    from_world = getattr(user_obj, "world", None)
    world_id = getattr(from_world, "ws_id", DEFAULT_WORLD_ID)
    room_id = from_room.room_id if from_room is not None else ""
    x = _coerce_int(getattr(from_peep, "x", DEFAULT_SPAWN_X), DEFAULT_SPAWN_X)
    y = _coerce_int(getattr(from_peep, "y", DEFAULT_SPAWN_Y), DEFAULT_SPAWN_Y)
    write_profile(
        user_obj.username,
        skin=getattr(user_obj, "skin", "base"),
        last_world_id=world_id,
        last_room_id=room_id,
        last_x=x,
        last_y=y,
    )


def save_all_user_states() -> None:
    """Save state of all currently connected users to their profile.yaml files."""
    from tinyrooms.user import connected_users
    if not connected_users:
        return
    for user_obj in connected_users.values():
        save_user_state(user_obj)
    print(f"Saved state for {len(connected_users)} connected users")
