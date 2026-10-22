"""Validation for chiptune.app tracks starred by Tinyrooms users."""

from __future__ import annotations

from dataclasses import dataclass


MAX_SONG_LENGTH = 500
MAX_LABEL_LENGTH = 120


@dataclass(frozen=True, slots=True)
class MusicTrack:
    """A validated chiptune.app song id or catalog path."""

    song: str
    label: str = ""

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-ready mapping of the track."""

        return {"song": self.song, "label": self.label}


def normalize_track(song: object, label: object = "") -> MusicTrack:
    """Validate and normalize a song id/path and optional label."""

    raw_song = str(song or "").strip()
    if not raw_song:
        raise ValueError("A music track needs a song id or path.")
    if len(raw_song) > MAX_SONG_LENGTH:
        raise ValueError("That music track is too long.")
    if any(ord(char) < 32 for char in raw_song):
        raise ValueError("That music track contains invalid characters.")
    text = str(label or "").strip()
    if len(text) > MAX_LABEL_LENGTH:
        raise ValueError("That music track label is too long.")
    return MusicTrack(song=raw_song, label=text)
