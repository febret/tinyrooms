"""Validation, storage, and identity helpers for user-designed stickers.

A custom sticker is persisted as a rendered PNG (served like a preset sticker)
plus a bounded JSON *design* recipe used for re-editing and for detecting
whether a swap actually changed anything. Nothing here trusts client-supplied
paths or part identifiers.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
from pathlib import Path
import re


CUSTOM_STICKER_PREFIX = "custom-"
MAX_IMAGE_BYTES = 512 * 1024
MAX_DESIGN_BYTES = 4096
MIN_DIMENSION = 32
MAX_DIMENSION = 1024

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_DATA_URL_PREFIX = "data:image/png;base64,"
_ACCOUNT_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_PART_ID_PATTERN = re.compile(r"^[a-z0-9_-]{1,40}$")
_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")

_DESIGN_VERSION = 1
_PART_SLOTS = ("body", "hair", "shoes", "back", "face", "eyes", "mouth")
_COLOR_SLOTS = (
    "skin",
    "skinDark",
    "shirt",
    "shirtDark",
    "pants",
    "pantsDark",
    "hair",
    "hairDark",
    "shoes",
    "shoesDark",
    "accent",
    "accentDark",
    "face",
)


def custom_sticker_name(account_id: str) -> str:
    """Return the deterministic asset filename for an account's custom sticker."""

    if not _ACCOUNT_ID_PATTERN.match(account_id):
        raise ValueError("Unknown account.")
    return f"{CUSTOM_STICKER_PREFIX}{account_id}.png"


def normalize_design(design: object) -> str:
    """Validate a sticker design recipe and return its canonical JSON string."""

    if not isinstance(design, dict):
        raise ValueError("A sticker design must be an object.")
    if design.get("version") != _DESIGN_VERSION:
        raise ValueError("Unsupported sticker design version.")
    parts: dict[str, str] = {}
    for slot in _PART_SLOTS:
        value = design.get(slot)
        if not isinstance(value, str) or not _PART_ID_PATTERN.match(value):
            raise ValueError(f"Invalid sticker design '{slot}'.")
        parts[slot] = value
    colors_raw = design.get("colors")
    if not isinstance(colors_raw, dict):
        raise ValueError("A sticker design must define colors.")
    colors: dict[str, str] = {}
    for slot in _COLOR_SLOTS:
        value = colors_raw.get(slot)
        if not isinstance(value, str) or not _COLOR_PATTERN.match(value):
            raise ValueError(f"Invalid sticker design color '{slot}'.")
        colors[slot] = value.lower()
    canonical = {"version": _DESIGN_VERSION, **parts, "colors": colors}
    serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_DESIGN_BYTES:
        raise ValueError("That sticker design is too complex.")
    return serialized


def decode_design(design_json: str | None) -> dict[str, object] | None:
    """Parse a stored design string into its client-facing object."""

    if not design_json:
        return None
    try:
        parsed = json.loads(design_json)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def sticker_identity(sticker_name: str | None, design_json: str | None) -> str:
    """Return a stable identity used to detect whether a swap changed the sticker."""

    if design_json:
        digest = hashlib.sha256(design_json.encode("utf-8")).hexdigest()
        return f"custom:{digest}"
    return f"preset:{sticker_name or ''}"


def decode_png_data_url(
    image: str,
    *,
    max_bytes: int = MAX_IMAGE_BYTES,
    min_dimension: int = MIN_DIMENSION,
    max_dimension: int = MAX_DIMENSION,
    label: str = "sticker",
) -> bytes:
    """Validate a base64 PNG data URL and return canonical RGBA PNG bytes."""

    if not isinstance(image, str) or not image.startswith(_DATA_URL_PREFIX):
        raise ValueError(f"That {label} must be a PNG image.")
    encoded = image[len(_DATA_URL_PREFIX):].strip()
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"That {label} image could not be read.") from exc
    if not raw:
        raise ValueError(f"That {label} image was empty.")
    if len(raw) > max_bytes:
        raise ValueError(f"That {label} image is too large.")
    if not raw.startswith(_PNG_MAGIC):
        raise ValueError(f"That {label} image must be a PNG.")

    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover - Pillow is a required dependency
        raise ValueError("Server image support is unavailable.") from exc

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(raw)) as source:
            width, height = source.size
            if not (min_dimension <= width <= max_dimension):
                raise ValueError(f"That {label} image has an invalid width.")
            if not (min_dimension <= height <= max_dimension):
                raise ValueError(f"That {label} image has an invalid height.")
            normalized = source.convert("RGBA")
            buffer = io.BytesIO()
            normalized.save(buffer, format="PNG")
    except UnidentifiedImageError as exc:
        raise ValueError(f"That {label} image could not be read.") from exc
    except OSError as exc:
        raise ValueError(f"That {label} image could not be read.") from exc
    return buffer.getvalue()


MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024
MAX_SCREENSHOT_DIMENSION = 2048


def decode_screenshot_data_url(image: str) -> bytes:
    """Validate a room screenshot, allowing larger PNGs than a sticker."""

    return decode_png_data_url(
        image,
        max_bytes=MAX_SCREENSHOT_BYTES,
        min_dimension=16,
        max_dimension=MAX_SCREENSHOT_DIMENSION,
        label="screenshot",
    )


def write_custom_sticker(directory: Path, filename: str, png_bytes: bytes) -> Path:
    """Atomically persist custom sticker bytes under *directory*."""

    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    temporary = directory / f".{filename}.tmp"
    temporary.write_bytes(png_bytes)
    temporary.replace(target)
    return target
