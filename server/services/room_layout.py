"""Validated room-owner decorative layout editing."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import uuid

from server.content.worlds import (
    BOARD_IMAGE_STYLES,
    PropDefinition,
    PropInstanceDefinition,
    RoomDefinition,
    WorldDefinition,
    prop_model_url,
)
from server.profiles import AccountRecord
from server.services.environment import EnvironmentService
from server.services.ownership import OwnershipService
from server.state.migrations import DatabaseHub
from server.state.world_state import LayoutRevisionConflict, WorldStateRepository


_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_MAX_PALETTE = 6


@dataclass(frozen=True, slots=True)
class LayoutUpdate:
    """A committed decorative layout ready to broadcast."""

    room_id: str
    revision: int
    props: list[dict[str, object]]
    environment: dict[str, object]

    def event(self) -> dict[str, object]:
        """Serialize the update as a room broadcast event."""

        return {
            "type": "room.layout.updated",
            "room_id": self.room_id,
            "revision": self.revision,
            "props": self.props,
            "environment": self.environment,
        }


def _vector(raw_value: object, fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 3:
        return fallback
    try:
        return (float(raw_value[0]), float(raw_value[1]), float(raw_value[2]))
    except (TypeError, ValueError):
        return fallback


class RoomLayoutService:
    """Owns the live decorative prop layout and validated editor saves."""

    def __init__(
        self,
        hub: DatabaseHub,
        world: WorldDefinition,
        world_state: WorldStateRepository,
        ownership: OwnershipService,
        environment: EnvironmentService,
    ) -> None:
        self._hub = hub
        self._world = world
        self._world_state = world_state
        self._ownership = ownership
        self._environment = environment

    def _room(self, room_id: str) -> RoomDefinition:
        room = self._world.rooms.get(room_id)
        if room is None:
            raise ValueError("That room does not exist.")
        return room

    def _approved_definitions(self, room: RoomDefinition) -> list[PropDefinition]:
        approved: dict[str, PropDefinition] = {}
        for instance in room.props.values():
            definition = self._world.props[instance.prop_id]
            if definition.editable:
                approved.setdefault(definition.id, definition)
        return list(approved.values())

    def can_edit(self, account: AccountRecord, room_id: str) -> bool:
        """Return whether an account may edit a room's decorative layout."""

        if room_id not in self._world.rooms:
            return False
        return self._ownership.can_edit(account, room_id)

    def revision(self, room_id: str) -> int:
        """Return the current layout revision for a room."""

        return int(self._world_state.read_room_layout(room_id)["revision"])

    def visual_environment(self, room_id: str) -> dict[str, object]:
        """Return only the whitelisted visual overrides for a room."""

        room = self._room(room_id)
        environment = self._environment.get(room_id)
        return {key: environment[key] for key in room.editor_environment if key in environment}

    def effective_board(self, room_id: str) -> dict[str, object]:
        """Return the room's effective palette and board image style."""

        room = self._room(room_id)
        visual = self.visual_environment(room_id)
        return {
            "palette": list(visual.get("palette") or room.palette),
            "board_image_style": str(visual.get("board_image_style") or room.board_image_style),
        }

    def effective_props(self, room_id: str) -> list[PropInstanceDefinition]:
        """Merge base gameplay props with the live editable layout."""

        room = self._room(room_id)
        live = self._world_state.read_room_layout(room_id)["props"]
        base = [instance for instance in room.props.values() if not self._world.props[instance.prop_id].editable]
        if live is None:
            base.extend(instance for instance in room.props.values() if self._world.props[instance.prop_id].editable)
            return base
        for entry in live:
            if not isinstance(entry, dict):
                continue
            definition = self._world.props.get(str(entry.get("prop_id")))
            if definition is None:
                continue
            base.append(
                PropInstanceDefinition(
                    id=str(entry.get("id")),
                    prop_id=definition.id,
                    pos=_vector(entry.get("position"), (50.0, 50.0, 0.0)),
                    rot=_vector(entry.get("rotation"), (0.0, 0.0, 0.0)),
                    scale=float(entry.get("scale", 1.0)),
                    behavior=None,
                    actions=(),
                    content=(),
                    cooldown=None,
                    personal=False,
                    recipes=(),
                    animation=None,
                    activity=None,
                )
            )
        return base

    def _serialize_instance(self, instance: PropInstanceDefinition) -> dict[str, object]:
        definition = self._world.props[instance.prop_id]
        animation = instance.animation if instance.animation is not None else definition.animation
        return {
            "id": instance.id,
            "prop_id": instance.prop_id,
            "position": list(instance.pos),
            "rotation": list(instance.rot),
            "scale": instance.scale * definition.scale,
            "behavior": instance.behavior,
            "model_url": prop_model_url(self._world.id, definition),
            "label": definition.label,
            "description": definition.description,
            "animation": animation,
            "quick_actions": [],
        }

    def _serialize_library(self, definition: PropDefinition) -> dict[str, object]:
        return {
            "prop_id": definition.id,
            "label": definition.label,
            "description": definition.description,
            "model_url": prop_model_url(self._world.id, definition),
            "base_scale": definition.scale,
            "scale_min": definition.editor_scale_min,
            "scale_max": definition.editor_scale_max,
        }

    def _editable_instances(self, room: RoomDefinition, live: list[object] | None) -> list[dict[str, object]]:
        if live is not None:
            return [
                {
                    "id": str(entry.get("id")),
                    "prop_id": str(entry.get("prop_id")),
                    "position": list(_vector(entry.get("position"), (50.0, 50.0, 0.0))),
                    "rotation": list(_vector(entry.get("rotation"), (0.0, 0.0, 0.0))),
                    "scale": float(entry.get("scale", 1.0)),
                }
                for entry in live
                if isinstance(entry, dict)
            ]
        return [
            {
                "id": instance.id,
                "prop_id": instance.prop_id,
                "position": list(instance.pos),
                "rotation": list(instance.rot),
                "scale": float(instance.scale),
            }
            for instance in room.props.values()
            if self._world.props[instance.prop_id].editable
        ]

    def view(self, account: AccountRecord, room_id: str) -> dict[str, object]:
        """Return the editable layout view for a room."""

        room = self._room(room_id)
        layout = self._world_state.read_room_layout(room_id)
        return {
            "room_id": room_id,
            "revision": int(layout["revision"]),
            "can_edit": self.can_edit(account, room_id),
            "props": self._editable_instances(room, layout["props"]),
            "library": [self._serialize_library(definition) for definition in self._approved_definitions(room)],
            "environment_whitelist": list(room.editor_environment),
            "environment": self.visual_environment(room_id),
        }

    def save(
        self,
        account: AccountRecord,
        room_id: str,
        base_revision: int,
        patch: dict[str, object],
    ) -> LayoutUpdate:
        """Validate and atomically commit a layout patch."""

        room = self._room(room_id)
        if not self.can_edit(account, room_id):
            raise ValueError("You do not have permission to edit this room.")
        if isinstance(base_revision, bool) or not isinstance(base_revision, int) or base_revision < 0:
            raise ValueError("A valid base revision is required.")
        if not isinstance(patch, dict):
            raise ValueError("The layout patch must be a mapping.")
        props = self._validate_props(room, patch.get("props"))
        environment_patch = self._validate_environment(room, patch.get("environment") or {})
        with self._hub.transaction() as connection:
            current_environment, current_revision = self._read(connection, room_id)
            if current_revision != base_revision:
                raise LayoutRevisionConflict("The room layout changed since you loaded it.")
            merged = {**current_environment, **environment_patch}
            revision = self._world_state.write_room_layout(
                connection,
                room_id,
                props,
                merged,
                expected_revision=base_revision,
            )
        effective = self.effective_props(room_id)
        return LayoutUpdate(
            room_id=room_id,
            revision=revision,
            props=[self._serialize_instance(instance) for instance in effective],
            environment=self.visual_environment(room_id),
        )

    @staticmethod
    def _read(connection, room_id: str) -> tuple[dict[str, object], int]:
        row = connection.execute(
            "SELECT environment_json, layout_revision FROM world.room_states WHERE room_id = ?",
            (room_id,),
        ).fetchone()
        if row is None:
            return {}, 0
        try:
            environment = json.loads(row["environment_json"])
        except (TypeError, ValueError):
            environment = {}
        return (environment if isinstance(environment, dict) else {}), int(row["layout_revision"])

    def _validate_props(self, room: RoomDefinition, raw_value: object) -> list[dict[str, object]]:
        if raw_value is None:
            raw_value = []
        if not isinstance(raw_value, list):
            raise ValueError("Layout props must be a list.")
        approved = {definition.id for definition in self._approved_definitions(room)}
        live = self._world_state.read_room_layout(room.id)["props"] or []
        known = {instance.id for instance in room.props.values() if self._world.props[instance.prop_id].editable}
        known.update(str(entry.get("id")) for entry in live if isinstance(entry, dict))
        seen: set[str] = set()
        props: list[dict[str, object]] = []
        for entry in raw_value:
            if not isinstance(entry, dict):
                raise ValueError("Each layout prop must be a mapping.")
            prop_id = str(entry.get("prop_id") or "")
            definition = self._world.props.get(prop_id)
            if definition is not None and not definition.editable:
                raise ValueError(f"Prop '{prop_id}' is not editable.")
            if prop_id not in approved:
                raise ValueError(f"Prop '{prop_id}' is not approved for editing.")
            instance_id = str(entry.get("id") or "")
            if not instance_id or instance_id in seen:
                raise ValueError("Layout prop IDs must be unique and non-empty.")
            if instance_id.startswith("custom:"):
                try:
                    uuid.UUID(instance_id[7:])
                except ValueError as exc:
                    raise ValueError(f"Invalid custom prop ID '{instance_id}'.") from exc
            elif instance_id not in known:
                raise ValueError(f"Unknown layout prop '{instance_id}'.")
            seen.add(instance_id)
            props.append(
                {
                    "id": instance_id,
                    "prop_id": prop_id,
                    "position": self._validate_position(entry.get("position")),
                    "rotation": self._validate_rotation(entry.get("rotation")),
                    "scale": self._validate_scale(entry.get("scale"), definition),
                }
            )
        return props

    @staticmethod
    def _validate_position(raw_value: object) -> list[float]:
        if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 3:
            raise ValueError("Prop positions must be [x, y, z] triples.")
        try:
            x, y, z = (float(raw_value[0]), float(raw_value[1]), float(raw_value[2]))
        except (TypeError, ValueError) as exc:
            raise ValueError("Prop positions must be numbers.") from exc
        if not (0 <= x <= 100 and 0 <= y <= 100):
            raise ValueError("Prop positions must stay on the board (x, y in 0-100).")
        if not (0 <= z <= 50):
            raise ValueError("Prop elevation must be between 0 and 50.")
        return [x, y, z]

    @staticmethod
    def _validate_rotation(raw_value: object) -> list[float]:
        if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 3:
            raise ValueError("Prop rotations must be [x, y, z] triples.")
        try:
            values = [float(raw_value[0]), float(raw_value[1]), float(raw_value[2])]
        except (TypeError, ValueError) as exc:
            raise ValueError("Prop rotations must be numbers.") from exc
        return [value % 360.0 for value in values]

    @staticmethod
    def _validate_scale(raw_value: object, definition: PropDefinition) -> float:
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise ValueError("Prop scale must be a number.")
        scale = float(raw_value)
        if not (definition.editor_scale_min <= scale <= definition.editor_scale_max):
            raise ValueError(
                f"Scale for '{definition.id}' must be between "
                f"{definition.editor_scale_min} and {definition.editor_scale_max}."
            )
        return scale

    @staticmethod
    def _validate_environment(room: RoomDefinition, raw_value: object) -> dict[str, object]:
        if raw_value is None:
            return {}
        if not isinstance(raw_value, dict):
            raise ValueError("The environment patch must be a mapping.")
        patch: dict[str, object] = {}
        for key, value in raw_value.items():
            if key not in room.editor_environment:
                raise ValueError(f"Environment setting '{key}' is not editable here.")
            if key == "palette":
                if not isinstance(value, list) or not 1 <= len(value) <= _MAX_PALETTE:
                    raise ValueError("Palette must be a short list of colors.")
                colors = [str(entry) for entry in value]
                if any(not _HEX_COLOR.match(color) for color in colors):
                    raise ValueError("Palette colors must be hex values like #a1b2c3.")
                patch[key] = colors
            elif key == "board_image_style":
                if value not in BOARD_IMAGE_STYLES:
                    raise ValueError("Unknown board image style.")
                patch[key] = str(value)
        return patch
