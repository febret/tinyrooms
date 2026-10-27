"""Shared cooldown helpers for built-in prop behaviors."""

from __future__ import annotations

from datetime import datetime, timedelta


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def remaining_seconds(context, cooldown_seconds: float) -> float:
    """Return the seconds left on a prop's shared last-used cooldown."""

    last_used = _parse_timestamp(context.state.get("last_used_at"))
    if last_used is None:
        return 0.0
    if last_used.tzinfo is None:
        last_used = last_used.replace(tzinfo=context.now.tzinfo)
    remaining = (last_used + timedelta(seconds=cooldown_seconds) - context.now).total_seconds()
    return max(0.0, remaining)


def mark_used(context) -> None:
    """Record that the acting prop behavior completed at the current time."""

    context.state["last_used_at"] = context.now.isoformat()
