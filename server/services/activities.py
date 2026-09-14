"""Activity session lifecycle service."""

from __future__ import annotations

from dataclasses import dataclass, replace
import threading
import uuid

from server.config import AppConfig


@dataclass(frozen=True, slots=True)
class ActivitySession:
    """A live activity session owned by the server."""

    id: str
    account_id: str
    kind: str
    title: str
    iframe_url: str
    room_bound: bool
    room_id: str | None
    bridge_url: str
    attention: bool = False


class ActivityService:
    """Manage one live activity per account."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._sessions: dict[str, ActivitySession] = {}

    @property
    def developer_sample_enabled(self) -> bool:
        """Return whether the development-only sample activity is enabled."""

        return bool(
            {"dev_sample_activity", "dev-sample-activity"} & self._config.features
        )

    def _make_session(
        self,
        *,
        account_id: str,
        kind: str,
        title: str,
        room_bound: bool,
        room_id: str | None,
    ) -> ActivitySession:
        activity_id = str(uuid.uuid4())
        return ActivitySession(
            id=activity_id,
            account_id=account_id,
            kind=kind,
            title=title,
            iframe_url=f"/activities/{kind}/?session_id={activity_id}",
            room_bound=room_bound,
            room_id=room_id,
            bridge_url=f"/api/activities/{activity_id}/bridge",
        )

    def get(self, account_id: str) -> ActivitySession | None:
        """Return the current activity for an account."""

        with self._lock:
            return self._sessions.get(account_id)

    def ensure_initial_sticker(self, account_id: str) -> ActivitySession:
        """Ensure the initial sticker activity exists for the account."""

        with self._lock:
            current = self._sessions.get(account_id)
            if current is not None and current.kind == "sticker-designer":
                return current
            session = self._make_session(
                account_id=account_id,
                kind="sticker-designer",
                title="Sticker Designer",
                room_bound=False,
                room_id=None,
            )
            self._sessions[account_id] = session
            return session

    def start(
        self,
        *,
        account_id: str,
        kind: str,
        title: str,
        room_bound: bool,
        room_id: str | None,
        replace_existing: bool = False,
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
                room_bound=room_bound,
                room_id=room_id,
            )
            self._sessions[account_id] = session
            return session, current

    def close(self, account_id: str) -> ActivitySession | None:
        """Close the current activity, if present."""

        with self._lock:
            return self._sessions.pop(account_id, None)

    def close_if_room_bound(self, account_id: str, new_room_id: str) -> ActivitySession | None:
        """Close the current activity if it was bound to another room."""

        with self._lock:
            current = self._sessions.get(account_id)
            if current is None:
                return None
            if current.room_bound and current.room_id != new_room_id:
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
            "room_bound": activity.room_bound,
            "room_id": activity.room_id,
            "attention": activity.attention,
        }
