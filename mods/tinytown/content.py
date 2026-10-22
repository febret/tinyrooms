"""Loaders for TinyTown house templates and floor finishes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from mods.tinytown.catalog import DISTRICTS_BY_ID, ROLE_ORDER
from server.content.common import ContentError, load_yaml_file, require_mapping
from server.content.worlds import WorldDefinition


_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})


@dataclass(frozen=True, slots=True)
class HouseRoomTemplate:
    key: str
    blueprint: str
    label: str
    role: str


@dataclass(frozen=True, slots=True)
class HouseRecord:
    house_id: str
    owner_account_id: str
    template_id: str
    room_ids: dict[str, str]
    locked: bool
    created_at: str


@dataclass(frozen=True, slots=True)
class HouseTemplate:
    id: str
    label: str
    description: str
    district: str
    price: int
    size: str
    preview: str
    palette: tuple[str, ...]
    rooms: tuple[HouseRoomTemplate, ...]

    @property
    def entry_key(self) -> str:
        return self.rooms[0].key

    def room_for_key(self, key: str) -> HouseRoomTemplate | None:
        return next((room for room in self.rooms if room.key == key), None)


@dataclass(frozen=True, slots=True)
class FloorTexture:
    id: str
    label: str
    description: str
    price: int
    image: str
    tags: tuple[str, ...]


def _image_path(root: Path, raw_name: str, context: str) -> Path:
    name = str(raw_name).strip()
    if not name or Path(name).name != name or Path(name).suffix.lower() not in _IMAGE_SUFFIXES:
        raise ContentError(f"{context} must name an image file in the world's rooms folder.")
    path = (root / "rooms" / name).resolve()
    if not path.is_file():
        raise ContentError(f"{context} references missing image '{name}'.")
    return path


def load_house_templates(path: Path, world: WorldDefinition) -> dict[str, HouseTemplate]:
    """Load every authored house template and validate its blueprint rooms."""

    payload = require_mapping(load_yaml_file(path), path)
    templates: dict[str, HouseTemplate] = {}
    for template_id, raw in payload.items():
        if not isinstance(template_id, str) or not isinstance(raw, dict):
            raise ContentError(f"{path} contains an invalid house template.")
        label = str(raw.get("label", "")).strip()
        description = str(raw.get("description", "")).strip()
        district = str(raw.get("district", "")).strip()
        size = str(raw.get("size", "")).strip()
        if not label or not description or not size:
            raise ContentError(f"House template '{template_id}' must define label, description, and size.")
        if district not in DISTRICTS_BY_ID:
            raise ContentError(f"House template '{template_id}' has unknown district '{district}'.")
        price = raw.get("price")
        if isinstance(price, bool) or not isinstance(price, int) or not (100 <= price <= 10000):
            raise ContentError(f"House template '{template_id}' price must be between 100 and 10000 Bops.")
        preview = str(raw.get("preview", "")).strip()
        _image_path(world.root_path, preview, f"House template '{template_id}' preview")
        raw_palette = raw.get("palette")
        if not isinstance(raw_palette, list) or not 1 <= len(raw_palette) <= 6:
            raise ContentError(f"House template '{template_id}' palette must be a short colour list.")
        palette = tuple(str(color) for color in raw_palette)
        if any(not _HEX_COLOR.match(color) for color in palette):
            raise ContentError(f"House template '{template_id}' palette contains an invalid colour.")
        raw_rooms = raw.get("rooms")
        if not isinstance(raw_rooms, list) or len(raw_rooms) < 2:
            raise ContentError(f"House template '{template_id}' needs at least two rooms.")
        rooms: list[HouseRoomTemplate] = []
        seen_keys: set[str] = set()
        entry_role_seen = False
        for index, raw_room in enumerate(raw_rooms):
            if not isinstance(raw_room, dict):
                raise ContentError(f"House template '{template_id}' room {index + 1} must be a mapping.")
            key = str(raw_room.get("key", "")).strip()
            blueprint = str(raw_room.get("blueprint", "")).strip()
            room_label = str(raw_room.get("label", "")).strip()
            role = str(raw_room.get("role", "")).strip()
            if not key or not re.fullmatch(r"[a-z][a-z0-9-]*", key):
                raise ContentError(f"House template '{template_id}' has an invalid room key '{key}'.")
            if key in seen_keys:
                raise ContentError(f"House template '{template_id}' repeats room key '{key}'.")
            seen_keys.add(key)
            if not room_label:
                raise ContentError(f"House template '{template_id}' room '{key}' needs a label.")
            if role not in ROLE_ORDER:
                raise ContentError(f"House template '{template_id}' room '{key}' has unknown role '{role}'.")
            if role == "entry":
                if index != 0 or entry_role_seen:
                    raise ContentError(f"House template '{template_id}' must put its only entry room first.")
                entry_role_seen = True
            blueprint_room = world.rooms.get(blueprint)
            if blueprint_room is None or not blueprint_room.template:
                raise ContentError(
                    f"House template '{template_id}' references unknown room blueprint '{blueprint}'."
                )
            rooms.append(HouseRoomTemplate(key=key, blueprint=blueprint, label=room_label, role=role))
        if not entry_role_seen:
            raise ContentError(f"House template '{template_id}' needs an entry-role room.")
        templates[template_id] = HouseTemplate(
            id=template_id,
            label=label,
            description=description,
            district=district,
            price=price,
            size=size,
            preview=preview,
            palette=palette,
            rooms=tuple(rooms),
        )
    if not templates:
        raise ContentError(f"{path} does not define any house templates.")
    return templates


def load_floor_textures(path: Path, world: WorldDefinition) -> dict[str, FloorTexture]:
    """Load decorative floor finishes that the Art Market can apply."""

    payload = require_mapping(load_yaml_file(path), path)
    floors: dict[str, FloorTexture] = {}
    for floor_id, raw in payload.items():
        if not isinstance(floor_id, str) or not isinstance(raw, dict):
            raise ContentError(f"{path} contains an invalid floor entry.")
        label = str(raw.get("label", "")).strip()
        description = str(raw.get("description", "")).strip()
        image = str(raw.get("image", "")).strip()
        if not label or not description or not image:
            raise ContentError(f"Floor '{floor_id}' must define label, description, and image.")
        _image_path(world.root_path, image, f"Floor '{floor_id}'")
        price = raw.get("price")
        if isinstance(price, bool) or not isinstance(price, int) or price < 0:
            raise ContentError(f"Floor '{floor_id}' price must be a non-negative integer.")
        raw_tags = raw.get("tags", []) or []
        if not isinstance(raw_tags, list):
            raise ContentError(f"Floor '{floor_id}' tags must be a list.")
        floors[floor_id] = FloorTexture(
            id=floor_id,
            label=label,
            description=description,
            price=price,
            image=image,
            tags=tuple(str(tag).strip() for tag in raw_tags if str(tag).strip()),
        )
    if not floors:
        raise ContentError(f"{path} does not define any floor textures.")
    return floors
