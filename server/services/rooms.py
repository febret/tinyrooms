"""Room snapshots, presence, chat, and navigation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import sqlite3

from server.behaviors.events import BehaviorEvent, PeepRef
from server.connections import ConnectionRegistry
from server.content.sounds import sounds_payload
from server.content.surface_props import DEFAULT_SIGN_STYLE, validate_sign_style
from server.content.worlds import ExitDefinition, PeepDefinition, PropDefinition, PropInstanceDefinition, QuickAction, RoomDefinition, WorldDefinition, prop_model_url
from server.profiles import AccountRecord, ProfileRepository
from server.protocol import (
    MAX_CHAT_SIZE,
    peep_enter_event,
    peep_leave_event,
    presence_enter_event,
    presence_leave_event,
)
from server.services.activities import ActivityService
from server.services.cards import CardService
from server.services.environment import DIORAMA_BOARD_TYPE, diorama_environment
from server.services.npc_movement import NpcMove, resolve_npc_move
from server.services.prop_surfaces import PropSurfaceService, surface_kind
from server.services.sprite_rooms import SpriteService
from server.services.stats import StatsService
from server.state.migrations import DatabaseHub, read_behavior_state
from server.state.npc_peep_states import NpcPeepStateRepository
from server.state.world_state import WorldStateRepository


LOGGER = logging.getLogger("tinyrooms.rooms")


BASE_QUICK_COMMANDS = frozenset({".go", ".inspect", ".look", ".play", ".shop"})


def _read_sign_style(raw_value: object) -> str:
    """Return a stored sign style, falling back when legacy data is invalid."""

    try:
        return validate_sign_style(raw_value)
    except ValueError:
        return DEFAULT_SIGN_STYLE


@dataclass(frozen=True, slots=True)
class NavigationResult:
    """Outcome of a room navigation command."""

    source_room_id: str
    destination_room_id: str
    destination_snapshot: dict[str, object]
    source_event: dict[str, object]
    destination_event: dict[str, object]
    closed_activity: dict[str, object] | None
    behavior_results: list[object] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WorldDeparture:
    """Outcome of leaving a room to travel to another world."""

    source_room_id: str
    source_event: dict[str, object]
    closed_activity: dict[str, object] | None
    behavior_results: list[object] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class NpcMoveResult:
    """Outcome of moving an NPC peep between rooms."""

    move: NpcMove
    source_event: dict[str, object]
    destination_event: dict[str, object]


@dataclass(frozen=True, slots=True)
class NpcSummonResult:
    """Outcome of moving an NPC peep directly into a room."""

    peep_id: str
    label: str
    source_room_id: str
    destination_room_id: str
    source_event: dict[str, object]
    destination_event: dict[str, object]


class RoomService:
    """Authoritative room state assembly and mutations."""

    ROOM_CHANGE_ENERGY_COST = 1
    CHAT_ENERGY_COST = 1

    def __init__(
        self,
        *,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        world_state: WorldStateRepository,
        connections: ConnectionRegistry,
        card_service: CardService,
        activities: ActivityService,
        world: WorldDefinition,
        stats: StatsService,
        command_verbs: frozenset[str] | None = None,
        environment: object | None = None,
        layout: object | None = None,
        room_effects: object | None = None,
        prop_states: object | None = None,
        peep_states: NpcPeepStateRepository | None = None,
        sprites: SpriteService | None = None,
        surfaces: PropSurfaceService | None = None,
        powers: object | None = None,
        vibes: object | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._world_state = world_state
        self._connections = connections
        self._card_service = card_service
        self._activities = activities
        self._world = world
        self._stats = stats
        self._peep_states = peep_states
        self._allowed_verbs = set(command_verbs or ()) | BASE_QUICK_COMMANDS
        self._behaviors: object | None = None
        self._dialogs: object | None = None
        self._environment = environment
        self._layout = layout
        self._room_effects = room_effects
        self._prop_states = prop_states
        self._sprites = sprites or SpriteService(world, layout=layout)
        self._surfaces = surfaces
        self._powers = powers
        self._vibes = vibes
        self._mod_states: list[object] = []

    @property
    def sprites(self) -> SpriteService:
        """Return the shared sprite placement service."""

        return self._sprites

    def attach_dispatcher(self, dispatcher: object) -> None:
        """Wire the behavior dispatcher used for navigation events."""

        self._behaviors = dispatcher

    def attach_mod_states(self, states: object) -> None:
        """Wire mod runtime state objects that contribute per-account prop actions."""

        self._mod_states = list(states)

    def attach_dialogs(self, dialogs: object) -> None:
        """Wire the dialog service used to cancel dialogs on departure."""

        self._dialogs = dialogs

    def current_room_for_account(self, account_id: str) -> str:
        """Return the remembered room for the given account."""

        profile = self._profiles.user_profile_for(account_id, self._world.id, self._world.entry_room_id)
        remembered = profile.remembered_room
        if remembered in self._world.rooms:
            return remembered
        return self._world.entry_room_id

    @property
    def world(self) -> WorldDefinition:
        """Return the loaded world definition."""

        return self._world

    @property
    def world_id(self) -> str:
        """Return the active world identifier."""

        return self._world.id

    def room_definition(self, room_id: str) -> RoomDefinition:
        """Return the world definition for a room."""

        return self._world.rooms[room_id]

    def prop_definition(self, prop_id: str) -> PropDefinition:
        """Return the world definition for a prop."""

        return self._world.props[prop_id]

    def require_room_target(self, room_id: str) -> None:
        """Require effective lighting for a room prop or floor-card target."""

        if self._environment is not None:
            self._environment.require_room_target(room_id)
        elif self._world.rooms[room_id].dark:
            raise ValueError("It is too dark to make anything out.")

    def require_prop_target(self, room_id: str, instance_id: str) -> PropInstanceDefinition:
        """Resolve an eligible placed prop, including effective layout props."""

        room = self._world.rooms[room_id]
        prop = next((prop for prop in self._effective_props(room) if prop.id == instance_id), None)
        if prop is None:
            raise ValueError("That prop is not in this room.")
        self.require_room_target(room_id)
        if self._environment is not None:
            self._environment.require_prop_target(room_id, prop.id, prop.prop_id)
        elif self._world.props[prop.prop_id].hidden:
            raise ValueError("That prop is not visible right now.")
        return prop

    def _states_payload(self, definition: PropDefinition) -> dict[str, str]:
        return {
            state_name: prop_model_url(self._world.id, definition, state_name) or ""
            for state_name in definition.states
        }

    def _active_state(
        self,
        room_id: str,
        prop_instance_id: str,
        definition: PropDefinition,
    ) -> str | None:
        if not definition.states:
            return None
        active = definition.active_state
        if self._prop_states is not None:
            active = self._prop_states.state_for(room_id, prop_instance_id, active)
        if active not in definition.states:
            return definition.active_state
        return active

    def _effect_sets_payload(self, definition: PropDefinition) -> dict[str, list[dict[str, object]]]:
        return {
            set_name: [
                self._world.effects[effect_id].serialize()
                for effect_id in effect_ids
                if effect_id in self._world.effects
            ]
            for set_name, effect_ids in definition.effect_sets.items()
        }

    def _active_effect(
        self,
        room_id: str,
        prop_instance_id: str,
        definition: PropDefinition,
    ) -> str | None:
        if not definition.effect_sets:
            return None
        default = definition.active_effect
        if self._room_effects is not None:
            default = self._room_effects.active_for(room_id, prop_instance_id, default)
        if default not in definition.effect_sets:
            return definition.active_effect
        return default

    def set_prop_state(
        self,
        room_id: str,
        prop_instance_id: str,
        state_name: str,
    ) -> dict[str, object]:
        """Switch the mesh state of a prop instance at runtime.

        Returns the room event a caller should broadcast. Raises ``ValueError``
        for unknown rooms, props, or states.
        """

        room = self._world.rooms.get(room_id)
        if room is None:
            raise ValueError("That room does not exist.")
        instance = next(
            (prop for prop in self._effective_props(room) if prop.id == prop_instance_id),
            None,
        )
        if instance is None:
            raise ValueError("That prop does not exist.")
        definition = self._world.props[instance.prop_id]
        if not definition.states:
            raise ValueError(f"{definition.label} has no states.")
        if state_name not in definition.states:
            raise ValueError(f"{definition.label} has no state '{state_name}'.")
        if self._prop_states is None:
            raise ValueError("Prop states are unavailable.")
        self._prop_states.set(room_id, prop_instance_id, state_name)
        return {
            "type": "room.prop.updated",
            "room_id": room_id,
            "prop": {
                "id": prop_instance_id,
                "state": state_name,
                "active_state": state_name,
                "model_url": prop_model_url(self._world.id, definition, state_name),
            },
        }

    def set_prop_active_state(
        self,
        room_id: str,
        prop_instance_id: str,
        state_name: str,
    ) -> dict[str, object]:
        """Switch a prop instance's mesh state (alias of :meth:`set_prop_state`)."""

        return self.set_prop_state(room_id, prop_instance_id, state_name)

    def set_prop_active_effect(
        self,
        room_id: str,
        prop_instance_id: str,
        set_name: str,
    ) -> dict[str, object]:
        """Switch a prop instance's active effect set at runtime.

        Returns the room event a caller should broadcast. Raises ``ValueError``
        for unknown rooms, props, or effect sets.
        """

        room = self._world.rooms.get(room_id)
        if room is None:
            raise ValueError("That room does not exist.")
        instance = next(
            (prop for prop in self._effective_props(room) if prop.id == prop_instance_id),
            None,
        )
        if instance is None:
            raise ValueError("That prop does not exist.")
        definition = self._world.props[instance.prop_id]
        if not definition.effect_sets:
            raise ValueError(f"{definition.label} has no effects.")
        if set_name not in definition.effect_sets:
            raise ValueError(f"{definition.label} has no effect set '{set_name}'.")
        if self._room_effects is None:
            raise ValueError("Prop effects are unavailable.")
        self._room_effects.set(room_id, prop_instance_id, set_name)
        return {
            "type": "room.prop.updated",
            "room_id": room_id,
            "prop": {"id": prop_instance_id, "active_effect": set_name},
        }

    def room_peeps(self, room_id: str) -> list[dict[str, object]]:
        """Serialize the NPC peeps present in a room."""

        return self._room_peeps(room_id)

    def _npc_peeps_in(self, room_id: str) -> list[PeepDefinition]:
        return [
            peep
            for peep in self._world.peeps.values()
            if self.peep_room(peep) == room_id
        ]

    @staticmethod
    def _exit_command(exit_id: str) -> str:
        return f".go @way:{exit_id}"

    def _action_enabled(self, room_id: str, command: str) -> bool:
        if self._environment is None:
            return True
        return bool(self._environment.is_action_enabled(room_id, command.split(maxsplit=1)[0]))

    def _normalize_quick_action(
        self,
        room: RoomDefinition,
        action: QuickAction,
    ) -> dict[str, object] | None:
        command = action.command
        is_default = action.default
        if command.startswith(".go "):
            remainder = command[4:].strip()
            if remainder in room.exits:
                command = self._exit_command(remainder)
                is_default = True
        if command.split(maxsplit=1)[0] not in self._allowed_verbs:
            return None
        if not self._action_enabled(room.id, command):
            return None
        normalized: dict[str, object] = {"label": action.label, "command": command}
        if is_default:
            normalized["default"] = True
        return normalized

    def _visible_exits(self, room: RoomDefinition) -> list[ExitDefinition]:
        if self._environment is None:
            return list(room.exits.values())
        return [
            exit_definition
            for exit_definition in room.exits.values()
            if self._environment.is_exit_enabled(room.id, exit_definition.id)
        ]

    def _effective_props(self, room: RoomDefinition) -> list[PropInstanceDefinition]:
        if self._layout is None:
            return list(room.props.values())
        return self._layout.effective_props(room.id)

    def props_in_room(self, room_id: str) -> list[PropInstanceDefinition]:
        """Return the room's effective props, including live layout placements."""

        room = self._world.rooms.get(room_id)
        return [] if room is None else self._effective_props(room)

    def surface_for(self, room_id: str, instance_id: str, kind: str) -> object | None:
        """Return a prop's stored surface, or None when unavailable."""

        if self._surfaces is None:
            return None
        default_content = None
        room = self._world.rooms.get(room_id)
        if room is not None:
            instance = next((prop for prop in self._effective_props(room) if prop.id == instance_id), None)
            if instance is not None and surface_kind(self._world.props[instance.prop_id].render_kind) == kind:
                default_content = instance.surface
        return self._surfaces.get(room_id, instance_id, kind, default_content=default_content)

    def _visible_props(self, room: RoomDefinition, *, dark: bool = False) -> list[PropInstanceDefinition]:
        del dark
        props = self._effective_props(room)
        visible = [prop for prop in props if not self._world.props[prop.prop_id].hidden]
        if self._environment is None:
            return visible
        return [
            prop
            for prop in visible
            if self._environment.is_prop_visible(room.id, prop.id)
        ]

    def _visible_prop_actions(
        self,
        room: RoomDefinition,
        actions: tuple[QuickAction, ...],
    ) -> list[dict[str, object]]:
        return [
            normalized
            for action in actions
            if (normalized := self._normalize_quick_action(room, action)) is not None
        ]

    async def room_occupants(self, room_id: str) -> list[dict[str, object]]:
        """Serialize connected users in a room."""

        live_connections = await self._connections.list_room(room_id)
        accounts = self._profiles.get_accounts_by_ids([connection.account_id for connection in live_connections])
        occupants: list[dict[str, object]] = []
        for connection in live_connections:
            account = accounts.get(connection.account_id)
            if account is None:
                continue
            occupants.append(
                {
                    "id": account.id,
                    "username": account.username_display,
                    "kind": "user",
                    "sticker_url": f"/assets/stickers/{account.sticker}" if account.sticker else None,
                    "audio_enabled": connection.audio_enabled,
                    "quick_actions": self._user_quick_actions(account),
                    **self._user_sprite_payload(account.id, room_id),
                }
            )
        return occupants

    def _user_sprite_payload(self, account_id: str, room_id: str) -> dict[str, object]:
        position = self._sprites.ensure_user(account_id, room_id)
        return {} if position is None else {"sprite": {"position": list(position)}}

    @staticmethod
    def _user_quick_actions(account: AccountRecord) -> list[dict[str, object]]:
        return [
            {"label": "Add Friend", "command": f".friend add @peep:{account.id}"},
        ]

    def peep_room(self, peep: PeepDefinition) -> str:
        """Return the peep's current room, falling back to its spawn room."""

        if self._peep_states is not None:
            current = self._peep_states.room_for(peep.id)
            if current in self._world.rooms:
                return current
        return peep.room_id

    def _room_peeps(
        self,
        room_id: str,
        *,
        vibes_by_id: dict[str, dict[str, object]] | None = None,
    ) -> list[dict[str, object]]:
        return [
            self.serialize_npc(
                peep,
                room_id,
                vibes=(vibes_by_id or {}).get(peep.id),
            )
            for peep in self._npc_peeps_in(room_id)
        ]

    def serialize_npc(
        self,
        peep: PeepDefinition,
        room_id: str | None = None,
        *,
        vibes: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Serialize an NPC definition with the actions available in its room."""

        resolved_room_id = room_id if room_id is not None else self.peep_room(peep)
        room = self._world.rooms.get(resolved_room_id)
        quick_actions = self._visible_prop_actions(room, peep.actions) if room is not None else []
        sprite_payload: dict[str, object] = {}
        position = self._sprites.ensure_npc(peep.id, resolved_room_id)
        if position is not None:
            sprite_payload["sprite"] = {"position": list(position)}
        payload: dict[str, object] = {
            "id": peep.id,
            "kind": "npc",
            "label": peep.label,
            "description": peep.description,
            "room_id": resolved_room_id,
            "image_url": f"/assets/world/{self._world.id}/peeps/{peep.image_name}",
            "quick_actions": quick_actions,
            **sprite_payload,
            **({"vibes": vibes} if vibes else {}),
        }
        for state in self._mod_states:
            hook = getattr(state, "npc_payload", None)
            if hook is None:
                continue
            try:
                extra = hook(peep, resolved_room_id)
            except Exception:  # noqa: BLE001 - mod decoration must not break snapshots
                LOGGER.exception("room.mod_npc_payload_failed")
                continue
            if isinstance(extra, dict):
                payload.update(extra)
        return payload

    async def move_npc(self, peep_id: str, exit_id: str) -> NpcMoveResult:
        """Move an NPC through an authored exit and return its room events."""

        peep = self._world.peeps.get(peep_id)
        if peep is None:
            raise ValueError("That peep does not exist.")
        if self._peep_states is None:
            raise ValueError("NPC movement is unavailable.")
        source_room_id = self.peep_room(peep)
        move = resolve_npc_move(self._world, peep, source_room_id, exit_id)
        with self._hub.transaction() as connection:
            self._peep_states.set_in_transaction(connection, peep_id, move.destination_room_id)
        self._peep_states.record(peep_id, move.destination_room_id)
        self._sprites.forget_npc(peep_id)
        source_room = self._world.rooms[move.source_room_id]
        return NpcMoveResult(
            move=move,
            source_event=peep_leave_event(
                peep_id=peep.id,
                label=peep.label,
                room_id=move.source_room_id,
                destination_room_id=move.destination_room_id,
                direction=move.direction,
            ),
            destination_event=peep_enter_event(
                peep_id=peep.id,
                label=peep.label,
                room_id=move.destination_room_id,
                source_room_id=move.source_room_id,
                source_room_label=source_room.label,
            ),
        )

    async def summon_npc(self, peep_id: str, room_id: str) -> NpcSummonResult:
        """Move an NPC directly into a room and return its room events."""

        peep = self._world.peeps.get(peep_id)
        if peep is None:
            raise ValueError("That peep does not exist.")
        if self._peep_states is None:
            raise ValueError("NPC movement is unavailable.")
        if room_id not in self._world.rooms:
            raise ValueError("That room does not exist.")
        source_room_id = self.peep_room(peep)
        if source_room_id == room_id:
            raise ValueError("That peep is already in that room.")
        source_room = self._world.rooms.get(source_room_id)
        if source_room is None:
            raise ValueError("That peep is not in a known room.")
        with self._hub.transaction() as connection:
            self._peep_states.set_in_transaction(connection, peep_id, room_id)
        self._peep_states.record(peep_id, room_id)
        self._sprites.forget_npc(peep_id)
        return NpcSummonResult(
            peep_id=peep.id,
            label=peep.label,
            source_room_id=source_room_id,
            destination_room_id=room_id,
            source_event=peep_leave_event(
                peep_id=peep.id,
                label=peep.label,
                room_id=source_room_id,
                destination_room_id=room_id,
            ),
            destination_event=peep_enter_event(
                peep_id=peep.id,
                label=peep.label,
                room_id=room_id,
                source_room_id=source_room_id,
                source_room_label=source_room.label,
            ),
        )

    def move_user_sprite(
        self,
        account: AccountRecord,
        room_id: str,
        x: float,
        y: float,
    ) -> dict[str, object]:
        """Move a user's board sprite and return the room event to broadcast."""

        position = self._sprites.set_user_position(account.id, room_id, x, y)
        return {
            "type": "peep.sprite",
            "room_id": room_id,
            "account_id": account.id,
            "position": list(position),
        }

    def _serialize_exit(self, exit_definition: ExitDefinition) -> dict[str, object]:
        return {
            "id": exit_definition.id,
            "label": exit_definition.label,
            "target_room_id": exit_definition.target_room_id,
            "target_world_id": exit_definition.target_world_id,
            "locked": exit_definition.locked,
            "requires_card_id": exit_definition.requires_card_id,
            "npc_barrier": exit_definition.npc_barrier,
            "quick_action": {"label": exit_definition.label, "command": self._exit_command(exit_definition.id)},
        }

    def _read_game_state(
        self,
        connection: sqlite3.Connection,
        room: RoomDefinition,
    ) -> dict[str, object] | None:
        """Read a room game's public state from its controller behavior row."""

        if room.game is None:
            return None
        raw = read_behavior_state(connection, "prop", room.game.controller)
        state = raw.get("game_state") if isinstance(raw, dict) else None
        return state if isinstance(state, dict) else None

    def _serialize_game(self, account: AccountRecord, room: RoomDefinition) -> dict[str, object] | None:
        game = room.game
        if game is None:
            return None
        assets = {
            name: f"/assets/world/{self._world.id}/{relative}"
            for name, relative in game.assets.items()
        }
        models: dict[str, dict[str, object]] = {}
        for name, model in game.models.items():
            definition = self._world.props[model.prop_id]
            models[name] = {
                "model_url": prop_model_url(self._world.id, definition),
                "scale": definition.scale,
            }
        effects = {
            set_name: [
                self._world.effects[effect_id].serialize()
                for effect_id in effect_ids
                if effect_id in self._world.effects
            ]
            for set_name, effect_ids in game.effect_sets.items()
        }
        can_reset = False
        if self._powers is not None and game.reset_powers:
            can_reset = any(self._powers.has_power(account.id, power) for power in game.reset_powers)
        return {
            "kind": game.kind,
            "controller": game.controller,
            "renderer": game.renderer,
            "config": dict(game.config),
            "assets": assets,
            "models": models,
            "effects": effects,
            "capabilities": {"reset": can_reset},
        }

    def _serialize_prop(
        self,
        account: AccountRecord,
        room: RoomDefinition,
        prop: PropInstanceDefinition,
        *,
        dark: bool = False,
        disable_actions: bool = False,
    ) -> dict[str, object]:
        prop_definition = self._world.props[prop.prop_id]
        animation = prop.animation if prop.animation is not None else prop_definition.animation
        active_state = None if dark else self._active_state(room.id, prop.id, prop_definition)
        if dark or disable_actions:
            quick_actions: list[dict[str, object]] = []
        else:
            quick_actions = self._visible_prop_actions(room, prop.actions)
            quick_actions.extend(self._surface_quick_actions(prop, prop_definition))
            for state in self._mod_states:
                personal_actions = getattr(state, "personal_actions", None)
                if personal_actions is None:
                    continue
                try:
                    personal = personal_actions(account, prop)
                except Exception:  # noqa: BLE001 - mod actions must not break props
                    LOGGER.exception("room.mod_personal_actions_failed")
                    continue
                if personal:
                    quick_actions = quick_actions + self._visible_prop_actions(room, tuple(personal))
        sounds = {**prop_definition.sounds, **prop.sounds}
        serialized_sounds = sounds_payload(sounds)
        action_sound = serialized_sounds.get("action")
        if action_sound is not None:
            quick_actions = [
                {**action, "sound": action_sound} if isinstance(action, dict) else action
                for action in quick_actions
            ]
        surface_kind_name = surface_kind(prop_definition.render_kind)
        surface = None
        if surface_kind_name is not None and self._surfaces is not None:
            surface = self._surfaces.get(
                room.id,
                prop.id,
                surface_kind_name,
                default_content=prop.surface,
            ).serialize()
        return {
            "id": prop.id,
            "prop_id": prop.prop_id,
            "position": list(prop.pos),
            "rotation": list(prop.rot),
            "scale": prop.scale * prop_definition.scale,
            "behavior": None if dark else prop.behavior,
            "model_url": prop_model_url(self._world.id, prop_definition, active_state),
            "render_kind": prop_definition.render_kind,
            **({"text": dict(prop.text)} if prop.text is not None else {}),
            **(
                {"sign_style": _read_sign_style(prop.sign_style)}
                if prop_definition.render_kind == "sign"
                else {}
            ),
            **({"surface": surface} if surface is not None else {}),
            "label": "Something in the dark" if dark else prop_definition.label,
            "description": "" if dark else prop_definition.description,
            "animation": animation,
            "quick_actions": quick_actions,
            "state": active_state,
            "active_state": active_state,
            "states": {} if dark else self._states_payload(prop_definition),
            "effect_sets": {} if dark else self._effect_sets_payload(prop_definition),
            "active_effect": None if dark else self._active_effect(room.id, prop.id, prop_definition),
            "sounds": serialized_sounds,
        }

    @staticmethod
    def _surface_quick_actions(
        prop: PropInstanceDefinition,
        definition: PropDefinition,
    ) -> list[dict[str, object]]:
        if definition.render_kind == "sign":
            return [{"label": "Edit sign", "command": f".sign {prop.id}", "default": True}]
        if definition.render_kind == "whiteboard":
            return [{"label": "Open whiteboard", "command": f".play {prop.id}", "default": True}]
        return []

    async def build_snapshot(
        self, account: AccountRecord, room_id: str, *, note: str | None = None
    ) -> dict[str, object]:
        """Build a coherent room snapshot for a specific account."""

        room = self._world.rooms[room_id]
        live_connections = await self._connections.list_room(room_id)
        occupant_ids = [connection.account_id for connection in live_connections]
        user_profile = self._profiles.user_profile_for(account.id, self._world.id, room_id)
        with self._hub.locked() as connection:
            occupant_accounts = self._profiles.get_accounts_by_ids(occupant_ids)
            room_cards, chat_history = self._world_state.read_room_view(room_id)
            inventory = self._profiles.list_inventory(account.id, self._world.id)
            occupant_views = self._stats.views(occupant_ids)
            game_state = self._read_game_state(connection, room)
        vibes_by_id: dict[str, dict[str, object]] = {}
        if self._vibes is not None:
            vibe_targets = [*occupant_ids, *[peep.id for peep in self._npc_peeps_in(room_id)]]
            vibes_by_id = self._vibes.pairs_for(account.id, vibe_targets)
        occupants: list[dict[str, object]] = []
        for connection in live_connections:
            occupant = occupant_accounts.get(connection.account_id)
            if occupant is None:
                continue
            counters = occupant_views[occupant.id].payload()
            occupants.append(
                {
                    "id": occupant.id,
                    "username": occupant.username_display,
                    "kind": "user",
                    "sticker_url": f"/assets/stickers/{occupant.sticker}" if occupant.sticker else None,
                    "statuses": list(counters["statuses"]),
                    "counters": counters,
                    "audio_enabled": connection.audio_enabled,
                    "quick_actions": self._user_quick_actions(occupant),
                    **self._user_sprite_payload(occupant.id, room_id),
                    **({"vibes": vibes_by_id[occupant.id]} if occupant.id in vibes_by_id else {}),
                }
            )
        visible_definitions = self._visible_exits(room)
        visible_exits = [self._serialize_exit(exit_definition) for exit_definition in visible_definitions]
        environment: dict[str, object] = {}
        environment_revision = 0
        if self._environment is not None:
            environment, environment_revision = self._environment.snapshot(room_id)
            dark = self._environment.lighting(room_id) == "dark"
        else:
            dark = room.dark
        if room.board_type == DIORAMA_BOARD_TYPE:
            environment = diorama_environment(environment)
        viewer_view = occupant_views.get(account.id)
        viewer_statuses = viewer_view.statuses if viewer_view is not None else ()
        status_definitions = self._stats.content.statuses
        disable_prop_actions = any(
            getattr(status_definitions.get(status_id), "disables_prop_actions", False)
            for status_id in viewer_statuses
        )
        board_palette = list(room.palette)
        board_style = room.board_image_style
        board_image = room.board_image_name
        layout_revision = environment_revision
        can_edit_room = room_id in user_profile.owned_rooms
        if self._layout is not None:
            effective_board = self._layout.effective_board(room_id)
            board_palette = list(effective_board.get("palette") or room.palette)
            board_style = str(effective_board.get("board_image_style") or room.board_image_style)
            board_image = str(effective_board.get("board_image") or room.board_image_name)
            layout_revision = self._layout.revision(room_id)
            can_edit_room = self._layout.can_edit(account, room_id)
        game = self._serialize_game(account, room)
        description = room.description
        if isinstance(game_state, dict):
            dynamic_description = game_state.get("room_description")
            if isinstance(dynamic_description, str) and dynamic_description.strip():
                description = dynamic_description
        quick_actions = [
            *[
                {"label": exit_definition.label, "command": self._exit_command(exit_definition.id)}
                for exit_definition in visible_definitions
            ],
            *self._mod_room_actions(account, room),
        ]
        if game is not None and game.get("capabilities", {}).get("reset"):
            quick_actions.append(
                {"label": "Reset game", "command": f".act reset @prop:{game['controller']}"}
            )
        return {
            "id": room.id,
            "label": room.label,
            "description": description,
            "board": {
                "type": room.board_type,
                "image_url": f"/assets/world/{self._world.id}/rooms/{board_image}",
                "image_style": board_style,
                "palette": board_palette,
                "dark": dark,
                "base_dark": room.dark,
                "sprites_enabled": room.sprites_enabled,
                "game": game,
                "state": game_state,
            },
            "metadata": {"note": note},
            "environment": environment,
            "environment_revision": environment_revision,
            "exits": visible_exits,
            "props": [
                self._serialize_prop(account, room, prop, dark=dark, disable_actions=disable_prop_actions)
                for prop in self._visible_props(room, dark=dark)
            ],
            "occupants": occupants,
            "npcs": self._room_peeps(room_id, vibes_by_id=vibes_by_id),
            "room_cards": self._card_service.serialize_room_stacks(room_cards),
            "chat_history": chat_history,
            "inventory": self._card_service.serialize_inventory_stacks(inventory),
            "editable": room_id in user_profile.owned_rooms,
            "layout_revision": layout_revision,
            "can_edit_room": can_edit_room,
            "dialog": self._dialog_payload(account.id),
            "quick_actions": quick_actions,
        }

    def _mod_room_actions(self, account: AccountRecord, room: RoomDefinition) -> list[dict[str, object]]:
        """Collect room-level quick actions contributed by mod runtime states."""

        actions: list[dict[str, object]] = []
        for state in self._mod_states:
            hook = getattr(state, "room_quick_actions", None)
            if hook is None:
                continue
            try:
                contributed = hook(account, room) or ()
            except Exception:  # noqa: BLE001 - mod actions must not break rooms
                LOGGER.exception("room.mod_room_actions_failed")
                continue
            for action in contributed:
                normalized = self._normalize_quick_action(room, action)
                if normalized is not None:
                    actions.append(normalized)
        return actions

    def _dialog_payload(self, account_id: str) -> dict[str, object] | None:
        if self._dialogs is None:
            return None
        return self._dialogs.serialize(self._dialogs.view(account_id))

    def say(self, account: AccountRecord, room_id: str, raw_text: str) -> dict[str, object]:
        """Record an in-memory room chat message and return the broadcast event."""

        style = "normal"
        text = raw_text.strip()
        if text.startswith("(.)"):
            style = "thinking"
            text = text[3:].strip()
        elif text.startswith("(!)"):
            style = "spiky"
            text = text[3:].strip()
        if not text:
            raise ValueError("Chat message cannot be empty.")
        if len(text) > MAX_CHAT_SIZE:
            raise ValueError(f"Chat message exceeds the {MAX_CHAT_SIZE}-character limit.")
        entry = {
            "speaker_id": account.id,
            "speaker": account.username_display,
            "style": style,
            "text": text,
        }
        with self._hub.transaction() as connection:
            if self.CHAT_ENERGY_COST:
                self._stats.charge_in_transaction(connection, account.id, self.CHAT_ENERGY_COST)
        self._world_state.append_chat_message(room_id, entry)
        return {"type": "chat.message", "room_id": room_id, **entry}

    async def navigate(self, account: AccountRecord, source_room_id: str, exit_id: str) -> NavigationResult:
        """Move a connected user between rooms and return ordered room events."""

        source_room = self._world.rooms[source_room_id]
        if exit_id not in source_room.exits:
            raise ValueError("That exit is not available from this room.")
        exit_definition = source_room.exits[exit_id]
        destination_room = self._world.rooms[exit_definition.target_room_id]
        if exit_definition.locked:
            raise ValueError("That way is locked.")
        if exit_definition.requires_card_id is not None:
            inventory_ids = {stack.card_def_id for stack in self._profiles.list_inventory(account.id, self._world.id)}
            if exit_definition.requires_card_id not in inventory_ids:
                raise ValueError(f"You need {exit_definition.requires_card_id} to go that way.")
        return await self._move(
            account,
            source_room=source_room,
            destination_room=destination_room,
            direction=exit_definition.label,
        )

    async def enter_room(
        self,
        account: AccountRecord,
        source_room_id: str,
        destination_room_id: str,
        *,
        direction: str = "a doorway",
    ) -> NavigationResult:
        """Move a connected user to an explicit room without an authored exit."""

        source_room = self._world.rooms[source_room_id]
        destination_room = self._world.rooms.get(destination_room_id)
        if destination_room is None:
            raise ValueError("That room does not exist.")
        return await self._move(
            account,
            source_room=source_room,
            destination_room=destination_room,
            direction=direction,
        )

    async def depart_to_world(
        self,
        account: AccountRecord,
        source_room_id: str,
        *,
        direction: str,
        destination_room_id: str | None = None,
    ) -> WorldDeparture:
        """Remove a connected user from a room when leaving for another world.

        This mirrors the departure half of :meth:`_move`, so the source room
        drops the peep immediately and broadcasts a ``presence.leave`` instead of
        waiting for the browser to close its socket. The destination world
        announces the matching ``presence.enter`` when the browser reconnects.
        """

        behavior_results: list[object] = []
        if self._behaviors is not None:
            behavior_results.append(
                await self._behaviors.dispatch(
                    BehaviorEvent(
                        type="leave",
                        actor=PeepRef(kind="user", peep_id=None, account_id=account.id),
                        target=None,
                        room_id=source_room_id,
                        action=None,
                        data={"destination_room_id": None},
                    )
                )
            )
        if self._dialogs is not None:
            self._dialogs.end(account.id, "room_changed")
        with self._hub.transaction() as connection:
            if self.ROOM_CHANGE_ENERGY_COST:
                self._stats.charge_in_transaction(connection, account.id, self.ROOM_CHANGE_ENERGY_COST)
        await self._connections.set_room(account.id, None)
        self._sprites.forget_user(account.id)
        closed = self._activities.close(account.id)
        return WorldDeparture(
            source_room_id=source_room_id,
            source_event=presence_leave_event(
                account_id=account.id,
                username=account.username_display,
                room_id=source_room_id,
                destination_room_id=destination_room_id,
                direction=direction,
            ),
            closed_activity=None if closed is None else self._activities.serialize(closed),
            behavior_results=behavior_results,
        )

    async def _move(
        self,
        account: AccountRecord,
        *,
        source_room: RoomDefinition,
        destination_room: RoomDefinition,
        direction: str,
    ) -> NavigationResult:
        """Perform a room change and return ordered room events."""

        source_room_id = source_room.id
        behavior_results: list[object] = []
        if self._behaviors is not None:
            behavior_results.append(
                await self._behaviors.dispatch(
                    BehaviorEvent(
                        type="leave",
                        actor=PeepRef(kind="user", peep_id=None, account_id=account.id),
                        target=None,
                        room_id=source_room_id,
                        action=None,
                        data={"destination_room_id": destination_room.id},
                    )
                )
            )
        if self._dialogs is not None:
            self._dialogs.end(account.id, "room_changed")
        with self._hub.transaction() as connection:
            if self.ROOM_CHANGE_ENERGY_COST:
                self._stats.charge_in_transaction(connection, account.id, self.ROOM_CHANGE_ENERGY_COST)
            self._profiles.set_remembered_room(connection, account.id, self._world.id, destination_room.id)
        await self._connections.set_room(account.id, destination_room.id)
        self._sprites.forget_user(account.id)
        closed = self._activities.close_if_room_changed(account.id, destination_room.id)
        if self._behaviors is not None:
            behavior_results.append(
                await self._behaviors.dispatch(
                    BehaviorEvent(
                        type="enter",
                        actor=PeepRef(kind="user", peep_id=None, account_id=account.id),
                        target=None,
                        room_id=destination_room.id,
                        action=None,
                        data={"source_room_id": source_room_id},
                    )
                )
            )
        snapshot = await self.build_snapshot(account, destination_room.id)
        return NavigationResult(
            source_room_id=source_room_id,
            destination_room_id=destination_room.id,
            destination_snapshot=snapshot,
            source_event=presence_leave_event(
                account_id=account.id,
                username=account.username_display,
                room_id=source_room_id,
                destination_room_id=destination_room.id,
                direction=direction,
            ),
            destination_event=presence_enter_event(
                account_id=account.id,
                username=account.username_display,
                room_id=destination_room.id,
                source_room_id=source_room_id,
                source_room_label=source_room.label,
            ),
            closed_activity=None if closed is None else self._activities.serialize(closed),
            behavior_results=behavior_results,
        )
