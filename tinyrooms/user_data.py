from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import threading

import yaml
from werkzeug.security import generate_password_hash, check_password_hash

from tinyrooms import db as _db


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


DEFAULT_JUICE = 100.0
DEFAULT_JUICE_RATE = 5.0  # juice per minute
DEFAULT_STARTING_BOPS = 50  # bops given to brand-new accounts
CLIENT_COLOR_THEMES = ("default", "ocean", "sunset", "forest")


def _default_client_config() -> dict[str, Any]:
    return {
        "show_own_chat_decorators": True,
        "show_text_bubbles": True,
        "color_theme": "default",
    }


def normalize_client_config(raw: Any, base: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = _default_client_config()
    if isinstance(base, dict):
        if isinstance(base.get("show_own_chat_decorators"), bool):
            normalized["show_own_chat_decorators"] = base["show_own_chat_decorators"]
        if isinstance(base.get("show_text_bubbles"), bool):
            normalized["show_text_bubbles"] = base["show_text_bubbles"]
        theme_name = base.get("color_theme")
        if isinstance(theme_name, str) and theme_name in CLIENT_COLOR_THEMES:
            normalized["color_theme"] = theme_name
    if not isinstance(raw, dict):
        return normalized
    if isinstance(raw.get("show_own_chat_decorators"), bool):
        normalized["show_own_chat_decorators"] = raw["show_own_chat_decorators"]
    if isinstance(raw.get("show_text_bubbles"), bool):
        normalized["show_text_bubbles"] = raw["show_text_bubbles"]
    theme_name = raw.get("color_theme")
    if isinstance(theme_name, str) and theme_name in CLIENT_COLOR_THEMES:
        normalized["color_theme"] = theme_name
    return normalized


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
        # Gameplay fields
        "juice": DEFAULT_JUICE,
        "juice_last_tick": _now_iso(),
        "bops": DEFAULT_STARTING_BOPS,
        "traits": [],
        "client_config": _default_client_config(),
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
        for key in ("password_hash", "skin", "last_world_id", "last_room_id", "updated_at", "juice_last_tick"):
            if key in loaded and isinstance(loaded[key], str):
                profile[key] = loaded[key]
        for key in ("last_x", "last_y"):
            if key in loaded:
                profile[key] = _coerce_int(loaded[key], profile[key])
        if "powers" in loaded and isinstance(loaded["powers"], list):
            profile["powers"] = [str(p) for p in loaded["powers"]]
        if "version" in loaded:
            profile["version"] = loaded["version"]
        if "juice" in loaded:
            try:
                profile["juice"] = float(loaded["juice"])
            except (TypeError, ValueError):
                pass
        if "bops" in loaded:
            profile["bops"] = _coerce_int(loaded["bops"], 0)
        if "traits" in loaded and isinstance(loaded["traits"], list):
            profile["traits"] = [str(t) for t in loaded["traits"]]
        if "client_config" in loaded:
            profile["client_config"] = normalize_client_config(loaded["client_config"])
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
    juice: float | None = None,
    juice_last_tick: str | None = None,
    bops: int | None = None,
    traits: list[str] | None = None,
    client_config: dict[str, Any] | None = None,
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
    if juice is not None:
        current["juice"] = float(juice)
    if juice_last_tick is not None:
        current["juice_last_tick"] = juice_last_tick
    if bops is not None:
        current["bops"] = int(bops)
    if traits is not None:
        current["traits"] = list(traits)
    if client_config is not None:
        current["client_config"] = normalize_client_config(client_config, base=current.get("client_config"))
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
    """Persist a connected User's current state to their profile.yaml and worldstate DB."""
    from_room = getattr(user_obj, "room", None)
    from_peep = getattr(user_obj, "peep", None)
    from_world = getattr(user_obj, "world", None)
    world_id = getattr(from_world, "ws_id", DEFAULT_WORLD_ID)
    room_id = from_room.room_id if from_room is not None else ""
    x = _coerce_int(getattr(from_peep, "x", DEFAULT_SPAWN_X), DEFAULT_SPAWN_X)
    y = _coerce_int(getattr(from_peep, "y", DEFAULT_SPAWN_Y), DEFAULT_SPAWN_Y)

    # Safely extract gameplay fields; ignore if values are not the expected type
    def _safe_float(attr):
        v = getattr(user_obj, attr, None)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _safe_int(attr):
        v = getattr(user_obj, attr, None)
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _safe_str(attr):
        v = getattr(user_obj, attr, None)
        return v if isinstance(v, str) else None

    def _safe_list(attr):
        v = getattr(user_obj, attr, None)
        return v if isinstance(v, list) else None

    write_profile(
        user_obj.username,
        skin=getattr(user_obj, "skin", "base") if isinstance(getattr(user_obj, "skin", None), str) else None,
        last_world_id=world_id if isinstance(world_id, str) else None,
        last_room_id=room_id if isinstance(room_id, str) else None,
        last_x=x,
        last_y=y,
        juice=_safe_float("juice"),
        juice_last_tick=_safe_str("juice_last_tick"),
        bops=_safe_int("bops"),
        traits=_safe_list("traits"),
        client_config=(
            getattr(user_obj, "client_config", None)
            if isinstance(getattr(user_obj, "client_config", None), dict)
            else None
        ),
    )
    # Persist user peep vibes to worldstate DB
    if from_peep is not None:
        try:
            vibes = getattr(from_peep, "vibes", {}) or {}
            with _db.get_worldstate_connection(world_id) as wsdb:
                _db.write_peep_data(wsdb, {user_obj.username: from_peep})
        except Exception as exc:
            print(f"save_user_state: could not persist vibes for '{user_obj.username}': {exc}")


def save_all_user_states() -> None:
    """Save state of all currently connected users to their profile.yaml files."""
    from tinyrooms.user import connected_users
    if not connected_users:
        return
    for user_obj in connected_users.values():
        save_user_state(user_obj)
    print(f"Saved state for {len(connected_users)} connected users")


# ---------------------------------------------------------------------------
# Per-user kudos state stored in kudos.yaml
# ---------------------------------------------------------------------------

DAILY_KUDOS_BUDGET = 5  # kudos a user may give per day


def kudos_yaml_path(username: str) -> Path:
    return user_root(username) / "kudos.yaml"


def _default_kudos() -> dict[str, Any]:
    return {
        "version": 1,
        "total_received": 0,
        "total_given_all_time": 0,
        "daily_given_budget": DAILY_KUDOS_BUDGET,
        "daily_given_remaining": DAILY_KUDOS_BUDGET,
        "last_daily_reset": _now_iso()[:10],  # YYYY-MM-DD
        "given": {},     # {username: total kudos given to them}
        "received": {},  # {username: total kudos received from them}
        "updated_at": _now_iso(),
    }


def read_kudos(username: str) -> dict[str, Any]:
    """Read kudos data from disk.  Returns defaults if file not present."""
    path = kudos_yaml_path(username)
    if not path.exists():
        return _default_kudos()
    with open(path, "r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    kudos = _default_kudos()
    if not isinstance(loaded, dict):
        return kudos
    for key in ("last_daily_reset", "updated_at"):
        if key in loaded and isinstance(loaded[key], str):
            kudos[key] = loaded[key]
    for key in ("total_received", "total_given_all_time", "daily_given_budget", "daily_given_remaining"):
        if key in loaded:
            kudos[key] = _coerce_int(loaded[key], kudos[key])
    for key in ("given", "received"):
        if key in loaded and isinstance(loaded[key], dict):
            kudos[key] = {str(k): _coerce_int(v, 0) for k, v in loaded[key].items()}
    return kudos


def write_kudos(
    username: str,
    total_received: int | None = None,
    total_given_all_time: int | None = None,
    daily_given_remaining: int | None = None,
    last_daily_reset: str | None = None,
    given: dict[str, int] | None = None,
    received: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Update and persist kudos data for a user.  Returns the final kudos dict."""
    ensure_user_paths(username)
    current = read_kudos(username)
    if total_received is not None:
        current["total_received"] = int(total_received)
    if total_given_all_time is not None:
        current["total_given_all_time"] = int(total_given_all_time)
    if daily_given_remaining is not None:
        current["daily_given_remaining"] = int(daily_given_remaining)
    if last_daily_reset is not None:
        current["last_daily_reset"] = last_daily_reset
    if given is not None:
        current["given"] = {str(k): int(v) for k, v in given.items()}
    if received is not None:
        current["received"] = {str(k): int(v) for k, v in received.items()}
    current["updated_at"] = _now_iso()
    path = kudos_yaml_path(username)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(current, handle, sort_keys=False)
    return current


def reset_daily_kudos_if_needed(username: str) -> dict[str, Any]:
    """Reset the daily kudos giving budget if the calendar day has changed.

    Returns the (possibly-updated) kudos dict.
    """
    kudos = read_kudos(username)
    today = _now_iso()[:10]
    if kudos.get("last_daily_reset", "") != today:
        kudos = write_kudos(
            username,
            daily_given_remaining=DAILY_KUDOS_BUDGET,
            last_daily_reset=today,
        )
    return kudos
