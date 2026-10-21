"""In-memory per-room chiptune.app music selection.

The hidden chiptune.app player is driven entirely by the track the server
reports for a room. Authored ``music:`` defaults come from the world definition;
runtime changes live here in memory and are broadcast as ``room.music`` events.
"""

from __future__ import annotations

from server.content.music import MusicTrack, normalize_track
from server.content.worlds import WorldDefinition


class MusicService:
    """Owns the current track for every room, overriding authored defaults in memory."""

    def __init__(self, world: WorldDefinition) -> None:
        self._world = world
        self._overrides: dict[str, tuple[MusicTrack | None, str]] = {}

    def _default(self, room_id: str) -> MusicTrack | None:
        room = self._world.rooms.get(room_id)
        if room is None or room.music is None:
            return None
        return MusicTrack(song=room.music.song, label=room.music.label)

    @staticmethod
    def _payload(track: MusicTrack | None, updated_by: str) -> dict[str, object] | None:
        if track is None:
            return None
        return {**track.to_payload(), "updated_by": updated_by}

    def current(self, room_id: str) -> dict[str, object] | None:
        """Return the room's current track payload, or ``None`` for silence."""

        if room_id in self._overrides:
            track, updated_by = self._overrides[room_id]
        else:
            track, updated_by = self._default(room_id), ""
        return self._payload(track, updated_by)

    def is_overridden(self, room_id: str) -> bool:
        """Return whether the room has a runtime override in place."""

        return room_id in self._overrides

    def set(self, room_id: str, song: object, *, label: object = "", updated_by: str) -> dict[str, object]:
        """Set a room track and return the event to broadcast."""

        self._require_room(room_id)
        track = normalize_track(song, label)
        self._overrides[room_id] = (track, updated_by)
        return self._event(room_id, track, updated_by)

    def silence(self, room_id: str, *, updated_by: str) -> dict[str, object]:
        """Explicitly silence a room regardless of its authored default."""

        self._require_room(room_id)
        self._overrides[room_id] = (None, updated_by)
        return self._event(room_id, None, updated_by)

    def reset(self, room_id: str, *, updated_by: str) -> dict[str, object]:
        """Drop a runtime override and fall back to the authored default."""

        self._require_room(room_id)
        self._overrides.pop(room_id, None)
        return self._event(room_id, self._default(room_id), updated_by)

    def _require_room(self, room_id: str) -> None:
        if room_id not in self._world.rooms:
            raise ValueError("That room does not exist.")

    @staticmethod
    def _event(room_id: str, track: MusicTrack | None, updated_by: str) -> dict[str, object]:
        return {
            "type": "room.music",
            "room_id": room_id,
            "track": MusicService._payload(track, updated_by),
            "updated_by": updated_by,
        }
