"""Structured audit trail for privileged actions."""

from __future__ import annotations

import json
import logging

from server.security import utc_now
from server.state.migrations import DatabaseHub


class AuditService:
    """Records privileged actions with actor, world, target, and result.

    Audit writes must never break gameplay, so callers use :meth:`safe_record`
    when a failure should be logged and swallowed.
    """

    def __init__(self, hub: DatabaseHub, world_id: str, logger: logging.Logger | None = None) -> None:
        self._hub = hub
        self._world_id = world_id
        self._logger = logger or logging.getLogger("tinyrooms.audit")

    def record(
        self,
        actor_account_id: str,
        action: str,
        target: str | None,
        result: str,
        detail: dict[str, object] | None = None,
    ) -> None:
        """Insert one audit entry for a privileged action."""

        with self._hub.transaction() as connection:
            connection.execute(
                """
                INSERT INTO audit_log (
                    world_id, actor_account_id, action, target, result, detail_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._world_id,
                    actor_account_id,
                    action,
                    target,
                    result,
                    json.dumps(detail or {}),
                    utc_now().isoformat(),
                ),
            )

    def safe_record(
        self,
        actor_account_id: str,
        action: str,
        target: str | None,
        result: str,
        detail: dict[str, object] | None = None,
    ) -> None:
        """Record an audit entry, logging rather than raising on failure."""

        try:
            self.record(actor_account_id, action, target, result, detail)
        except Exception as exc:  # noqa: BLE001 - auditing must not break gameplay
            self._logger.warning(
                json.dumps(
                    {"event": "audit.error", "action": action, "error": str(exc)},
                    separators=(",", ":"),
                )
            )

    def entries(self, limit: int = 50) -> list[dict[str, object]]:
        """Return the most recent audit entries for this world."""

        with self._hub.locked() as connection:
            rows = connection.execute(
                """
                SELECT audit_id, actor_account_id, action, target, result, detail_json, created_at
                FROM audit_log
                WHERE world_id = ?
                ORDER BY audit_id DESC
                LIMIT ?
                """,
                (self._world_id, int(limit)),
            ).fetchall()
        entries: list[dict[str, object]] = []
        for row in rows:
            try:
                detail = json.loads(row["detail_json"])
            except (TypeError, ValueError):
                detail = {}
            entries.append(
                {
                    "id": int(row["audit_id"]),
                    "actor_account_id": row["actor_account_id"],
                    "action": row["action"],
                    "target": row["target"],
                    "result": row["result"],
                    "detail": detail if isinstance(detail, dict) else {},
                    "created_at": row["created_at"],
                }
            )
        return entries
