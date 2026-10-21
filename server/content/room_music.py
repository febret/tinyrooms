"""Authored per-room music defaults."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.content.common import ContentError
from server.content.music import normalize_track


@dataclass(frozen=True, slots=True)
class RoomMusicDefinition:
    """An authored default track for a room's chiptune.app player."""

    song: str
    label: str = ""


def load_room_music(raw_value: Any, room_id: str) -> RoomMusicDefinition | None:
    """Validate an authored room music value."""

    if raw_value is None:
        return None
    if isinstance(raw_value, str):
        raw_song = raw_value
        raw_label = ""
    elif isinstance(raw_value, dict):
        raw_song = raw_value.get("song", "")
        raw_label = raw_value.get("label", "")
    else:
        raise ContentError(f"Room '{room_id}' music must be a song id/path string or a mapping.")
    try:
        track = normalize_track(raw_song, raw_label)
    except ValueError as exc:
        raise ContentError(f"Room '{room_id}' music: {exc}") from exc
    return RoomMusicDefinition(song=track.song, label=track.label)
