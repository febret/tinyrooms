"""Build the Hacker Collective bake lists, placeholder art, and WebP files.

Usage:
    python tools/build_hacker_assets.py --bake            # image + prop bake lists
    python tools/build_hacker_assets.py --placeholders    # procedural vector-style art
    python tools/build_hacker_assets.py --convert         # baked PNGs -> WebP
    python tools/build_hacker_assets.py --check

Real art comes from ``tools/bake_assets.py`` once ComfyUI is reachable. This
helper keeps prompts, seeds, filenames, and fallback art in sync with the
authored megacorps. The placeholders are deliberately drawn as phosphor vector
emblems, not gradients, so the activity looks finished before a bake.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTENT_ROOT = REPO_ROOT / "mods" / "tinytown" / "content" / "hacker"
ART_ROOT = REPO_ROOT / "mods" / "tinytown" / "activities" / "hacker" / "art"
BAKE_PATH = REPO_ROOT / "worlds" / "tinytown" / "hacker" / "bake.json"
PROP_PREVIEW = REPO_ROOT / "worlds" / "tinytown" / "rooms" / "preview-hacker-tower.png"
PROP_TARGET = REPO_ROOT / "worlds" / "tinytown" / "props" / "hacker-tower.glb"
FALLBACK_GLB = REPO_ROOT / "worlds" / "tinytown" / "props" / "office-building.glb"

LOGO_SIZE = 512
LOGO_STEPS = 24
BG_WIDTH = 1024
BG_HEIGHT = 576
BG_STEPS = 26
ARENA_WIDTH = 768
ARENA_HEIGHT = 432
ARENA_STEPS = 24
NEGATIVE = (
    "people, person, human, hands, fingers, face, faces, text, letters, words, numbers, "
    "writing, signage, logo wordmark, watermark, clutter, blurry, low quality, photo"
)
STYLE = (
    "monochrome phosphor vector line art, glowing CRT terminal aesthetic, 1980s retro computing, "
    "thin geometric strokes, dark background, subtle bloom, no text, no letters, no numbers"
)
BG_STYLE = (
    "subtle dark terminal backdrop, faint circuitry and grid, low contrast, deep vignette, "
    "empty centre, monochrome phosphor glow, 1980s retro computer graphics, no text, no letters, no numbers"
)
MOTIF_PROMPTS = {
    "lock": "a padlock emblem made of circuit traces and a keyhole",
    "gear": "a cogwheel emblem with a keyhole centre and cable traces",
    "eye": "a stylised surveillance eye emblem inside a data ring",
    "bolt": "a lightning bolt emblem inside a hexagonal circuit badge",
    "tower": "a stepped server tower emblem with an antenna and orbit ring",
}


def _load_corps() -> dict[str, dict]:
    with (CONTENT_ROOT / "corps.yaml").open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    corps = document.get("corps")
    if not isinstance(corps, dict) or not corps:
        raise SystemExit(f"{CONTENT_ROOT / 'corps.yaml'} has no corps mapping.")
    return corps


def _seed(label: str) -> int:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def _alpha(value: str, alpha: int) -> tuple[int, int, int, int]:
    return (*_rgb(value), alpha)


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def build_tasks(corps: dict[str, dict]) -> list[dict]:
    tasks: list[dict] = []
    for corp_id, corp in corps.items():
        motif = str(corp.get("motif", "lock"))
        title = str(corp.get("title", corp_id))
        tasks.append(
            {
                "label": f"hacker-{corp_id}-logo",
                "tool": "image",
                "prompt": (
                    f"{title}, {MOTIF_PROMPTS.get(motif, MOTIF_PROMPTS['lock'])}, {STYLE}."
                ),
                "output": _relative(ART_ROOT / f"{corp_id}-logo.png"),
                "args": {
                    "width": LOGO_SIZE,
                    "height": LOGO_SIZE,
                    "seed": _seed(f"hacker-{corp_id}-logo"),
                    "steps": LOGO_STEPS,
                    "negative": NEGATIVE,
                },
            }
        )
        tasks.append(
            {
                "label": f"hacker-{corp_id}-bg",
                "tool": "image",
                "prompt": (
                    "abstract circuit board texture with faint phosphor traces, "
                    f"tiny nodes, and a dark grid, {BG_STYLE}."
                ),
                "output": _relative(ART_ROOT / f"{corp_id}-bg.png"),
                "args": {
                    "width": BG_WIDTH,
                    "height": BG_HEIGHT,
                    "seed": _seed(f"hacker-{corp_id}-bg"),
                    "steps": BG_STEPS,
                    "negative": NEGATIVE,
                },
            }
        )
        tasks.append(
            {
                "label": f"hacker-{corp_id}-arena",
                "tool": "image",
                "prompt": (
                    f"{title} hacking arena, overhead terminal table, faint circuit rings, "
                    f"{BG_STYLE}."
                ),
                "output": _relative(ART_ROOT / f"{corp_id}-arena.png"),
                "args": {
                    "width": ARENA_WIDTH,
                    "height": ARENA_HEIGHT,
                    "seed": _seed(f"hacker-{corp_id}-arena"),
                    "steps": ARENA_STEPS,
                    "negative": NEGATIVE,
                },
            }
        )
    tasks.append(
        {
            "label": "hacker-tower-preview",
            "tool": "image",
            "prompt": (
                "cozy storybook miniature retro relay tower diorama, tiny neon server building "
                "with a satellite dish, cable bundles, and glowing antenna, isolated game asset, "
                "no text, no letters, no numbers, no people"
            ),
            "output": _relative(PROP_PREVIEW),
            "args": {
                "width": BG_WIDTH,
                "height": BG_HEIGHT,
                "seed": _seed("hacker-tower-preview"),
                "steps": BG_STEPS,
                "negative": NEGATIVE,
            },
        }
    )
    tasks.append(
        {
            "label": "tinytown-hacker-tower",
            "tool": "asset",
            "prompt": (
                "cozy storybook miniature retro computer tower diorama, tiny neon server "
                "building with a satellite dish and cable bundles, isolated game asset, no text"
            ),
            "output": _relative(PROP_TARGET),
            "args": {
                "image": _relative(PROP_PREVIEW),
                "seed": 97810,
                "faces": 6000,
            },
            "simplify": False,
        }
    )
    return tasks


def write_bake(corps: dict[str, dict]) -> None:
    BAKE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tasks": build_tasks(corps)}
    BAKE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(payload['tasks'])} tasks to {_relative(BAKE_PATH)}")


# -- procedural fallback art -------------------------------------------------


def _glow_layer(size: tuple[int, int], draw_callback, blur: int = 10) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw_callback(ImageDraw.Draw(layer))
    return layer.filter(ImageFilter.GaussianBlur(blur))


def _emblem(draw: ImageDraw.ImageDraw, motif: str, phosphor: str, accent: str, scale: float = 1.0) -> None:
    centre = 256

    def point(x: float, y: float) -> tuple[int, int]:
        return (int(centre + (x - centre) * scale), int(centre + (y - centre) * scale))

    def box(x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
        return (*point(x0, y0), *point(x1, y1))

    width = max(2, int(7 * scale))
    thin = max(1, int(3 * scale))
    if motif == "lock":
        draw.rounded_rectangle(box(160, 236, 352, 408), radius=int(22 * scale), outline=phosphor, width=width)
        draw.arc(box(188, 118, 324, 300), start=180, end=360, fill=phosphor, width=width)
        draw.ellipse(box(240, 292, 272, 324), outline=accent, width=thin)
        draw.line([point(256, 318), point(256, 356)], fill=accent, width=thin)
        for x in (140, 372):
            draw.line([point(x, 260), point(x, 384)], fill=accent, width=thin)
    elif motif == "gear":
        ring = []
        for index in range(24):
            angle = (index / 24) * math.tau
            radius = 132 if index % 2 == 0 else 108
            ring.append(point(centre + math.cos(angle) * radius, centre + math.sin(angle) * radius))
        draw.polygon(ring, outline=phosphor, width=width)
        draw.ellipse(box(206, 206, 306, 306), outline=phosphor, width=width)
        draw.ellipse(box(240, 240, 272, 272), outline=accent, width=thin)
        draw.line([point(256, 272), point(256, 312)], fill=accent, width=thin)
    elif motif == "eye":
        draw.arc(box(120, 156, 392, 356), start=200, end=340, fill=phosphor, width=width)
        draw.arc(box(120, 156, 392, 356), start=20, end=160, fill=phosphor, width=width)
        draw.ellipse(box(196, 196, 316, 316), outline=phosphor, width=width)
        draw.ellipse(box(236, 236, 276, 276), outline=accent, width=thin)
        for index in range(8):
            angle = (index / 8) * math.tau
            draw.line(
                [
                    point(centre + math.cos(angle) * 160, centre + math.sin(angle) * 160),
                    point(centre + math.cos(angle) * 196, centre + math.sin(angle) * 196),
                ],
                fill=accent,
                width=thin,
            )
    elif motif == "bolt":
        hexagon = [
            point(centre + math.cos((index / 6) * math.tau - math.pi / 2) * 176,
                  centre + math.sin((index / 6) * math.tau - math.pi / 2) * 176)
            for index in range(6)
        ]
        draw.polygon(hexagon, outline=phosphor, width=width)
        draw.polygon(
            [point(286, 148), point(196, 270), point(252, 270), point(214, 366), point(320, 228), point(262, 228)],
            outline=accent,
            width=thin,
        )
    else:
        draw.rectangle(box(190, 232, 322, 408), outline=phosphor, width=width)
        draw.rectangle(box(216, 262, 296, 300), outline=accent, width=thin)
        draw.rectangle(box(216, 320, 296, 358), outline=accent, width=thin)
        draw.line([point(256, 232), point(256, 132)], fill=phosphor, width=width)
        draw.ellipse(box(238, 158, 274, 194), outline=accent, width=thin)
        draw.arc(box(148, 292, 364, 420), start=200, end=340, fill=accent, width=thin)
    for index in range(4):
        draw.line(
            [point(96, 112 + index * 26), point(156, 112 + index * 26)],
            fill=accent,
            width=max(1, thin - 1),
        )
        draw.line(
            [point(356, 112 + index * 26), point(416, 112 + index * 26)],
            fill=accent,
            width=max(1, thin - 1),
        )


def draw_logo(corp_id: str, corp: dict) -> Image.Image:
    palette = corp["palette"]
    phosphor = palette["phosphor"]
    accent = palette["accent"]
    motif = str(corp.get("motif", "lock"))
    canvas = Image.new("RGBA", (LOGO_SIZE, LOGO_SIZE), (0, 0, 0, 0))
    glow = _glow_layer(
        (LOGO_SIZE, LOGO_SIZE),
        lambda draw: _emblem(draw, motif, phosphor, accent),
        blur=14,
    )
    canvas.alpha_composite(glow)
    canvas.alpha_composite(glow)
    sharp = Image.new("RGBA", (LOGO_SIZE, LOGO_SIZE), (0, 0, 0, 0))
    _emblem(ImageDraw.Draw(sharp), motif, phosphor, accent)
    canvas.alpha_composite(sharp)
    rng = random.Random(_seed(f"{corp_id}-logo-dust"))
    draw = ImageDraw.Draw(canvas)
    for _ in range(26):
        angle = rng.uniform(0, math.tau)
        radius = rng.uniform(170, 244)
        x = 256 + math.cos(angle) * radius
        y = 256 + math.sin(angle) * radius
        draw.ellipse((x, y, x + 3, y + 3), fill=_alpha(accent, rng.randint(40, 150)))
    return canvas


def draw_background(corp_id: str, corp: dict) -> Image.Image:
    """A subtle dark terminal backdrop in the corp's phosphor colour."""

    palette = corp["palette"]
    ink = palette["ink"]
    deep = palette["deep"]
    phosphor = palette["phosphor"]
    accent = palette["accent"]
    rng = random.Random(_seed(f"{corp_id}-bg"))
    image = Image.new("RGB", (BG_WIDTH, BG_HEIGHT), _rgb(ink))
    draw = ImageDraw.Draw(image)
    for y in range(BG_HEIGHT):
        blend = y / BG_HEIGHT
        colour = tuple(int(_rgb(ink)[i] * (1 - blend) + _rgb(deep)[i] * blend * 0.85) for i in range(3))
        draw.line([(0, y), (BG_WIDTH, y)], fill=colour)
    glow = Image.new("RGB", (BG_WIDTH, BG_HEIGHT), (0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((BG_WIDTH * 0.35, BG_HEIGHT * 0.18, BG_WIDTH * 0.75, BG_HEIGHT * 0.9), fill=_rgb(deep))
    image = Image.blend(image, glow.filter(ImageFilter.GaussianBlur(80)), 0.35)
    draw = ImageDraw.Draw(image)
    for x in range(0, BG_WIDTH, 48):
        draw.line([(x, 0), (x, BG_HEIGHT)], fill=_alpha_blend(deep, phosphor, 0.12))
    for y in range(0, BG_HEIGHT, 48):
        draw.line([(0, y), (BG_WIDTH, y)], fill=_alpha_blend(deep, phosphor, 0.12))
    for _ in range(16):
        x = rng.randrange(40, BG_WIDTH - 120)
        y = rng.randrange(40, BG_HEIGHT - 60)
        path = [(x, y)]
        for _step in range(rng.randint(3, 7)):
            dx = rng.choice((-56, -32, 32, 56))
            dy = rng.choice((0, 0, 24, -24))
            x = max(24, min(BG_WIDTH - 24, x + dx))
            y = max(24, min(BG_HEIGHT - 24, y + dy))
            path.append((x, y))
        draw.line(path, fill=_alpha_blend(deep, phosphor, 0.3), width=2)
        for px, py in path[::2]:
            draw.rectangle((px - 3, py - 3, px + 3, py + 3), outline=_alpha_blend(deep, accent, 0.35))
    emblem_glow = _glow_layer((360, 360), lambda d: _emblem(d, str(corp.get("motif", "lock")), phosphor, accent, 0.62), blur=8)
    emblem = Image.new("RGBA", (BG_WIDTH, BG_HEIGHT), (0, 0, 0, 0))
    emblem.alpha_composite(emblem_glow, (BG_WIDTH - 330, BG_HEIGHT - 300))
    emblem.putalpha(emblem.getchannel("A").point(lambda value: int(value * 0.3)))
    image = Image.alpha_composite(image.convert("RGBA"), emblem).convert("RGB")
    draw = ImageDraw.Draw(image)
    for y in range(0, BG_HEIGHT, 3):
        draw.line([(0, y), (BG_WIDTH, y)], fill=_alpha_blend(ink, phosphor, 0.05))
    mask = Image.radial_gradient("L").resize((BG_WIDTH, BG_HEIGHT))
    mask = mask.point(lambda value: max(0, 255 - int(value * 0.82)))
    dark = Image.new("RGB", (BG_WIDTH, BG_HEIGHT), _rgb(ink))
    image = Image.composite(image, dark, mask)
    noise = Image.effect_noise((BG_WIDTH, BG_HEIGHT), 12).convert("L")
    image = Image.blend(image, Image.merge("RGB", (noise, noise, noise)), 0.03)
    return image


def draw_arena(corp_id: str, corp: dict) -> Image.Image:
    palette = corp["palette"]
    ink = palette["ink"]
    deep = palette["deep"]
    phosphor = palette["phosphor"]
    rng = random.Random(_seed(f"{corp_id}-arena"))
    image = Image.new("RGB", (ARENA_WIDTH, ARENA_HEIGHT), _rgb(ink))
    draw = ImageDraw.Draw(image)
    horizon = 150
    for index in range(14):
        y = horizon + int((index / 13) ** 2.1 * (ARENA_HEIGHT - horizon))
        draw.line([(0, y), (ARENA_WIDTH, y)], fill=_alpha_blend(ink, deep, 0.5 + index * 0.02))
    for index in range(-10, 11):
        draw.line(
            [(ARENA_WIDTH / 2, horizon), (ARENA_WIDTH / 2 + index * 90, ARENA_HEIGHT)],
            fill=_alpha_blend(ink, deep, 0.45),
        )
    for radius in (70, 120, 176):
        draw.ellipse(
            (ARENA_WIDTH / 2 - radius, horizon - radius * 0.3, ARENA_WIDTH / 2 + radius, horizon + radius * 0.3),
            outline=_alpha_blend(deep, phosphor, 0.35),
            width=2,
        )
    draw.rounded_rectangle((150, 196, ARENA_WIDTH - 150, ARENA_HEIGHT - 60), radius=72, outline=_alpha_blend(deep, phosphor, 0.28), width=2)
    for x, y in ((54, 44), (ARENA_WIDTH - 54, 44), (54, ARENA_HEIGHT - 44), (ARENA_WIDTH - 54, ARENA_HEIGHT - 44)):
        draw.line([(x - 18, y), (x, y), (x, y + (18 if y < ARENA_HEIGHT / 2 else -18))], fill=_alpha_blend(deep, phosphor, 0.6), width=3)
    for _ in range(10):
        x = rng.randrange(30, ARENA_WIDTH - 30)
        y = rng.randrange(24, horizon)
        draw.ellipse((x, y, x + 4, y + 4), fill=_alpha_blend(deep, phosphor, 0.5))
    for y in range(0, ARENA_HEIGHT, 4):
        draw.line([(0, y), (ARENA_WIDTH, y)], fill=_alpha_blend(ink, phosphor, 0.05))
    return image


def _alpha_blend(base: str, accent: str, amount: float) -> tuple[int, int, int]:
    base_rgb = _rgb(base)
    accent_rgb = _rgb(accent)
    return tuple(int(base_rgb[i] * (1 - amount) + accent_rgb[i] * amount) for i in range(3))


def draw_prop_preview(corp: dict) -> Image.Image:
    """A stand-in preview image for the prop GLB bake."""

    palette = corp["palette"]
    size = 900
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    phosphor = palette["phosphor"]
    accent = palette["accent"]
    ink = palette["ink"]
    glow = _glow_layer((size, size), lambda d: d.rectangle((300, 220, 600, 700), outline=phosphor, width=8), blur=18)
    image.alpha_composite(glow)
    image.alpha_composite(glow)
    draw.rounded_rectangle((300, 220, 600, 700), radius=28, fill=_alpha(ink, 230), outline=phosphor, width=6)
    for row in range(5):
        for column in range(3):
            x = 340 + column * 84
            y = 270 + row * 76
            draw.rectangle((x, y, x + 52, y + 44), outline=_alpha(accent, 180), width=3)
            draw.line([(x + 6, y + 10), (x + 46, y + 10)], fill=_alpha(phosphor, 120), width=2)
    draw.line([(450, 220), (450, 120)], fill=phosphor, width=6)
    draw.ellipse((420, 96, 480, 156), outline=accent, width=5)
    draw.arc((250, 180, 650, 330), start=200, end=340, fill=_alpha(accent, 200), width=4)
    return image


def write_placeholders(corps: dict[str, dict]) -> None:
    ART_ROOT.mkdir(parents=True, exist_ok=True)
    for corp_id, corp in corps.items():
        draw_logo(corp_id, corp).save(ART_ROOT / f"{corp_id}-logo.png")
        draw_background(corp_id, corp).save(ART_ROOT / f"{corp_id}-bg.png")
        draw_arena(corp_id, corp).save(ART_ROOT / f"{corp_id}-arena.png")
    PROP_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    draw_prop_preview(corps["nibble"] if "nibble" in corps else next(iter(corps.values()))).save(PROP_PREVIEW)
    print(f"wrote {len(corps) * 3} placeholder images and {_relative(PROP_PREVIEW)}")


def write_glb_placeholder() -> None:
    if PROP_TARGET.is_file():
        print(f"{_relative(PROP_TARGET)} already exists")
        return
    if not FALLBACK_GLB.is_file():
        raise SystemExit(f"Missing fallback GLB {FALLBACK_GLB}.")
    PROP_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FALLBACK_GLB, PROP_TARGET)
    print(f"copied placeholder {_relative(FALLBACK_GLB)} -> {_relative(PROP_TARGET)}")


def convert(corps: dict[str, dict]) -> None:
    count = 0
    for corp_id, corp in corps.items():
        phosphor = _rgb(corp["palette"]["phosphor"])
        ink = _rgb(corp["palette"]["ink"])
        for suffix in ("logo", "bg", "arena"):
            source = ART_ROOT / f"{corp_id}-{suffix}.png"
            if not source.is_file():
                continue
            target = source.with_suffix(".webp")
            with Image.open(source) as image:
                if suffix == "logo":
                    # Keep the baked line art but recolour it to the corporation
                    # phosphor and turn the dark plate into transparency.
                    gray = image.convert("L")
                    alpha = gray.point(lambda value: min(255, int(value * 1.12)))
                    tinted = ImageOps.colorize(gray, black=(0, 0, 0), white=phosphor).convert("RGBA")
                    tinted.putalpha(alpha)
                    tinted.save(target, "WEBP", quality=92, method=6)
                else:
                    # A faint duotone keeps the baked scene in the corporation's
                    # phosphor palette instead of a generic dark render.
                    gray = ImageOps.autocontrast(image.convert("L"), cutoff=0)
                    gray = ImageEnhance.Brightness(gray).enhance(1.6)
                    tinted = ImageOps.colorize(gray, black=ink, white=phosphor)
                    tinted.save(target, "WEBP", quality=90, method=6)
            source.unlink()
            count += 1
    print(f"converted {count} images to WebP")


def check(corps: dict[str, dict]) -> int:
    missing: list[str] = []
    for corp_id in corps:
        for suffix in ("logo", "bg", "arena"):
            target = ART_ROOT / f"{corp_id}-{suffix}.webp"
            if not target.is_file():
                missing.append(_relative(target))
    if not PROP_TARGET.is_file():
        missing.append(_relative(PROP_TARGET))
    if not PROP_PREVIEW.is_file():
        missing.append(_relative(PROP_PREVIEW))
    if BAKE_PATH.is_file():
        tasks = json.loads(BAKE_PATH.read_text("utf-8")).get("tasks", [])
    else:
        tasks = []
    print(
        f"corps={len(corps)} art={len(corps) * 3} bake_tasks={len(tasks)} "
        f"missing={len(missing)}"
    )
    for path in missing:
        print(f"  missing {path}")
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bake", action="store_true", help="write the bake task list")
    parser.add_argument("--placeholders", action="store_true", help="draw procedural fallback art")
    parser.add_argument("--glb-placeholder", action="store_true", help="copy a stand-in prop GLB")
    parser.add_argument("--convert", action="store_true", help="convert PNG art to WebP")
    parser.add_argument("--check", action="store_true", help="report missing art and bake tasks")
    args = parser.parse_args(argv)
    if not any((args.bake, args.placeholders, args.glb_placeholder, args.convert, args.check)):
        parser.print_help()
        return 0
    corps = _load_corps()
    if args.bake:
        write_bake(corps)
    if args.placeholders:
        write_placeholders(corps)
    if args.glb_placeholder:
        write_glb_placeholder()
    if args.convert:
        convert(corps)
    if args.check:
        return check(corps)
    return 0


if __name__ == "__main__":
    sys.exit(main())
