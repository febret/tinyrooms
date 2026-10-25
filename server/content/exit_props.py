"""Built-in procedural exit props: style variants, finishes, and textures."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from server.content.common import ContentError


DOOR_PROP_ID = "builtin:door"
ARROW_PROP_ID = "builtin:arrow"
STAIRS_PROP_ID = "builtin:stairs"

EXIT_PROP_RENDER_KINDS = frozenset({"door", "arrow", "stairs"})

EXIT_DOOR_STYLES = (
    ("panel", "Paneled"),
    ("arch", "Arched"),
    ("slab", "Modern slab"),
)
EXIT_ARROW_STYLES = (
    ("floor", "Floor chevron"),
    ("signpost", "Signpost"),
)
EXIT_STAIRS_STYLES = (
    ("straight", "Straight"),
    ("grand", "Grand"),
)
EXIT_STYLES_BY_KIND = {
    "door": EXIT_DOOR_STYLES,
    "arrow": EXIT_ARROW_STYLES,
    "stairs": EXIT_STAIRS_STYLES,
}

EXIT_TEXTURES = (
    ("plain", "Plain"),
    ("wood", "Wood grain"),
    ("stone", "Stone"),
    ("metal", "Brushed metal"),
)
EXIT_TEXTURE_FILES = {
    "wood": "exit-wood.png",
    "stone": "exit-stone.png",
    "metal": "exit-metal.png",
}

DEFAULT_EXIT_FINISH = {
    "door": {"style": "panel", "main": "#b07a4a", "accent": "#6b4a2f", "texture": "plain"},
    "arrow": {"style": "floor", "main": "#e8b23a", "accent": "#7a4d00", "texture": "plain"},
    "stairs": {"style": "straight", "main": "#9d8b74", "accent": "#5c3a20", "texture": "plain"},
}

_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")


def default_exit_finish(render_kind: str) -> dict[str, str]:
    """Return the default finish recipe for an exit prop kind."""

    return dict(DEFAULT_EXIT_FINISH[render_kind])


def exit_style_options() -> dict[str, object]:
    """Return client-facing exit style variants, textures, and defaults."""

    return {
        "door": [{"id": style_id, "label": label} for style_id, label in EXIT_DOOR_STYLES],
        "arrow": [{"id": style_id, "label": label} for style_id, label in EXIT_ARROW_STYLES],
        "stairs": [{"id": style_id, "label": label} for style_id, label in EXIT_STAIRS_STYLES],
        "textures": [
            {"id": texture_id, "label": label, **({"file": EXIT_TEXTURE_FILES[texture_id]} if texture_id in EXIT_TEXTURE_FILES else {})}
            for texture_id, label in EXIT_TEXTURES
        ],
        "defaults": {kind: dict(finish) for kind, finish in DEFAULT_EXIT_FINISH.items()},
    }


def validate_exit_finish(raw_value: object, render_kind: str) -> dict[str, str]:
    """Validate a complete exit finish recipe for one exit prop kind."""

    styles = EXIT_STYLES_BY_KIND.get(render_kind)
    if styles is None:
        raise ValueError("Only door, arrow, and stairs props may have an exit_style.")
    if not isinstance(raw_value, Mapping):
        raise ValueError("Exit props require an exit_style recipe with style, main, accent, and texture.")
    if set(raw_value) != {"style", "main", "accent", "texture"}:
        raise ValueError("Exit style recipes must contain only style, main, accent, and texture.")
    style, main, accent, texture = (raw_value[key] for key in ("style", "main", "accent", "texture"))
    if not isinstance(style, str) or style not in {style_id for style_id, _ in styles}:
        expected = ", ".join(style_id for style_id, _ in styles)
        raise ValueError(f"Unknown exit style '{style}'; expected one of {expected}.")
    for name, color in (("main", main), ("accent", accent)):
        if not isinstance(color, str) or not _COLOR.fullmatch(color):
            raise ValueError(f"Exit {name} color must be a six-digit hex value like #a1b2c3.")
    if not isinstance(texture, str) or texture not in {texture_id for texture_id, _ in EXIT_TEXTURES}:
        expected = ", ".join(texture_id for texture_id, _ in EXIT_TEXTURES)
        raise ValueError(f"Unknown exit texture '{texture}'; expected one of {expected}.")
    return {"style": style, "main": main, "accent": accent, "texture": texture}


def load_exit_style(
    raw_instance: Mapping[str, Any],
    render_kind: str,
    context: str,
) -> dict[str, str] | None:
    """Validate an instance's exit finish, rejecting it on other prop kinds."""

    if render_kind not in EXIT_STYLES_BY_KIND:
        if "exit_style" in raw_instance:
            raise ContentError(f"{context}: Only door, arrow, and stairs props may have an exit_style.")
        return None
    if raw_instance.get("exit_style") is None:
        return None
    try:
        return validate_exit_finish(raw_instance.get("exit_style"), render_kind)
    except ValueError as exc:
        raise ContentError(f"{context} exit_style: {exc}") from exc
