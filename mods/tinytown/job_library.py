"""Strict loader for the TinyTown Job Office story library."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.content.common import ContentError, load_yaml_file, require_mapping

APPROACHES = ("grit", "nouse", "charm", "care", "chaos")
GAMES = ("drop-catch", "sweep-stop", "ring-match", "rhythm-lane", "pop-whack", "hold-meter")
ENDING_KEYS = ("disaster", "scraped", "okay", "great", "legendary")
ART_SUFFIX = ".webp"
ART_ROOT_URL = "/activities/jobs/art"
SPRITE_ROOT_URL = "/activities/jobs/sprites"
ARENA_ROOT_URL = "/activities/jobs/arenas"
_HEX_COLOUR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_JOB_ID = re.compile(r"^[a-z][a-z0-9-]*$")

MAX_TITLE = 96
MAX_TEXT = 420
MAX_LABEL = 160
MAX_ART_SCENE = 260
MAX_SPRITE = 160
MIN_JOBS = 50
STEP_COUNT = 4
CHOICE_COUNT = 3
MIN_COMPLICATIONS = 4
MIN_DETAILS = 8


@dataclass(frozen=True, slots=True)
class JobChoice:
    """One authored response to a story step."""

    label: str
    approach: str
    success: str
    failure: str


@dataclass(frozen=True, slots=True)
class JobStep:
    """One of a job's four story beats."""

    title: str
    setup: str
    scene: str
    pool: str
    game: str
    sprite: str
    choices: tuple[JobChoice, ...]


@dataclass(frozen=True, slots=True)
class JobComplication:
    """A procedural wrinkle drawn for one step."""

    id: str
    text: str
    favors: str | None
    hinders: str | None


@dataclass(frozen=True, slots=True)
class JobDefinition:
    """One complete Job Office shift."""

    id: str
    title: str
    profession: str
    tier: int
    accent: str
    blurb: str
    setting: str
    steps: tuple[JobStep, ...]
    endings: dict[str, str]

    def step_art(self, index: int) -> str:
        """Return the served background URL for one story step."""

        return f"{ART_ROOT_URL}/{self.id}-step-{index + 1}{ART_SUFFIX}"

    def step_arena(self, index: int) -> str:
        """Return the served minigame backdrop URL for one story step."""

        return f"{ARENA_ROOT_URL}/{self.id}-step-{index + 1}{ART_SUFFIX}"

    def step_sprite(self, index: int) -> str:
        """Return the served minigame token URL for one story step."""

        return f"{SPRITE_ROOT_URL}/{self.id}-step-{index + 1}{ART_SUFFIX}"

    @property
    def success_art(self) -> str:
        return f"{ART_ROOT_URL}/{self.id}-success{ART_SUFFIX}"

    @property
    def fail_art(self) -> str:
        return f"{ART_ROOT_URL}/{self.id}-fail{ART_SUFFIX}"

    @property
    def preview_art(self) -> str:
        return self.step_art(0)


@dataclass(frozen=True, slots=True)
class JobLibrary:
    """The merged, validated job content."""

    jobs: dict[str, JobDefinition]
    complications: dict[str, tuple[JobComplication, ...]]
    details: tuple[str, ...]


def _text(raw: Any, label: str, limit: int) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ContentError(f"{label} must not be empty.")
    if len(value) > limit:
        raise ContentError(f"{label} must be at most {limit} characters.")
    return value


def _optional_approach(raw: Any, label: str) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if value not in APPROACHES:
        raise ContentError(f"{label} must be one of {', '.join(APPROACHES)}.")
    return value


def _validate_art(art_root: Path | None, job_id: str, suffix: str, label: str, kind: str = "background") -> None:
    name = f"{job_id}-{suffix}{ART_SUFFIX}"
    if art_root is not None and not (art_root / name).is_file():
        raise ContentError(f"{label} references missing {kind} '{name}'.")


