"""Built-in sign and whiteboard surfaces, styles, and complexity limits."""

from __future__ import annotations

from collections.abc import Mapping
import re
import unicodedata
from typing import Any

from server.content.common import ContentError


SIGN_PROP_ID = "builtin:sign"
WHITEBOARD_PROP_ID = "builtin:whiteboard"

MAX_SIGN_TEXT_LENGTH = 240
MAX_SIGN_LINES = 8
MAX_SIGN_PROPS = 8
MAX_WHITEBOARD_PROPS = 4
DEFAULT_SIGN_TEXT = "New sign"
DEFAULT_SIGN_STYLE = "wood"

SIGN_STYLES = (
    ("wood", "Painted wood"),
    ("chalk", "Chalkboard"),
    ("brass", "Brass plaque"),
    ("paper", "Paper notice"),
    ("neon", "Neon"),
)

WHITEBOARD_WIDTH = 1024
WHITEBOARD_HEIGHT = 640
WHITEBOARD_COLORS = ("#1f2933", "#d64545", "#2f6fdb", "#2f8f5b", "#e08a1e")
MAX_WHITEBOARD_STROKES = 500
MAX_WHITEBOARD_POINTS = 6000
MAX_WHITEBOARD_POINTS_PER_STROKE = 400
MAX_WHITEBOARD_TEXTS = 20
MAX_WHITEBOARD_TEXT_LENGTH = 160
MAX_WHITEBOARD_TEXT_SIZE = 120
MIN_WHITEBOARD_TEXT_SIZE = 12
MAX_WHITEBOARD_STROKE_WIDTH = 40

DEFAULT_SIGN_SURFACE = {"text": DEFAULT_SIGN_TEXT}
DEFAULT_WHITEBOARD_SURFACE = {"strokes": [], "texts": []}

_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
SIGN_STYLE_IDS = frozenset(style_id for style_id, _ in SIGN_STYLES)


def default_activity(render_kind: str) -> str | None:
    """Return the activity a procedural surface launches by default."""

    return "whiteboard" if render_kind == "whiteboard" else None


def sign_options() -> dict[str, object]:
    """Return client-facing sign styles and authoritative editing limits."""

    return {
        "styles": [
            {"id": style_id, "label": label}
            for style_id, label in SIGN_STYLES
        ],
        "default_style": DEFAULT_SIGN_STYLE,
        "max_length": MAX_SIGN_TEXT_LENGTH,
        "max_lines": MAX_SIGN_LINES,
        "max_props": MAX_SIGN_PROPS,
    }


def whiteboard_options() -> dict[str, object]:
    """Return client-facing whiteboard canvas, marker, and size limits."""

    return {
        "width": WHITEBOARD_WIDTH,
        "height": WHITEBOARD_HEIGHT,
        "colors": list(WHITEBOARD_COLORS),
        "max_strokes": MAX_WHITEBOARD_STROKES,
        "max_points": MAX_WHITEBOARD_POINTS,
        "max_points_per_stroke": MAX_WHITEBOARD_POINTS_PER_STROKE,
        "max_texts": MAX_WHITEBOARD_TEXTS,
        "max_text_length": MAX_WHITEBOARD_TEXT_LENGTH,
        "min_text_size": MIN_WHITEBOARD_TEXT_SIZE,
        "max_text_size": MAX_WHITEBOARD_TEXT_SIZE,
        "max_stroke_width": MAX_WHITEBOARD_STROKE_WIDTH,
        "max_props": MAX_WHITEBOARD_PROPS,
    }


def validate_sign_style(raw_value: object) -> str:
    """Normalize a sign background style, defaulting when omitted."""

    if raw_value is None:
        return DEFAULT_SIGN_STYLE
    style = str(raw_value).strip()
    if style not in SIGN_STYLE_IDS:
        raise ValueError(
            "Unknown sign style; expected one of "
            + ", ".join(style_id for style_id, _ in SIGN_STYLES)
            + "."
        )
    return style


def load_sign_style(
    raw_instance: Mapping[str, Any],
    render_kind: str,
    context: str,
) -> str | None:
    """Validate an instance's sign finish, rejecting it on other prop kinds."""

    if render_kind != "sign":
        if "sign_style" in raw_instance:
            raise ContentError(f"{context}: Only builtin:sign props may have a sign_style.")
        return None
    try:
        return validate_sign_style(raw_instance.get("sign_style"))
    except ValueError as exc:
        raise ContentError(f"{context} sign_style: {exc}") from exc


def load_authored_surface(
    raw_instance: Mapping[str, Any],
    render_kind: str,
    context: str,
) -> dict[str, object] | None:
    """Load an authored starting surface for a sign or whiteboard prop."""

    if "surface" not in raw_instance:
        return None
    raw_surface = raw_instance.get("surface")
    if render_kind == "sign":
        try:
            return dict(validate_sign_text(raw_surface))
        except ValueError as exc:
            raise ContentError(f"{context}: {exc}") from exc
    if render_kind == "whiteboard":
        try:
            return dict(validate_whiteboard(raw_surface))
        except ValueError as exc:
            raise ContentError(f"{context}: {exc}") from exc
    raise ContentError(f"{context}: Only builtin:sign and builtin:whiteboard props may have a surface.")


