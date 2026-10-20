"""Persistent travel beacons shared between friends across worlds."""

from __future__ import annotations

from dataclasses import dataclass

from server.profiles import AccountRecord, ProfileRepository
from server.security import utc_now

MAX_BEACONS = 100


@dataclass(frozen=True, slots=True)
class BeaconView:
    """A serialized beacon awaiting one recipient."""

    from_account_id: str
    from_username: str
    world_id: str
    world_label: str
    room_id: str
    room_label: str
    created_at: str
    cross_world: bool

    def as_dict(self) -> dict[str, object]:
        """Serialize the beacon for the client."""

        return {
            "from_account_id": self.from_account_id,
            "from_username": self.from_username,
            "world_id": self.world_id,
            "world_label": self.world_label,
            "room_id": self.room_id,
            "room_label": self.room_label,
            "created_at": self.created_at,
            "cross_world": self.cross_world,
        }


def _beacon_entries(profile: dict[str, object]) -> list[dict[str, object]]:
    raw = profile.get("beacons")
    if not isinstance(raw, list):
        return []
    return [dict(entry) for entry in raw if isinstance(entry, dict)]


class BeaconService:
    """Stores beacons in the shared profile so they survive world changes."""

    def __init__(self, profiles: ProfileRepository) -> None:
        self._profiles = profiles

    def send(
        self,
        account: AccountRecord,
        target: AccountRecord,
        *,
        world_id: str,
        world_label: str,
        room_id: str,
        room_label: str,
    ) -> BeaconView:
        """Send or replace a beacon from *account* to a friend."""

        if target.id == account.id:
            raise ValueError("You cannot send a beacon to yourself.")
        sender_profile = self._profiles.get_user_profile(account.id)
        if sender_profile is None or target.id not in sender_profile.friends:
            raise ValueError("You can only send beacons to friends.")
        entry: dict[str, object] = {
            "from_account_id": account.id,
            "world_id": world_id,
            "world_label": world_label,
            "room_id": room_id,
            "room_label": room_label,
            "created_at": utc_now().isoformat(),
        }

        def mutate(profile: dict[str, object]) -> None:
            entries = [
                existing
                for existing in _beacon_entries(profile)
                if existing.get("from_account_id") != account.id
            ]
            entries.insert(0, entry)
            profile["beacons"] = entries[:MAX_BEACONS]

        self._profiles.update_profile(target.id, mutate)
        return self._view(entry, account.username_display, cross_world=False)

    def find(self, account_id: str, from_account_id: str) -> dict[str, object] | None:
        """Return one stored beacon without removing it."""

        profile = self._profiles.get_user_profile(account_id)
        if profile is None or from_account_id not in profile.friends:
            return None
        for entry in _beacon_entries(profile.profile):
            if entry.get("from_account_id") == from_account_id:
                return entry
        return None

    def remove(self, account_id: str, from_account_id: str) -> bool:
        """Remove one beacon, returning whether it existed."""

        removed = False

        def mutate(profile: dict[str, object]) -> None:
            nonlocal removed
            entries = _beacon_entries(profile)
            kept = [
                entry
                for entry in entries
                if entry.get("from_account_id") != from_account_id
            ]
            removed = len(kept) != len(entries)
            profile["beacons"] = kept

        self._profiles.update_profile(account_id, mutate)
        return removed

    def serialize(self, account_id: str, current_world_id: str) -> list[dict[str, object]]:
        """Build the recipient's beacon list, excluding non-friends."""

        profile = self._profiles.get_user_profile(account_id)
        if profile is None:
            return []
        friends = set(profile.friends)
        entries = [
            entry
            for entry in _beacon_entries(profile.profile)
            if entry.get("from_account_id") in friends
        ]
        sender_ids = [
            str(entry.get("from_account_id") or "")
            for entry in entries
            if entry.get("from_account_id")
        ]
        accounts = self._profiles.get_accounts_by_ids(sender_ids)
        views: list[dict[str, object]] = []
        for entry in entries:
            sender = accounts.get(str(entry.get("from_account_id") or ""))
            if sender is None:
                continue
            view = self._view(
                entry,
                sender.username_display,
                cross_world=str(entry.get("world_id") or "") != current_world_id,
            )
            views.append(view.as_dict())
        return views

    def _view(
        self,
        entry: dict[str, object],
        from_username: str,
        *,
        cross_world: bool,
    ) -> BeaconView:
        return BeaconView(
            from_account_id=str(entry.get("from_account_id") or ""),
            from_username=from_username,
            world_id=str(entry.get("world_id") or ""),
            world_label=str(entry.get("world_label") or ""),
            room_id=str(entry.get("room_id") or ""),
            room_label=str(entry.get("room_label") or ""),
            created_at=str(entry.get("created_at") or ""),
            cross_world=cross_world,
        )
