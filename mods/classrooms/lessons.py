"""Shared school-lesson domain rules: subjects, traits, and grading.

Both the classrooms mod's lesson engine and the authored student behavior
script import these helpers, so the tuning lives in exactly one place.
"""

from __future__ import annotations

from typing import Protocol


class _Random(Protocol):
    def randint(self, a: int, b: int) -> int: ...


SUBJECTS: tuple[tuple[str, str], ...] = (
    ("reading", "Reading"),
    ("writing", "Writing"),
    ("math", "Math"),
    ("history", "History"),
    ("geography", "Geography"),
    ("chemistry", "Chemistry"),
    ("tech", "Tech"),
    ("sport", "Sport"),
    ("biology", "Biology"),
)
SUBJECT_IDS: tuple[str, ...] = tuple(subject_id for subject_id, _ in SUBJECTS)
SUBJECT_LABELS: dict[str, str] = dict(SUBJECTS)

DEFAULT_ENERGY = 10
DEFAULT_ATTENTION = 5
MAX_ENERGY = 10
MAX_ATTENTION = 10

TIRED_ENERGY = 3
VERY_TIRED_ENERGY = 1

# Generated students wait here when they are not in a lesson. This is
# deliberately not a real room: nobody can enter it, and room snapshots and
# behavior routing treat it as offstage.
OFFSTAGE_ROOM = "scammon-staffroom"

# Trait ids are stable, kebab-cased identifiers used in generated rosters.
TRAITS: dict[str, dict[str, object]] = {
    "superfocused": {"label": "Superfocused", "attention": 8},
    "head-in-the-clouds": {"label": "Head in the Clouds", "attention": 3},
    "extra-gas": {"label": "Extra gas", "energy": 15, "max_energy": 15},
    "bad-sleeper": {"label": "Bad sleeper", "energy": 5},
    "runs-hot": {"label": "Runs hot", "runs_hot": True},
}
TRAIT_IDS: tuple[str, ...] = tuple(TRAITS)

# Topic cards carry these tags; the skill is derived from the subject.
SUBJECT_TAG_PREFIX = "subject:"
SKILL_TAG_PREFIX = "skill:"

GRADE_POINTS: dict[str, float] = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0}


def starting_energy(trait_id: str | None) -> int:
    """Return a student's starting Energy after trait modifiers."""

    entry = TRAITS.get(str(trait_id)) if trait_id is not None else None
    if entry is not None and "energy" in entry:
        return int(entry["energy"])  # type: ignore[arg-type]
    return DEFAULT_ENERGY


def starting_attention(trait_id: str | None) -> int:
    """Return a student's starting attention after trait modifiers."""

    entry = TRAITS.get(str(trait_id)) if trait_id is not None else None
    if entry is not None and "attention" in entry:
        return int(entry["attention"])  # type: ignore[arg-type]
    return DEFAULT_ATTENTION


def max_energy_for(trait_id: str | None) -> int:
    """Return the student's maximum Energy (Extra gas raises it)."""

    entry = TRAITS.get(str(trait_id)) if trait_id is not None else None
    if entry is not None and "max_energy" in entry:
        return int(entry["max_energy"])  # type: ignore[arg-type]
    return MAX_ENERGY


def topic_energy_cost(trait_id: str | None, rng: _Random) -> int:
    """Return the Energy a student spends listening to one topic."""

    if trait_id == "runs-hot":
        return 3
    return rng.randint(1, 2)


def affinity(subject_id: str, favorites: tuple[str, ...], tricky: str | None) -> str:
    """Classify a subject as ``favorite``, ``tricky``, or ``neutral`` for a student."""

    if subject_id in favorites:
        return "favorite"
    if tricky is not None and subject_id == tricky:
        return "tricky"
    return "neutral"


def letter_grade(*, attention: float, energy: float, max_energy: float, affinity: str) -> str:
    """Return the test letter grade from final attention, energy, and affinity."""

    attention_ratio = _clamp(attention / MAX_ATTENTION)
    energy_ratio = _clamp(energy / max(1.0, max_energy))
    affinity_bonus = {"favorite": 0.2, "neutral": 0.1, "tricky": 0.0}.get(affinity, 0.1)
    score = 0.5 * attention_ratio + 0.3 * energy_ratio + affinity_bonus
    if score >= 0.8:
        return "A"
    if score >= 0.65:
        return "B"
    if score >= 0.45:
        return "C"
    return "D"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
