"""Built-in sign and whiteboard surfaces, styles, and complexity limits."""

from __future__ import annotations

from collections.abc import Mapping
import base64
import io
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
WHITEBOARD_IMAGE_MAX_BYTES = 2 * 1024 * 1024
WHITEBOARD_FRAME_OUTERS = (
    ("float", "Float"),
    ("flat", "Flat"),
    ("bevel", "Bevel"),
    ("stepped", "Stepped"),
    ("ornate", "Ornate"),
)
WHITEBOARD_FRAME_INNERS = (
    ("none", "None"),
    ("hairline", "Hairline"),
    ("bevel", "Bevel"),
    ("double", "Double"),
    ("inlay", "Inlay"),
)
WHITEBOARD_FRAME_MATTES = (
    ("none", "No matte"),
    ("slim", "Slim"),
    ("gallery", "Gallery"),
    ("linen", "Linen"),
    ("shadowbox", "Shadowbox"),
)
WHITEBOARD_FRAME_COLOR_PRESETS = (
    "#7a5230", "#2f3b3a", "#101418", "#8b1e2d", "#14424f", "#c9a45c",
)
DEFAULT_WHITEBOARD_FRAME = {
    "outer": "bevel",
    "inner": "hairline",
    "matte": "gallery",
    "main": "#7a5230",
    "accent": "#c9a45c",
}
# Caps used only when rasterizing pre-image vector whiteboards.
LEGACY_WHITEBOARD_MAX_STROKES = 500
LEGACY_WHITEBOARD_MAX_POINTS = 6000
LEGACY_WHITEBOARD_MAX_POINTS_PER_STROKE = 400
LEGACY_WHITEBOARD_MAX_TEXTS = 20
LEGACY_WHITEBOARD_MAX_TEXT_LENGTH = 160
LEGACY_WHITEBOARD_MAX_TEXT_SIZE = 120
LEGACY_WHITEBOARD_MIN_TEXT_SIZE = 12
LEGACY_WHITEBOARD_MAX_STROKE_WIDTH = 40

DEFAULT_SIGN_SURFACE = {"text": DEFAULT_SIGN_TEXT}
DEFAULT_WHITEBOARD_SURFACE = {
    "image_url": "",
    "image_hash": "",
    "frame": dict(DEFAULT_WHITEBOARD_FRAME),
}

