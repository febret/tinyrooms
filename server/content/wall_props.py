"""Built-in procedural wall props: texture presets, trim finishes, and colors."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from server.content.common import ContentError


WALL_PROP_ID = "builtin:wall"
WALL_RENDER_KIND = "wall"

WALL_TEXTURES = (
    ("plaster", "Smooth plaster"),
    ("wallpaper", "Floral wallpaper"),
    ("brick", "Red brick"),
    ("whitewashed-brick", "Whitewashed brick"),
    ("stone", "Fieldstone"),
    ("river-rock", "River rock"),
    ("concrete", "Concrete"),
    ("wood", "Wood planks"),
    ("bamboo", "Bamboo"),
    ("subway-tile", "Subway tile"),
    ("beadboard", "Beadboard"),
    ("bone", "Whale bone"),
)
WALL_TEXTURE_FILES = {
    "plaster": "wall-plaster.png",
    "wallpaper": "wall-wallpaper.png",
    "brick": "wall-brick.png",
    "whitewashed-brick": "wall-brick-whitewashed.png",
    "stone": "wall-stone.png",
    "river-rock": "wall-river-rock.png",
    "concrete": "wall-concrete.png",
    "wood": "wall-wood.png",
    "bamboo": "wall-bamboo.png",
    "subway-tile": "wall-subway-tile.png",
    "beadboard": "wall-beadboard.png",
    "bone": "wall-bone.png",
}

WALL_FINISHES = (
    ("none", "Clean edge"),
    ("baseboard", "Baseboard"),
    ("crown", "Crown moulding"),
    ("crown-base", "Crown + baseboard"),
    ("wainscot", "Wainscot"),
)

DEFAULT_WALL_STYLE = {
    "texture": "plaster",
    "finish": "baseboard",
    "main": "#f1eadb",
    "accent": "#b9a889",
}

_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
_WALL_STYLE_KEYS = frozenset({"texture", "finish", "main", "accent"})


def default_wall_style() -> dict[str, str]:
    """Return a copy of the default wall finish recipe."""

    return dict(DEFAULT_WALL_STYLE)


def wall_style_options() -> dict[str, object]:
    """Return client-facing wall textures, finishes, and defaults."""

    return {
        "textures": [
            {
                "id": texture_id,
                "label": label,
                **({"file": WALL_TEXTURE_FILES[texture_id]} if texture_id in WALL_TEXTURE_FILES else {}),
            }
            for texture_id, label in WALL_TEXTURES
        ],
        "finishes": [{"id": finish_id, "label": label} for finish_id, label in WALL_FINISHES],
        "defaults": {WALL_RENDER_KIND: default_wall_style()},
    }


def validate_wall_style(raw_value: object) -> dict[str, str]:
    """Validate a complete wall finish recipe."""

    if not isinstance(raw_value, Mapping):
        raise ValueError("Walls require a wall_style recipe with texture, finish, main, and accent.")
    if set(raw_value) != _WALL_STYLE_KEYS:
        raise ValueError("Wall styles must contain only texture, finish, main, and accent.")
    texture, finish, main, accent = (raw_value[key] for key in ("texture", "finish", "main", "accent"))
    if not isinstance(texture, str) or texture not in {texture_id for texture_id, _ in WALL_TEXTURES}:
        expected = ", ".join(texture_id for texture_id, _ in WALL_TEXTURES)
        raise ValueError(f"Unknown wall texture '{texture}'; expected one of {expected}.")
    if not isinstance(finish, str) or finish not in {finish_id for finish_id, _ in WALL_FINISHES}:
        expected = ", ".join(finish_id for finish_id, _ in WALL_FINISHES)
        raise ValueError(f"Unknown wall finish '{finish}'; expected one of {expected}.")
    for name, color in (("main", main), ("accent", accent)):
        if not isinstance(color, str) or not _COLOR.fullmatch(color):
            raise ValueError(f"Wall {name} color must be a six-digit hex value like #a1b2c3.")
    return {"texture": texture, "finish": finish, "main": main, "accent": accent}


def load_wall_style(
    raw_instance: Mapping[str, Any],
    render_kind: str,
    context: str,
) -> dict[str, str] | None:
    """Validate an instance's wall finish, rejecting it on other prop kinds."""

    if render_kind != WALL_RENDER_KIND:
        if "wall_style" in raw_instance:
            raise ContentError(f"{context}: Only wall props may have a wall_style.")
        return None
    if raw_instance.get("wall_style") is None:
        return None
    try:
        return validate_wall_style(raw_instance.get("wall_style"))
    except ValueError as exc:
        raise ContentError(f"{context} wall_style: {exc}") from exc
