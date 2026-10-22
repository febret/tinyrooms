"""TinyTown housing, house visits, and the Art Market."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import sqlite3
import uuid

from mods.tinytown.art import ART_BY_ID, ART_PIECES, art_payload
from mods.tinytown.catalog import (
    DISTRICTS,
    DISTRICTS_BY_ID,
    MAX_HOUSES,
    MAX_NPCS_PER_HOUSE,
)
from mods.tinytown.content import FloorTexture, HouseRecord, HouseTemplate, load_floor_textures, load_house_templates
from mods.tinytown.npcs import NpcHouse
from server.content.worlds import ExitDefinition, RoomDefinition
from server.security import utc_now
from server.state.world_state import LayoutRevisionConflict


HOUSE_ROOM_PREFIX = "home:"
ENTRY_ROOM_ID = "town"
MAX_LAYOUT_WHITEBOARDS = 4


@dataclass(frozen=True, slots=True)
class DecorationResult:
    message: str
    layout_event: dict[str, object]
    surface_event: dict[str, object] | None = None
    bops_spent: int = 0
    unlocked: bool = False


@dataclass(frozen=True, slots=True)
class HouseEntryResult:
    source_room_id: str
    destination_room_id: str
    direction: str
    navigation: object


class TinytownHousing:
    """Owns house templates, private room materialization, and decoration."""

    def __init__(self, runtime: object) -> None:
        self.runtime = runtime
        self._world = runtime.world
        self._hub = runtime.hub
        self._profiles = runtime.profiles
        self._world_state = runtime.world_state
        self._ownership = runtime.ownership
        self._layout = runtime.layout
        self._surfaces = runtime.surfaces
        self._environment = runtime.environment
        if self._world.id == "tinytown":
            self._templates = load_house_templates(
                Path(__file__).resolve().parent / "content" / "houses.yaml", self._world
            )
            self._floors = load_floor_textures(
                Path(__file__).resolve().parent / "content" / "floor_textures.yaml", self._world
            )
            self._floor_by_image = {floor.image: floor for floor in self._floors.values()}
            self._ensure_schema()
        else:
            self._templates = {}
            self._floors = {}
            self._floor_by_image = {}

    # -- setup ---------------------------------------------------------------

    def _ensure_schema(self) -> None:
        with self._hub.transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS world.tinytown_houses (
                    house_id TEXT PRIMARY KEY,
                    owner_account_id TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    room_ids_json TEXT NOT NULL,
                    locked INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS world.tinytown_npcs (
                    npc_id TEXT PRIMARY KEY,
                    house_id TEXT NOT NULL,
                    owner_account_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    avatar TEXT NOT NULL,
                    traits_json TEXT NOT NULL,
                    stats_json TEXT NOT NULL,
                    room_id TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT 'idle',
                    target TEXT NOT NULL DEFAULT '',
                    last_tick TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS world.tinytown_unlocks (
                    account_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, kind, item_id)
                )
                """
            )

    def prepare(self) -> None:
        """Materialize every persisted house and every household NPC."""

        if self._world.id != "tinytown":
            return
        for record in self._records():
            if record.template_id not in self._templates:
                continue
            try:
                self._register_rooms(record)
            except (KeyError, ValueError):
                continue
        self.npcs.prepare()

    @property
    def templates(self) -> dict[str, HouseTemplate]:
        return self._templates

    @property
    def floors(self) -> dict[str, FloorTexture]:
        return self._floors

    @property
    def npcs(self) -> NpcHouse:
        npc_house = getattr(self, "_npc_house", None)
        if npc_house is None:
            self._npc_house = NpcHouse(self)
            npc_house = self._npc_house
        return npc_house

    # -- records -------------------------------------------------------------

    def _records(self) -> list[HouseRecord]:
        with self._hub.locked() as connection:
            rows = connection.execute(
                "SELECT * FROM world.tinytown_houses ORDER BY created_at, house_id"
            ).fetchall()
        records: list[HouseRecord] = []
        for row in rows:
            try:
                room_ids = json.loads(row["room_ids_json"])
            except (TypeError, ValueError):
                continue
            if not isinstance(room_ids, dict):
                continue
            records.append(
                HouseRecord(
                    house_id=str(row["house_id"]),
                    owner_account_id=str(row["owner_account_id"]),
                    template_id=str(row["template_id"]),
                    room_ids={str(key): str(value) for key, value in room_ids.items()},
                    locked=bool(row["locked"]),
                    created_at=str(row["created_at"]),
                )
            )
        return records

    def record_for(self, house_id: str) -> HouseRecord | None:
        for record in self._records():
            if record.house_id == house_id:
                return record
        return None

    def record_for_room(self, room_id: str) -> HouseRecord | None:
        for record in self._records():
            if room_id in record.room_ids.values():
                return record
        return None

    def records_for_owner(self, account_id: str) -> list[HouseRecord]:
        return [record for record in self._records() if record.owner_account_id == account_id]

    def template_for(self, record: HouseRecord) -> HouseTemplate:
        return self._templates[record.template_id]

    def entry_room(self, record: HouseRecord) -> str:
        template = self.template_for(record)
        return record.room_ids[template.entry_key]

    def room_key(self, record: HouseRecord, room_id: str) -> str | None:
        return next((key for key, value in record.room_ids.items() if value == room_id), None)

    # -- materialization -----------------------------------------------------

    @staticmethod
    def _room_id(house_id: str, key: str) -> str:
        return f"{HOUSE_ROOM_PREFIX}{house_id}:{key}"

    def _build_room(
        self,
        record: HouseRecord,
        key: str,
        template: HouseTemplate,
        room_ids: dict[str, str],
    ) -> RoomDefinition:
        room_template = template.room_for_key(key)
        if room_template is None:
            raise ValueError("That house room is not defined.")
        blueprint = self._world.rooms[room_template.blueprint]
        exits: dict[str, ExitDefinition] = {}
        if key == template.entry_key:
            exits["front-door"] = ExitDefinition(
                id="front-door",
                label="Step out to TinyTown",
                target_room_id=ENTRY_ROOM_ID,
                locked=False,
                requires_card_id=None,
            )
            for other in template.rooms:
                if other.key == key:
                    continue
                exits[f"to-{other.key}"] = ExitDefinition(
                    id=f"to-{other.key}",
                    label=f"Go to {other.label}",
                    target_room_id=room_ids[other.key],
                    locked=False,
                    requires_card_id=None,
                )
        else:
            exits["to-entry"] = ExitDefinition(
                id="to-entry",
                label=f"Back to {template.rooms[0].label}",
                target_room_id=room_ids[template.entry_key],
                locked=False,
                requires_card_id=None,
            )
        owner = self._profiles.get_account_by_id(record.owner_account_id)
        owner_name = owner.username_display if owner is not None else "Someone"
        return replace(
            blueprint,
            id=room_ids[key],
            label=f"{owner_name}'s {room_template.label}",
            description=(
                f"The {room_template.label.lower()} of {owner_name}'s {template.label}. "
                f"{template.description}"
            ),
            exits=exits,
            palette=template.palette,
            template=False,
            sprites_enabled=True,
        )

    def _register_rooms(self, record: HouseRecord) -> dict[str, RoomDefinition]:
        template = self.template_for(record)
        for key in template.rooms:
            if key.key not in record.room_ids:
                record.room_ids[key.key] = self._room_id(record.house_id, key.key)
        built: dict[str, RoomDefinition] = {}
        for room_template in template.rooms:
            room = self._build_room(record, room_template.key, template, record.room_ids)
            self._world.rooms[room.id] = room
            built[room_template.key] = room
        return built

    def _seed_rooms(self, record: HouseRecord, built: dict[str, RoomDefinition]) -> None:
        for room in built.values():
            if room.id in self._world.rooms:
                self._world_state.seed_player_room(room.id, room, self._world)

    def _write_house(
        self,
        connection: sqlite3.Connection,
        record: HouseRecord,
    ) -> None:
        connection.execute(
            """
            INSERT INTO world.tinytown_houses (
                house_id, owner_account_id, template_id, room_ids_json, locked, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record.house_id,
                record.owner_account_id,
                record.template_id,
                json.dumps(record.room_ids),
                1 if record.locked else 0,
                record.created_at,
            ),
        )

    def _update_locked(self, house_id: str, locked: bool) -> None:
        with self._hub.transaction() as connection:
            connection.execute(
                "UPDATE world.tinytown_houses SET locked = ? WHERE house_id = ?",
                (1 if locked else 0, house_id),
            )

    # -- views ---------------------------------------------------------------

    def _owner_name(self, account_id: str) -> str:
        account = self._profiles.get_account_by_id(account_id)
        return account.username_display if account is not None else "A former resident"

    def house_payload(self, record: HouseRecord, viewer_id: str) -> dict[str, object]:
        template = self._templates[record.template_id]
        district = DISTRICTS_BY_ID[template.district]
        return {
            "id": record.house_id,
            "template_id": template.id,
            "label": template.label,
            "description": template.description,
            "district": district.id,
            "district_label": district.label,
            "district_accent": district.accent,
            "price": template.price,
            "size": template.size,
            "rooms": [
                {
                    "key": room.key,
                    "label": room.label,
                    "role": room.role,
                    "room_id": record.room_ids.get(room.key, ""),
                }
                for room in template.rooms
            ],
            "room_count": len(template.rooms),
            "owner_id": record.owner_account_id,
            "owner_username": self._owner_name(record.owner_account_id),
            "is_owner": record.owner_account_id == viewer_id,
            "locked": record.locked,
            "preview_url": f"/assets/world/{self._world.id}/rooms/{template.preview}",
            "entry_room_id": self.entry_room(record),
            "created_at": record.created_at,
        }

    def template_payload(self, template: HouseTemplate, *, owned: int = 0) -> dict[str, object]:
        district = DISTRICTS_BY_ID[template.district]
        return {
            "id": template.id,
            "label": template.label,
            "description": template.description,
            "district": template.district,
            "district_label": district.label,
            "district_accent": district.accent,
            "price": template.price,
            "size": template.size,
            "room_count": len(template.rooms),
            "rooms": [{"key": room.key, "label": room.label, "role": room.role} for room in template.rooms],
            "preview_url": f"/assets/world/{self._world.id}/rooms/{template.preview}",
            "owned": owned,
        }

    def ensure_welcome_grant(self, account: object) -> int:
        """Give a first-time resident enough Bops for the cheapest home."""

        current = self._profiles.get_account_by_id(account.id) or account
        if getattr(current, "bops", 0) >= 100 or self.records_for_owner(account.id):
            return 0
        progression = getattr(self.runtime, "progression", None)
        if progression is None:
            return 0
        granted = progression.reward_once(
            account.id,
            f"tinytown:welcome:{self._world.id}",
            bops=150,
            kind="tinytown",
        )
        return 150 if granted else 0

    def list_payload(self, account: object) -> dict[str, object]:
        records = self._records()
        mine = [record for record in records if record.owner_account_id == account.id]
        owned_templates: dict[str, int] = {}
        for record in mine:
            owned_templates[record.template_id] = owned_templates.get(record.template_id, 0) + 1
        return {
            "districts": [
                {
                    "id": district.id,
                    "label": district.label,
                    "tagline": district.tagline,
                    "description": district.description,
                    "accent": district.accent,
                }
                for district in DISTRICTS
            ],
            "templates": [
                self.template_payload(template, owned=owned_templates.get(template.id, 0))
                for template in self._templates.values()
            ],
            "houses": [self.house_payload(record, account.id) for record in records],
            "mine": [self.house_payload(record, account.id) for record in mine],
            "wallet": int(account.bops),
            "max_houses": MAX_HOUSES,
            "max_npcs": MAX_NPCS_PER_HOUSE,
        }

    # -- purchase and access -------------------------------------------------

    def purchase(self, account: object, template_id: str) -> HouseRecord:
        template = self._templates.get(template_id)
        if template is None:
            raise ValueError("That house template does not exist.")
        if len(self.records_for_owner(account.id)) >= MAX_HOUSES:
            raise ValueError(f"You already own {MAX_HOUSES} homes. That is quite enough keys.")
        house_id = uuid.uuid4().hex
        room_ids = {room.key: self._room_id(house_id, room.key) for room in template.rooms}
        record = HouseRecord(
            house_id=house_id,
            owner_account_id=account.id,
            template_id=template.id,
            room_ids=room_ids,
            locked=False,
            created_at=utc_now().isoformat(),
        )
        built = self._register_rooms(record)
        try:
            with self._hub.transaction() as connection:
                current = self._profiles.get_account_by_id(account.id)
                if current is None:
                    raise ValueError("That account no longer exists.")
                if current.bops < template.price:
                    raise ValueError(
                        f"You need {template.price - current.bops} more Bops for {template.label}."
                    )
                if len(self.records_for_owner(account.id)) >= MAX_HOUSES:
                    raise ValueError(f"You already own {MAX_HOUSES} homes.")
                self._profiles.update_progress(
                    connection,
                    current,
                    bops=current.bops - template.price,
                )
                self._write_house(connection, record)
                for room in built.values():
                    self._world_state.insert_player_room(
                        connection,
                        room_id=room.id,
                        owner_account_id=account.id,
                        door={"house_id": house_id, "template_id": template.id},
                    )
                    self._ownership.grant_in_transaction(connection, room.id, account.id)
        except Exception:
            for room in built.values():
                self._world.rooms.pop(room.id, None)
            raise
        self._seed_rooms(record, built)
        return record

    def set_locked(self, account: object, house_id: str, locked: bool) -> HouseRecord:
        record = self.record_for(house_id)
        if record is None:
            raise ValueError("That house does not exist.")
        if record.owner_account_id != account.id:
            raise ValueError("Only the owner can lock this house.")
        self._update_locked(house_id, locked)
        updated = self.record_for(house_id)
        return updated if updated is not None else record

    def require_entry(self, account: object, house_id: str) -> HouseRecord:
        record = self.record_for(house_id)
        if record is None:
            raise ValueError("That house does not exist.")
        if record.locked and record.owner_account_id != account.id:
            raise ValueError("That front door is locked.")
        return record

    def current_house(self, room_id: str) -> HouseRecord | None:
        return self.record_for_room(room_id)

    def require_owned_room(self, account: object, room_id: str) -> HouseRecord:
        record = self.record_for_room(room_id)
        if record is None:
            raise ValueError("The Art Market only hangs work inside a TinyTown home.")
        if record.owner_account_id != account.id:
            raise ValueError("You can only decorate a home you own.")
        return record

    # -- Art Market ----------------------------------------------------------

    def _floor_payload(self, floor: FloorTexture, account_id: str, current: str | None) -> dict[str, object]:
        return {
            "id": floor.id,
            "label": floor.label,
            "description": floor.description,
            "price": floor.price,
            "tags": list(floor.tags),
            "image_url": f"/assets/world/{self._world.id}/rooms/{floor.image}",
            "unlocked": self.is_unlocked(account_id, "floor", floor.id),
            "current": floor.id == current,
        }

    def current_floor(self, room_id: str) -> FloorTexture | None:
        room = self._world.rooms.get(room_id)
        if room is None:
            return None
        environment = self._environment.get(room_id)
        image = environment.get("board_image")
        if not isinstance(image, str) or not image:
            image = room.board_image_name
        return self._floor_by_image.get(image)

    def decor_payload(self, account: object, room_id: str) -> dict[str, object]:
        record = self.require_owned_room(account, room_id)
        template = self.template_for(record)
        floor = self.current_floor(room_id)
        layout = self._layout.view(account, room_id)
        whiteboards = sum(1 for prop in layout.get("props", []) if prop.get("prop_id") == "builtin:whiteboard")
        account_record = self._profiles.get_account_by_id(account.id) or account
        return {
            "room": {
                "id": room_id,
                "label": self._world.rooms[room_id].label,
                "house_id": record.house_id,
                "house": template.label,
                "current_floor": floor.id if floor is not None else "",
            },
            "floors": [self._floor_payload(entry, account.id, floor.id if floor else None) for entry in self._floors.values()],
            "art": [art_payload(piece) for piece in ART_PIECES],
            "unlocked_art": [
                piece.id for piece in ART_PIECES if self.is_unlocked(account.id, "art", piece.id)
            ],
            "whiteboards": whiteboards,
            "max_whiteboards": MAX_LAYOUT_WHITEBOARDS,
            "wallet": int(account_record.bops),
        }

    def is_unlocked(self, account_id: str, kind: str, item_id: str) -> bool:
        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT 1 FROM world.tinytown_unlocks WHERE account_id = ? AND kind = ? AND item_id = ?",
                (account_id, kind, item_id),
            ).fetchone()
        return row is not None

    def _unlock_in_transaction(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        kind: str,
        item_id: str,
    ) -> bool:
        existing = connection.execute(
            "SELECT 1 FROM world.tinytown_unlocks WHERE account_id = ? AND kind = ? AND item_id = ?",
            (account_id, kind, item_id),
        ).fetchone()
        if existing is not None:
            return False
        connection.execute(
            "INSERT INTO world.tinytown_unlocks (account_id, kind, item_id, created_at) VALUES (?, ?, ?, ?)",
            (account_id, kind, item_id, utc_now().isoformat()),
        )
        return True

    def _charge_and_unlock(
        self,
        account: object,
        *,
        kind: str,
        item_id: str,
        price: int,
    ) -> tuple[bool, int]:
        with self._hub.transaction() as connection:
            current = self._profiles.get_account_by_id(account.id)
            if current is None:
                raise ValueError("That account no longer exists.")
            newly_unlocked = self._unlock_in_transaction(connection, account.id, kind, item_id)
            if not newly_unlocked:
                return False, 0
            if current.bops < price:
                raise ValueError(f"You need {price - current.bops} more Bops for that.")
            self._profiles.update_progress(connection, current, bops=current.bops - price)
        return True, price

    def _layout_props(self, layout: dict[str, object]) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        raw_props = layout.get("props")
        if not isinstance(raw_props, list):
            return entries
        for prop in raw_props:
            if not isinstance(prop, dict):
                continue
            entry: dict[str, object] = {
                "id": str(prop.get("id", "")),
                "prop_id": str(prop.get("prop_id", "")),
                "position": list(prop.get("position") or [50.0, 50.0, 0.0]),
                "rotation": list(prop.get("rotation") or [0.0, 0.0, 0.0]),
                "scale": float(prop.get("scale", 1.0)),
                "locked": bool(prop.get("locked", False)),
            }
            if isinstance(prop.get("text"), dict):
                entry["text"] = dict(prop["text"])
            if isinstance(prop.get("sign_style"), str):
                entry["sign_style"] = prop["sign_style"]
            entries.append(entry)
        return entries

    def buy_floor(self, account: object, room_id: str, floor_id: str) -> DecorationResult:
        record = self.require_owned_room(account, room_id)
        del record
        floor = self._floors.get(floor_id)
        if floor is None:
            raise ValueError("That floor finish is not sold here.")
        unlocked_before = self.is_unlocked(account.id, "floor", floor.id)
        bops_spent = 0
        if not unlocked_before:
            _new, bops_spent = self._charge_and_unlock(
                account, kind="floor", item_id=floor.id, price=floor.price
            )
        layout = self._layout.view(account, room_id)
        entries = self._layout_props(layout)
        update = self._layout.save(
            account,
            room_id,
            int(layout["revision"]),
            {"props": entries, "environment": {"board_image": floor.image}},
        )
        return DecorationResult(
            message=f"{floor.label} fitted into {self._world.rooms[room_id].label}.",
            layout_event=update.event(),
            bops_spent=bops_spent,
            unlocked=not unlocked_before,
        )

    def hang_art(self, account: object, room_id: str, art_id: str) -> DecorationResult:
        self.require_owned_room(account, room_id)
        piece = ART_BY_ID.get(art_id)
        if piece is None:
            raise ValueError("That artwork is not sold here.")
        layout = self._layout.view(account, room_id)
        whiteboards = [prop for prop in layout.get("props", []) if prop.get("prop_id") == "builtin:whiteboard"]
        if len(whiteboards) >= MAX_LAYOUT_WHITEBOARDS:
            raise ValueError(
                f"This room already has {MAX_LAYOUT_WHITEBOARDS} pieces on the walls. "
                "Make space before hanging another."
            )
        unlocked_before = self.is_unlocked(account.id, "art", piece.id)
        bops_spent = 0
        if not unlocked_before:
            _new, bops_spent = self._charge_and_unlock(
                account, kind="art", item_id=piece.id, price=piece.price
            )
        entries = self._layout_props(layout)
        slots = ((18.0, 9.0), (39.0, 9.0), (61.0, 9.0), (82.0, 9.0))
        x, y = slots[len(whiteboards) % len(slots)]
        instance_id = f"custom:{uuid.uuid4()}"
        entries.append(
            {
                "id": instance_id,
                "prop_id": "builtin:whiteboard",
                "position": [x, y, 0.0],
                "rotation": [0.0, 0.0, 0.0],
                "scale": 0.9,
                "locked": False,
            }
        )
        try:
            update = self._layout.save(
                account,
                room_id,
                int(layout["revision"]),
                {"props": entries, "environment": {}},
            )
        except LayoutRevisionConflict:
            raise ValueError("The room changed while the Art Market was wrapping your piece. Try again.")
        surface = self._surfaces.save_whiteboard(room_id, instance_id, account.id, piece.surface)
        return DecorationResult(
            message=f"{piece.label} is now hanging in {self._world.rooms[room_id].label}.",
            layout_event=update.event(),
            surface_event={
                "type": "room.prop.surface",
                "room_id": room_id,
                "prop_id": instance_id,
                "surface": surface.serialize(),
            },
            bops_spent=bops_spent,
            unlocked=not unlocked_before,
        )


class TinytownService:
    """Runtime state object registered by the TinyTown mod."""

    def __init__(self, runtime: object) -> None:
        self.runtime = runtime
        self.housing = TinytownHousing(runtime)
        self.npcs = self.housing.npcs

    @property
    def available(self) -> bool:
        return self.runtime.world.id == "tinytown"

    def prepare(self) -> None:
        self.housing.prepare()

    def start(self) -> None:
        self.npcs.start()

    def stop(self) -> None:
        self.npcs.stop()

    def npc_payload(self, peep: object, room_id: str | None) -> dict[str, object] | None:
        return self.npcs.npc_payload(peep, room_id)

    def room_quick_actions(self, account: object, room: RoomDefinition) -> tuple[object, ...]:
        if not self.available:
            return ()
        if room.id == ENTRY_ROOM_ID:
            from server.content.worlds import QuickAction

            return (QuickAction(label="Find your TinyTown home", command=".play tinytown"),)
        return ()

    def personal_actions(self, account: object, prop: object) -> tuple[object, ...]:
        del account, prop
        return ()
