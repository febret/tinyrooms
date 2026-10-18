"""Built-in text recipes, font identities, and complexity limits."""

from __future__ import annotations

import re
import unicodedata


TEXT_PROP_ID = "builtin:text"
MAX_TEXT_LENGTH = 200
MAX_TEXT_LINES = 4
MAX_TEXT_PROPS = 20
MAX_ROOM_TEXT_LENGTH = 2000
DEFAULT_TEXT = {"content": "Text", "font_id": "sans", "color": "#ffffff"}

TEXT_FONTS = (
    ("sans", "Sans", "helvetiker_regular.typeface.json"),
    ("serif", "Serif", "optimer_regular.typeface.json"),
    ("mono", "Display", "gentilis_regular.typeface.json"),
)
_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")


def text_options() -> dict[str, object]:
    """Return client-facing font identities and authoritative editing limits."""

    return {
        "fonts": [
            {"id": font_id, "label": label, "file": filename}
            for font_id, label, filename in TEXT_FONTS
        ],
        "max_length": MAX_TEXT_LENGTH,
        "max_lines": MAX_TEXT_LINES,
        "max_props": MAX_TEXT_PROPS,
        "max_total_length": MAX_ROOM_TEXT_LENGTH,
    }


def validate_text(raw_value: object) -> dict[str, str]:
    """Normalize client text to NFC/LF, then validate the stored recipe."""

    if not isinstance(raw_value, dict):
        raise ValueError("Text props require a text recipe with content, font_id, and color.")
    if set(raw_value) != {"content", "font_id", "color"}:
        raise ValueError("Text recipes must contain only content, font_id, and color.")
    content, font_id, color = (raw_value[key] for key in ("content", "font_id", "color"))
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Text content must be a non-empty string.")
    content = unicodedata.normalize("NFC", content).replace("\r\n", "\n").replace("\r", "\n")
    if len(content) > MAX_TEXT_LENGTH:
        raise ValueError(f"Text content must be at most {MAX_TEXT_LENGTH} Unicode codepoints.")
    if content.count("\n") + 1 > MAX_TEXT_LINES:
        raise ValueError(f"Text content must be at most {MAX_TEXT_LINES} lines.")
    if not isinstance(font_id, str) or font_id not in {font[0] for font in TEXT_FONTS}:
        raise ValueError("Unknown text font_id; expected sans, serif, or mono.")
    if not isinstance(color, str) or not _COLOR.fullmatch(color):
        raise ValueError("Text color must be a six-digit hex value like #a1b2c3.")
    return {"content": content, "font_id": font_id, "color": color}
