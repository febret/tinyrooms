"""Room snapshots, presence, chat, and navigation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from server.behaviors.events import BehaviorEvent, PeepRef
from server.connections import ConnectionRegistry
from server.content.worlds import ExitDefinition, PeepDefinition, PropDefinition, PropInstanceDefinition, QuickAction, RoomDefinition, WorldDefinition, prop_model_url
from server.profiles import AccountRecord, ProfileRepository
from server.protocol import MAX_CHAT_SIZE, presence_enter_event, presence_leave_event
from server.services.activities import ActivityService
from server.services.cards import CardService
from server.services.stats import StatsService
from server.state.migrations import DatabaseHub
from server.state.world_state import WorldStateRepository


BASE_QUICK_COMMANDS = frozenset({".go", ".inspect", ".look", ".play", ".shop"})


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


class RoomService:
    """Authoritative room state assembly and mutations."""

    ROOM_CHANGE_ENERGY_COST = 1

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
        auras: object | None = None,
        layout: object | None = None,
        room_effects: object | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._world_state = world_state
        self._connections = connections
        self._card_service = card_service
        self._activities = activities
        self._world = world
        self._stats = stats
        self._allowed_verbs = set(command_verbs or ()) | BASE_QUICK_COMMANDS
        self._behaviors: object | None = None
        self._dialogs: object | None = None
        self._environment = environment
        self._auras = auras
        self._layout = layout
        self._room_effects = room_effects
        self._mod_states: list[object] = []

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

    def _visible_props(self, room: RoomDefinition) -> list[PropInstanceDefinition]:
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
                }
            )
        return occupants

    @staticmethod
    def _user_quick_actions(account: AccountRecord) -> list[dict[str, object]]:
        return [
            {"label": "Look", "command": f".look @{account.username_display}"},
            {"label": "Add Friend", "command": f".friend add @peep:{account.id}"},
        ]

    def _room_peeps(self, room_id: str) -> list[dict[str, object]]:
        peeps: list[dict[str, object]] = []
        for peep in self._world.peeps.values():
            if peep.room_id != room_id:
                continue
            peeps.append(self.serialize_npc(peep))
        return peeps

    def serialize_npc(self, peep: PeepDefinition) -> dict[str, object]:
        """Serialize a static NPC definition with its authored actions."""

        room = self._world.rooms.get(peep.room_id)
        quick_actions = self._visible_prop_actions(room, peep.actions) if room is not None else []
        quick_actions.append({"label": "Look", "command": f".look @peep:{peep.id}"})
        return {
            "id": peep.id,
            "kind": "npc",
            "label": peep.label,
            "description": peep.description,
            "image_url": f"/assets/world/{self._world.id}/peeps/{peep.image_name}",
            "quick_actions": quick_actions,
        }

    def _serialize_exit(self, exit_definition: ExitDefinition) -> dict[str, object]:
        return {
            "id": exit_definition.id,
            "label": exit_definition.label,
            "target_room_id": exit_definition.target_room_id,
            "locked": exit_definition.locked,
            "requires_card_id": exit_definition.requires_card_id,
            "quick_action": {"label": exit_definition.label, "command": self._exit_command(exit_definition.id)},
        }

    def _serialize_prop(self, account: AccountRecord, room: RoomDefinition, prop: PropInstanceDefinition) -> dict[str, object]:
        prop_definition = self._world.props[prop.prop_id]
        animation = prop.animation if prop.animation is not None else prop_definition.animation
        quick_actions = self._visible_prop_actions(room, prop.actions)
        for state in self._mod_states:
            personal_actions = getattr(state, "personal_actions", None)
            if personal_actions is None:
                continue
            personal = personal_actions(account, prop)
            if personal:
                quick_actions = quick_actions + self._visible_prop_actions(room, tuple(personal))
        return {
            "id": prop.id,
            "prop_id": prop.prop_id,
            "position": list(prop.pos),
            "rotation": list(prop.rot),
            "scale": prop.scale * prop_definition.scale,
            "behavior": prop.behavior,
            "model_url": prop_model_url(self._world.id, prop_definition),
            "label": prop_definition.label,
            "description": prop_definition.description,
            "animation": animation,
            "quick_actions": quick_actions,
            "effect_sets": self._effect_sets_payload(prop_definition),
            "active_effect": self._active_effect(room.id, prop.id, prop_definition),
        }

    async def build_snapshot(
        self, account: AccountRecord, room_id: str, *, note: str | None = None
    ) -> dict[str, object]:
        """Build a coherent room snapshot for a specific account."""

        room = self._world.rooms[room_id]
        live_connections = await self._connections.list_room(room_id)
        occupant_ids = [connection.account_id for connection in live_connections]
        user_profile = self._profiles.user_profile_for(account.id, self._world.id, room_id)
        with self._hub.locked():
            occupant_accounts = self._profiles.get_accounts_by_ids(occupant_ids)
            room_cards, chat_history = self._world_state.read_room_view(room_id)
            inventory = self._profiles.list_inventory(account.id, self._world.id)
            occupant_views = self._stats.views(occupant_ids)
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
                }
            )
        visible_definitions = self._visible_exits(room)
        visible_exits = [self._serialize_exit(exit_definition) for exit_definition in visible_definitions]
        environment: dict[str, object] = {}
        environment_revision = 0
        if self._environment is not None:
            environment, environment_revision = self._environment.snapshot(room_id)
        lighting = environment.get("lighting")
        dark = lighting == "dark" if lighting in {"normal", "dark"} else room.dark
        board_palette = list(room.palette)
        board_style = room.board_image_style
        layout_revision = environment_revision
        can_edit_room = room_id in user_profile.owned_rooms
        if self._layout is not None:
            effective_board = self._layout.effective_board(room_id)
            board_palette = list(effective_board.get("palette") or room.palette)
            board_style = str(effective_board.get("board_image_style") or room.board_image_style)
            layout_revision = self._layout.revision(room_id)
            can_edit_room = self._layout.can_edit(account, room_id)
        return {
            "id": room.id,
            "label": room.label,
            "description": room.description,
            "board": {
                "type": room.board_type,
                "image_url": f"/assets/world/{self._world.id}/rooms/{room.board_image_name}",
                "image_style": board_style,
                "palette": board_palette,
                "dark": dark,
            },
            "metadata": {"note": note},
            "environment": environment,
            "environment_revision": environment_revision,
            "exits": visible_exits,
            "props": [self._serialize_prop(account, room, prop) for prop in self._visible_props(room)],
            "occupants": occupants,
            "npcs": self._room_peeps(room_id),
            "room_cards": [self._card_service.serialize_room_stack(stack) for stack in room_cards],
            "chat_history": chat_history,
            "inventory": [self._card_service.serialize_inventory_stack(stack) for stack in inventory],
            "editable": room_id in user_profile.owned_rooms,
            "layout_revision": layout_revision,
            "can_edit_room": can_edit_room,
            "dialog": self._dialog_payload(account.id),
            "quick_actions": [
                *[{"label": exit_definition.label, "command": self._exit_command(exit_definition.id)} for exit_definition in visible_definitions],
            ],
        }

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
        if self._auras is not None:
            self._auras.leave(account.id, source_room_id)
        with self._hub.transaction() as connection:
            if self.ROOM_CHANGE_ENERGY_COST:
                self._stats.charge_in_transaction(connection, account.id, self.ROOM_CHANGE_ENERGY_COST)
            self._profiles.set_remembered_room(connection, account.id, self._world.id, destination_room.id)
        await self._connections.set_room(account.id, destination_room.id)
        if self._auras is not None:
            self._auras.enter(account.id, destination_room.id)
        closed = self._activities.close_if_room_bound(account.id, destination_room.id)
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
