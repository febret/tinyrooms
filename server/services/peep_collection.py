"""Shared peep sticker collection: non-player peeps a player has met across worlds.

Encounters live in the shared profile database so the collection follows the
player into every world. Each row snapshots the peep's label, description, and
picture so other activities (for example mod companions) can reuse the peep
even when its home world is not loaded. Every ``MILESTONE_SIZE`` new peeps pays
a milestone reward exactly once through the reward ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import logging
from pathlib import Path
import shutil
import sqlite3

from server.content.worlds import PeepDefinition, WorldDefinition
from server.profiles import ProfileRepository
from server.security import utc_now
from server.services.progression import ProgressionService
from server.services.vibes import describe_vibe
from server.state.migrations import DatabaseHub


LOGGER = logging.getLogger(__name__)

MILESTONE_SIZE = 10
MILESTONE_BOPS = 100
MILESTONE_KUDOS = 1
PEEP_STICKER_DIRECTORY = "peeps"
PEEP_STICKER_URL_PREFIX = "/assets/peep-stickers/"
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"})


def peep_key(world_id: str, peep_id: str) -> str:
    """Return the globally unique collection key for one world's peep."""

    return f"{world_id}:{peep_id}"


def milestone_ledger_key(milestone: int) -> str:
    """Return the idempotent reward-ledger key for one collection milestone."""

    return f"peep-collection:milestone:{int(milestone)}"


@dataclass(frozen=True, slots=True)
class SharedPeep:
    """One collected peep, reusable outside its home world."""

    peep_key: str
    world_id: str
    peep_id: str
    label: str
    description: str
    image_name: str
    vibe: int
    traits: dict[str, object]
    first_room_id: str
    first_met_at: str
    last_met_at: str

    @property
    def image_url(self) -> str:
        """Return the collection-owned picture URL, or empty when none was copied."""

        return f"{PEEP_STICKER_URL_PREFIX}{self.image_name}" if self.image_name else ""

    def to_payload(self) -> dict[str, object]:
        """Serialize the peep for the client and for activity companions."""

        return {
            "key": self.peep_key,
            "world_id": self.world_id,
            "peep_id": self.peep_id,
            "label": self.label,
            "description": self.description,
            "image_url": self.image_url,
            "vibe": self.vibe,
            "vibe_label": describe_vibe(self.vibe),
            "traits": dict(self.traits),
            "first_room_id": self.first_room_id,
            "first_met_at": self.first_met_at,
            "last_met_at": self.last_met_at,
        }


@dataclass(slots=True)
class EncounterResult:
    """Outcome of one recorded encounter."""

    new: bool = False
    peep: SharedPeep | None = None
    milestones: list[int] = field(default_factory=list)
    events: list[dict[str, object]] = field(default_factory=list)


def _row_to_peep(row: sqlite3.Row) -> SharedPeep:
    try:
        traits = json.loads(row["traits_json"] or "{}")
    except json.JSONDecodeError:
        traits = {}
    return SharedPeep(
        peep_key=row["peep_key"],
        world_id=row["world_id"],
        peep_id=row["peep_id"],
        label=row["label"],
        description=row["description"],
        image_name=row["image_name"],
        vibe=int(row["vibe"]),
        traits=traits if isinstance(traits, dict) else {},
        first_room_id=row["first_room_id"],
        first_met_at=row["first_met_at"],
        last_met_at=row["last_met_at"],
    )


def _json_scalar_map(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(item, (str, int, float, bool)) or item is None
    }


