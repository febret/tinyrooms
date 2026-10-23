"""Validated room-owner decorative layout editing."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import uuid

from server.content.surface_props import (
    DEFAULT_SIGN_STYLE,
    MAX_SIGN_PROPS,
    MAX_WHITEBOARD_PROPS,
    SIGN_PROP_ID,
    WHITEBOARD_PROP_ID,
    default_activity,
    sign_options,
    validate_sign_style,
    whiteboard_options,
)
from server.content.text_props import (
    MAX_ROOM_TEXT_LENGTH,
    MAX_TEXT_PROPS,
    TEXT_PROP_ID,
    text_options,
    validate_text,
)
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
from server.services.prop_shop import PropShopService, serialize_prop_entry
from server.services.prop_surfaces import PropSurfaceService, surface_kind
from server.state.migrations import DatabaseHub
from server.state.world_state import LayoutRevisionConflict, WorldStateRepository


def _read_sign_style(raw_value: object) -> str:
    """Return a stored sign style, falling back when legacy data is invalid."""

    try:
        return validate_sign_style(raw_value)
    except ValueError:
        return DEFAULT_SIGN_STYLE


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


@dataclass(frozen=True, slots=True)
class RoomReset:
    """A committed room reset ready to broadcast."""

    room_id: str
    revision: int
    prop_instance_ids: tuple[str, ...]

    def event(self) -> dict[str, object]:
        """Serialize the reset as a room broadcast event."""

        return {
            "type": "room.reset",
            "room_id": self.room_id,
            "revision": self.revision,
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
        prop_shop: PropShopService,
        room_effects: object | None = None,
        prop_states: object | None = None,
        surfaces: PropSurfaceService | None = None,
    ) -> None:
        self._hub = hub
        self._world = world
        self._world_state = world_state
        self._ownership = ownership
        self._environment = environment
        self._prop_shop = prop_shop
        self._room_effects = room_effects
        self._prop_states = prop_states
        self._surfaces = surfaces

    def _room(self, room_id: str) -> RoomDefinition:
        room = self._world.rooms.get(room_id)
        if room is None:
            raise ValueError("That room does not exist.")
        return room

    def _catalog_definitions(self, room: RoomDefinition) -> list[PropDefinition]:
        # Shared propset props form a global decorative catalog owners may add
        # from; world and mod props stay curated by the room's own instances.
        approved: dict[str, PropDefinition] = {}
        for definition in self._world.props.values():
            if definition.decorative and not definition.hidden and definition.source_kind in {"propset", "builtin"}:
                approved.setdefault(definition.id, definition)
        for instance in room.props.values():
            definition = self._world.props[instance.prop_id]
            if definition.decorative and not definition.hidden:
                approved.setdefault(definition.id, definition)
        return sorted(approved.values(), key=lambda definition: definition.id)

    def _unlocked(self, account: AccountRecord) -> set[str]:
        return self._prop_shop.unlocked(account.id)

    def _is_locked(self, definition: PropDefinition, unlocked: set[str]) -> bool:
        return self._prop_shop.is_locked(definition, unlocked)

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
            "board_image": str(visual.get("board_image") or room.board_image_name),
        }

    def effective_props(self, room_id: str) -> list[PropInstanceDefinition]:
        """Merge base gameplay props with the live editable layout."""

        room = self._room(room_id)
        live = self._world_state.read_room_layout(room_id)["props"]
        base = [
            instance
            for instance in room.props.values()
            if not self._world.props[instance.prop_id].decorative
            and not self._world.props[instance.prop_id].hidden
        ]
        if live is None:
            base.extend(
                instance
                for instance in room.props.values()
                if self._world.props[instance.prop_id].decorative
                and not self._world.props[instance.prop_id].hidden
            )
            return [
                instance
                if instance.activity or not default_activity(self._world.props[instance.prop_id].render_kind)
                else replace(instance, activity=default_activity(self._world.props[instance.prop_id].render_kind))
                for instance in base
            ]
        for entry in live:
            if not isinstance(entry, dict):
                continue
            definition = self._world.props.get(str(entry.get("prop_id")))
            if definition is None or definition.hidden:
                continue
            instance_id = str(entry.get("id"))
            source = room.props.get(instance_id)
            base.append(
                PropInstanceDefinition(
                    id=instance_id,
                    prop_id=definition.id,
                    pos=_vector(entry.get("position"), (50.0, 50.0, 0.0)),
                    rot=_vector(entry.get("rotation"), (0.0, 0.0, 0.0)),
                    scale=float(entry.get("scale", 1.0)),
                    behavior=source.behavior if source else None,
                    actions=source.actions if source else (),
                    content=source.content if source else (),
                    cooldown=source.cooldown if source else None,
                    personal=source.personal if source else False,
                    recipes=source.recipes if source else (),
                    animation=source.animation if source else None,
                    activity=(
                        source.activity
                        if source and source.activity
                        else default_activity(definition.render_kind)
                    ),
                    draw_weight=source.draw_weight if source else {},
                    only_missing=source.only_missing if source else False,
                    text=dict(entry["text"]) if definition.render_kind == "text" else None,
                    sign_style=(
                        str(entry.get("sign_style") or "")
                        if definition.render_kind == "sign" and entry.get("sign_style")
                        else (source.sign_style if source and definition.render_kind == "sign" else None)
                    ),
                    surface=source.surface if source else None,
                )
            )
        return base

    def _state_payload(
        self,
        room_id: str,
        instance_id: str,
        definition: PropDefinition,
    ) -> dict[str, object]:
        if not definition.states:
            return {}
        active = definition.active_state
        if self._prop_states is not None:
            active = self._prop_states.state_for(room_id, instance_id, active)
        if active not in definition.states:
            active = definition.active_state
        return {
            "state": active,
            "active_state": active,
            "states": {
                state_name: prop_model_url(self._world.id, definition, state_name) or ""
                for state_name in definition.states
            },
        }

    def _effect_payload(
        self,
        room_id: str,
        instance_id: str,
        definition: PropDefinition,
    ) -> dict[str, object]:
        if not definition.effect_sets:
            return {}
        active = definition.active_effect
        if self._room_effects is not None:
            active = self._room_effects.active_for(room_id, instance_id, active)
        if active not in definition.effect_sets:
            active = definition.active_effect
        return {
            "effect_sets": {
                set_name: [
                    self._world.effects[effect_id].serialize()
                    for effect_id in effect_ids
                    if effect_id in self._world.effects
                ]
                for set_name, effect_ids in definition.effect_sets.items()
            },
            "active_effect": active,
        }

    def _serialize_instance(self, room_id: str, instance: PropInstanceDefinition) -> dict[str, object]:
        definition = self._world.props[instance.prop_id]
        animation = instance.animation if instance.animation is not None else definition.animation
        state_payload = self._state_payload(room_id, instance.id, definition)
        active_state = state_payload.get("state")
        surface = self._surface_payload(room_id, instance, definition)
        return {
            "id": instance.id,
            "prop_id": instance.prop_id,
            "position": list(instance.pos),
            "rotation": list(instance.rot),
            "scale": instance.scale * definition.scale,
            "behavior": instance.behavior,
            "model_url": prop_model_url(
                self._world.id,
                definition,
                active_state if isinstance(active_state, str) else None,
            ),
            "render_kind": definition.render_kind,
            **({"text": dict(instance.text)} if instance.text is not None else {}),
            **({"sign_style": _read_sign_style(instance.sign_style)} if definition.render_kind == "sign" else {}),
            **({"surface": surface} if surface is not None else {}),
            "label": definition.label,
            "description": definition.description,
            "animation": animation,
            "quick_actions": [],
            **state_payload,
            **self._effect_payload(room_id, instance.id, definition),
        }

    def _surface_payload(
        self,
        room_id: str,
        instance: PropInstanceDefinition,
        definition: PropDefinition,
    ) -> dict[str, object] | None:
        kind = surface_kind(definition.render_kind)
        if kind is None or self._surfaces is None:
            return None
        return self._surfaces.get(
            room_id,
            instance.id,
            kind,
            default_content=instance.surface,
        ).serialize()

    def _serialize_library(self, definition: PropDefinition) -> dict[str, object]:
        # Locking is reported statically; the client hides locked props unless
        # the account owns them, so purchases reflect instantly without a refetch.
        return serialize_prop_entry(self._world, definition)

    def _editable_instances(self, room: RoomDefinition, live: list[object] | None) -> list[dict[str, object]]:
        if live is not None:
            entries = [
                {
                    "id": str(entry.get("id")),
                    "prop_id": str(entry.get("prop_id")),
                    "position": list(_vector(entry.get("position"), (50.0, 50.0, 0.0))),
                    "rotation": list(_vector(entry.get("rotation"), (0.0, 0.0, 0.0))),
                    "scale": float(entry.get("scale", 1.0)),
                    "locked": bool(entry.get("locked")),
                    **({"text": dict(entry["text"])} if isinstance(entry.get("text"), dict) else {}),
                    **({"sign_style": str(entry["sign_style"])} if isinstance(entry.get("sign_style"), str) else {}),
                }
                for entry in live
                if isinstance(entry, dict)
            ]
        else:
            entries = [
                {
                    "id": instance.id,
                    "prop_id": instance.prop_id,
                    "position": list(instance.pos),
                    "rotation": list(instance.rot),
                    "scale": float(instance.scale),
                    "locked": False,
                    **({"text": dict(instance.text)} if instance.text is not None else {}),
                    **({"sign_style": instance.sign_style} if instance.sign_style is not None else {}),
                }
                for instance in room.props.values()
                if self._world.props[instance.prop_id].decorative
                and not self._world.props[instance.prop_id].hidden
            ]
        entries = [
            entry
            for entry in entries
            if (definition := self._world.props.get(str(entry["prop_id"]))) is None
            or not definition.hidden
        ]
        for entry in entries:
            definition = self._world.props.get(str(entry["prop_id"]))
            if definition is not None:
                entry["render_kind"] = definition.render_kind
                if definition.render_kind == "sign":
                    entry["sign_style"] = _read_sign_style(entry.get("sign_style"))
                entry.update(self._effect_payload(room.id, str(entry["id"]), definition))
                kind = surface_kind(definition.render_kind)
                if kind is not None and self._surfaces is not None:
                    source = room.props.get(str(entry["id"]))
                    entry["surface"] = self._surfaces.get(
                        room.id,
                        str(entry["id"]),
                        kind,
                        default_content=source.surface if source is not None else None,
                    ).serialize()
        return entries

    def view(self, account: AccountRecord, room_id: str) -> dict[str, object]:
        """Return the editable layout view for a room."""

        room = self._room(room_id)
        layout = self._world_state.read_room_layout(room_id)
        return {
            "room_id": room_id,
            "revision": int(layout["revision"]),
            "can_edit": self.can_edit(account, room_id),
            "props": self._editable_instances(room, layout["props"]),
            "library": [
                self._serialize_library(definition)
                for definition in self._catalog_definitions(room)
            ],
            "environment_whitelist": list(room.editor_environment),
            "environment": self.visual_environment(room_id),
            "text_options": text_options(),
            "sign_options": sign_options(),
            "whiteboard_options": whiteboard_options(),
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
        props = self._validate_props(room, patch.get("props"), account)
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
        if self._surfaces is not None:
            self._surfaces.prune_room(room_id, {str(entry["id"]) for entry in props})
        return LayoutUpdate(
            room_id=room_id,
            revision=revision,
            props=[self._serialize_instance(room_id, instance) for instance in effective],
            environment=self.visual_environment(room_id),
        )

    def reset(
        self,
        account: AccountRecord,
        room_id: str,
        *,
        authorized_override: bool = False,
    ) -> RoomReset:
        """Restore a room's live state to its definition and return the update.

        ``authorized_override`` lets an already-gated editor route (World
        Editor) reset rooms the actor does not own; ordinary room editors use
        the standard ownership check.
        """

        room = self._room(room_id)
        if not authorized_override and not self.can_edit(account, room_id):
            raise ValueError("You do not have permission to edit this room.")
        if room.template:
            raise ValueError("Template rooms cannot be reset.")
        revision = self._world_state.reset_room_state(self._world, room_id)
        if self._room_effects is not None:
            self._room_effects.clear_room(room_id)
        if self._prop_states is not None:
            self._prop_states.clear_room(room_id)
        if self._surfaces is not None:
            self._surfaces.clear_room(room_id)
        return RoomReset(
            room_id=room_id,
            revision=revision,
            prop_instance_ids=tuple(room.props.keys()),
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

    def _validate_props(
        self,
        room: RoomDefinition,
        raw_value: object,
        account: AccountRecord,
    ) -> list[dict[str, object]]:
        if raw_value is None:
            raw_value = []
        if not isinstance(raw_value, list):
            raise ValueError("Layout props must be a list.")
        unlocked = self._unlocked(account)
        approved = {
            definition.id
            for definition in self._catalog_definitions(room)
            if not self._is_locked(definition, unlocked)
        }
        # Props already placed in this room stay editable even when locked, so
        # owners can keep, move, or remove them without buying the unlock.
        approved.update(
            instance.prop_id
            for instance in room.props.values()
            if self._world.props[instance.prop_id].decorative
        )
        live = self._world_state.read_room_layout(room.id)["props"] or []
        approved.update(str(entry.get("prop_id")) for entry in live if isinstance(entry, dict))
        known = {instance.id for instance in room.props.values() if self._world.props[instance.prop_id].decorative}
        known.update(str(entry.get("id")) for entry in live if isinstance(entry, dict))
        # Hidden props are invisible to the room editor, so a saved visible
        # layout must carry them forward rather than dropping them from state.
        hidden_existing: dict[str, dict[str, object]] = {}
        for instance in room.props.values():
            definition = self._world.props[instance.prop_id]
            if definition.decorative and definition.hidden:
                hidden_existing[instance.id] = {
                    "id": instance.id,
                    "prop_id": instance.prop_id,
                    "position": list(instance.pos),
                    "rotation": list(instance.rot),
                    "scale": float(instance.scale),
                    "locked": False,
                    **({"sign_style": instance.sign_style} if instance.sign_style is not None else {}),
                }
        for entry in live:
            if not isinstance(entry, dict):
                continue
            definition = self._world.props.get(str(entry.get("prop_id")))
            if definition is None or not definition.hidden:
                continue
            hidden_existing[str(entry.get("id"))] = {
                "id": str(entry.get("id")),
                "prop_id": definition.id,
                "position": list(_vector(entry.get("position"), (50.0, 50.0, 0.0))),
                "rotation": list(_vector(entry.get("rotation"), (0.0, 0.0, 0.0))),
                "scale": float(entry.get("scale", 1.0)),
                "locked": bool(entry.get("locked")),
                **({"sign_style": str(entry["sign_style"])} if isinstance(entry.get("sign_style"), str) else {}),
            }
        seen: set[str] = set()
        props: list[dict[str, object]] = []
        for entry in raw_value:
            if not isinstance(entry, dict):
                raise ValueError("Each layout prop must be a mapping.")
            prop_id = str(entry.get("prop_id") or "")
            definition = self._world.props.get(prop_id)
            if definition is not None and not definition.decorative:
                raise ValueError(f"Prop '{prop_id}' is not decorative.")
            if prop_id not in approved:
                raise ValueError(f"Prop '{prop_id}' is not approved for editing.")
            instance_id = str(entry.get("id") or "")
            if not instance_id or instance_id in seen:
                raise ValueError("Layout prop IDs must be unique and non-empty.")
            authored = room.props.get(instance_id)
            if authored is not None and not self._world.props[authored.prop_id].decorative:
                raise ValueError(f"Layout prop ID '{instance_id}' belongs to an immutable gameplay prop.")
            if instance_id.startswith("custom:"):
                try:
                    uuid.UUID(instance_id[7:])
                except ValueError as exc:
                    raise ValueError(f"Invalid custom prop ID '{instance_id}'.") from exc
            elif instance_id not in known:
                raise ValueError(f"Unknown layout prop '{instance_id}'.")
            seen.add(instance_id)
            text = None
            if prop_id == TEXT_PROP_ID:
                text = validate_text(entry.get("text"))
            elif "text" in entry:
                raise ValueError("Only builtin:text props may have a text recipe.")
            sign_style = None
            if definition is not None and definition.render_kind == "sign":
                sign_style = validate_sign_style(entry.get("sign_style"))
            elif "sign_style" in entry:
                raise ValueError("Only builtin:sign props may have a sign_style.")
            props.append(
                {
                    "id": instance_id,
                    "prop_id": prop_id,
                    "position": self._validate_position(entry.get("position")),
                    "rotation": self._validate_rotation(entry.get("rotation")),
                    "scale": self._validate_scale(entry.get("scale"), definition),
                    "locked": bool(entry.get("locked")),
                    **({"text": text} if text is not None else {}),
                    **({"sign_style": sign_style} if sign_style is not None else {}),
                }
            )
        for instance_id, entry in hidden_existing.items():
            if instance_id not in seen:
                props.append(entry)
        texts = [entry["text"] for entry in props if entry["prop_id"] == TEXT_PROP_ID]
        if len(texts) > MAX_TEXT_PROPS:
            raise ValueError(f"A room may contain at most {MAX_TEXT_PROPS} text props.")
        if sum(len(text["content"]) for text in texts) > MAX_ROOM_TEXT_LENGTH:
            raise ValueError(f"A room's text props may contain at most {MAX_ROOM_TEXT_LENGTH} total characters.")
        signs = [entry for entry in props if entry["prop_id"] == SIGN_PROP_ID]
        if len(signs) > MAX_SIGN_PROPS:
            raise ValueError(f"A room may contain at most {MAX_SIGN_PROPS} signs.")
        whiteboards = [entry for entry in props if entry["prop_id"] == WHITEBOARD_PROP_ID]
        if len(whiteboards) > MAX_WHITEBOARD_PROPS:
            raise ValueError(f"A room may contain at most {MAX_WHITEBOARD_PROPS} whiteboards.")
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

    def _validate_environment(self, room: RoomDefinition, raw_value: object) -> dict[str, object]:
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
            elif key == "board_image":
                name = str(value).strip()
                if not name or Path(name).name != name:
                    raise ValueError("Floor images must be a filename in the world rooms folder.")
                if Path(name).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    raise ValueError("Floor images must be PNG, JPEG, or WebP files.")
                rooms_root = (self._world.root_path / "rooms").resolve()
                candidate = (rooms_root / name).resolve()
                if rooms_root not in candidate.parents or not candidate.is_file():
                    raise ValueError("That floor image is not available in this world.")
                patch[key] = name
        return patch