_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
_IMAGE_HASH = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE_ASSET_PREFIX = "/assets/whiteboards"
SIGN_STYLE_IDS = frozenset(style_id for style_id, _ in SIGN_STYLES)
WHITEBOARD_OUTER_IDS = frozenset(style_id for style_id, _ in WHITEBOARD_FRAME_OUTERS)
WHITEBOARD_INNER_IDS = frozenset(style_id for style_id, _ in WHITEBOARD_FRAME_INNERS)
WHITEBOARD_MATTE_IDS = frozenset(style_id for style_id, _ in WHITEBOARD_FRAME_MATTES)


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
    """Return client-facing whiteboard image, palette, and frame limits."""

    def _styles(styles: tuple[tuple[str, str], ...]) -> list[dict[str, str]]:
        return [{"id": style_id, "label": label} for style_id, label in styles]

    return {
        "width": WHITEBOARD_WIDTH,
        "height": WHITEBOARD_HEIGHT,
        "colors": list(WHITEBOARD_COLORS),
        "max_image_bytes": WHITEBOARD_IMAGE_MAX_BYTES,
        "frame_styles": {
            "outer": _styles(WHITEBOARD_FRAME_OUTERS),
            "inner": _styles(WHITEBOARD_FRAME_INNERS),
            "matte": _styles(WHITEBOARD_FRAME_MATTES),
        },
        "default_frame": dict(DEFAULT_WHITEBOARD_FRAME),
        "frame_color_presets": list(WHITEBOARD_FRAME_COLOR_PRESETS),
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
    *,
    allow_legacy_whiteboards: bool = False,
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
            if isinstance(raw_surface, dict) and (
                "strokes" in raw_surface or "texts" in raw_surface
            ):
                if not allow_legacy_whiteboards:
                    raise ValueError(
                        "Legacy vector whiteboards require --legacy-features svg-boards."
                    )
                return dict(normalize_legacy_whiteboard(raw_surface))
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


def validate_whiteboard_frame(raw_value: object) -> dict[str, str]:
    """Validate and normalize a whiteboard frame, defaulting when omitted."""

    if raw_value is None:
        return dict(DEFAULT_WHITEBOARD_FRAME)
    if not isinstance(raw_value, dict):
        raise ValueError("A whiteboard frame must be an object.")
    unknown = set(raw_value) - {"outer", "inner", "matte", "main", "accent"}
    if unknown:
        raise ValueError("A whiteboard frame may contain only outer, inner, matte, main, and accent.")
    outer = str(raw_value.get("outer", DEFAULT_WHITEBOARD_FRAME["outer"]))
    inner = str(raw_value.get("inner", DEFAULT_WHITEBOARD_FRAME["inner"]))
    matte = str(raw_value.get("matte", DEFAULT_WHITEBOARD_FRAME["matte"]))
    main = str(raw_value.get("main", DEFAULT_WHITEBOARD_FRAME["main"]))
    accent = str(raw_value.get("accent", DEFAULT_WHITEBOARD_FRAME["accent"]))
    if outer not in WHITEBOARD_OUTER_IDS:
        raise ValueError("Unknown whiteboard outer frame style.")
    if inner not in WHITEBOARD_INNER_IDS:
        raise ValueError("Unknown whiteboard inner border style.")
    if matte not in WHITEBOARD_MATTE_IDS:
        raise ValueError("Unknown whiteboard matte style.")
    if not _HEX_COLOR.fullmatch(main):
        raise ValueError("A whiteboard frame main color must be #rrggbb.")
    if not _HEX_COLOR.fullmatch(accent):
        raise ValueError("A whiteboard frame accent color must be #rrggbb.")
    return {
        "outer": outer,
        "inner": inner,
        "matte": matte,
        "main": main.lower(),
        "accent": accent.lower(),
    }


def validate_whiteboard(raw_value: object) -> dict[str, object]:
    """Validate and normalize an image-backed whiteboard surface."""

    if not isinstance(raw_value, dict):
        raise ValueError("Whiteboard content must be an image and frame object.")
    unknown = set(raw_value) - {"image_url", "image_hash", "frame"}
    if unknown:
        raise ValueError("Whiteboard content may contain only image_url, image_hash, and frame.")
    if "image" in raw_value:
        raise ValueError("Whiteboard image uploads must be stored as an image asset.")
    image_url = raw_value.get("image_url", "")
    image_hash = raw_value.get("image_hash", "")
    if not isinstance(image_url, str) or not isinstance(image_hash, str):
        raise ValueError("A whiteboard image reference must use strings.")
    if not image_url:
        if image_hash:
            raise ValueError("A blank whiteboard must not have an image hash.")
    else:
        prefix = f"{_IMAGE_ASSET_PREFIX}/"
        if not image_url.startswith(prefix) or not image_url.endswith(".png"):
            raise ValueError("A whiteboard image must use a whiteboard asset URL.")
        digest = image_url[len(prefix):-len(".png")]
        if not _IMAGE_HASH.fullmatch(digest) or digest != image_hash:
            raise ValueError("A whiteboard image URL and hash do not match.")
    return {
        "image_url": image_url,
        "image_hash": image_hash,
        "frame": validate_whiteboard_frame(raw_value.get("frame")),
    }


def normalize_legacy_whiteboard(raw_value: object) -> dict[str, object]:
    """Validate and normalize a pre-image vector whiteboard for conversion."""

    if not isinstance(raw_value, dict):
        raise ValueError("Whiteboard content must be a strokes and texts object.")
    unknown = set(raw_value) - {"strokes", "texts"}
    if unknown:
        raise ValueError("Whiteboard content may contain only strokes and texts.")
    raw_strokes = raw_value.get("strokes", [])
    raw_texts = raw_value.get("texts", [])
    if not isinstance(raw_strokes, list) or not isinstance(raw_texts, list):
        raise ValueError("Whiteboard strokes and texts must be lists.")
    if len(raw_strokes) > LEGACY_WHITEBOARD_MAX_STROKES:
        raise ValueError(f"A whiteboard may contain at most {LEGACY_WHITEBOARD_MAX_STROKES} strokes.")
    if len(raw_texts) > LEGACY_WHITEBOARD_MAX_TEXTS:
        raise ValueError(f"A whiteboard may contain at most {LEGACY_WHITEBOARD_MAX_TEXTS} text labels.")
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
            LEGACY_WHITEBOARD_MAX_STROKE_WIDTH,
            f"Whiteboard stroke {index + 1} width",
        )
        raw_points = raw_stroke.get("points")
        if not isinstance(raw_points, list) or not raw_points:
            raise ValueError(f"Whiteboard stroke {index + 1} needs at least one point.")
        if len(raw_points) > LEGACY_WHITEBOARD_MAX_POINTS_PER_STROKE:
            raise ValueError(
                f"Whiteboard stroke {index + 1} may contain at most "
                f"{LEGACY_WHITEBOARD_MAX_POINTS_PER_STROKE} points."
            )
        points_total += len(raw_points)
        if points_total > LEGACY_WHITEBOARD_MAX_POINTS:
            raise ValueError(f"A whiteboard may contain at most {LEGACY_WHITEBOARD_MAX_POINTS} points.")
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
        if len(content) > LEGACY_WHITEBOARD_MAX_TEXT_LENGTH:
            raise ValueError(
                f"Whiteboard text {index + 1} must be at most {LEGACY_WHITEBOARD_MAX_TEXT_LENGTH} characters."
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
                LEGACY_WHITEBOARD_MIN_TEXT_SIZE,
                LEGACY_WHITEBOARD_MAX_TEXT_SIZE,
                "Whiteboard text size",
            ),
            "color": color.lower(),
        })
    return {"strokes": strokes, "texts": texts}


def rasterize_legacy_whiteboard(raw_value: object) -> str:
    """Render a normalized legacy vector whiteboard to a PNG data URL."""

    surface = normalize_legacy_whiteboard(raw_value)

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:  # pragma: no cover - Pillow is a required dependency
        raise ValueError("Server image support is unavailable.") from exc

    image = Image.new("RGB", (WHITEBOARD_WIDTH, WHITEBOARD_HEIGHT), "#fbfbf7")
    draw = ImageDraw.Draw(image)
    for stroke in surface["strokes"]:
        points = [(float(x), float(y)) for x, y in stroke["points"]]
        width = max(1, int(round(float(stroke["width"]))))
        if len(points) == 1:
            x, y = points[0]
            draw.ellipse([x - width / 2, y - width / 2, x + width / 2, y + width / 2], fill=str(stroke["color"]))
        else:
            draw.line(points, fill=str(stroke["color"]), width=width, joint="curve")
    for item in surface["texts"]:
        size = max(1, int(round(float(item["size"]))))
        try:
            font = ImageFont.load_default(size=size)
        except TypeError:  # pragma: no cover - older Pillow fallback
            font = ImageFont.load_default()
        draw.text((float(item["x"]), float(item["y"])), str(item["text"]), fill=str(item["color"]), font=font)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


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
