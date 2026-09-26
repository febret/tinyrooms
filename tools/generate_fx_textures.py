"""Generate the simple RGBA sprite textures used by prop effects.

Run with ``python tools/generate_fx_textures.py``. The output PNGs live beside
their effect definitions in ``data/fx`` and are committed. The generator is
dependency-free (only the standard library) so it stays reproducible.
"""

from __future__ import annotations

import math
from pathlib import Path
import struct
import zlib


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "data" / "fx"


def _png_bytes(width: int, height: int, pixels: bytearray) -> bytes:
    """Encode a top-to-bottom RGBA buffer as an 8-bit PNG."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = bytearray()
    stride = width * 4
    for row in range(height):
        raw.append(0)
        raw.extend(pixels[row * stride:(row + 1) * stride])
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def _blend(over: tuple[float, float, float, float], under: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Alpha-composite an (r, g, b, a) float over an 8-bit RGBA pixel."""

    alpha = max(0.0, min(1.0, over[3]))
    if alpha <= 0:
        return under
    out_a = alpha + (under[3] / 255.0) * (1 - alpha)
    if out_a <= 0:
        return (0, 0, 0, 0)
    out_rgb = [
        (over[index] * alpha + (under[index] / 255.0) * (under[3] / 255.0) * (1 - alpha)) / out_a
        for index in range(3)
    ]
    return (
        int(round(max(0.0, min(1.0, out_rgb[0])) * 255)),
        int(round(max(0.0, min(1.0, out_rgb[1])) * 255)),
        int(round(max(0.0, min(1.0, out_rgb[2])) * 255)),
        int(round(max(0.0, min(1.0, out_a)) * 255)),
    )


def _fill(size: int, shader) -> bytearray:
    pixels = bytearray(size * size * 4)
    half = (size - 1) / 2.0
    for y in range(size):
        for x in range(size):
            nx = (x - half) / half
            ny = (y - half) / half
            straight = shader(nx, ny)
            offset = (y * size + x) * 4
            pixels[offset:offset + 4] = bytes(straight)
    return pixels


def smoke_texture(size: int = 64) -> bytearray:
    """A soft grey puff with a slightly lumpy silhouette."""

    def shader(nx: float, ny: float) -> tuple[int, int, int, int]:
        radius = math.hypot(nx, ny * 1.05)
        wobble = 0.08 * math.sin(math.atan2(ny, nx) * 5.0) + 0.05 * math.sin(math.atan2(ny, nx) * 9.0)
        falloff = max(0.0, 1.0 - (radius + wobble))
        alpha = falloff ** 1.7 * 0.85
        shade = 0.78 + 0.22 * falloff
        return _blend((shade, shade, shade, alpha), (0, 0, 0, 0))

    return _fill(size, shader)


def fire_texture(size: int = 64) -> bytearray:
    """A hot radial gradient: white core through yellow and orange."""

    def shader(nx: float, ny: float) -> tuple[int, int, int, int]:
        radius = math.hypot(nx, ny * 0.92)
        if radius >= 1.0:
            return (0, 0, 0, 0)
        heat = max(0.0, 1.0 - radius) ** 1.4
        red = min(1.0, 0.65 + heat)
        green = min(1.0, heat * 1.15 + 0.08)
        blue = max(0.0, heat - 0.72) * 1.6
        alpha = (1.0 - radius) ** 0.85
        return _blend((red, green, blue, alpha), (0, 0, 0, 0))

    return _fill(size, shader)


def spark_texture(size: int = 32) -> bytearray:
    """A small bright point with a soft cross flare."""

    def shader(nx: float, ny: float) -> tuple[int, int, int, int]:
        radius = math.hypot(nx, ny)
        core = max(0.0, 1.0 - radius * 2.4) ** 1.5
        flare = max(0.0, 1.0 - abs(nx) * 6.0) * max(0.0, 1.0 - abs(ny)) * 0.5
        flare = max(flare, max(0.0, 1.0 - abs(ny) * 6.0) * max(0.0, 1.0 - abs(nx)) * 0.5)
        intensity = min(1.0, core + flare)
        alpha = min(1.0, intensity * 1.4)
        return _blend((1.0, 0.92, 0.55, alpha), (0, 0, 0, 0))

    return _fill(size, shader)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    textures = {
        "smoke-puff.png": (64, smoke_texture(64)),
        "fire-puff.png": (64, fire_texture(64)),
        "spark.png": (32, spark_texture(32)),
    }
    for name, (size, pixels) in textures.items():
        path = OUTPUT_DIR / name
        path.write_bytes(_png_bytes(size, size, pixels))
        print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
