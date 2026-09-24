"""Bounded in-memory audit ring for privileged mission-control actions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import threading

from server.security import utc_now


@dataclass(frozen=True, slots=True)
class McAuditEntry:
    """One recorded mission-control action."""

    at: str
    actor: str
    action: str
    target: str | None
    result: str
    detail: dict[str, object]


class McAuditLog:
    """A bounded, newest-first ring of mission-control audit entries."""

    def __init__(self, limit: int = 500) -> None:
        self._entries: deque[McAuditEntry] = deque(maxlen=limit)
        self._lock = threading.Lock()

    def record(
        self,
        actor: str,
        action: str,
        *,
        target: str | None = None,
        result: str = "ok",
        detail: dict[str, object] | None = None,
    ) -> None:
        """Append one entry to the audit ring."""

        entry = McAuditEntry(
            at=utc_now().isoformat(),
            actor=actor,
            action=action,
            target=target,
            result=result,
            detail=dict(detail or {}),
        )
        with self._lock:
            self._entries.append(entry)

    def entries(self, limit: int = 100) -> list[dict[str, object]]:
        """Return the newest entries first."""

        with self._lock:
            snapshot = list(self._entries)
        snapshot.reverse()
        return [
            {
                "at": entry.at,
                "actor": entry.actor,
                "action": entry.action,
                "target": entry.target,
                "result": entry.result,
                "detail": entry.detail,
            }
            for entry in snapshot[:limit]
        ]
