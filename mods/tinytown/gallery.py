"""Procedurally generated TinyTown art gallery rooms.

The gallery is rebuilt from the current art catalog plus active resident
listings. Rooms are distributed so each one displays four to eight works, with
statuary, seating, lighting, plants, and purchasable decor between them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging
import math

from mods.tinytown.art import ART_BY_ID
from server.content.prop_definitions import PropInstanceDefinition, QuickAction
from server.content.surface_props import DEFAULT_WHITEBOARD_FRAME, WHITEBOARD_PROP_ID
from server.content.worlds import ExitDefinition, RoomDefinition


LOGGER = logging.getLogger("tinyrooms.mod.tinytown.gallery")

GALLERY_ROOM_PREFIX = "gallery:"
TOWN_ROOM_ID = "town"
ART_INSTANCE_PREFIX = "gallery-art:"
LISTING_INSTANCE_PREFIX = "gallery-listing:"
MAX_ART_PER_ROOM = 8
MIN_ART_PER_ROOM = 4
GALLERY_SYSTEM_ACCOUNT = "system:tinytown-gallery"

BASE_ROOMS = (
    "gallery-atrium-base",
    "gallery-hall-base",
    "gallery-cabinet-base",
)
ROOM_NAMES = (
    "The Atrium",
    "The Long Gallery",
    "The Cabinet Room",
    "The Print Room",
    "The East Salon",
    "The Sculpture Court",
    "The Blue Hall",
    "The West Salon",
    "The Lantern Gallery",
    "The Quiet Cabinet",
)
ROOM_DESCRIPTIONS = (
    "Marble, warm light, and a clear view of the collection.",
    "A long, quiet hang with a warm oak floor and excellent echo.",
    "A small cabinet for bright treasures and carefully placed shadows.",
)
FRAME_COLORS = ("#2f3b3a", "#101418", "#7a5230", "#14424f", "#8b1e2d", "#3b2a1f")
GALLERY_ART_ORDER = (
    "sunset-stroll",
    "midnight-harbor",
    "hilltop-bloom",
    "city-lights",
    "seed-packet",
    "cosmic-cat",
    "little-cottage",
    "golden-orchard",
    "dream-train",
    "starlight-library",
    "friendly-monster",
    "abstract-joy",
    "tidepool",
    "paper-boats",
)
DOOR_STYLE = {"style": "arch", "main": "#7a5230", "accent": "#c9a45c", "texture": "wood"}
DOOR_ROT_LEFT = (0.0, math.pi / 2, 0.0)
DOOR_ROT_RIGHT = (0.0, -math.pi / 2, 0.0)

ART_LAYOUTS = {
    1: ((50.0, 0.80),),
    2: ((35.0, 0.78), (65.0, 0.78)),
    3: ((23.0, 0.72), (50.0, 0.72), (77.0, 0.72)),
    4: ((16.0, 0.78), (38.67, 0.78), (61.33, 0.78), (84.0, 0.78)),
    5: ((12.0, 0.62), (31.0, 0.62), (50.0, 0.62), (69.0, 0.62), (88.0, 0.62)),
    6: ((11.0, 0.60), (26.6, 0.60), (42.2, 0.60), (57.8, 0.60), (73.4, 0.60), (89.0, 0.60)),
    7: ((9.0, 0.51), (22.7, 0.51), (36.3, 0.51), (50.0, 0.51), (63.7, 0.51), (77.3, 0.51), (91.0, 0.51)),
    8: ((8.0, 0.45), (20.0, 0.45), (32.0, 0.45), (44.0, 0.45), (56.0, 0.45), (68.0, 0.45), (80.0, 0.45), (92.0, 0.45)),
}


def art_slots(count: int) -> tuple[tuple[float, float], ...]:
    """Return stable back-wall slots for up to eight works."""

    if count <= 0:
        return ()
    if count in ART_LAYOUTS:
        return ART_LAYOUTS[count]
    return ART_LAYOUTS[8][:min(count, MAX_ART_PER_ROOM)]

DECOR_VARIANTS = (
    (
        ("marble-lion", 22.0, 58.0, 0.55, 0.0),
        ("marble-lion", 78.0, 58.0, 0.55, 0.0),
        ("marble-bust", 50.0, 38.0, 0.60, math.pi),
        ("italian-settee", 50.0, 60.0, 0.70, 0.0),
        ("italian-lemon-pot", 18.0, 86.0, 0.78, 0.0),
        ("italian-lemon-pot", 82.0, 86.0, 0.78, 0.0),
        ("gilt-floor-candlestick", 34.0, 88.0, 0.50, 0.0),
        ("gilt-floor-candlestick", 66.0, 88.0, 0.50, 0.0),
    ),
    (
        ("italian-settee", 50.0, 68.0, 0.70, 0.0),
        ("marble-discobolus", 22.0, 56.0, 0.60, -math.pi / 2),
        ("marble-discobolus", 78.0, 56.0, 0.60, math.pi / 2),
        ("italian-lemon-pot", 24.0, 88.0, 0.72, 0.0),
        ("italian-lemon-pot", 76.0, 88.0, 0.72, 0.0),
        ("gilt-floor-candlestick", 38.0, 92.0, 0.45, 0.0),
        ("gilt-floor-candlestick", 62.0, 92.0, 0.45, 0.0),
    ),
    (
        ("italian-amphora", 22.0, 54.0, 0.55, 0.0),
        ("italian-amphora", 78.0, 54.0, 0.55, 0.0),
        ("marble-goddess", 50.0, 58.0, 0.55, math.pi),
        ("crimson-chaise", 50.0, 78.0, 0.70, 0.0),
        ("italian-lemon-pot", 22.0, 87.0, 0.70, 0.0),
        ("italian-lemon-pot", 78.0, 87.0, 0.70, 0.0),
        ("gilt-floor-candlestick", 32.0, 92.0, 0.42, 0.0),
        ("gilt-floor-candlestick", 68.0, 92.0, 0.42, 0.0),
    ),
)


@dataclass(frozen=True, slots=True)
class GalleryArt:
    kind: str
    item_id: str
    title: str
    description: str
    price: int
    artist: str
    surface: dict[str, object]

    @property
    def instance_id(self) -> str:
        prefix = ART_INSTANCE_PREFIX if self.kind == "art" else LISTING_INSTANCE_PREFIX
        return f"{prefix}{self.item_id}"


@dataclass(frozen=True, slots=True)
class GalleryPurchase:
    message: str
    destination_room_id: str
    destination_label: str
    layout_event: dict[str, object]
    surface_event: dict[str, object] | None
    bops_spent: int


def parse_art_instance(instance_id: str) -> tuple[str, str] | None:
    """Return ``(kind, item_id)`` for a gallery art prop instance id."""

    if instance_id.startswith(ART_INSTANCE_PREFIX):
        return "art", instance_id[len(ART_INSTANCE_PREFIX):]
    if instance_id.startswith(LISTING_INSTANCE_PREFIX):
        return "listing", instance_id[len(LISTING_INSTANCE_PREFIX):]
    return None


class TinytownGallery:
    """Build and maintain the room-based gallery wing."""

    def __init__(self, housing: object) -> None:
        self.housing = housing
        self.runtime = housing.runtime
        self.world = housing.runtime.world
        self.hub = housing.runtime.hub
        self.world_state = housing.runtime.world_state
        self.surfaces = housing.runtime.surfaces
        self.market = housing.market
        self._signature: tuple[tuple[str, str, str], ...] | None = None
        self._room_ids: list[str] = []

    @property
    def room_ids(self) -> tuple[str, ...]:
        return tuple(self._room_ids)

    @property
    def entry_room_id(self) -> str:
        return f"{GALLERY_ROOM_PREFIX}1"

    def prepare(self) -> None:
        """Build the gallery during runtime startup."""

        self.ensure()

    def ensure(self, *, force: bool = False) -> None:
        """Rebuild the gallery when its art feed or room count has changed."""

        arts = self._art_entries()
        signature = tuple(
            (art.kind, art.item_id, str(art.surface.get("image_hash") or "")) for art in arts
        )
        if not force and signature == self._signature and self._rooms_loaded():
            return
        self._build(arts)
        self._signature = signature

    def _rooms_loaded(self) -> bool:
        return bool(self._room_ids) and all(room_id in self.world.rooms for room_id in self._room_ids)

    def _art_entries(self) -> list[GalleryArt]:
        entries: list[GalleryArt] = []
        payloads = {str(payload["id"]): payload for payload in self.market.art_payloads()}
        ordered_ids = [piece_id for piece_id in GALLERY_ART_ORDER if piece_id in payloads]
        ordered_ids.extend(sorted(set(payloads) - set(ordered_ids)))
        for piece_id in ordered_ids:
            payload = payloads[piece_id]
            entries.append(
                GalleryArt(
                    kind="art",
                    item_id=str(payload["id"]),
                    title=str(payload["label"]),
                    description=str(payload.get("description") or ""),
                    price=int(payload.get("price") or 0),
                    artist="The TinyTown Collection",
                    surface=dict(payload.get("surface") or {}),
                )
            )
        for listing in self.market.gallery_listings():
            entries.append(
                GalleryArt(
                    kind="listing",
                    item_id=str(listing["id"]),
                    title=str(listing["title"]),
                    description=str(listing.get("description") or ""),
                    price=int(listing.get("price") or 0),
                    artist=str(listing.get("seller_username") or "A resident"),
                    surface=dict(listing.get("surface") or {}),
                )
            )
        return entries

    @staticmethod
    def _room_count(total: int) -> int:
        if total <= 0:
            return 1
        maximum = max(1, total // MIN_ART_PER_ROOM)
        ideal = max(1, math.ceil(total / 6))
        return min(ideal, maximum)

    @staticmethod
    def _room_sizes(total: int, count: int) -> list[int]:
        base, extra = divmod(total, count)
        return [base + (1 if index < extra else 0) for index in range(count)]

    def _build(self, arts: list[GalleryArt]) -> None:
        count = self._room_count(len(arts))
        sizes = self._room_sizes(len(arts), count)
        new_rooms: list[RoomDefinition] = []
        cursor = 0
        for index, size in enumerate(sizes):
            chunk = arts[cursor:cursor + size]
            cursor += size
            new_rooms.append(self._build_room(index, count, chunk))

        old_ids = set(self._room_ids)
        self._room_ids = [room.id for room in new_rooms]
        for room in new_rooms:
            self.world.rooms[room.id] = room
            self.world_state.sync_generated_room(room.id, room, self.world)
            self._install_surfaces(room)
        for room_id in old_ids - set(self._room_ids):
            with self.hub.transaction() as connection:
                connection.execute("DELETE FROM world.room_cards WHERE room_id = ?", (room_id,))
                self.world_state.delete_room_state(connection, room_id)
            self.world.rooms.pop(room_id, None)

    def _build_room(self, index: int, total_rooms: int, arts: list[GalleryArt]) -> RoomDefinition:
        base = self.world.rooms[BASE_ROOMS[index % len(BASE_ROOMS)]]
        room_id = f"{GALLERY_ROOM_PREFIX}{index + 1}"
        name = ROOM_NAMES[index] if index < len(ROOM_NAMES) else f"Gallery {index + 1}"
        variant = index % len(DECOR_VARIANTS)
        props = self._art_props(arts)
        props.update(self._decor_props(variant))
        exits, doors = self._doors(index, total_rooms)
        props.update(doors)
        work_count = len(arts)
        description = (
            f"{ROOM_DESCRIPTIONS[variant]} {work_count} work{'s' if work_count != 1 else ''} "
            "on display, with pieces available for residents' homes."
        )
        return replace(
            base,
            id=room_id,
            label=name,
            description=description,
            props=props,
            exits=exits,
            template=False,
            sprites_enabled=True,
        )

    def _art_props(self, arts: list[GalleryArt]) -> dict[str, PropInstanceDefinition]:
        props: dict[str, PropInstanceDefinition] = {}
        slots = art_slots(len(arts))
        for index, art in enumerate(arts):
            x, scale = slots[index]
            y = 10.5
            rotation = 0.0
            surface = self._framed_surface(art.surface, index + len(art.item_id))
            price = f" · {art.price} Bops" if art.price else ""
            if art.kind == "art":
                label = f"“{art.title}”{price}"
            else:
                label = f"“{art.title}” by {art.artist}{price}"
            props[art.instance_id] = PropInstanceDefinition(
                id=art.instance_id,
                prop_id=WHITEBOARD_PROP_ID,
                pos=(x, y, 0.0),
                rot=(0.0, rotation, 0.0),
                scale=scale,
                actions=(),
                personal=False,
                animation=None,
                label=label,
                description=art.description or "A framed work from the TinyTown gallery.",
                surface=surface,
                read_only_surface=True,
            )
        return props

    @staticmethod
    def _framed_surface(surface: dict[str, object], seed: int) -> dict[str, object]:
        content = dict(surface)
        raw_frame = content.get("frame")
        frame = dict(raw_frame) if isinstance(raw_frame, dict) else dict(DEFAULT_WHITEBOARD_FRAME)
        frame["main"] = FRAME_COLORS[seed % len(FRAME_COLORS)]
        content["frame"] = frame
        return content

    def _decor_props(self, variant: int) -> dict[str, PropInstanceDefinition]:
        props: dict[str, PropInstanceDefinition] = {}
        for index, (prop_id, x, y, scale, rotation) in enumerate(DECOR_VARIANTS[variant]):
            definition = self.world.props.get(prop_id)
            if definition is None:
                LOGGER.warning("tinytown.gallery_missing_decor prop_id=%s", prop_id)
                continue
            actions: tuple[QuickAction, ...] = ()
            if definition.decorative and definition.locked and definition.source_kind == "propset":
                actions = (
                    QuickAction(
                        label=f"Unlock {definition.label} · {definition.price} Bops",
                        command=f".buy_prop {definition.id}",
                        default=True,
                    ),
                )
            instance_id = f"gallery-decor-{variant}-{index}-{prop_id}"
            props[instance_id] = PropInstanceDefinition(
                id=instance_id,
                prop_id=prop_id,
                pos=(x, y, 0.0),
                rot=(0.0, rotation, 0.0),
                scale=scale,
                actions=actions,
                personal=False,
                animation=None,
                label=definition.label,
                description=definition.description,
            )
        return props

    def _doors(
        self, index: int, total_rooms: int
    ) -> tuple[dict[str, ExitDefinition], dict[str, PropInstanceDefinition]]:
        exits: dict[str, ExitDefinition] = {}
        props: dict[str, PropInstanceDefinition] = {}
        if index == 0:
            left_target: str | None = TOWN_ROOM_ID
        else:
            left_target = f"{GALLERY_ROOM_PREFIX}{index}"
        if index + 1 < total_rooms:
            right_target: str | None = f"{GALLERY_ROOM_PREFIX}{index + 2}"
        elif index > 0:
            right_target = TOWN_ROOM_ID
        else:
            right_target = None

        if left_target == TOWN_ROOM_ID:
            exits["to-town"] = self._exit("to-town", "Return to TinyTown", TOWN_ROOM_ID)
            props["gallery-door-left"] = self._door("gallery-door-left", 3.0, DOOR_ROT_LEFT, "to-town")
        elif left_target is not None:
            exit_id = f"to-{left_target.split(':')[-1]}"
            exits[exit_id] = self._exit(exit_id, f"Back to {ROOM_NAMES[index - 1]}", left_target)
            props["gallery-door-left"] = self._door("gallery-door-left", 3.0, DOOR_ROT_LEFT, exit_id)

        if right_target == TOWN_ROOM_ID:
            exits["to-town"] = self._exit("to-town", "Return to TinyTown", TOWN_ROOM_ID)
            props["gallery-door-right"] = self._door("gallery-door-right", 97.0, DOOR_ROT_RIGHT, "to-town")
        elif right_target is not None:
            exit_id = f"to-{right_target.split(':')[-1]}"
            next_name = ROOM_NAMES[index + 1] if index + 1 < len(ROOM_NAMES) else f"Gallery {index + 2}"
            exits[exit_id] = self._exit(exit_id, f"Enter {next_name}", right_target)
            props["gallery-door-right"] = self._door("gallery-door-right", 97.0, DOOR_ROT_RIGHT, exit_id)
        return exits, props

    @staticmethod
    def _exit(exit_id: str, label: str, target: str) -> ExitDefinition:
        return ExitDefinition(
            id=exit_id,
            label=label,
            target_room_id=target,
            locked=False,
            requires_card_id=None,
        )

    @staticmethod
    def _door(
        instance_id: str,
        x: float,
        rotation: tuple[float, float, float],
        exit_id: str,
    ) -> PropInstanceDefinition:
        return PropInstanceDefinition(
            id=instance_id,
            prop_id="builtin:door",
            pos=(x, 50.0, 0.0),
            rot=rotation,
            scale=1.0,
            actions=(),
            personal=False,
            animation=None,
            exit_to=exit_id,
            exit_style=dict(DOOR_STYLE),
        )

    def _install_surfaces(self, room: RoomDefinition) -> None:
        for prop in room.props.values():
            if prop.prop_id != WHITEBOARD_PROP_ID or not isinstance(prop.surface, dict):
                continue
            try:
                self.surfaces.install_whiteboard(
                    room.id,
                    prop.id,
                    GALLERY_SYSTEM_ACCOUNT,
                    prop.surface,
                    locked=True,
                )
            except ValueError as exc:
                LOGGER.warning(
                    "tinytown.gallery_surface_failed room=%s instance=%s error=%s",
                    room.id,
                    prop.id,
                    exc,
                )

    def personal_actions(self, account: object, prop: object) -> tuple[QuickAction, ...]:
        parsed = parse_art_instance(getattr(prop, "id", ""))
        if parsed is None:
            return ()
        kind, item_id = parsed
        price, owned, own_listing = self._purchase_state(account, kind, item_id)
        if own_listing:
            return (
                QuickAction(
                    label="Your own listing is on display",
                    command=f".tinytown collect {kind} {item_id}",
                    default=True,
                ),
            )
        destinations = self.housing.art_destinations(account)
        if not destinations:
            has_homes = bool(self.housing.records_for_owner(account.id))
            label = (
                "All your walls are full — make space"
                if has_homes
                else "Collecting art needs a home with wall space"
            )
            return (
                QuickAction(
                    label=label,
                    command=f".tinytown collect {kind} {item_id}",
                    default=True,
                ),
            )
        actions: list[QuickAction] = []
        for record, room_id in destinations:
            house = self.housing.template_for(record).label
            room = self.world.rooms[room_id].label
            if owned:
                label = f"Hang another copy in {house} · {room}"
            else:
                label = f"Buy for {house} · {room} · {price} Bops"
            actions.append(
                QuickAction(
                    label=label,
                    command=f".tinytown collect {kind} {item_id} {record.house_id}",
                    default=not actions,
                )
            )
        return tuple(actions)

    def _purchase_state(self, account: object, kind: str, item_id: str) -> tuple[int, bool, bool]:
        if kind == "art":
            piece = ART_BY_ID.get(item_id)
            if piece is None:
                raise ValueError("That artwork is not in the collection.")
            return piece.price, self.housing.is_unlocked(account.id, "art", piece.id), False
        listing = self.market.get_listing(item_id)
        if listing is None or listing.status != "active":
            raise ValueError("That resident print is no longer for sale.")
        return (
            listing.price,
            self.market.owns_listing(account.id, listing.listing_id),
            listing.seller_id == account.id,
        )

    def collect(self, account: object, kind: str, item_id: str, house_id: str | None) -> GalleryPurchase:
        """Buy or re-hang a gallery work into the selected owned home."""

        if not house_id:
            if kind == "listing":
                listing = self.market.get_listing(item_id)
                if listing is not None and listing.seller_id == account.id:
                    raise ValueError("This is your own listing. It stays on display at the gallery.")
            if kind not in {"art", "listing"}:
                raise ValueError("That artwork is not in the collection.")
            raise ValueError("Choose one of your homes from the purchase actions.")
        room_id = self.housing.art_room_for_house(account, house_id)
        if room_id is None:
            owned = any(record.house_id == house_id for record in self.housing.records_for_owner(account.id))
            if not owned:
                raise ValueError("You do not own that home.")
            raise ValueError("That home has no free wall space. Make room for another print first.")
        if kind == "art":
            if item_id not in ART_BY_ID:
                raise ValueError("That artwork is not in the collection.")
            result = self.housing.hang_art(account, room_id, item_id)
        elif kind == "listing":
            listing = self.market.get_listing(item_id)
            if listing is None or listing.status != "active":
                raise ValueError("That resident print is no longer for sale.")
            if listing.seller_id == account.id:
                raise ValueError("You cannot buy your own listing.")
            if self.market.owns_listing(account.id, item_id):
                result = self.market.hang_owned(account, room_id, item_id)
            else:
                result = self.market.buy(account, room_id, item_id)
        else:
            raise ValueError("That gallery item is not available.")
        return GalleryPurchase(
            message=result.message,
            destination_room_id=room_id,
            destination_label=self.world.rooms[room_id].label,
            layout_event=result.layout_event,
            surface_event=result.surface_event,
            bops_spent=result.bops_spent,
        )
