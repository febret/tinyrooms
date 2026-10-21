"""Persistence for user-authored sign text and whiteboard drawings."""

from __future__ import annotations

from dataclasses import dataclass
import json

from server.content.surface_props import (
    DEFAULT_SIGN_SURFACE,
    DEFAULT_WHITEBOARD_SURFACE,
    validate_sign_text,
    validate_whiteboard,
)
from server.security import utc_now
from server.state.migrations import DatabaseHub


@dataclass(frozen=True, slots=True)
class SurfaceRecord:
    """One stored sign or whiteboard surface."""

    instance_id: str
    kind: str
    content: dict[str, object]
    revision: int
    updated_by: str | None = None

    def serialize(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "content": dict(self.content),
            "revision": self.revision,
            "updated_by": self.updated_by,
        }


def surface_kind(render_kind: str) -> str | None:
    """Map a prop render kind to its stored surface kind."""

    if render_kind == "sign":
        return "sign"
    if render_kind == "whiteboard":
        return "whiteboard"
    return None


def default_surface(
    instance_id: str,
    kind: str,
    content: dict[str, object] | None = None,
) -> SurfaceRecord:
    fallback = DEFAULT_SIGN_SURFACE if kind == "sign" else DEFAULT_WHITEBOARD_SURFACE
    return SurfaceRecord(
        instance_id=instance_id,
        kind=kind,
        content=dict(content if content is not None else fallback),
        revision=0,
    )


class PropSurfaceService:
    """Read and write per-instance surface content with last-write-wins revisions."""

    def __init__(self, hub: DatabaseHub) -> None:
        self._hub = hub

    def get(
        self,
        room_id: str,
        instance_id: str,
        kind: str,
        *,
        default_content: dict[str, object] | None = None,
    ) -> SurfaceRecord:
        """Return one surface, falling back to an authored or built-in default."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT * FROM world.prop_surfaces WHERE room_id = ? AND instance_id = ?",
                (room_id, instance_id),
            ).fetchone()
        if row is None:
            return default_surface(instance_id, kind, default_content)
        return _surface_from_row(row)

    def save_sign(
        self,
        room_id: str,
        instance_id: str,
        account_id: str,
        raw_text: object,
    ) -> SurfaceRecord:
        """Validate and store a sign's text."""

        return self._write(room_id, instance_id, "sign", account_id, validate_sign_text(raw_text))

    def save_whiteboard(
        self,
        room_id: str,
        instance_id: str,
        account_id: str,
        raw_content: object,
    ) -> SurfaceRecord:
        """Validate and store a whiteboard's strokes and text labels."""

        return self._write(
            room_id,
            instance_id,
            "whiteboard",
            account_id,
            validate_whiteboard(raw_content),
        )

    def _write(
        self,
        room_id: str,
        instance_id: str,
        kind: str,
        account_id: str,
        content: dict[str, object],
    ) -> SurfaceRecord:
        now = utc_now().isoformat()
        payload = json.dumps(content, separators=(",", ":"))
        with self._hub.transaction() as connection:
            connection.execute(
                """
                INSERT INTO world.prop_surfaces (
                    room_id, instance_id, kind, content_json, revision,
                    updated_by_account_id, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(room_id, instance_id) DO UPDATE SET
                    kind = excluded.kind,
                    content_json = excluded.content_json,
                    revision = prop_surfaces.revision + 1,
                    updated_by_account_id = excluded.updated_by_account_id,
                    updated_at = excluded.updated_at
                """,
                (room_id, instance_id, kind, payload, account_id, now),
            )
            row = connection.execute(
                "SELECT * FROM world.prop_surfaces WHERE room_id = ? AND instance_id = ?",
                (room_id, instance_id),
            ).fetchone()
        if row is None:
            raise ValueError("The surface could not be saved.")
        return _surface_from_row(row)

    def prune_room(self, room_id: str, live_instance_ids: set[str]) -> None:
        """Delete surfaces whose prop instance is no longer in the room layout."""

        with self._hub.transaction() as connection:
            rows = connection.execute(
                "SELECT instance_id FROM world.prop_surfaces WHERE room_id = ?",
                (room_id,),
            ).fetchall()
            removed = [
                str(row["instance_id"])
                for row in rows
                if str(row["instance_id"]) not in live_instance_ids
            ]
            for instance_id in removed:
                connection.execute(
                    "DELETE FROM world.prop_surfaces WHERE room_id = ? AND instance_id = ?",
                    (room_id, instance_id),
                )

    def clear_room(self, room_id: str) -> None:
        """Delete every surface in a room, used when the room is reset."""

        with self._hub.transaction() as connection:
            connection.execute(
                "DELETE FROM world.prop_surfaces WHERE room_id = ?",
                (room_id,),
            )

    def save_activity_surface(
        self,
        activity: object,
        account_id: str,
        raw_content: object,
    ) -> SurfaceRecord | None:
        """Save the whiteboard bound to an activity session, if any."""

        config = getattr(activity, "config", None) or {}
        instance_id = str(config.get("prop_instance_id") or "")
        room_id = getattr(activity, "room_id", None)
        if not instance_id or not room_id or getattr(activity, "kind", "") != "whiteboard":
            return None
        return self.save_whiteboard(room_id, instance_id, account_id, raw_content)


def _surface_from_row(row: object) -> SurfaceRecord:
    try:
        content = json.loads(row["content_json"])
    except (TypeError, ValueError):
        content = {}
    kind = str(row["kind"])
    if kind == "sign" and not isinstance(content, dict):
        content = dict(DEFAULT_SIGN_SURFACE)
    if kind == "whiteboard" and not isinstance(content, dict):
        content = dict(DEFAULT_WHITEBOARD_SURFACE)
    return SurfaceRecord(
        instance_id=str(row["instance_id"]),
        kind=kind,
        content=content,
        revision=int(row["revision"]),
        updated_by=str(row["updated_by_account_id"]) if row["updated_by_account_id"] else None,
    )
