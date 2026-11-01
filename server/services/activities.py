"""Activity session lifecycle service."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from collections.abc import Mapping
import hashlib
import hmac
import secrets
import threading
import uuid

from server.config import AppConfig


@dataclass(frozen=True, slots=True)
class ActivitySession:
    """Server-owned, in-memory activity; only one is current per account.

    The id identifies this launch in iframe/bridge traffic, not the activity kind.
    Sessions are not persisted across process restarts.
    """

    id: str
    account_id: str
    username: str
    kind: str
    title: str
    iframe_url: str
    # Travel away from room_id closes the activity.
    room_id: str
    bridge_url: str
    # Per-launch signing key stays server-side; clients receive only its token.
    secret: str
    # Requests window attention (including a minimized-window indicator).
    attention: bool = False
    # Launch-specific guest configuration, copied into the client descriptor.
    config: dict[str, object] = field(default_factory=dict)

    @property
    def token(self) -> str:
        """Return the HMAC signature that signs this session's results."""

        payload = f"{self.account_id}:{self.id}:{self.kind}"
        return hmac.new(self.secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


class ActivityService:
    """Manage one live activity per account."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._sessions: dict[str, ActivitySession] = {}
        # Memory-only activity runtime state. Behavior state for room activity
        # controllers and their public snapshots live here so the realtime
        # tick/stream path never touches SQLite; everything resets on restart.
        self._behavior_states: dict[str, dict[str, object]] = {}
        self._public_states: dict[tuple[str, str], dict[str, object]] = {}

    def feature_enabled(self, feature: str) -> bool:
        """Return whether a feature flag is enabled, normalizing separators."""

        normalized = feature.replace("-", "_")
        return any(
            enabled.replace("-", "_") == normalized for enabled in self._config.features
        )

    def _make_session(
        self,
        *,
        account_id: str,
        kind: str,
        title: str,
        room_id: str,
        username: str = "",
        config: dict[str, object] | None = None,
    ) -> ActivitySession:
        activity_id = str(uuid.uuid4())
        return ActivitySession(
            id=activity_id,
            account_id=account_id,
            username=str(username or ""),
            kind=kind,
            title=title,
            iframe_url=f"/activities/{kind}/?session_id={activity_id}",
            room_id=room_id,
            bridge_url=f"/api/activities/{activity_id}/bridge",
            secret=secrets.token_urlsafe(32),
            config=dict(config or {}),
        )

    def get(self, account_id: str) -> ActivitySession | None:
        """Return the current activity for an account."""

        with self._lock:
            return self._sessions.get(account_id)

    def ensure_initial_sticker(self, account_id: str, room_id: str, username: str = "") -> ActivitySession:
        """Ensure the initial sticker activity exists for the account."""

        with self._lock:
            current = self._sessions.get(account_id)
            if current is not None and current.kind == "sticker-designer":
                return current
            session = self._make_session(
                account_id=account_id,
                kind="sticker-designer",
                title="Sticker Designer",
                room_id=room_id,
                username=username,
            )
            self._sessions[account_id] = session
            return session

    def start(
        self,
        *,
        account_id: str,
        kind: str,
        title: str,
        room_id: str,
        replace_existing: bool = False,
        username: str = "",
        config: dict[str, object] | None = None,
    ) -> tuple[ActivitySession, ActivitySession | None]:
        """Start an activity, optionally replacing the current one."""

        with self._lock:
            current = self._sessions.get(account_id)
            if current is not None and not replace_existing:
                if current.kind == kind and current.room_id == room_id:
                    return current, None
                raise ValueError("Another activity is already running.")
            session = self._make_session(
                account_id=account_id,
                kind=kind,
                title=title,
                room_id=room_id,
                username=username or (current.username if current is not None else ""),
                config=config,
            )
            self._sessions[account_id] = session
            return session, current

    def close(self, account_id: str) -> ActivitySession | None:
        """Close the current activity, if present."""

        with self._lock:
            return self._sessions.pop(account_id, None)

    def close_if_room_changed(self, account_id: str, new_room_id: str) -> ActivitySession | None:
        """Close the current activity when the user moves to another room."""

        with self._lock:
            current = self._sessions.get(account_id)
            if current is None:
                return None
            if current.room_id != new_room_id:
                return self._sessions.pop(account_id)
            return None

    def mark_attention(self, account_id: str) -> ActivitySession | None:
        """Mark the current activity as needing attention."""

        with self._lock:
            current = self._sessions.get(account_id)
            if current is None:
                return None
            updated = replace(current, attention=True)
            self._sessions[account_id] = updated
            return updated

    def sessions_in_room(self, room_id: str, kind: str = "") -> list[ActivitySession]:
        """Return open sessions for a room, optionally filtered by activity kind."""

        with self._lock:
            return [
                session
                for session in self._sessions.values()
                if session.room_id == room_id and (not kind or session.kind == kind)
            ]

    def has_sessions(self, room_id: str, kind: str = "") -> bool:
        """Return whether any open session matches a room and activity kind."""

        with self._lock:
            return any(
                session.room_id == room_id and (not kind or session.kind == kind)
                for session in self._sessions.values()
            )

    def behavior_state(self, namespace: str, instance_id: str) -> dict[str, object]:
        """Return the live behavior state dict for an activity controller."""

        key = f"{namespace}:{instance_id}"
        with self._lock:
            return self._behavior_states.setdefault(key, {})

    def save_behavior_state(self, namespace: str, instance_id: str, state: Mapping[str, object]) -> None:
        """Persist an activity controller's behavior state in memory only."""

        key = f"{namespace}:{instance_id}"
        with self._lock:
            self._behavior_states[key] = dict(state) if not isinstance(state, dict) else state

    def room_state(self, room_id: str, kind: str) -> dict[str, object] | None:
        """Return the latest public activity state for a room and kind."""

        with self._lock:
            stored = self._public_states.get((str(room_id), str(kind)))
            return dict(stored) if isinstance(stored, dict) else None

    def set_room_state(self, room_id: str, kind: str, state: Mapping[str, object]) -> None:
        """Store the latest public activity state for snapshots and stream diffs."""

        with self._lock:
            self._public_states[(str(room_id), str(kind))] = (
                dict(state) if isinstance(state, dict) else {}
            )

    def room_states(self, room_id: str) -> dict[str, dict[str, object]]:
        """Return copies of every stored public activity state for a room."""

        with self._lock:
            return {
                kind: dict(state)
                for (stored_room, kind), state in self._public_states.items()
                if stored_room == room_id and isinstance(state, dict)
            }

    def serialize(self, activity: ActivitySession | None) -> dict[str, object] | None:
        """Serialize an activity descriptor for HTTP or WebSocket clients."""

        if activity is None:
            return None
        return {
            "id": activity.id,
            "kind": activity.kind,
            "title": activity.title,
            "iframe_url": activity.iframe_url,
            "bridge_url": activity.bridge_url,
            "room_id": activity.room_id,
            "attention": activity.attention,
            "token": activity.token,
            "config": dict(activity.config),
        }
