"""Basic Pillow postprocess operations for baked image assets."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any


def _load_rgba(path: Path):
    from PIL import Image

    image = Image.open(path)
    return image.convert("RGBA")


def _corner_background(pixels, width: int, height: int) -> tuple[int, int, int]:
    corners = [
        pixels[0, 0][:3],
        pixels[width - 1, 0][:3],
        pixels[0, height - 1][:3],
        pixels[width - 1, height - 1][:3],
    ]
    return sorted(corners)[len(corners) // 2]


def remove_background(path: Path, params: dict[str, Any]) -> dict[str, Any]:
    """Flood-fill the border background to transparent with a color tolerance."""

    tolerance = params.get("tolerance", 32)
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)):
        raise ValueError("tolerance must be a number.")
    tolerance = max(0, min(128, int(tolerance)))
    image = _load_rgba(path)
    width, height = image.size
    pixels = image.load()
    assert pixels is not None
    background = _corner_background(pixels, width, height)

    def near(pixel) -> bool:
        return (
            abs(pixel[0] - background[0]) <= tolerance
            and abs(pixel[1] - background[1]) <= tolerance
            and abs(pixel[2] - background[2]) <= tolerance
        )

    seen = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()
    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width - 1, y))
    cleared = 0
    while queue:
        x, y = queue.popleft()
        if not 0 <= x < width or not 0 <= y < height:
            continue
        index = y * width + x
        if seen[index]:
            continue
        seen[index] = 1
        pixel = pixels[x, y]
        if pixel[3] == 0 or not near(pixel):
            continue
        pixels[x, y] = (pixel[0], pixel[1], pixel[2], 0)
        cleared += 1
        queue.append((x + 1, y))
        queue.append((x - 1, y))
        queue.append((x, y + 1))
        queue.append((x, y - 1))
    image.save(path)
    return {
        "operation": "bg_remove",
        "cleared_pixels": cleared,
        "width": width,
        "height": height,
        "tolerance": tolerance,
    }


def resize_image(path: Path, params: dict[str, Any]) -> dict[str, Any]:
    """Resize an image, preserving aspect ratio when one dimension is given."""

    from PIL import Image

    width = params.get("width")
    height = params.get("height")
    if width is None and height is None:
        raise ValueError("resize needs a width and/or height.")
    for name, value in (("width", width), ("height", height)):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or not 16 <= value <= 4096
        ):
            raise ValueError(f"{name} must be an integer between 16 and 4096.")
    image = _load_rgba(path)
    source_width, source_height = image.size
    target_width = int(width) if width else round(source_width * int(height) / source_height)
    target_height = int(height) if height else round(source_height * int(width) / source_width)
    resized = image.resize((target_width, target_height), Image.LANCZOS)
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        resized.convert("RGB").save(path)
    else:
        resized.save(path)
    return {"operation": "resize", "width": target_width, "height": target_height}


def trim_image(path: Path, params: dict[str, Any]) -> dict[str, Any]:
    """Crop transparent borders with optional padding."""

    padding = params.get("padding", 0)
    if isinstance(padding, bool) or not isinstance(padding, int) or not 0 <= padding <= 256:
        raise ValueError("padding must be an integer between 0 and 256.")
    image = _load_rgba(path)
    bbox = image.getbbox()
    if bbox is None:
        raise ValueError("Image is fully transparent; nothing to trim.")
    left = max(0, bbox[0] - padding)
    upper = max(0, bbox[1] - padding)
    right = min(image.width, bbox[2] + padding)
    lower = min(image.height, bbox[3] + padding)
    image.crop((left, upper, right, lower)).save(path)
    return {"operation": "trim", "width": right - left, "height": lower - upper, "padding": padding}


def apply_operation(path: Path, operation: str, params: dict[str, Any]) -> dict[str, Any]:
    """Apply one named postprocess operation to an image file."""

    name = str(operation or "").strip().lower().replace("-", "_")
    if name in {"bg_remove", "background_remove", "remove_bg", "remove_background"}:
        return remove_background(path, params)
    if name == "resize":
        return resize_image(path, params)
    if name == "trim":
        return trim_image(path, params)
    raise ValueError(f"Unknown postprocess operation '{operation}'.")
