"""TinyTown housing, house visits, and the Art Market."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import logging
from pathlib import Path
import sqlite3
import uuid

from mods.tinytown.art import ART_BY_ID, ART_PIECES
from mods.tinytown.catalog import (
    DISTRICTS,
    DISTRICTS_BY_ID,
    MAX_HOUSES,
    MAX_NPCS_PER_HOUSE,
)
from mods.tinytown.content import FloorTexture, HouseRecord, HouseTemplate, load_floor_textures, load_house_templates
from mods.tinytown.day_night import DayNightCycle
from mods.tinytown.gallery import TinytownGallery
from mods.tinytown.npcs import NpcHouse
from server.content.room_grid import allocate_grid_block, room_grid_enabled
from server.content.surface_props import MAX_WHITEBOARD_PROPS, WHITEBOARD_PROP_ID
from server.content.worlds import ExitDefinition, RoomDefinition, apply_room_grid
from server.security import utc_now
from server.state.world_state import LayoutRevisionConflict


LOGGER = logging.getLogger("tinyrooms.mod.tinytown")

HOUSE_ROOM_PREFIX = "home:"
ENTRY_ROOM_ID = "town"
HOUSE_GRID_ORIGIN = (64, 64, 0)
HOUSE_GRID_COLUMNS = 3
MAX_LAYOUT_WHITEBOARDS = MAX_WHITEBOARD_PROPS

PROPSET_LABELS = {
    "beach-hut-base": "Beach Hut",
    "harbor-house-base": "Harbor House",
    "sea-villa-base": "Sea Villa",
    "brick-loft-base": "Brick Loft",
    "penthouse-base": "City Penthouse",
    "neon-flat-base": "Neon Apartment",
    "nature-cottage-base": "Nature Cottage",
    "italian-manor-base": "Italian Manor",
    "pool-house-base": "Pool House",
    "family-home-base": "Family Home",
}


def propset_label(propset_id: str) -> str:
    """Return the display label for a home-unlocked propset."""

    return PROPSET_LABELS.get(propset_id, propset_id)


def _grant_prop_unlocks(profile_json: dict[str, object], prop_ids: list[str]) -> None:
    """Add *prop_ids* to the profile's unlocked props without duplicates."""

    raw = profile_json.get("unlocked_props")
    owned = [str(entry) for entry in raw] if isinstance(raw, list) else []
    for prop_id in prop_ids:
        if prop_id not in owned:
            owned.append(prop_id)
    profile_json["unlocked_props"] = owned


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
            for statement in (
                "ALTER TABLE world.tinytown_npcs ADD COLUMN likes_interest TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE world.tinytown_npcs ADD COLUMN dislikes_interest TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE world.tinytown_npcs ADD COLUMN job_id TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE world.tinytown_npcs ADD COLUMN job_claim_json TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE world.tinytown_npcs ADD COLUMN job_ready_at TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE world.tinytown_npcs ADD COLUMN job_cooldown_until TEXT NOT NULL DEFAULT ''",
            ):
                try:
                    connection.execute(statement)
                except sqlite3.OperationalError:
                    pass
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS world.tinytown_npc_message_hours (
                    npc_id TEXT PRIMARY KEY,
                    last_hour INTEGER NOT NULL
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS world.tinytown_roommate_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    owner_account_id TEXT NOT NULL,
                    house_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    avatar TEXT NOT NULL,
                    traits_json TEXT NOT NULL,
                    stats_json TEXT NOT NULL,
                    headline TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            for statement in (
                "ALTER TABLE world.tinytown_roommate_candidates ADD COLUMN likes_interest TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE world.tinytown_roommate_candidates ADD COLUMN dislikes_interest TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE world.tinytown_roommate_candidates ADD COLUMN job_hint TEXT NOT NULL DEFAULT ''",
            ):
                try:
                    connection.execute(statement)
                except sqlite3.OperationalError:
                    pass
            connection.execute(
                "CREATE INDEX IF NOT EXISTS world.idx_tinytown_candidates_house "
                "ON tinytown_roommate_candidates(owner_account_id, house_id, created_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS world.tinytown_art_listings (
                    listing_id TEXT PRIMARY KEY,
                    seller_account_id TEXT NOT NULL,
                    source_room_id TEXT NOT NULL,
                    source_instance_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    surface_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS world.idx_tinytown_listings_status "
                "ON tinytown_art_listings(status, created_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS world.idx_tinytown_listings_seller "
                "ON tinytown_art_listings(seller_account_id, status)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS world.tinytown_art_sales (
                    sale_id TEXT PRIMARY KEY,
                    listing_id TEXT NOT NULL,
                    buyer_account_id TEXT NOT NULL,
                    seller_account_id TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    surface_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (listing_id, buyer_account_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS world.idx_tinytown_sales_buyer "
                "ON tinytown_art_sales(buyer_account_id, created_at)"
            )

    def prepare(self) -> None:
        """Materialize every persisted house and every household NPC."""

        if self._world.id != "tinytown":
            return
        for record in self._records():
            try:
                before = dict(record.room_ids)
                built = self._register_rooms(record)
            except (KeyError, ValueError):
                continue
            new_keys = [key for key in record.room_ids if key not in before]
            if new_keys:
                self._persist_room_ids(record)
                self._grant_new_rooms(record, built, new_keys)
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

    @property
    def roommates(self) -> object:
        from mods.tinytown.roommates import RoommateCandidates

        candidates = getattr(self, "_roommate_candidates", None)
        if candidates is None:
            self._roommate_candidates = RoommateCandidates(self)
            candidates = self._roommate_candidates
        return candidates

    @property
    def market(self) -> object:
        from mods.tinytown.market import TinyTownArtMarket

        market = getattr(self, "_art_market", None)
        if market is None:
            self._art_market = TinyTownArtMarket(self)
            market = self._art_market
        return market

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
            template_id = str(row["template_id"])
            if template_id not in self._templates:
                LOGGER.warning(
                    "tinytown.orphaned_house house_id=%s template_id=%s",
                    row["house_id"],
                    template_id,
                )
                continue
            records.append(
                HouseRecord(
                    house_id=str(row["house_id"]),
                    owner_account_id=str(row["owner_account_id"]),
                    template_id=template_id,
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
        template = self._templates.get(record.template_id)
        if template is None:
            raise ValueError(
                f"The house template '{record.template_id}' is no longer available."
            )
        return template

    def entry_room(self, record: HouseRecord) -> str:
        template = self.template_for(record)
        return record.room_ids[template.entry_key]

    def room_key(self, record: HouseRecord, room_id: str) -> str | None:
        return next((key for key, value in record.room_ids.items() if value == room_id), None)

    # -- materialization -----------------------------------------------------

    @staticmethod
    def _room_id(house_id: str, key: str) -> str:
        return f"{HOUSE_ROOM_PREFIX}{house_id}:{key}"

    def _house_grid_positions(
        self, record: HouseRecord, template: HouseTemplate
    ) -> dict[str, tuple[int, int, int]]:
        """Reuse existing coordinates and allocate free space only for new rooms."""

        positions: dict[str, tuple[int, int, int]] = {}
        for room in template.rooms:
            existing = self._world.rooms.get(record.room_ids.get(room.key, ""))
            if existing is not None and existing.grid is not None and not existing.template:
                positions[room.key] = existing.grid
        missing = [room.key for room in template.rooms if room.key not in positions]
        if missing:
            block = allocate_grid_block(
                self._world.rooms,
                len(missing),
                origin=HOUSE_GRID_ORIGIN,
                columns=HOUSE_GRID_COLUMNS,
            )
            positions.update(zip(missing, block))
        return positions

    def _build_room(
        self,
        record: HouseRecord,
        key: str,
        template: HouseTemplate,
        room_ids: dict[str, str],
        grid_positions: dict[str, tuple[int, int, int]] | None = None,
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
        grid = (grid_positions or {}).get(key)
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
            grid=grid,
            palette=template.palette,
            template=False,
            sprites_enabled=True,
        )

    def _register_rooms(self, record: HouseRecord) -> dict[str, RoomDefinition]:
        template = self.template_for(record)
        for key in template.rooms:
            if key.key not in record.room_ids:
                record.room_ids[key.key] = self._room_id(record.house_id, key.key)
        grid_positions = (
            self._house_grid_positions(record, template)
            if room_grid_enabled(self._world.rooms)
            else {}
        )
        built: dict[str, RoomDefinition] = {}
        for room_template in template.rooms:
            room = self._build_room(
                record, room_template.key, template, record.room_ids, grid_positions
            )
            self._world.rooms[room.id] = room
            built[room_template.key] = room
        apply_room_grid(self._world.rooms)
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

    def _persist_room_ids(self, record: HouseRecord) -> None:
        with self._hub.transaction() as connection:
            connection.execute(
                "UPDATE world.tinytown_houses SET room_ids_json = ? WHERE house_id = ?",
                (json.dumps(record.room_ids), record.house_id),
            )

    def _grant_new_rooms(
        self,
        record: HouseRecord,
        built: dict[str, RoomDefinition],
        new_keys: list[str],
    ) -> None:
        if self._profiles.get_account_by_id(record.owner_account_id) is None:
            LOGGER.warning("tinytown.orphaned_owner house_id=%s owner=%s", record.house_id, record.owner_account_id)
            return
        door = {"house_id": record.house_id, "template_id": record.template_id}
        with self._hub.transaction() as connection:
            for key in new_keys:
                room = built[key]
                self._world_state.insert_player_room(
                    connection,
                    room_id=room.id,
                    owner_account_id=record.owner_account_id,
                    door=door,
                )
                self._ownership.grant_in_transaction(connection, room.id, record.owner_account_id)
        for key in new_keys:
            self._world_state.seed_player_room(built[key].id, built[key], self._world)

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

    def _unlock_payload(self, template: HouseTemplate) -> list[dict[str, object]]:
        """Describe the propsets a house template unlocks on purchase."""

        payload: list[dict[str, object]] = []
        for propset_id in template.unlocks:
            prop_count = sum(
                1 for definition in self._world.props.values() if definition.source == propset_id
            )
            payload.append(
                {"id": propset_id, "label": propset_label(propset_id), "prop_count": prop_count}
            )
        return payload

    def _unlock_prop_ids(self, template: HouseTemplate) -> list[str]:
        """Return every prop id granted when *template* is purchased."""

        return sorted(
            definition.id
            for definition in self._world.props.values()
            if definition.source in set(template.unlocks)
        )

    def house_payload(self, record: HouseRecord, viewer_id: str) -> dict[str, object]:
        template = self._templates[record.template_id]
        district = DISTRICTS_BY_ID[template.district]
        return {
            "id": record.house_id,
            "template_id": record.template_id,
            "label": template.label,
            "description": template.description,
            "district": district.id,
            "district_label": district.label,
            "district_accent": district.accent,
            "price": template.price,
            "size": template.size,
            "unlocks": self._unlock_payload(template),
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
            "resident_count": len(self.npcs.records_for_house(record.house_id)),
            "max_residents": MAX_NPCS_PER_HOUSE,
            "owner_id": record.owner_account_id,
            "owner_username": self._owner_name(record.owner_account_id),
            "is_owner": record.owner_account_id == viewer_id,
            "locked": record.locked,
            "preview_url": f"/assets/world/{self._world.id}/rooms/{template.preview}",
            "key_url": f"/assets/world/{self._world.id}/keys/{template.id}.png",
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
            "unlocks": self._unlock_payload(template),
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

    def diorama_payload(self, account: object) -> dict[str, object]:
        """Describe every house model the viewer may see on the town diorama."""

        records = self._records()
        by_template: dict[str, list[HouseRecord]] = {}
        for record in records:
            by_template.setdefault(record.template_id, []).append(record)
        owner_names = {
            account_id: account.username_display
            for account_id, account in self._profiles.get_accounts_by_ids(
                [record.owner_account_id for record in records]
            ).items()
        }
        houses: list[dict[str, object]] = []
        for template in self._templates.values():
            template_records = by_template.get(template.id, [])
            owned = any(record.owner_account_id == account.id for record in template_records)
            instances: list[dict[str, object]] = []
            for record in template_records:
                is_owner = record.owner_account_id == account.id
                if not is_owner and record.locked:
                    continue
                entry = {
                    "house_id": record.house_id,
                    "owner_id": record.owner_account_id,
                    "owner_username": owner_names.get(
                        record.owner_account_id, "A former resident"
                    ),
                    "is_owner": is_owner,
                    "entry_room_id": self.entry_room(record),
                }
                if is_owner:
                    instances.insert(0, entry)
                else:
                    instances.append(entry)
            district = DISTRICTS_BY_ID[template.district]
            houses.append(
                {
                    "id": template.id,
                    "label": template.label,
                    "description": template.description,
                    "district": template.district,
                    "district_label": district.label,
                    "district_accent": district.accent,
                    "price": template.price,
                    "size": template.size,
                    "palette": list(template.palette),
                    "model_url": f"/assets/world/{self._world.id}/props/{template.model}",
                    "preview_url": f"/assets/world/{self._world.id}/rooms/{template.preview}",
                    "key_url": f"/assets/world/{self._world.id}/keys/{template.id}.png",
                    "lot": template.lot.payload(),
                    "owned": owned,
                    "available": owned or bool(instances),
                    "instances": instances,
                }
            )
        return {"houses": houses}

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
        owned = self.records_for_owner(account.id)
        if any(record.template_id == template.id for record in owned):
            raise ValueError(
                f"You already own a {template.label}. One copy of each home is plenty."
            )
        if len(owned) >= MAX_HOUSES:
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
                unlock_ids = self._unlock_prop_ids(template)
                if unlock_ids:
                    self._profiles.update_profile_in_transaction(
                        connection,
                        account.id,
                        lambda profile_json, ids=unlock_ids: _grant_prop_unlocks(
                            profile_json, ids
                        ),
                    )
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

    def art_room_for_house(self, account: object, house_id: str) -> str | None:
        """Return the preferred room in one owned house that can take a print."""

        record = next(
            (entry for entry in self.records_for_owner(account.id) if entry.house_id == house_id),
            None,
        )
        if record is None:
            return None
        template = self.template_for(record)
        preferred = {"gallery": 0, "studio": 1, "living": 2, "entry": 3}
        rooms = sorted(
            enumerate(template.rooms),
            key=lambda pair: (preferred.get(pair[1].role, 4), pair[0]),
        )
        for _index, room_template in rooms:
            room_id = record.room_ids.get(room_template.key)
            if not room_id or room_id not in self._world.rooms:
                continue
            view = self._layout.view(account, room_id)
            whiteboards = sum(
                1
                for prop in view.get("props", [])
                if str(prop.get("prop_id")) == WHITEBOARD_PROP_ID
            )
            if whiteboards < MAX_LAYOUT_WHITEBOARDS:
                return room_id
        return None

    def art_destinations(self, account: object) -> list[tuple[HouseRecord, str]]:
        """Return every owned house with its first room that can take a print."""

        results: list[tuple[HouseRecord, str]] = []
        for record in self.records_for_owner(account.id):
            room_id = self.art_room_for_house(account, record.house_id)
            if room_id is not None:
                results.append((record, room_id))
        return results

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
        whiteboards = sum(1 for prop in layout.get("props", []) if prop.get("prop_id") == WHITEBOARD_PROP_ID)
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
            "art": self.market.art_payloads(),
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

    def _refund_unlock(
        self,
        account: object,
        *,
        kind: str,
        item_id: str,
        price: int,
    ) -> None:
        if price <= 0:
            return
        with self._hub.transaction() as connection:
            connection.execute(
                "DELETE FROM world.tinytown_unlocks WHERE account_id = ? AND kind = ? AND item_id = ?",
                (account.id, kind, item_id),
            )
            current = self._profiles.get_account_by_id(account.id)
            if current is not None:
                self._profiles.update_progress(connection, current, bops=current.bops + price)

    def _layout_props(self, layout: dict[str, object]) -> list[dict[str, object]]:
        raw_props = layout.get("props")
        if not isinstance(raw_props, list):
            return []
        return [dict(prop) for prop in raw_props if isinstance(prop, dict)]

    def buy_floor(self, account: object, room_id: str, floor_id: str) -> DecorationResult:
        record = self.require_owned_room(account, room_id)
        del record
        floor = self._floors.get(floor_id)
        if floor is None:
            raise ValueError("That floor finish is not sold here.")
        unlocked_before = self.is_unlocked(account.id, "floor", floor.id)
        charged, bops_spent = False, 0
        if not unlocked_before:
            charged, bops_spent = self._charge_and_unlock(
                account, kind="floor", item_id=floor.id, price=floor.price
            )
        layout = self._layout.view(account, room_id)
        entries = self._layout_props(layout)
        try:
            update = self._layout.save(
                account,
                room_id,
                int(layout["revision"]),
                {"props": entries, "environment": {"board_image": floor.image}},
            )
        except LayoutRevisionConflict as exc:
            if charged:
                self._refund_unlock(account, kind="floor", item_id=floor.id, price=bops_spent)
            raise ValueError("The room changed while the Art Market was fitting the floor. Try again.") from exc
        except Exception:
            if charged:
                self._refund_unlock(account, kind="floor", item_id=floor.id, price=bops_spent)
            raise
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
        whiteboards = [prop for prop in layout.get("props", []) if prop.get("prop_id") == WHITEBOARD_PROP_ID]
        if len(whiteboards) >= MAX_LAYOUT_WHITEBOARDS:
            raise ValueError(
                f"This room already has {MAX_LAYOUT_WHITEBOARDS} pieces on the walls. "
                "Make space before hanging another."
            )
        unlocked_before = self.is_unlocked(account.id, "art", piece.id)
        charged, bops_spent = False, 0
        if not unlocked_before:
            charged, bops_spent = self._charge_and_unlock(
                account, kind="art", item_id=piece.id, price=piece.price
            )
        entries = self._layout_props(layout)
        slots = ((18.0, 9.0), (39.0, 9.0), (61.0, 9.0), (82.0, 9.0))
        used_x = {
            round(float(prop.get("position", [0.0])[0]), 1)
            for prop in whiteboards
            if isinstance(prop.get("position"), list) and prop.get("position")
        }
        x, y = next(
            (slot for slot in slots if round(slot[0], 1) not in used_x),
            slots[len(whiteboards) % len(slots)],
        )
        instance_id = f"custom:{uuid.uuid4()}"
        entries.append(
            {
                "id": instance_id,
                "prop_id": WHITEBOARD_PROP_ID,
                "position": [x, y, 0.0],
                "rotation": [0.0, 0.0, 0.0],
                "scale": 0.9,
                "locked": False,
            }
        )
        try:
            generated = self._surfaces.materialize_whiteboard(piece.surface, allow_legacy=True)
            surface = self._surfaces.install_whiteboard(room_id, instance_id, account.id, generated, locked=True)
            update = self._layout.save(
                account,
                room_id,
                int(layout["revision"]),
                {"props": entries, "environment": {}},
            )
        except LayoutRevisionConflict as exc:
            if charged:
                self._refund_unlock(account, kind="art", item_id=piece.id, price=bops_spent)
            raise ValueError("The room changed while the Art Market was wrapping your piece. Try again.") from exc
        except Exception:
            if charged:
                self._refund_unlock(account, kind="art", item_id=piece.id, price=bops_spent)
            raise
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
        self.gallery = TinytownGallery(self.housing)
        self.npcs = self.housing.npcs
        self.roommates = self.housing.roommates
        self.market = self.housing.market
        self._day_night = DayNightCycle(runtime)

    @property
    def available(self) -> bool:
        return self.runtime.world.id == "tinytown"

    def prepare(self) -> None:
        self.housing.prepare()
        if self.available:
            self.gallery.prepare()
        self._wire_dialog_settlement()

    def start(self) -> None:
        self.npcs.start()
        self._day_night.start()
        self._wire_dialog_settlement()

    def _wire_dialog_settlement(self) -> None:
        dialogs = getattr(self.runtime, "dialogs", None)
        attach = getattr(dialogs, "attach_side_effect_hook", None)
        if callable(attach):
            attach(self.npcs.on_dialog_choice)

    def stop(self) -> None:
        self.npcs.stop()
        self._day_night.stop()

    def npc_payload(self, peep: object, room_id: str | None) -> dict[str, object] | None:
        return self.npcs.npc_payload(peep, room_id)

    def phone_peers(self, owner_account_id: str) -> list[dict[str, str]]:
        """Return adopted roommates the owner can text, as thread peers."""

        if not self.available:
            return []
        from server.services.phone_messages import npc_thread_key

        try:
            records = self.npcs.records_for_owner(owner_account_id)
        except Exception:  # noqa: BLE001 - peers must never break the inbox
            return []
        return [
            {"thread_key": npc_thread_key("tinytown", record.npc_id), "name": record.name}
            for record in records
        ]

    def roommate_reply_text(
        self, owner: object, npc_id: str, player_text: str
    ) -> tuple[str, str] | None:
        """Return a canned (reply, name) for one owned roommate, if reachable."""

        if not self.available:
            return None
        try:
            record = self.npcs.record_for(npc_id)
        except Exception:  # noqa: BLE001 - replies must never break sending
            return None
        if record is None or record.owner_account_id != getattr(owner, "id", None):
            return None
        from mods.tinytown.roommate_messages import choose_reply_text, snapshot_for

        snapshot = snapshot_for(self.npcs, record)
        return (choose_reply_text(self.npcs._random, record, snapshot, player_text), record.name)

    def room_quick_actions(self, account: object, room: RoomDefinition) -> tuple[object, ...]:
        if not self.available:
            return ()
        if room.id == ENTRY_ROOM_ID:
            from server.content.worlds import QuickAction

            return (
                QuickAction(label="Find your TinyTown home", command=".play tiny-mag"),
                QuickAction(label="Visit the Art Gallery", command=".tinytown gallery"),
            )
        return ()

    def diorama_payload(self, account: object, room: RoomDefinition) -> dict[str, object] | None:
        """Contribute the viewer's house ownership and visitable instances."""

        if not self.available or room.id != ENTRY_ROOM_ID:
            return None
        try:
            return self.housing.diorama_payload(account)
        except Exception:  # noqa: BLE001 - diorama decoration must never break a room
            LOGGER.exception("tinytown.diorama_payload_failed")
            return None

    def personal_actions(self, account: object, prop: object) -> tuple[object, ...]:
        if not self.available:
            return ()
        try:
            return self.gallery.personal_actions(account, prop)
        except Exception:  # noqa: BLE001 - prop actions must never break room snapshots
            LOGGER.exception("tinytown.gallery_personal_actions_failed")
            return ()