class PeepCollectionService:
    """Owns encounter rows, collection payloads, and milestone rewards."""

    def __init__(
        self,
        *,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        progression: ProgressionService,
        world: WorldDefinition,
        stickers_root: Path,
        vibes: object | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._progression = progression
        self._world = world
        self._images_root = Path(stickers_root) / PEEP_STICKER_DIRECTORY
        self._vibes = vibes

    @property
    def images_root(self) -> Path:
        """Return the directory holding collection-owned peep pictures."""

        return self._images_root

    def record_encounter(
        self,
        account_id: str,
        peep_id: str,
        *,
        room_id: str = "",
        payload: dict[str, object] | None = None,
    ) -> EncounterResult:
        """Record that *account_id* met world peep *peep_id*.

        Repeat encounters only refresh the vibe snapshot and last-met time. A
        new encounter may cross one or more milestones; each pays once.
        """

        definition = self._world.peeps.get(peep_id)
        if definition is None or not account_id:
            return EncounterResult()
        key = peep_key(self._world.id, peep_id)
        vibe = self._current_vibe(peep_id, account_id)
        now = utc_now().isoformat()
        with self._hub.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM encountered_peeps WHERE account_id = ? AND peep_key = ?",
                (account_id, key),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    "UPDATE encountered_peeps SET vibe = ?, last_met_at = ? WHERE account_id = ? AND peep_key = ?",
                    (vibe, now, account_id, key),
                )
                return EncounterResult(new=False, peep=_row_to_peep(existing))
            serialized = payload or {}
            label = str(serialized.get("label") or definition.label)
            description = str(serialized.get("description") or definition.description or "")
            image_name = self._copy_image(definition)
            traits = self._traits(definition, room_id, serialized)
            connection.execute(
                "INSERT INTO encountered_peeps (account_id, peep_key, world_id, peep_id, label, description,"
                " image_name, vibe, traits_json, counts_toward_rewards, first_room_id, first_met_at, last_met_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (
                    account_id,
                    key,
                    self._world.id,
                    peep_id,
                    label,
                    description,
                    image_name,
                    vibe,
                    json.dumps(traits),
                    room_id,
                    now,
                    now,
                ),
            )
            milestones = self._pay_milestones(connection, account_id)
            row = connection.execute(
                "SELECT * FROM encountered_peeps WHERE account_id = ? AND peep_key = ?",
                (account_id, key),
            ).fetchone()
        peep = _row_to_peep(row)
        result = EncounterResult(new=True, peep=peep, milestones=milestones)
        result.events.append(
            {"type": "toast", "tone": "success", "text": f"New sticker: you met {peep.label}!"}
        )
        for milestone in milestones:
            result.events.append(
                {
                    "type": "toast",
                    "tone": "success",
                    "text": (
                        f"🌟 {milestone * MILESTONE_SIZE} peeps met! "
                        f"+{MILESTONE_BOPS} Bops, +{MILESTONE_KUDOS} Kudos"
                    ),
                }
            )
        return result

    def list_for_account(self, account_id: str) -> list[SharedPeep]:
        """Return every collected peep for *account_id*, oldest encounter first."""

        with self._hub.locked() as connection:
            rows = connection.execute(
                "SELECT * FROM encountered_peeps WHERE account_id = ? ORDER BY first_met_at, peep_key",
                (account_id,),
            ).fetchall()
        return [_row_to_peep(row) for row in rows]

    def companion_profile(self, account_id: str, key: str) -> SharedPeep | None:
        """Return one collected peep for reuse in side activities, or None if unmet."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT * FROM encountered_peeps WHERE account_id = ? AND peep_key = ?",
                (account_id, key),
            ).fetchone()
        return _row_to_peep(row) if row is not None else None

    def collection_payload(self, account_id: str) -> dict[str, object]:
        """Serialize the sticker collection and milestone progress."""

        peeps = self.list_for_account(account_id)
        return {
            "peeps": [peep.to_payload() for peep in peeps],
            "count": len(peeps),
            "milestone_size": MILESTONE_SIZE,
            "milestone_reward": {"bops": MILESTONE_BOPS, "kudos": MILESTONE_KUDOS},
            "next_milestone_at": (len(peeps) // MILESTONE_SIZE + 1) * MILESTONE_SIZE,
        }

    def _pay_milestones(self, connection: sqlite3.Connection, account_id: str) -> list[int]:
        row = connection.execute(
            "SELECT COUNT(*) AS total FROM encountered_peeps WHERE account_id = ? AND counts_toward_rewards = 1",
            (account_id,),
        ).fetchone()
        reached = int(row["total"]) // MILESTONE_SIZE
        paid: list[int] = []
        for milestone in range(1, reached + 1):
            if self._progression.grant_in_transaction(
                connection,
                account_id,
                kudos=MILESTONE_KUDOS,
                bops=MILESTONE_BOPS,
                ledger_key=milestone_ledger_key(milestone),
                kind="peep_collection",
            ):
                paid.append(milestone)
        return paid

    def _current_vibe(self, peep_id: str, account_id: str) -> int:
        getter = getattr(self._vibes, "get", None)
        if not callable(getter):
            return 0
        try:
            return int(getter(peep_id, account_id))
        except Exception:  # noqa: BLE001 - a missing vibe never blocks collection
            LOGGER.warning("peep_collection.vibe_failed peep_id=%s", peep_id)
            return 0

    def _traits(
        self,
        definition: PeepDefinition,
        room_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        room = self._world.rooms.get(room_id)
        traits: dict[str, object] = {
            "world_label": self._world.label,
            "room_label": room.label if room is not None else "",
            "has_dialog": definition.dialog is not None,
            "activity": definition.activity or "",
            "actions": [action.label for action in definition.actions if getattr(action, "label", "")],
        }
        counters = _json_scalar_map(payload.get("counters"))
        if counters:
            traits["counters"] = counters
        return traits

    def _copy_image(self, definition: PeepDefinition) -> str:
        source = Path(definition.image_path)
        suffix = source.suffix.lower()
        if suffix not in _IMAGE_SUFFIXES or not source.is_file():
            return ""
        try:
            data = source.read_bytes()
            name = f"{hashlib.sha256(data).hexdigest()}{suffix}"
            target = self._images_root / name
            if not target.is_file():
                self._images_root.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".tmp")
                shutil.copyfile(source, temporary)
                temporary.replace(target)
            return name
        except OSError:
            LOGGER.warning("peep_collection.image_copy_failed peep_id=%s", definition.id)
            return ""
