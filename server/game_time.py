"""Game calendar helpers shared by timezone-aware services."""

from __future__ import annotations

from datetime import datetime, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from server.security import utc_now


def game_date(iso_timestamp: str | None, timezone: ZoneInfo) -> str:
    """Return the configured-timezone game date for a stored UTC timestamp."""

    if not iso_timestamp:
        return ""
    try:
        parsed = datetime.fromisoformat(iso_timestamp)
    except (TypeError, ValueError):
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime_timezone.utc)
    return parsed.astimezone(timezone).date().isoformat()


def game_month(iso_timestamp: str | None, timezone: ZoneInfo) -> tuple[int, int] | None:
    """Return the configured-timezone (year, month) for a stored timestamp."""

    local = game_date(iso_timestamp, timezone)
    if not local:
        return None
    year, month, _ = local.split("-")
    return int(year), int(month)


def today_in(timezone: ZoneInfo) -> str:
    """Return the current game date in the configured timezone."""

    return utc_now().astimezone(timezone).date().isoformat()


def current_game_month(timezone: ZoneInfo) -> tuple[int, int]:
    """Return the current game (year, month) in the configured timezone."""

    now = utc_now().astimezone(timezone)
    return now.year, now.month
