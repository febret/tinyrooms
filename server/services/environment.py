"""Persistent room environment state with revisioned broadcasts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json

from server.content.worlds import WorldDefinition
from server.security import utc_now
from server.state.migrations import DatabaseHub
from server.state.world_state import WorldStateRepository


ENVIRONMENT_KEYS = ("lighting", "hidden_props", "disabled_exits", "disabled_actions")


@dataclass(frozen=True, slots=True)
class EnvironmentUpdate:
    """A revisioned room environment change ready to broadcast."""

    room_id: str
    revision: int
    environment: dict[str, object]

    def event(self) -> dict[str, object]:
        """Serialize the update as a room broadcast event."""

        return {
            "type": "room.environment",
            "room_id": self.room_id,
            "revision": self.revision,
            "environment": self.environment,
        }


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class EnvironmentService:
    """Reads and writes persistent room environment state."""

    def __init__(
        self,
        hub: DatabaseHub,
        world: WorldDefinition,
        world_state: WorldStateRepository,
    ) -> None:
        self._hub = hub
        self._world = world
        self._world_state = world_state

    def get(self, room_id: str) -> dict[str, object]:
        """Return the persisted environment for a room."""

        environment, _revision = self._world_state.read_room_environment(room_id)
        return environment

    def snapshot(self, room_id: str) -> tuple[dict[str, object], int]:
        """Return the persisted environment and layout revision in one read."""

        return self._world_state.read_room_environment(room_id)

    def revision(self, room_id: str) -> int:
        """Return the current layout revision for a room."""

        _environment, revision = self._world_state.read_room_environment(room_id)
        return revision

    def set(self, room_id: str, patch: dict[str, object]) -> EnvironmentUpdate:
        """Merge a patch into the room environment and bump its revision."""

        with self._hub.transaction() as connection:
            return self.set_in_transaction(connection, room_id, patch)

    def set_in_transaction(self, connection, room_id: str, patch: dict[str, object]) -> EnvironmentUpdate:
        """Merge a patch inside a caller-owned transaction."""

        if room_id not in self._world.rooms:
            raise ValueError("That room does not exist.")
        for key in patch:
            if key not in ENVIRONMENT_KEYS:
                raise ValueError(f"Unknown environment key '{key}'.")
        environment, revision = self._read(connection, room_id)
        for key, value in patch.items():
            if value is None:
                environment.pop(key, None)
            else:
                environment[key] = value
        revision += 1
        self._world_state.write_room_environment(
            connection,
            room_id=room_id,
            environment=environment,
            revision=revision,
        )
        return EnvironmentUpdate(room_id=room_id, revision=revision, environment=dict(environment))

    def _read(self, connection, room_id: str) -> tuple[dict[str, object], int]:
        row = connection.execute(
            "SELECT environment_json, layout_revision FROM world.room_states WHERE room_id = ?",
            (room_id,),
        ).fetchone()
        if row is None:
            return {}, 0
        try:
            environment = json.loads(row["environment_json"])
        except (TypeError, ValueError):
            environment = {}
        return (environment if isinstance(environment, dict) else {}), int(row["layout_revision"])

    def expire(self, room_id: str) -> EnvironmentUpdate | None:
        """Remove expired entries and return a revisioned update when changed."""

        environment = self.get(room_id)
        now = utc_now()
        patch: dict[str, object] = {}
        for key in ENVIRONMENT_KEYS:
            if key == "lighting":
                continue
            value = environment.get(key)
            if not isinstance(value, dict):
                continue
            kept = {
                entry_key: entry
                for entry_key, entry in value.items()
                if not _is_expired(entry, now)
            }
            if kept != value:
                patch[key] = kept if kept else None
        if not patch:
            return None
        return self.set(room_id, patch)

    def is_prop_visible(self, room_id: str, prop_instance_id: str) -> bool:
        """Return whether a prop instance is visible in the room."""

        hidden = self.get(room_id).get("hidden_props")
        return not isinstance(hidden, dict) or prop_instance_id not in hidden

    def is_exit_enabled(self, room_id: str, exit_id: str) -> bool:
        """Return whether an exit is currently available."""

        disabled = self.get(room_id).get("disabled_exits")
        return not isinstance(disabled, dict) or exit_id not in disabled

    def is_action_enabled(self, room_id: str, action: str) -> bool:
        """Return whether an action verb is currently allowed in a room."""

        disabled = self.get(room_id).get("disabled_actions")
        return not isinstance(disabled, dict) or action not in disabled

    def lighting(self, room_id: str) -> str:
        """Return the room lighting mode, defaulting to the definition."""

        value = self.get(room_id).get("lighting")
        if value in {"normal", "dark"}:
            return str(value)
        return "dark" if self._world.rooms[room_id].dark else "normal"


def _is_expired(entry: object, now: datetime) -> bool:
    if not isinstance(entry, dict):
        return False
    expires_at = _parse_timestamp(entry.get("expires_at"))
    return expires_at is not None and expires_at <= now
