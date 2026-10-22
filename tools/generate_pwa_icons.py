"""Generate the installable app icons from the bundled peep sticker."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "data" / "stickers" / "s1.png"
OUTPUT = REPO_ROOT / "client" / "mission-control" / "icons"
BACKGROUND = "#061923"


def render(source: Path, size: int, scale: float) -> Image.Image:
    """Return a square icon with the sticker centred on the brand background."""

    canvas = Image.new("RGB", (size, size), BACKGROUND)
    sticker = Image.open(source).convert("RGBA")
    box = sticker.getbbox()
    if box is not None:
        sticker = sticker.crop(box)
    target = max(1, round(size * scale))
    ratio = min(target / sticker.width, target / sticker.height)
    sticker = sticker.resize(
        (max(1, round(sticker.width * ratio)), max(1, round(sticker.height * ratio))),
        Image.Resampling.LANCZOS,
    )
    left = (size - sticker.width) // 2
    top = (size - sticker.height) // 2
    canvas.paste(sticker, (left, top), sticker)
    return canvas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)

    args.output.mkdir(parents=True, exist_ok=True)
    icon_512 = render(args.source, 512, 0.72)
    icon_512.save(args.output / "icon-512.png", "PNG")
    icon_512.resize((192, 192), Image.Resampling.LANCZOS).save(args.output / "icon-192.png", "PNG")
    icon_512.resize((180, 180), Image.Resampling.LANCZOS).save(args.output / "apple-touch-icon-180.png", "PNG")
    render(args.source, 512, 0.54).save(args.output / "icon-maskable-512.png", "PNG")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
