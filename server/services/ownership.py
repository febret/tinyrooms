"""Room ownership grants and edit authorization."""

from __future__ import annotations

from collections.abc import Callable

from server.content.worlds import WorldDefinition
from server.profiles import AccountRecord, ProfileRepository
from server.state.migrations import DatabaseHub
from server.state.world_state import WorldStateRepository


class OwnershipService:
    """Owns room-owner state and centralizes edit authorization."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        world_state: WorldStateRepository,
        world: WorldDefinition,
        has_power: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._world_state = world_state
        self._world = world
        self._has_power = has_power or (lambda _account_id, _power: False)

    def owner_of(self, room_id: str) -> str | None:
        """Return the account ID that owns *room_id*, if any."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT owner_account_id FROM world.room_states WHERE room_id = ?",
                (room_id,),
            ).fetchone()
        if row is None:
            return None
        owner = row["owner_account_id"]
        return str(owner) if owner else None

    def _write_owner(self, connection, room_id: str, account_id: str | None) -> None:
        cursor = connection.execute(
            "UPDATE world.room_states SET owner_account_id = ? WHERE room_id = ?",
            (account_id, room_id),
        )
        if cursor.rowcount != 1:
            connection.execute(
                """
                INSERT INTO world.room_states (room_id, initialized, owner_account_id, props_json)
                VALUES (?, 0, ?, '{}')
                """,
                (room_id, account_id),
            )

    def grant(self, room_id: str, account_id: str) -> None:
        """Assign room ownership to an account."""

        if room_id not in self._world.rooms:
            raise ValueError("That room does not exist.")
        if self._profiles.get_account_by_id(account_id) is None:
            raise ValueError("That account does not exist.")
        with self._hub.transaction() as connection:
            self.grant_in_transaction(connection, room_id, account_id)

    def grant_in_transaction(self, connection, room_id: str, account_id: str) -> None:
        """Assign ownership using an existing transaction connection."""

        if room_id not in self._world.rooms:
            raise ValueError("That room does not exist.")
        if self._profiles.get_account_by_id(account_id) is None:
            raise ValueError("That account does not exist.")
        previous = self.owner_of(room_id)
        self._write_owner(connection, room_id, account_id)
        self._set_mirror(connection, account_id, room_id, owned=True)
        if previous is not None and previous != account_id:
            self._set_mirror(connection, previous, room_id, owned=False)

    def revoke(self, room_id: str) -> None:
        """Clear ownership for a room."""

        previous = self.owner_of(room_id)
        with self._hub.transaction() as connection:
            self._write_owner(connection, room_id, None)
            if previous is not None:
                self._set_mirror(connection, previous, room_id, owned=False)

    def modify(self, room_id: str, account_id: str) -> None:
        """Replace the owner of a room."""

        self.grant(room_id, account_id)

    def _set_mirror(self, connection, account_id: str, room_id: str, *, owned: bool) -> None:
        profile = self._profiles.get_user_profile(account_id)
        ownership = dict(profile.ownership) if profile is not None else {}
        raw = ownership.get("rooms")
        rooms = [str(entry) for entry in raw] if isinstance(raw, list) else []
        if owned and room_id not in rooms:
            rooms.append(room_id)
        elif not owned:
            rooms = [entry for entry in rooms if entry != room_id]
        ownership["rooms"] = rooms
        self._profiles.write_ownership(connection, account_id, ownership)

    def can_edit(self, account: AccountRecord, room_id: str) -> bool:
        """Return whether an account may edit a room's decorative layout.

        Room owners and the builder power may edit; admins may edit any room.
        """

        if self.owner_of(room_id) == account.id:
            return True
        return bool(
            self._has_power(account.id, "builder") or self._has_power(account.id, "admin")
        )
