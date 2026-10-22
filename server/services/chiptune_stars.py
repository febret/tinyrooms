"""Per-user chiptune.app stars shared across worlds."""

from __future__ import annotations

from server.content.music import normalize_track
from server.profiles import ProfileRepository, UserProfileRecord
from server.security import utc_now

MAX_STARRED_TRACKS = 100


class ChiptuneStarService:
    """Store and query chiptune.app tracks starred by Tinyrooms users."""

    def __init__(self, profiles: ProfileRepository) -> None:
        self._profiles = profiles

    def _profile(self, account_id: str) -> UserProfileRecord:
        profile = self._profiles.get_user_profile(account_id)
        if profile is None:
            raise ValueError("Unknown account.")
        return profile

    @staticmethod
    def _entries(profile: dict[str, object]) -> list[dict[str, object]]:
        raw = profile.get("starred_tracks")
        if not isinstance(raw, list):
            return []
        entries: list[dict[str, object]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            song = str(entry.get("song") or "").strip()
            if not song:
                continue
            entries.append(
                {
                    "song": song,
                    "label": str(entry.get("label") or "").strip(),
                    "starred_at": str(entry.get("starred_at") or ""),
                }
            )
        return entries

    def starred(self, account_id: str) -> list[dict[str, object]]:
        """Return the user's starred tracks in reverse chronological order."""

        return self._entries(self._profile(account_id).profile)

    def set_starred(
        self,
        account_id: str,
        song: object,
        label: object = "",
        *,
        starred: bool = True,
    ) -> list[dict[str, object]]:
        """Star or unstar a track and return the updated list."""

        track = normalize_track(song, label)

        def mutate(profile: dict[str, object]) -> None:
            entries = [
                entry for entry in self._entries(profile) if entry["song"] != track.song
            ]
            if starred:
                if len(entries) >= MAX_STARRED_TRACKS:
                    raise ValueError("Your starred track list is full.")
                entries.insert(
                    0,
                    {
                        "song": track.song,
                        "label": track.label,
                        "starred_at": utc_now().isoformat(),
                    },
                )
            profile["starred_tracks"] = entries

        updated = self._profiles.update_profile(account_id, mutate)
        return self._entries(updated.profile)

    def starred_counts(self, account_id: str, limit: int = 20) -> list[dict[str, object]]:
        """Return tracks starred by other users with their star counts."""

        return self._profiles.starred_track_counts(account_id, limit)