def _load_choice(raw: Any, label: str) -> JobChoice:
    if not isinstance(raw, dict):
        raise ContentError(f"{label} must be a mapping.")
    approach = str(raw.get("approach", "")).strip()
    if approach not in APPROACHES:
        raise ContentError(f"{label} approach must be one of {', '.join(APPROACHES)}.")
    return JobChoice(
        label=_text(raw.get("label"), f"{label} label", MAX_LABEL),
        approach=approach,
        success=_text(raw.get("success"), f"{label} success", MAX_TEXT),
        failure=_text(raw.get("failure"), f"{label} failure", MAX_TEXT),
    )


def _load_step(raw: Any, label: str, pools: dict[str, tuple[JobComplication, ...]]) -> JobStep:
    if not isinstance(raw, dict):
        raise ContentError(f"{label} must be a mapping.")
    pool = str(raw.get("pool", "")).strip()
    if pool not in pools:
        raise ContentError(f"{label} references unknown complication pool '{pool}'.")
    game = str(raw.get("game", "")).strip()
    if game not in GAMES:
        raise ContentError(f"{label} game must be one of {', '.join(GAMES)}.")
    raw_choices = raw.get("choices")
    if not isinstance(raw_choices, list) or len(raw_choices) != CHOICE_COUNT:
        raise ContentError(f"{label} must define exactly {CHOICE_COUNT} choices.")
    choices = tuple(
        _load_choice(choice, f"{label} choice {index + 1}")
        for index, choice in enumerate(raw_choices)
    )
    return JobStep(
        title=_text(raw.get("title"), f"{label} title", MAX_TITLE),
        setup=_text(raw.get("setup"), f"{label} setup", MAX_TEXT),
        scene=_text(raw.get("scene"), f"{label} scene", MAX_ART_SCENE),
        pool=pool,
        game=game,
        sprite=_text(raw.get("sprite"), f"{label} sprite", MAX_SPRITE),
        choices=choices,
    )


def _load_endings(raw: Any, label: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ContentError(f"{label} endings must be a mapping.")
    endings: dict[str, str] = {}
    for key in ENDING_KEYS:
        endings[key] = _text(raw.get(key), f"{label} ending '{key}'", MAX_TEXT)
    return endings


def _load_job(
    job_id: str,
    raw: Any,
    pools: dict[str, tuple[JobComplication, ...]],
    art_root: Path | None,
    sprite_root: Path | None = None,
    arena_root: Path | None = None,
) -> JobDefinition:
    if not _JOB_ID.match(job_id):
        raise ContentError(f"Job id '{job_id}' must use lower-case words and hyphens.")
    if not isinstance(raw, dict):
        raise ContentError(f"Job '{job_id}' must be a mapping.")
    tier = raw.get("tier")
    if isinstance(tier, bool) or not isinstance(tier, int) or not 1 <= tier <= 3:
        raise ContentError(f"Job '{job_id}' tier must be 1, 2, or 3.")
    accent = str(raw.get("accent", "")).strip()
    if not _HEX_COLOUR.match(accent):
        raise ContentError(f"Job '{job_id}' accent must be a hex colour.")
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) != STEP_COUNT:
        raise ContentError(f"Job '{job_id}' must define exactly {STEP_COUNT} steps.")
    steps = tuple(
        _load_step(step, f"Job '{job_id}' step {index + 1}", pools)
        for index, step in enumerate(raw_steps)
    )
    games = [step.game for step in steps]
    if len(set(games)) != len(games):
        raise ContentError(f"Job '{job_id}' must use four different minigames.")
    for index in range(STEP_COUNT):
        label = f"Job '{job_id}' step {index + 1}"
        _validate_art(art_root, job_id, f"step-{index + 1}", label)
        _validate_art(sprite_root, job_id, f"step-{index + 1}", label, kind="sprite")
        _validate_art(arena_root, job_id, f"step-{index + 1}", label, kind="arena")
    _validate_art(art_root, job_id, "success", f"Job '{job_id}' success ending")
    _validate_art(art_root, job_id, "fail", f"Job '{job_id}' fail ending")
    return JobDefinition(
        id=job_id,
        title=_text(raw.get("title"), f"Job '{job_id}' title", MAX_TITLE),
        profession=_text(raw.get("profession"), f"Job '{job_id}' profession", MAX_TITLE),
        tier=tier,
        accent=accent,
        blurb=_text(raw.get("blurb"), f"Job '{job_id}' blurb", MAX_TEXT),
        setting=_text(raw.get("setting"), f"Job '{job_id}' setting", MAX_ART_SCENE),
        steps=steps,
        endings=_load_endings(raw.get("endings"), f"Job '{job_id}'"),
    )


