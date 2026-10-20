"""Deterministic Scammon Academia student roster loading and fallback generation.

The authored ``students.json`` manifest is the source of truth for names,
favorite subjects, classroom traits, and avatar files. The generator tool and
this loader share the same payload shape, so a sticker always matches the
student it belongs to. Worlds without a manifest keep the original random
fallback for compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path
import random
import re

from mods.classrooms.lesson_state import StudentRecord
from mods.classrooms.lessons import SUBJECT_IDS, TRAIT_IDS


MANIFEST_NAME = "students.json"
MANIFEST_VERSION = 2
STUDENTS_PER_GRADE = 15
GRADES = 8
FIRST_NAMES = (
    "Jack",
    "Jill",
    "Lisa",
    "Tom",
    "Luca",
    "Jimmy",
    "Lana",
    "Rose",
    "Blue",
    "Red",
    "Gigi",
    "Toto",
    "Tato",
    "Robert",
)
LAST_NAMES = (
    "Pesto",
    "Spaghetto",
    "Toto",
    "Tato",
    "Crickets",
    "Hearts",
    "Malinki",
    "BamBam",
    "Obert",
)
AVATARS = tuple(f"student-sticker-{index:02d}.svg" for index in range(1, 121))

_AVATAR_PATTERN = re.compile(r"^student-sticker-\d{2,3}\.svg$")
_STUDENT_ID_PATTERN = re.compile(r"^student:[1-8]:\d{2}$")


def _invalid(message: str) -> ValueError:
    return ValueError(f"Invalid student roster: {message}")


def load_student_manifest(world_root: Path) -> list[StudentRecord] | None:
    """Load and validate the authored student manifest, if one exists."""

    path = world_root / "peeps" / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _invalid(f"{MANIFEST_NAME} could not be read.") from exc
    if not isinstance(raw, dict) or raw.get("version") != MANIFEST_VERSION:
        raise _invalid("unsupported manifest version.")
    entries = raw.get("students")
    if not isinstance(entries, list) or not entries:
        raise _invalid("students must be a non-empty list.")

    students: list[StudentRecord] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise _invalid("every student must be an object.")
        student_id = str(entry.get("student_id", ""))
        if not _STUDENT_ID_PATTERN.match(student_id) or student_id in seen_ids:
            raise _invalid(f"bad or duplicate student id '{student_id}'.")
        grade = int(entry.get("grade", 0))
        first_name = str(entry.get("first_name", "")).strip()
        last_name = str(entry.get("last_name", "")).strip()
        label = f"{first_name} {last_name}".strip()
        if not first_name or not last_name or label in seen_names:
            raise _invalid(f"bad or duplicate student name '{label}'.")
        if grade not in range(1, GRADES + 1):
            raise _invalid(f"bad grade for '{label}'.")

        favorites_raw = entry.get("favorites")
        favorites = tuple(str(item) for item in favorites_raw) if isinstance(favorites_raw, list) else ()
        if len(favorites) != 2 or len(set(favorites)) != 2:
            raise _invalid(f"'{label}' must have two distinct favorite subjects.")
        if any(subject not in SUBJECT_IDS for subject in favorites):
            raise _invalid(f"'{label}' has an unknown favorite subject.")
        tricky = str(entry.get("tricky", ""))
        if tricky not in SUBJECT_IDS or tricky in favorites:
            raise _invalid(f"'{label}' has an invalid tricky subject.")
        trait_raw = entry.get("trait")
        trait = str(trait_raw) if trait_raw is not None else None
        if trait is not None and trait not in TRAIT_IDS:
            raise _invalid(f"'{label}' has an unknown trait.")
        avatar = str(entry.get("avatar", ""))
        if not _AVATAR_PATTERN.match(avatar):
            raise _invalid(f"'{label}' has an invalid avatar name.")
        avatar_path = path.parent / avatar
        if not avatar_path.is_file():
            raise _invalid(f"'{label}' points to missing avatar '{avatar}'.")

        seen_ids.add(student_id)
        seen_names.add(label)
        students.append(
            StudentRecord(
                student_id=student_id,
                grade=grade,
                first_name=first_name,
                last_name=last_name,
                favorites=favorites,
                tricky=tricky,
                trait=trait,
                avatar=avatar,
            )
        )
    return students


def random_roster(rng: random.Random | None = None) -> list[StudentRecord]:
    """Create the legacy random roster for worlds without a manifest."""

    source = rng or random
    combos = [(first, last) for first in FIRST_NAMES for last in LAST_NAMES]
    source.shuffle(combos)
    students: list[StudentRecord] = []
    cursor = 0
    for grade in range(1, GRADES + 1):
        for index in range(STUDENTS_PER_GRADE):
            if cursor < len(combos):
                first_name, last_name = combos[cursor]
            else:
                first_name, last_name = source.choice(FIRST_NAMES), source.choice(LAST_NAMES)
            cursor += 1
            favorites = tuple(source.sample(SUBJECT_IDS, k=2))
            tricky = source.choice([subject for subject in SUBJECT_IDS if subject not in favorites])
            trait = (
                source.choice(TRAIT_IDS)
                if source.random() < 0.5
                else None
            )
            students.append(
                StudentRecord(
                    student_id=f"student:{grade}:{index:02d}",
                    grade=grade,
                    first_name=first_name,
                    last_name=last_name,
                    favorites=favorites,
                    tricky=tricky,
                    trait=trait,
                    avatar=source.choice(AVATARS),
                )
            )
    return students
