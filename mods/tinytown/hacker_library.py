"""Strict content loader for the Hacker Collective activity."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from mods.tinytown.catalog import TRAITS_BY_ID
from server.content.common import ContentError

MOD_ROOT = Path(__file__).resolve().parent
DEFAULT_CONTENT_ROOT = MOD_ROOT / "content" / "hacker"
DEFAULT_ART_ROOT = MOD_ROOT / "activities" / "hacker" / "art"

SUPPORTED_GRADES = frozenset({1, 5})
FLOOR_COUNT = 10
PALETTE_KEYS = ("phosphor", "deep", "ink", "accent")
MOTIFS = ("lock", "gear", "eye", "bolt", "tower")
BANTER_EVENTS = (
    "greet",
    "correct",
    "wrong",
    "streak",
    "timeout",
    "lowtime",
    "nodewin",
    "nodelose",
    "central",
    "drain",
    "tip",
)
BANTER_MOODS = ("rested", "tired", "drained")
COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")


@dataclass(frozen=True, slots=True)
class FloorDefinition:
    """One floor of a megacorp tower, mapped to a maths topic."""

    level: int
    title: str
    topic: str
    available: bool
    nodes: int = 10


@dataclass(frozen=True, slots=True)
class CorpDefinition:
    """One megacorp, its phosphor palette, and its tower floors."""

    id: str
    title: str
    tagline: str
    blurb: str
    grade: int
    topic: str
    motif: str
    palette: dict[str, str]
    logo: str
    background: str
    arena: str
    floors: tuple[FloorDefinition, ...]

    @property
    def playable(self) -> bool:
        """Whether this corporation can be entered at all."""

        return self.grade in SUPPORTED_GRADES

    def floor(self, level: int) -> FloorDefinition | None:
        return next((floor for floor in self.floors if floor.level == level), None)

    @property
    def open_floor(self) -> FloorDefinition | None:
        """The lowest playable floor, or ``None`` when the corp is sealed."""

        if not self.playable:
            return None
        return next((floor for floor in self.floors if floor.available), None)


@dataclass(frozen=True, slots=True)
class BanterLine:
    """One authored roommate reaction."""

    event: str
    text: str
    traits: tuple[str, ...] = ()
    mood: str = ""


@dataclass(frozen=True, slots=True)
class HackerLibrary:
    """Validated corps, floors, and roommate banter."""

    corps: dict[str, CorpDefinition]
    banter: tuple[BanterLine, ...]
    art_root: Path

    def corp(self, corp_id: str) -> CorpDefinition:
        definition = self.corps.get(corp_id)
        if definition is None:
            raise ContentError(f"Unknown megacorp '{corp_id}'.")
        return definition

    def lines_for(self, event: str) -> tuple[BanterLine, ...]:
        return tuple(line for line in self.banter if line.event == event)


def _require_text(raw: dict[str, Any], key: str, path: str, *, limit: int = 160) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{path}: '{key}' must be a non-empty string.")
    text = value.strip()
    if len(text) > limit:
        raise ContentError(f"{path}: '{key}' is longer than {limit} characters.")
    return text


def _require_int(raw: dict[str, Any], key: str, path: str, low: int, high: int) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ContentError(f"{path}: '{key}' must be an integer from {low} to {high}.")
    return value


def _require_palette(raw: Any, path: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ContentError(f"{path}: 'palette' must be a mapping.")
    palette: dict[str, str] = {}
    for key in PALETTE_KEYS:
        value = raw.get(key)
        if not isinstance(value, str) or not COLOR_PATTERN.match(value):
            raise ContentError(f"{path}: palette '{key}' must be a #rrggbb colour.")
        palette[key] = value.lower()
    extra = set(raw) - set(PALETTE_KEYS)
    if extra:
        raise ContentError(f"{path}: unexpected palette keys {sorted(extra)}.")
    return palette


def _require_asset(value: Any, art_root: Path, path: str, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{path}: '{key}' must name a file in the activity art folder.")
    name = value.strip()
    if Path(name).name != name:
        raise ContentError(f"{path}: '{key}' must be a bare filename, got {name!r}.")
    if not (art_root / name).is_file():
        raise ContentError(f"{path}: missing art file {art_root / name}.")
    return name


def _load_floors(raw: Any, path: str) -> tuple[FloorDefinition, ...]:
    if not isinstance(raw, list) or len(raw) != FLOOR_COUNT:
        raise ContentError(f"{path}: 'floors' must be a list of exactly {FLOOR_COUNT} floors.")
    floors: list[FloorDefinition] = []
    seen: set[int] = set()
    for index, entry in enumerate(raw):
        floor_path = f"{path}.floors[{index}]"
        if not isinstance(entry, dict):
            raise ContentError(f"{floor_path}: each floor must be a mapping.")
        level = _require_int(entry, "level", floor_path, 1, FLOOR_COUNT)
        if level in seen:
            raise ContentError(f"{floor_path}: duplicate floor level {level}.")
        seen.add(level)
        available = entry.get("available", False)
        if not isinstance(available, bool):
            raise ContentError(f"{floor_path}: 'available' must be true or false.")
        nodes = entry.get("nodes", 10)
        if isinstance(nodes, bool) or not isinstance(nodes, int) or not 5 <= nodes <= 12:
            raise ContentError(f"{floor_path}: 'nodes' must be an integer from 5 to 12.")
        floors.append(
            FloorDefinition(
                level=level,
                title=_require_text(entry, "title", floor_path, limit=48),
                topic=_require_text(entry, "topic", floor_path, limit=64),
                available=available,
                nodes=nodes,
            )
        )
    floors.sort(key=lambda floor: floor.level)
    if [floor.level for floor in floors] != list(range(1, FLOOR_COUNT + 1)):
        raise ContentError(f"{path}: floors must cover levels 1 through {FLOOR_COUNT}.")
    return tuple(floors)


def _load_corp(corp_id: str, raw: Any, art_root: Path) -> CorpDefinition:
    path = f"corps.yaml:{corp_id}"
    if not ID_PATTERN.match(corp_id):
        raise ContentError(f"{path}: corp id must be lowercase and hyphenated.")
    if not isinstance(raw, dict):
        raise ContentError(f"{path}: corp entry must be a mapping.")
    motif = raw.get("motif")
    if motif not in MOTIFS:
        raise ContentError(f"{path}: 'motif' must be one of {MOTIFS}.")
    return CorpDefinition(
        id=corp_id,
        title=_require_text(raw, "title", path, limit=40),
        tagline=_require_text(raw, "tagline", path, limit=90),
        blurb=_require_text(raw, "blurb", path, limit=220),
        grade=_require_int(raw, "grade", path, 1, 5),
        topic=_require_text(raw, "topic", path, limit=64),
        motif=motif,
        palette=_require_palette(raw.get("palette"), path),
        logo=_require_asset(raw.get("logo"), art_root, path, "logo"),
        background=_require_asset(raw.get("background"), art_root, path, "background"),
        arena=_require_asset(raw.get("arena"), art_root, path, "arena"),
        floors=_load_floors(raw.get("floors"), path),
    )


def _load_banter(raw: Any) -> tuple[BanterLine, ...]:
    if not isinstance(raw, dict):
        raise ContentError("banter.yaml: expected a mapping with a 'lines' list.")
    lines = raw.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ContentError("banter.yaml: 'lines' must be a non-empty list.")
    loaded: list[BanterLine] = []
    seen_text: set[str] = set()
    for index, entry in enumerate(lines):
        path = f"banter.yaml.lines[{index}]"
        if not isinstance(entry, dict):
            raise ContentError(f"{path}: each line must be a mapping.")
        event = entry.get("event")
        if event not in BANTER_EVENTS:
            raise ContentError(f"{path}: 'event' must be one of {BANTER_EVENTS}.")
        text = _require_text(entry, "text", path, limit=120)
        if text in seen_text:
            raise ContentError(f"{path}: duplicate banter line {text!r}.")
        seen_text.add(text)
        raw_traits = entry.get("traits", [])
        if not isinstance(raw_traits, list) or any(not isinstance(t, str) for t in raw_traits):
            raise ContentError(f"{path}: 'traits' must be a list of trait ids.")
        unknown = [trait for trait in raw_traits if trait not in TRAITS_BY_ID]
        if unknown:
            raise ContentError(f"{path}: unknown traits {unknown}.")
        mood = entry.get("mood", "")
        if mood and mood not in BANTER_MOODS:
            raise ContentError(f"{path}: 'mood' must be one of {BANTER_MOODS}.")
        loaded.append(BanterLine(event=str(event), text=text, traits=tuple(raw_traits), mood=mood))
    return tuple(loaded)


def load_hacker_library(
    content_root: Path | None = None,
    art_root: Path | None = None,
) -> HackerLibrary:
    """Load and validate every megacorp, floor, and banter line."""

    content = content_root or DEFAULT_CONTENT_ROOT
    art = art_root or DEFAULT_ART_ROOT
    corps_path = content / "corps.yaml"
    banter_path = content / "banter.yaml"
    if not corps_path.is_file():
        raise ContentError(f"Missing hacker content file {corps_path}.")
    if not banter_path.is_file():
        raise ContentError(f"Missing hacker content file {banter_path}.")
    with corps_path.open("r", encoding="utf-8") as handle:
        corps_document = yaml.safe_load(handle) or {}
    with banter_path.open("r", encoding="utf-8") as handle:
        banter_document = yaml.safe_load(handle) or {}
    raw_corps = corps_document.get("corps") if isinstance(corps_document, dict) else None
    if not isinstance(raw_corps, dict) or not raw_corps:
        raise ContentError("corps.yaml: expected a non-empty 'corps' mapping.")
    corps: dict[str, CorpDefinition] = {}
    for corp_id, raw in raw_corps.items():
        if not isinstance(corp_id, str):
            raise ContentError(f"corps.yaml: invalid corp key {corp_id!r}.")
        corps[corp_id] = _load_corp(corp_id, raw, art)
    grades = [corp.grade for corp in corps.values()]
    if len(set(grades)) != len(grades):
        raise ContentError("corps.yaml: each grade must have exactly one megacorp.")
    if set(grades) != {1, 2, 3, 4, 5}:
        raise ContentError("corps.yaml: megacorps must cover grades 1 through 5.")
    for corp in corps.values():
        open_floors = [floor for floor in corp.floors if floor.available]
        if corp.playable and not open_floors:
            raise ContentError(
                f"corps.yaml:{corp.id}: a playable megacorp needs at least one open floor."
            )
        if not corp.playable and open_floors:
            raise ContentError(
                f"corps.yaml:{corp.id}: grade {corp.grade} is sealed but has an open floor."
            )
    return HackerLibrary(
        corps=corps,
        banter=_load_banter(banter_document),
        art_root=art,
    )
