"""Generate Memebase card fronts from the base animated-emote card template.

Run from the repository root:

    python tools/generate_memebase_cards.py

Each meme source frame is composited into the gold "ANIMATION" card frame used
by the collectible base emotes (``wave``/``heart``/``happy-dance``), the title
line is redrawn, and the result is written as a WebP card front. The pack back
is derived from the base pack back with a redrawn subtitle.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
MEMEBASE_DIR = REPO_ROOT / "data" / "cardsets" / "memebase"
BASE_DIR = REPO_ROOT / "data" / "cardsets" / "base"
TEMPLATE_CARD = BASE_DIR / "wave.png"
TEMPLATE_PACK_BACK = BASE_DIR / "base-pack-back.webp"

# Fixed geometry of the gold animated-emote template (344x512).
PANEL_BOX = (46, 46, 298, 312)
TITLE_BOX = (58, 286, 395, 427)

FONT_CANDIDATES = [
    "C:/Windows/Fonts/comicbd.ttf",
    "C:/Windows/Fonts/comic.ttf",
    "C:/Windows/Fonts/Candarab.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]

CARDS: list[tuple[str, str, str]] = [
    ("beach-day", "Beach Day", "4897.gif"),
    ("cherry-cat", "Cherry Cat", "5d526c55e610a00.webp"),
    ("bitaroo-blaze", "Bitaroo Blaze", "bitcoin-bitaroo.gif"),
    ("tina-uhh", "Uhh... Tina", "bobs-burgers-tina-belcher.gif"),
    ("troll-dance", "Troll Dance", "download.png"),
    ("masked-laugh", "Masked Laugh", "giphy.gif"),
    ("ok-hamster", "OK Hamster", "hamster.gif"),
    ("troll-problem", "Troll Problem", "hilarious-internet-troll-face-h96vg67m33zwomzh.gif"),
    ("pixel-hamster", "Pixel Hamster", "tumblr_mit6l0CKMR1rfjowdo1_500.gif"),
    ("grumpy-munchkin", "Grumpy Munchkin", "tumblr_nmu6r4U9XW1s3lkzpo1_400.gif"),
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


def load_frame(path: Path) -> Image.Image:
    """Return a representative RGBA frame from a (possibly animated) image."""

    image = Image.open(path)
    frame_count = getattr(image, "n_frames", 1)
    if frame_count > 1:
        image.seek(frame_count // 2)
    return image.convert("RGBA")


def cover_fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale and center-crop *image* to exactly cover *size*."""

    target_w, target_h = size
    scale = max(target_w / image.width, target_h / image.height)
    scaled = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.LANCZOS,
    )
    left = (scaled.width - target_w) // 2
    top = (scaled.height - target_h) // 2
    return scaled.crop((left, top, left + target_w, top + target_h))


def blank_title(template: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    """Erase the title text by vertically interpolating across its band."""

    x0, x1, y0, y1 = box
    result = template.copy()
    pixels = result.load()
    span = (y1 - y0) + 1
    for x in range(x0, x1):
        top = template.getpixel((x, y0 - 1))
        bottom = template.getpixel((x, y1 + 1))
        for y in range(y0, y1 + 1):
            ratio = (y - y0 + 1) / (span + 1)
            blended = tuple(round(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
            pixels[x, y] = (*blended, template.getpixel((x, y))[3])
    return result


def title_color(template: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """Sample the darkest pixels of the original title as the text color."""

    x0, x1, y0, y1 = box
    samples = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            red, green, blue, _ = template.getpixel((x, y))
            if 0.3 * red + 0.6 * green + 0.1 * blue < 110:
                samples.append((red, green, blue))
    if not samples:
        return (60, 44, 30)
    return tuple(round(sum(channel[i] for channel in samples) / len(samples)) for i in range(3))


def fit_font(text: str, max_width: int, max_height: int) -> ImageFont.FreeTypeFont:
    size = max_height + 4
    while size > 8:
        font = load_font(size)
        left, top, right, bottom = font.getbbox(text)
        if right - left <= max_width and bottom - top <= max_height:
            return font
        size -= 1
    return load_font(8)


def build_card(template: Image.Image, frame: Image.Image, label: str) -> Image.Image:
    card = blank_title(template, TITLE_BOX)
    color = title_color(template, TITLE_BOX)

    x0, y0, x1, y1 = PANEL_BOX
    panel_size = (x1 - x0, y1 - y0)
    art = cover_fit(frame, panel_size)
    mask = Image.new("L", panel_size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, panel_size[0] - 1, panel_size[1] - 1), radius=9, fill=255
    )
    card.paste(art, (x0, y0), mask)

    draw = ImageDraw.Draw(card)
    font = fit_font(label, max_width=196, max_height=24)
    draw.text((template.width // 2, 411), label, font=font, fill=color, anchor="mm")
    return card


def build_pack_back() -> Image.Image:
    source = Image.open(TEMPLATE_PACK_BACK).convert("RGBA")
    alpha = source.getchannel("A")
    back = source.convert("RGB")
    # Sample a clean patch of the pattern below the subtitle to hide the old text.
    patch_box = (150, 640, 746, 720)
    sample_box = (150, 820, 746, 900)
    back.paste(back.crop(sample_box), patch_box[:2])
    font = fit_font("Memebase", max_width=430, max_height=64)
    glow = Image.new("RGB", back.size, (0, 0, 0))
    ImageDraw.Draw(glow).text(
        (back.width // 2, 680), "Memebase", font=font, fill=(90, 200, 255), anchor="mm"
    )
    glow = glow.filter(ImageFilter.GaussianBlur(8))
    back = ImageChops.screen(back, glow)
    ImageDraw.Draw(back).text(
        (back.width // 2, 680), "Memebase", font=font, fill=(170, 232, 255), anchor="mm"
    )
    result = back.convert("RGBA")
    result.putalpha(alpha)
    return result


def main() -> None:
    template = Image.open(TEMPLATE_CARD).convert("RGBA")
    for card_id, label, source in CARDS:
        source_path = MEMEBASE_DIR / source
        if not source_path.is_file():
            raise SystemExit(f"Missing source image for '{card_id}': {source_path}")
        card = build_card(template, load_frame(source_path), label)
        output = MEMEBASE_DIR / f"{card_id}.webp"
        card.save(output, "WEBP", quality=90, method=6)
        print(f"wrote {output.relative_to(REPO_ROOT)}")

    back = build_pack_back()
    back_output = MEMEBASE_DIR / "memebase-pack-back.webp"
    back.save(back_output, "WEBP", quality=90, method=6)
    print(f"wrote {back_output.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
