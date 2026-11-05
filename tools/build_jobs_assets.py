"""Build the Job Office bake task list, placeholders, and WebP art files.

Usage:
    python tools/build_jobs_assets.py --bake            # background, sprite, and arena bake lists
    python tools/build_jobs_assets.py --placeholders    # development fallbacks
    python tools/build_jobs_assets.py --convert         # baked PNGs -> WebP (sprites get a round alpha mask)
    python tools/build_jobs_assets.py --check

The image generator is still ``tools/bake_assets.py``. This helper only keeps
prompts, filenames, seeds, and placeholder/WebP post-processing in sync with
the authored job content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTENT_ROOT = REPO_ROOT / "mods" / "tinytown" / "content" / "jobs"
ART_ROOT = REPO_ROOT / "mods" / "tinytown" / "activities" / "jobs" / "art"
SPRITE_ROOT = REPO_ROOT / "mods" / "tinytown" / "activities" / "jobs" / "sprites"
ARENA_ROOT = REPO_ROOT / "mods" / "tinytown" / "activities" / "jobs" / "arenas"
ARENA_BAKE_PATH = REPO_ROOT / "worlds" / "tinytown" / "jobs" / "arenas" / "bake.json"
BAKE_PATH = REPO_ROOT / "worlds" / "tinytown" / "jobs" / "bake.json"
SPRITE_BAKE_PATH = REPO_ROOT / "worlds" / "tinytown" / "jobs" / "sprites" / "bake.json"
SPRITE_SIZE = 512
SPRITE_STEPS = 24
SPRITE_STYLE = (
    "single centered object filling a round game-token emblem, thick dark brown outline, "
    "bold flat cel shading, bright saturated colors, soft highlight, simple clear silhouette, "
    "on a plain warm cream circular badge background that fills the frame edge to edge, "
    "no text, no letters, no numbers, no people, no hands, no faces, no scenery"
)
SPRITE_NEGATIVE = (
    "people, person, hands, fingers, face, faces, text, letters, words, numbers, writing, "
    "logo, watermark, scenery, background clutter, multiple objects, blurry, low quality"
)
ARENA_WIDTH = 768
ARENA_HEIGHT = 432
ARENA_STEPS = 24
ARENA_STYLE = (
    "stylized game-board backdrop, overhead flat-lay close-up of the work surface and props, "
    "rich painterly texture, soft diffuse light, low contrast, darkened vignette edges, "
    "calm uncluttered center, cozy storybook miniature, "
    "no people, no hands, no characters, no text, no letters, no numbers, no watermark"
)
WIDTH = 1024
HEIGHT = 576
STEPS = 28
STYLE = (
    "cozy storybook miniature diorama illustration, warm tabletop lighting, "
    "painterly, cinematic wide shot, detailed, environmental storytelling, "
    "no people, no characters, no text, no letters, no words, no numbers, no watermark"
)
NO_TEXT = "no people, no characters, no text, no letters, no words, no numbers, no watermark"
NEGATIVE = (
    "people, person, human, humans, crowd, audience, customer, customers, patron, waiter, "
    "bartender, barista, face, faces, portrait, hands, fingers, child, children, guest, guests, "
    "group, figure, figures, silhouette, text, letters, words, numbers, writing, signage, "
    "sign text, menu text, labels with text, watermark, logo, blurry, low quality, deformed"
)


def _load_yaml(path: Path) -> dict:
    import yaml

    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a mapping.")
    return payload


def load_jobs() -> dict[str, dict]:
    jobs: dict[str, dict] = {}
    for path in sorted(CONTENT_ROOT.glob("*.yaml")):
        if path.name == "complications.yaml":
            continue
        for job_id, raw in _load_yaml(path).items():
            key = str(job_id).strip()
            if key in jobs:
                raise ValueError(f"Duplicate job id {key}.")
            jobs[key] = raw
    return jobs


def seed_for(*parts: str) -> int:
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 2_000_000_000


def clean_prompt(text: str) -> str:
    """Strip trailing hand-authored no-people suffixes before the shared style is appended."""

    value = str(text or "").strip()
    for suffix in (", no people, no text", ". no people, no text", " no people, no text"):
        if value.lower().endswith(suffix):
            value = value[: -len(suffix)].rstrip(" .,")
    return value


def art_name(job_id: str, suffix: str) -> str:
    return f"{job_id}-{suffix}.png"


def art_output(name: str) -> str:
    return (ART_ROOT / name).relative_to(REPO_ROOT).as_posix()


def image_args(seed: int) -> dict:
    return {
        "width": WIDTH,
        "height": HEIGHT,
        "seed": seed,
        "steps": STEPS,
        "negative": NEGATIVE,
    }


def build_tasks() -> list[dict]:
    tasks: list[dict] = []
    for job_id, job in load_jobs().items():
        setting = clean_prompt(str(job.get("setting", "")))
        title = str(job.get("title", job_id)).strip()
        steps = job.get("steps") or []
        for index, step in enumerate(steps):
            scene = clean_prompt(str(step.get("scene", "")))
            prompt = f"{setting}. {scene}. {STYLE}."
            tasks.append(
                {
                    "label": f"jobs-{job_id}-step-{index + 1}",
                    "tool": "image",
                    "prompt": prompt,
                    "output": art_output(art_name(job_id, f"step-{index + 1}")),
                    "args": image_args(seed_for(job_id, f"step-{index + 1}")),
                }
            )
        tasks.append(
            {
                "label": f"jobs-{job_id}-success",
                "tool": "image",
                "prompt": (
                    f"{setting}. Triumphant aftermath of {title}, golden warm light, "
                    f"tidy resolution, small celebratory details, relieved municipal energy, {NO_TEXT}."
                ),
                "output": art_output(art_name(job_id, "success")),
                "args": image_args(seed_for(job_id, "success")),
            }
        )
        tasks.append(
            {
                "label": f"jobs-{job_id}-fail",
                "tool": "image",
                "prompt": (
                    f"{setting}. Chaotic aftermath of {title}, comic disaster, "
                    f"spilled mess, deflated mood, one apologetic detail, {NO_TEXT}."
                ),
                "output": art_output(art_name(job_id, "fail")),
                "args": image_args(seed_for(job_id, "fail")),
            }
        )
    return tasks


def build_sprite_tasks() -> list[dict]:
    tasks: list[dict] = []
    for job_id, job in load_jobs().items():
        for index, step in enumerate(job.get("steps") or []):
            sprite = clean_prompt(str(step.get("sprite", "")))
            tasks.append(
                {
                    "label": f"sprite-{job_id}-step-{index + 1}",
                    "tool": "image",
                    "prompt": f"{sprite}, {SPRITE_STYLE}.",
                    "output": (SPRITE_ROOT / f"{job_id}-step-{index + 1}.png").relative_to(REPO_ROOT).as_posix(),
                    "args": {
                        "width": SPRITE_SIZE,
                        "height": SPRITE_SIZE,
                        "seed": seed_for(job_id, f"sprite-{index + 1}"),
                        "steps": SPRITE_STEPS,
                        "negative": SPRITE_NEGATIVE,
                    },
                }
            )
    return tasks


def build_arena_tasks() -> list[dict]:
    tasks: list[dict] = []
    for job_id, job in load_jobs().items():
        setting = clean_prompt(str(job.get("setting", "")))
        for index, step in enumerate(job.get("steps") or []):
            scene = clean_prompt(str(step.get("scene", "")))
            tasks.append(
                {
                    "label": f"arena-{job_id}-step-{index + 1}",
                    "tool": "image",
                    "prompt": f"{scene}, {setting}. {ARENA_STYLE}.",
                    "output": (ARENA_ROOT / f"{job_id}-step-{index + 1}.png").relative_to(REPO_ROOT).as_posix(),
                    "args": {
                        "width": ARENA_WIDTH,
                        "height": ARENA_HEIGHT,
                        "seed": seed_for(job_id, f"arena-{index + 1}"),
                        "steps": ARENA_STEPS,
                        "negative": NEGATIVE,
                    },
                }
            )
    return tasks


def write_bake() -> None:
    for path, tasks in (
        (BAKE_PATH, build_tasks()),
        (SPRITE_BAKE_PATH, build_sprite_tasks()),
        (ARENA_BAKE_PATH, build_arena_tasks()),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"tasks": tasks}, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(tasks)} tasks to {path.relative_to(REPO_ROOT)}")


def step_suffixes(job: dict) -> list[str]:
    return [f"step-{index + 1}" for index in range(len(job.get("steps") or []))]


def background_suffixes(job: dict) -> list[str]:
    return [*step_suffixes(job), "success", "fail"]


def placeholder_image(job_id: str, suffix: str, accent: str) -> Image.Image:
    seed = seed_for(job_id, suffix)
    top = tuple(int(accent[index:index + 2], 16) for index in (1, 3, 5))
    bottom = tuple(max(0, value - 45) for value in top)
    image = Image.new("RGB", (WIDTH, HEIGHT), top)
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        mix = y / max(1, HEIGHT - 1)
        colour = tuple(int(top[i] * (1 - mix) + bottom[i] * mix) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=colour)
    for index in range(18):
        x = (seed + index * 137) % WIDTH
        y = (seed // 7 + index * 89) % HEIGHT
        radius = 18 + (seed + index * 31) % 90
        draw.ellipse(
            [x - radius, y - radius, x + radius, y + radius],
            fill=tuple(min(255, value + 20) for value in top),
        )
    label = f"{job_id} / {suffix}"
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    draw.text((36, HEIGHT - 58), label, fill=(255, 248, 232), font=font)
    return image


def placeholder_arena(job_id: str, suffix: str, accent: str) -> Image.Image:
    rgb = tuple(int(accent[i:i + 2], 16) for i in (1, 3, 5))
    image = Image.new("RGB", (ARENA_WIDTH, ARENA_HEIGHT))
    draw = ImageDraw.Draw(image)
    for y in range(ARENA_HEIGHT):
        mix = y / max(1, ARENA_HEIGHT - 1)
        draw.line(
            [(0, y), (ARENA_WIDTH, y)],
            fill=tuple(int(value * (0.42 - 0.22 * mix)) for value in rgb),
        )
    return image


def placeholder_sprite(job_id: str, suffix: str, accent: str) -> Image.Image:
    index = int(suffix.rsplit("-", 1)[1]) - 1
    size = SPRITE_SIZE
    rgb = tuple(int(accent[i:i + 2], 16) for i in (1, 3, 5))
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse([4, 4, size - 4, size - 4], fill=(247, 238, 217, 255), outline=(62, 44, 30, 255), width=10)
    inset = 120 + (index % 3) * 10
    draw.ellipse([inset, inset, size - inset, size - inset], fill=rgb + (255,), outline=(62, 44, 30, 255), width=8)
    return image


def apply_round_mask(image: Image.Image) -> Image.Image:
    """Return *image* as RGBA clipped to a soft-edged circle."""

    rgba = image.convert("RGBA")
    scale = 4
    mask = Image.new("L", (rgba.width * scale, rgba.height * scale), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, mask.width - 1, mask.height - 1], fill=255)
    mask = mask.resize(rgba.size, Image.LANCZOS)
    rgba.putalpha(mask)
    return rgba


def write_placeholders() -> None:
    jobs = load_jobs()
    for root, label, suffixes, make, quality in (
        (ART_ROOT, "backgrounds", background_suffixes, placeholder_image, 86),
        (SPRITE_ROOT, "sprites", step_suffixes, placeholder_sprite, 88),
        (ARENA_ROOT, "arenas", step_suffixes, placeholder_arena, 80),
    ):
        root.mkdir(parents=True, exist_ok=True)
        written = 0
        for job_id, job in jobs.items():
            accent = str(job.get("accent", "#d7795c"))
            for suffix in suffixes(job):
                target = root / f"{job_id}-{suffix}.webp"
                if target.is_file():
                    continue
                make(job_id, suffix, accent).save(target, "WEBP", quality=quality)
                written += 1
        print(f"wrote {written} placeholder {label} under {root.relative_to(REPO_ROOT)}")


def convert_pngs() -> None:
    for root, label, prepare, quality in (
        (ART_ROOT, "backgrounds", lambda image: image.convert("RGB"), 88),
        (SPRITE_ROOT, "sprites (round-masked)", apply_round_mask, 90),
        (ARENA_ROOT, "arenas", lambda image: image.convert("RGB"), 82),
    ):
        root.mkdir(parents=True, exist_ok=True)
        converted = 0
        for source in sorted(root.glob("*.png")):
            with Image.open(source) as image:
                prepare(image).save(source.with_suffix(".webp"), "WEBP", quality=quality, method=6)
            source.unlink()
            converted += 1
        print(f"converted {converted} PNG {label} to WebP")


def check() -> int:
    jobs = load_jobs()
    missing: list[str] = []
    counts: list[tuple[int, int]] = []
    for root, suffixes in (
        (ART_ROOT, background_suffixes),
        (SPRITE_ROOT, step_suffixes),
        (ARENA_ROOT, step_suffixes),
    ):
        expected = [root / f"{job_id}-{suffix}.webp" for job_id, job in jobs.items() for suffix in suffixes(job)]
        missing.extend(str(path.relative_to(REPO_ROOT)) for path in expected if not path.is_file())
        counts.append((len(list(root.glob("*.webp"))), len(expected)))
    (art, art_total), (sprites, sprite_total), (arenas, arena_total) = counts
    print(
        f"jobs={len(jobs)} backgrounds={art}/{art_total} sprites={sprites}/{sprite_total} "
        f"arenas={arenas}/{arena_total} missing={len(missing)}"
    )
    for path in missing[:20]:
        print(f"  missing {path}")
    return 0 if not missing and all(actual == total for actual, total in counts) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bake", action="store_true", help="write worlds/tinytown/jobs/bake.json")
    parser.add_argument("--placeholders", action="store_true", help="write missing placeholder WebP backgrounds")
    parser.add_argument("--convert", action="store_true", help="convert baked PNGs to WebP")
    parser.add_argument("--check", action="store_true", help="verify every job has six WebP backgrounds")
    args = parser.parse_args()
    if not any((args.bake, args.placeholders, args.convert, args.check)):
        parser.print_help()
        return 2
    if args.bake:
        write_bake()
    if args.placeholders:
        write_placeholders()
    if args.convert:
        convert_pngs()
    if args.check:
        return check()
    return 0


if __name__ == "__main__":
    sys.exit(main())