def _load_complications(path: Path) -> tuple[dict[str, tuple[JobComplication, ...]], tuple[str, ...]]:
    payload = require_mapping(load_yaml_file(path), path)
    raw_pools = payload.get("pools")
    if not isinstance(raw_pools, dict):
        raise ContentError(f"{path} must define a 'pools' mapping.")
    pools: dict[str, tuple[JobComplication, ...]] = {}
    for pool_name, raw_entries in raw_pools.items():
        name = str(pool_name).strip()
        if not _JOB_ID.match(name):
            raise ContentError(f"Complication pool '{name}' must use lower-case words and hyphens.")
        if not isinstance(raw_entries, list) or len(raw_entries) < MIN_COMPLICATIONS:
            raise ContentError(
                f"Complication pool '{name}' must define at least {MIN_COMPLICATIONS} entries."
            )
        entries: list[JobComplication] = []
        for index, raw in enumerate(raw_entries):
            if not isinstance(raw, dict):
                raise ContentError(f"Complication '{name}' entry {index + 1} must be a mapping.")
            entries.append(
                JobComplication(
                    id=f"{name}:{index + 1}",
                    text=_text(raw.get("text"), f"Complication '{name}' entry {index + 1}", MAX_TEXT),
                    favors=_optional_approach(raw.get("favors"), f"Complication '{name}' favors"),
                    hinders=_optional_approach(raw.get("hinders"), f"Complication '{name}' hinders"),
                )
            )
        pools[name] = tuple(entries)
    raw_details = payload.get("details")
    if not isinstance(raw_details, list) or len(raw_details) < MIN_DETAILS:
        raise ContentError(f"{path} must define at least {MIN_DETAILS} details.")
    details = tuple(
        _text(entry, f"Detail {index + 1}", MAX_TEXT)
        for index, entry in enumerate(raw_details)
    )
    return pools, details


def load_job_library(
    root: Path,
    *,
    art_root: Path | None = None,
    sprite_root: Path | None = None,
    arena_root: Path | None = None,
) -> JobLibrary:
    """Load every job YAML file beneath *root* and validate it strictly."""

    content_root = root if root.is_dir() else root / "jobs"
    complications_path = content_root / "complications.yaml"
    if not complications_path.is_file():
        raise ContentError(f"Missing job complications at {complications_path}.")
    complications, details = _load_complications(complications_path)
    jobs: dict[str, JobDefinition] = {}
    for path in sorted(content_root.glob("*.yaml")):
        if path.name == "complications.yaml":
            continue
        payload = require_mapping(load_yaml_file(path), path)
        for job_id, raw in payload.items():
            key = str(job_id).strip()
            if key in jobs:
                raise ContentError(f"Job '{key}' is defined more than once.")
            jobs[key] = _load_job(key, raw, complications, art_root, sprite_root, arena_root)
    if len(jobs) < MIN_JOBS:
        raise ContentError(f"Job library must define at least {MIN_JOBS} jobs, found {len(jobs)}.")
    return JobLibrary(jobs=jobs, complications=complications, details=details)