def validate_sign_text(raw_value: object) -> dict[str, str]:
    """Normalize and validate the text stored for a sign surface."""

    if isinstance(raw_value, str):
        raw_value = {"text": raw_value}
    if not isinstance(raw_value, dict) or set(raw_value) != {"text"}:
        raise ValueError("Sign surfaces must contain only text.")
    content = raw_value.get("text")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Sign text must be a non-empty string.")
    content = _normalize_text(content)
    if len(content) > MAX_SIGN_TEXT_LENGTH:
        raise ValueError(f"Sign text must be at most {MAX_SIGN_TEXT_LENGTH} characters.")
    if content.count("\n") + 1 > MAX_SIGN_LINES:
        raise ValueError(f"Sign text must be at most {MAX_SIGN_LINES} lines.")
    return {"text": content}


def validate_whiteboard(raw_value: object) -> dict[str, object]:
    """Validate and normalize a whiteboard's vector strokes and text labels."""

    if not isinstance(raw_value, dict):
        raise ValueError("Whiteboard content must be a strokes and texts object.")
    unknown = set(raw_value) - {"strokes", "texts"}
    if unknown:
        raise ValueError("Whiteboard content may contain only strokes and texts.")
    raw_strokes = raw_value.get("strokes", [])
    raw_texts = raw_value.get("texts", [])
    if not isinstance(raw_strokes, list) or not isinstance(raw_texts, list):
        raise ValueError("Whiteboard strokes and texts must be lists.")
    if len(raw_strokes) > MAX_WHITEBOARD_STROKES:
        raise ValueError(f"A whiteboard may contain at most {MAX_WHITEBOARD_STROKES} strokes.")
    if len(raw_texts) > MAX_WHITEBOARD_TEXTS:
        raise ValueError(f"A whiteboard may contain at most {MAX_WHITEBOARD_TEXTS} text labels.")
    strokes: list[dict[str, object]] = []
    points_total = 0
    for index, raw_stroke in enumerate(raw_strokes):
        if not isinstance(raw_stroke, dict):
            raise ValueError(f"Whiteboard stroke {index + 1} must be an object.")
        color = raw_stroke.get("color")
        if not isinstance(color, str) or not _HEX_COLOR.fullmatch(color):
            raise ValueError(f"Whiteboard stroke {index + 1} has an invalid color.")
        width = _bounded_number(
            raw_stroke.get("width"),
            1,
            MAX_WHITEBOARD_STROKE_WIDTH,
            f"Whiteboard stroke {index + 1} width",
        )
        raw_points = raw_stroke.get("points")
        if not isinstance(raw_points, list) or not raw_points:
            raise ValueError(f"Whiteboard stroke {index + 1} needs at least one point.")
        if len(raw_points) > MAX_WHITEBOARD_POINTS_PER_STROKE:
            raise ValueError(
                f"Whiteboard stroke {index + 1} may contain at most "
                f"{MAX_WHITEBOARD_POINTS_PER_STROKE} points."
            )
        points_total += len(raw_points)
        if points_total > MAX_WHITEBOARD_POINTS:
            raise ValueError(f"A whiteboard may contain at most {MAX_WHITEBOARD_POINTS} points.")
        points: list[list[float]] = []
        for raw_point in raw_points:
            if not isinstance(raw_point, (list, tuple)) or len(raw_point) != 2:
                raise ValueError(f"Whiteboard stroke {index + 1} points must be [x, y] pairs.")
            points.append([
                _bounded_number(raw_point[0], 0, WHITEBOARD_WIDTH, "Whiteboard point x"),
                _bounded_number(raw_point[1], 0, WHITEBOARD_HEIGHT, "Whiteboard point y"),
            ])
        strokes.append({"color": color.lower(), "width": width, "points": points})
    texts: list[dict[str, object]] = []
    for index, raw_text in enumerate(raw_texts):
        if not isinstance(raw_text, dict):
            raise ValueError(f"Whiteboard text {index + 1} must be an object.")
        content = raw_text.get("text")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"Whiteboard text {index + 1} must be a non-empty string.")
        content = _normalize_text(content)
        if len(content) > MAX_WHITEBOARD_TEXT_LENGTH:
            raise ValueError(
                f"Whiteboard text {index + 1} must be at most {MAX_WHITEBOARD_TEXT_LENGTH} characters."
            )
        color = raw_text.get("color")
        if not isinstance(color, str) or not _HEX_COLOR.fullmatch(color):
            raise ValueError(f"Whiteboard text {index + 1} has an invalid color.")
        texts.append({
            "text": content,
            "x": _bounded_number(raw_text.get("x"), 0, WHITEBOARD_WIDTH, "Whiteboard text x"),
            "y": _bounded_number(raw_text.get("y"), 0, WHITEBOARD_HEIGHT, "Whiteboard text y"),
            "size": _bounded_number(
                raw_text.get("size"),
                MIN_WHITEBOARD_TEXT_SIZE,
                MAX_WHITEBOARD_TEXT_SIZE,
                "Whiteboard text size",
            ),
            "color": color.lower(),
        })
    return {"strokes": strokes, "texts": texts}


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    return normalized.strip("\n")


def _bounded_number(raw_value: Any, minimum: float, maximum: float, label: str) -> float:
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise ValueError(f"{label} must be a number.")
    value = float(raw_value)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"{label} must be a finite number.")
    if not (minimum <= value <= maximum):
        raise ValueError(f"{label} must be between {minimum} and {maximum}.")
    return round(value, 2)
