"""Friendships and friend requests with offline persistence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from server.profiles import AccountRecord, ProfileRepository, UserProfileRecord
from server.security import utc_now
from server.state.migrations import DatabaseHub

MAX_FRIENDS = 100
MAX_PENDING_REQUESTS = 100


@dataclass(frozen=True, slots=True)
class FriendView:
    """A serialized friend or request entry."""

    account_id: str
    username: str
    online: bool


@dataclass(frozen=True, slots=True)
class FriendsPayload:
    """The Friends panel payload for one user."""

    friends: tuple[FriendView, ...]
    incoming: tuple[FriendView, ...]
    outgoing: tuple[FriendView, ...]

    def as_dict(self) -> dict[str, object]:
        """Serialize the payload for the client."""

        def render(entries: tuple[FriendView, ...]) -> list[dict[str, object]]:
            return [
                {"account_id": entry.account_id, "username": entry.username, "online": entry.online}
                for entry in entries
            ]

        return {
            "friends": render(self.friends),
            "incoming": render(self.incoming),
            "outgoing": render(self.outgoing),
        }


def _list_key(profile: dict[str, object], key: str) -> list[str]:
    raw = profile.get(key)
    if not isinstance(raw, list):
        return []
    return [str(entry) for entry in raw]


class FriendsService:
    """Owns the friend-request lifecycle and mutual relationship creation."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        is_online: Callable[[str], bool] | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._is_online = is_online or (lambda account_id: False)

    def _profile(self, account_id: str) -> UserProfileRecord:
        profile = self._profiles.get_user_profile(account_id)
        if profile is None:
            raise ValueError("Unknown account.")
        return profile

    def _mutate(self, connection, account_id: str, mutate) -> None:
        self._profiles.update_profile_in_transaction(connection, account_id, mutate)

    def send_request(self, account: AccountRecord, target: AccountRecord) -> str:
        """Send a friend request, auto-accepting a mutual pending request."""

        if target.id == account.id:
            raise ValueError("You cannot add yourself as a friend.")
        with self._hub.transaction() as connection:
            actor = self._profile(account.id)
            other = self._profile(target.id)
            if len(actor.friends) >= MAX_FRIENDS:
                raise ValueError("Your friends list is full.")
            if len(_list_key(actor.profile, "friend_requests_sent")) >= MAX_PENDING_REQUESTS:
                raise ValueError("You have too many pending friend requests.")
            if len(_list_key(other.profile, "friend_requests_received")) >= MAX_PENDING_REQUESTS:
                raise ValueError("That peep has too many pending friend requests.")
            if target.id in actor.friends:
                raise ValueError(f"{target.username_display} is already your friend.")
            if target.id in actor.profile.get("friend_requests_sent", []):
                raise ValueError("That friend request is already pending.")
            if account.id in other.profile.get("friend_requests_sent", []):
                self._accept(connection, account.id, target.id)
                return "friends"
            if target.id in actor.profile.get("friend_requests_received", []):
                self._accept(connection, account.id, target.id)
                return "friends"

            def add_sent(profile: dict[str, object]) -> None:
                sent = _list_key(profile, "friend_requests_sent")
                if target.id not in sent:
                    sent.append(target.id)
                profile["friend_requests_sent"] = sent

            def add_received(profile: dict[str, object]) -> None:
                received = _list_key(profile, "friend_requests_received")
                if account.id not in received:
                    received.append(account.id)
                profile["friend_requests_received"] = received

            self._mutate(connection, account.id, add_sent)
            self._mutate(connection, target.id, add_received)
        return "requested"

    def _accept(self, connection, account_id: str, other_id: str) -> None:
        def link_first(profile: dict[str, object]) -> None:
            friends = _list_key(profile, "friends")
            if other_id not in friends:
                friends.append(other_id)
            profile["friends"] = friends
            profile["friend_requests_sent"] = [
                entry for entry in _list_key(profile, "friend_requests_sent") if entry != other_id
            ]
            profile["friend_requests_received"] = [
                entry for entry in _list_key(profile, "friend_requests_received") if entry != other_id
            ]
            added = profile.get("friend_added_at")
            if not isinstance(added, dict):
                added = {}
            added.setdefault(other_id, utc_now().isoformat())
            profile["friend_added_at"] = added

        def link_second(profile: dict[str, object]) -> None:
            friends = _list_key(profile, "friends")
            if account_id not in friends:
                friends.append(account_id)
            profile["friends"] = friends
            profile["friend_requests_sent"] = [
                entry for entry in _list_key(profile, "friend_requests_sent") if entry != account_id
            ]
            profile["friend_requests_received"] = [
                entry for entry in _list_key(profile, "friend_requests_received") if entry != account_id
            ]
            added = profile.get("friend_added_at")
            if not isinstance(added, dict):
                added = {}
            added.setdefault(account_id, utc_now().isoformat())
            profile["friend_added_at"] = added

        self._mutate(connection, account_id, link_first)
        self._mutate(connection, other_id, link_second)

    def accept_request(self, account: AccountRecord, requester_id: str) -> None:
        """Accept an incoming request, creating the single mutual friendship."""

        with self._hub.transaction() as connection:
            profile = self._profile(account.id)
            if requester_id not in _list_key(profile.profile, "friend_requests_received"):
                raise ValueError("There is no pending request from that peep.")
            if len(profile.friends) >= MAX_FRIENDS:
                raise ValueError("Your friends list is full.")
            if len(self._profile(requester_id).friends) >= MAX_FRIENDS:
                raise ValueError("That peep's friends list is full.")
            self._accept(connection, account.id, requester_id)

    def decline_request(self, account: AccountRecord, requester_id: str) -> None:
        """Decline an incoming request without creating a friendship."""

        with self._hub.transaction() as connection:
            profile = self._profile(account.id)
            if requester_id not in _list_key(profile.profile, "friend_requests_received"):
                raise ValueError("There is no pending request from that peep.")

            def drop_received(data: dict[str, object]) -> None:
                data["friend_requests_received"] = [
                    entry for entry in _list_key(data, "friend_requests_received") if entry != requester_id
                ]

            def drop_sent(data: dict[str, object]) -> None:
                data["friend_requests_sent"] = [
                    entry for entry in _list_key(data, "friend_requests_sent") if entry != account.id
                ]

            self._mutate(connection, account.id, drop_received)
            self._mutate(connection, requester_id, drop_sent)

    def cancel_request(self, account: AccountRecord, target_id: str) -> None:
        """Cancel an outgoing request."""

        with self._hub.transaction() as connection:
            profile = self._profile(account.id)
            if target_id not in _list_key(profile.profile, "friend_requests_sent"):
                raise ValueError("There is no pending request to that peep.")

            def drop_sent(data: dict[str, object]) -> None:
                data["friend_requests_sent"] = [
                    entry for entry in _list_key(data, "friend_requests_sent") if entry != target_id
                ]

            def drop_received(data: dict[str, object]) -> None:
                data["friend_requests_received"] = [
                    entry for entry in _list_key(data, "friend_requests_received") if entry != account.id
                ]

            self._mutate(connection, account.id, drop_sent)
            self._mutate(connection, target_id, drop_received)

    def remove_friend(self, account: AccountRecord, target_id: str) -> None:
        """Remove a friendship for both users."""

        with self._hub.transaction() as connection:
            profile = self._profile(account.id)
            if target_id not in profile.friends:
                raise ValueError("That peep is not on your friends list.")

            def unlink(data: dict[str, object], other: str) -> None:
                data["friends"] = [entry for entry in _list_key(data, "friends") if entry != other]

            self._mutate(connection, account.id, lambda data: unlink(data, target_id))
            self._mutate(connection, target_id, lambda data: unlink(data, account.id))

    def serialize(self, account_id: str) -> FriendsPayload:
        """Build the Friends panel payload with current online state."""

        profile = self._profile(account_id)
        friend_ids = _list_key(profile.profile, "friends")
        incoming_ids = _list_key(profile.profile, "friend_requests_received")
        outgoing_ids = _list_key(profile.profile, "friend_requests_sent")
        accounts = self._profiles.get_accounts_by_ids([*friend_ids, *incoming_ids, *outgoing_ids])

        def render(ids: list[str]) -> tuple[FriendView, ...]:
            entries: list[FriendView] = []
            for account_id_value in ids:
                record = accounts.get(account_id_value)
                if record is None:
                    continue
                entries.append(
                    FriendView(
                        account_id=record.id,
                        username=record.username_display,
                        online=bool(self._is_online(record.id)),
                    )
                )
            return tuple(entries)

        return FriendsPayload(
            friends=render(friend_ids),
            incoming=render(incoming_ids),
            outgoing=render(outgoing_ids),
        )
