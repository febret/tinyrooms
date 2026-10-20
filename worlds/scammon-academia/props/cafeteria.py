"""Cafeteria crowd manager for a sprite-mode room."""

from __future__ import annotations

from datetime import datetime, timedelta
import random

from mods.classrooms.lessons import OFFSTAGE_ROOM

CAFETERIA_ROOM = "cafeteria"
MAX_STUDENTS = 10
JOIN_TARGET = (5, 8)
CHANGE_INTERVAL = (3.0, 7.0)


def _students(context) -> list[dict[str, object]]:
    return [
        peep
        for peep in (context.room.get("peeps") or [])
        if str(peep.get("id", "")).startswith("student:")
    ]


def _offstage_students(context) -> list[dict[str, object]]:
    return [
        peep
        for peep in context.peeps_in(OFFSTAGE_ROOM)
        if str(peep.get("id", "")).startswith("student:")
    ]


def _deadline(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _next_deadline(context) -> str:
    seconds = random.uniform(*CHANGE_INTERVAL)
    return (context.now + timedelta(seconds=seconds)).isoformat()


def _join(context, peep_id: str) -> None:
    context.move_peep(peep_id, CAFETERIA_ROOM)


def _leave(context, peep_id: str) -> None:
    context.move_peep(peep_id, OFFSTAGE_ROOM)


def on_enter(context, event):
    """Seed a lunch crowd when someone first walks into the cafeteria."""

    if not context.sprites_enabled or _students(context):
        return
    candidates = _offstage_students(context)
    random.shuffle(candidates)
    target = min(MAX_STUDENTS, random.randint(*JOIN_TARGET))
    for peep in candidates[:target]:
        _join(context, str(peep["id"]))
    context.state["next_change_at"] = _next_deadline(context)


def on_tick(context, event):
    """Let students trickle in and out, never exceeding the room cap."""

    if not context.sprites_enabled:
        return
    deadline = _deadline(context.state.get("next_change_at"))
    if deadline is None or context.now < deadline:
        if deadline is None:
            context.state["next_change_at"] = _next_deadline(context)
        return
    context.state["next_change_at"] = _next_deadline(context)

    students = _students(context)
    candidates = _offstage_students(context)
    if len(students) < MAX_STUDENTS and candidates and (not students or random.random() < 0.6):
        _join(context, str(random.choice(candidates)["id"]))
        return
    if students and random.random() < 0.5:
        _leave(context, str(random.choice(students)["id"]))
