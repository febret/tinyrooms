"""Persistence for user-authored sign text and whiteboard drawings."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging

from server.content.surface_props import (
    DEFAULT_SIGN_SURFACE,
    DEFAULT_WHITEBOARD_FRAME,
    DEFAULT_WHITEBOARD_SURFACE,
    rasterize_legacy_whiteboard,
    validate_sign_text,
    validate_whiteboard,
    validate_whiteboard_frame,
)
from server.security import utc_now
from server.services.whiteboard_images import WhiteboardImageStore
from server.state.migrations import DatabaseHub


LOGGER = logging.getLogger("tinyrooms.surfaces")


@dataclass(frozen=True, slots=True)
class SurfaceRecord:
    """One stored sign or whiteboard surface."""

    instance_id: str
    kind: str
    content: dict[str, object]
    revision: int
    updated_by: str | None = None
    locked: bool = False
    locked_by: str | None = None
    locked_at: str | None = None

    def serialize(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "content": dict(self.content),
            "revision": self.revision,
            "updated_by": self.updated_by,
            "locked": self.locked,
            "locked_by": self.locked_by,
        }


def surface_kind(render_kind: str) -> str | None:
    """Map a prop render kind to its stored surface kind."""

    if render_kind == "sign":
        return "sign"
    if render_kind == "whiteboard":
        return "whiteboard"
    return None


def _copy_surface_content(content: dict[str, object]) -> dict[str, object]:
    copied = dict(content)
    frame = copied.get("frame")
    if isinstance(frame, dict):
        copied["frame"] = dict(frame)
    return copied


def _blank_whiteboard_content() -> dict[str, object]:
    return {
        "image_url": "",
        "image_hash": "",
        "frame": dict(DEFAULT_WHITEBOARD_FRAME),
    }


def default_surface(
    instance_id: str,
    kind: str,
    content: dict[str, object] | None = None,
) -> SurfaceRecord:
    fallback = DEFAULT_SIGN_SURFACE if kind == "sign" else DEFAULT_WHITEBOARD_SURFACE
    return SurfaceRecord(
        instance_id=instance_id,
        kind=kind,
        content=_copy_surface_content(content if content is not None else fallback),
        revision=0,
    )


class PropSurfaceService:
    """Read and write per-instance surface content with last-write-wins revisions."""

    def __init__(
        self,
        hub: DatabaseHub,
        image_store: WhiteboardImageStore | None = None,
        *,
        allow_legacy_whiteboards: bool = False,
    ) -> None:
        self._hub = hub
        self._images = image_store
        self._allow_legacy_whiteboards = allow_legacy_whiteboards
        self._default_cache: dict[tuple[str, str], tuple[str, dict[str, object]]] = {}

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
            content = (
                _copy_surface_content(default_content)
                if isinstance(default_content, dict)
                else _blank_whiteboard_content()
                if kind == "whiteboard"
                else dict(DEFAULT_SIGN_SURFACE)
            )
            if kind == "whiteboard":
                content = self._canonicalize_default(room_id, instance_id, content)
            return SurfaceRecord(instance_id=instance_id, kind=kind, content=content, revision=0)
        record = _surface_from_row(row)
        if record.kind == "whiteboard":
            upgraded = self._upgrade_row_content(room_id, instance_id, record.content)
            if upgraded is not None:
                record = SurfaceRecord(
                    instance_id=record.instance_id,
                    kind=record.kind,
                    content=upgraded,
                    revision=record.revision,
                    updated_by=record.updated_by,
                    locked=record.locked,
                    locked_by=record.locked_by,
                    locked_at=record.locked_at,
                )
        return record

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
        *,
        connection: object | None = None,
    ) -> SurfaceRecord:
        """Validate and store an editable whiteboard's image and frame."""

        if self.is_locked(room_id, instance_id):
            raise ValueError("This artwork is locked and cannot be modified.")
        return self._write(
            room_id,
            instance_id,
            "whiteboard",
            account_id,
            self._prepare_whiteboard_content(raw_content),
            connection=connection,
        )

    def install_whiteboard(
        self,
        room_id: str,
        instance_id: str,
        account_id: str,
        raw_content: object,
        *,
        locked: bool = True,
        connection: object | None = None,
    ) -> SurfaceRecord:
        """Install a whiteboard, optionally locking it as a purchased print."""

        return self._write(
            room_id,
            instance_id,
            "whiteboard",
            account_id,
            self._prepare_whiteboard_content(raw_content),
            locked=locked,
            lock_owner=account_id if locked else None,
            connection=connection,
        )

    def materialize_whiteboard(
        self, raw_content: object, *, allow_legacy: bool | None = None
    ) -> dict[str, object]:
        """Convert generated or legacy content into canonical image-backed content.

        Pass ``allow_legacy=True`` for first-party generated art, which always
        converts. Reading pre-existing legacy client data defaults to the
        ``svg-boards`` compatibility flag.
        """

        return self._prepare_whiteboard_content(raw_content, allow_legacy=allow_legacy)

    def is_locked(self, room_id: str, instance_id: str) -> bool:
        """Return whether a stored surface is locked against content edits."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT locked FROM world.prop_surfaces WHERE room_id = ? AND instance_id = ?",
                (room_id, instance_id),
            ).fetchone()
        return bool(row is not None and row["locked"])

    def _prepare_whiteboard_content(
        self, raw_content: object, *, allow_legacy: bool | None = None
    ) -> dict[str, object]:
        """Convert an upload, asset reference, or legacy board into canonical content."""

        legacy_allowed = self._allow_legacy_whiteboards if allow_legacy is None else allow_legacy
        if not isinstance(raw_content, dict):
            raise ValueError("Whiteboard content must be an object.")
        if "strokes" in raw_content or "texts" in raw_content:
            if not legacy_allowed:
                raise ValueError("Legacy vector whiteboards require --legacy-features svg-boards.")
            image = rasterize_legacy_whiteboard(raw_content)
            frame = validate_whiteboard_frame(raw_content.get("frame"))
            return self._store_upload(image, frame)
        if "image" in raw_content:
            frame = validate_whiteboard_frame(raw_content.get("frame"))
            return self._store_upload(raw_content["image"], frame)
        content = validate_whiteboard(raw_content)
        if content["image_url"] and self._images is not None:
            if not self._images.exists(str(content["image_hash"])):
                raise ValueError("That whiteboard image is no longer available.")
        return content

    def _store_upload(self, image: object, frame: dict[str, str]) -> dict[str, object]:
        """Store a PNG data URL and return canonical asset-backed content."""

        if self._images is None:
            raise ValueError("Whiteboard image storage is unavailable.")
        stored = self._images.store_data_url(image)
        return {
            "image_url": stored["image_url"],
            "image_hash": stored["image_hash"],
            "frame": dict(frame),
        }

    def _canonicalize_default(
        self,
        room_id: str,
        instance_id: str,
        content: dict[str, object],
    ) -> dict[str, object]:
        """Convert authored/default whiteboard content without writing a DB row."""

        try:
            signature = json.dumps(content, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return _blank_whiteboard_content()
        cached = self._default_cache.get((room_id, instance_id))
        if cached is not None and cached[0] == signature:
            return _copy_surface_content(cached[1])
        try:
            canonical = self._prepare_whiteboard_content(content)
        except ValueError as exc:
            LOGGER.warning("whiteboard default unavailable: %s", exc)
            canonical = _blank_whiteboard_content()
        self._default_cache[(room_id, instance_id)] = (signature, _copy_surface_content(canonical))
        return canonical

    def _upgrade_row_content(
        self,
        room_id: str,
        instance_id: str,
        content: dict[str, object],
    ) -> dict[str, object] | None:
        """Upgrade stored legacy/upload content to canonical form when needed."""

        if not isinstance(content, dict):
            return None
        if "strokes" in content or "texts" in content or "image" in content:
            try:
                upgraded = self._prepare_whiteboard_content(content)
            except ValueError as exc:
                LOGGER.warning("legacy whiteboard unavailable: %s", exc)
                return _blank_whiteboard_content()
            payload = json.dumps(upgraded, separators=(",", ":"))
            with self._hub.transaction() as connection:
                connection.execute(
                    "UPDATE world.prop_surfaces SET content_json = ? WHERE room_id = ? AND instance_id = ?",
                    (payload, room_id, instance_id),
                )
            return upgraded
        try:
            canonical = validate_whiteboard(content)
        except ValueError:
            return None
        if canonical != content:
            return canonical
        return None

    def _write(
        self,
        room_id: str,
        instance_id: str,
        kind: str,
        account_id: str,
        content: dict[str, object],
        *,
        locked: bool | None = None,
        lock_owner: str | None = None,
        connection: object | None = None,
    ) -> SurfaceRecord:
        now = utc_now().isoformat()
        payload = json.dumps(content, separators=(",", ":"))
        if locked is None:
            statement = """
                INSERT INTO world.prop_surfaces (
                    room_id, instance_id, kind, content_json, revision,
                    updated_by_account_id, updated_at, locked
                ) VALUES (?, ?, ?, ?, 1, ?, ?, 0)
                ON CONFLICT(room_id, instance_id) DO UPDATE SET
                    kind = excluded.kind,
                    content_json = excluded.content_json,
                    revision = prop_surfaces.revision + 1,
                    updated_by_account_id = excluded.updated_by_account_id,
                    updated_at = excluded.updated_at
            """
            values = (room_id, instance_id, kind, payload, account_id, now)
        else:
            statement = """
                INSERT INTO world.prop_surfaces (
                    room_id, instance_id, kind, content_json, revision,
                    updated_by_account_id, updated_at, locked,
                    locked_by_account_id, locked_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(room_id, instance_id) DO UPDATE SET
                    kind = excluded.kind,
                    content_json = excluded.content_json,
                    revision = prop_surfaces.revision + 1,
                    updated_by_account_id = excluded.updated_by_account_id,
                    updated_at = excluded.updated_at,
                    locked = excluded.locked,
                    locked_by_account_id = excluded.locked_by_account_id,
                    locked_at = excluded.locked_at
            """
            values = (
                room_id, instance_id, kind, payload, account_id, now,
                1 if locked else 0, lock_owner if locked else None,
                now if locked else None,
            )
        if connection is None:
            with self._hub.transaction() as owned_connection:
                row = self._write_row(owned_connection, statement, values, room_id, instance_id)
        else:
            row = self._write_row(connection, statement, values, room_id, instance_id)
        if row is None:
            raise ValueError("The surface could not be saved.")
        return _surface_from_row(row)

    @staticmethod
    def _write_row(connection, statement: str, values: tuple[object, ...], room_id: str, instance_id: str):
        connection.execute(statement, values)
        return connection.execute(
            "SELECT * FROM world.prop_surfaces WHERE room_id = ? AND instance_id = ?",
            (room_id, instance_id),
        ).fetchone()

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
        content = _blank_whiteboard_content()
    keys = row.keys()
    return SurfaceRecord(
        instance_id=str(row["instance_id"]),
        kind=kind,
        content=content,
        revision=int(row["revision"]),
        updated_by=str(row["updated_by_account_id"]) if row["updated_by_account_id"] else None,
        locked=bool(row["locked"]) if "locked" in keys else False,
        locked_by=str(row["locked_by_account_id"]) if "locked_by_account_id" in keys and row["locked_by_account_id"] else None,
        locked_at=str(row["locked_at"]) if "locked_at" in keys and row["locked_at"] else None,
    )
