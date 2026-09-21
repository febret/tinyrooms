"""Room snapshots, presence, chat, and navigation helpers."""

from __future__ import annotations

from dataclasses import dataclass

from server.connections import ConnectionRegistry
from server.content.worlds import ExitDefinition, PeepDefinition, PropDefinition, PropInstanceDefinition, QuickAction, RoomDefinition, WorldDefinition
from server.profiles import AccountRecord, ProfileRepository
from server.protocol import MAX_CHAT_SIZE, presence_enter_event, presence_leave_event
from server.services.activities import ActivityService
from server.services.cards import CardService
from server.state.migrations import DatabaseHub
from server.state.world_state import WorldStateRepository


@dataclass(frozen=True, slots=True)
class NavigationResult:
    """Outcome of a room navigation command."""

    source_room_id: str
    destination_room_id: str
    source_seq: int
    destination_seq: int
    destination_snapshot: dict[str, object]
    destination_snapshot_seq: int
    source_event: dict[str, object]
    destination_event: dict[str, object]
    closed_activity: dict[str, object] | None


class RoomService:
    """Authoritative room state assembly and mutations."""

    MILESTONE_ROOM_IDS = frozenset({"hub", "playroom"})

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
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._world_state = world_state
        self._connections = connections
        self._card_service = card_service
        self._activities = activities
        self._world = world

    def current_room_for_account(self, account_id: str) -> str:
        """Return the remembered room for the given account."""

        profile = self._profiles.user_profile_for(account_id, self._world.id, self._world.entry_room_id)
        remembered = profile.remembered_room
        if remembered in self._world.rooms:
            return remembered
        return self._world.entry_room_id

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

    def room_peeps(self, room_id: str) -> list[dict[str, object]]:
        """Serialize the NPC peeps present in a room."""

        return self._room_peeps(room_id)

    @staticmethod
    def _exit_command(exit_id: str) -> str:
        return f".go @way:{exit_id}"

    def _normalize_quick_action(
        self,
        room: RoomDefinition,
        action: QuickAction,
    ) -> dict[str, object] | None:
        command = action.command
        if command.startswith(".go "):
            remainder = command[4:].strip()
            if remainder in room.exits:
                exit_definition = room.exits[remainder]
                if exit_definition.target_room_id not in self.MILESTONE_ROOM_IDS:
                    return None
                command = self._exit_command(remainder)
        if command.split(maxsplit=1)[0] not in {
            ".go",
            ".inspect",
            ".look",
            ".play",
        }:
            return None
        return {"label": action.label, "command": command}

    def _visible_exits(self, room: RoomDefinition) -> list[ExitDefinition]:
        return [
            exit_definition
            for exit_definition in room.exits.values()
            if exit_definition.target_room_id in self.MILESTONE_ROOM_IDS
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
                    "quick_actions": [{"label": "Look", "command": f".look @{account.username_display}"}],
                }
            )
        return occupants

    def _room_peeps(self, room_id: str) -> list[dict[str, object]]:
        peeps: list[dict[str, object]] = []
        for peep in self._world.peeps.values():
            if peep.room_id != room_id:
                continue
            peeps.append(self.serialize_npc(peep))
        return peeps

    def serialize_npc(self, peep: PeepDefinition) -> dict[str, object]:
        """Serialize a static NPC definition."""

        return {
            "id": peep.id,
            "kind": "npc",
            "label": peep.label,
            "description": peep.description,
            "image_url": f"/assets/world/{self._world.id}/peeps/{peep.image_name}",
            "quick_actions": [
                {"label": "Look", "command": f".look @peep:{peep.id}"}
            ],
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

    def _serialize_prop(self, room: RoomDefinition, prop: PropInstanceDefinition) -> dict[str, object]:
        prop_definition = self._world.props[prop.prop_id]
        animation = prop.animation if prop.animation is not None else prop_definition.animation
        return {
            "id": prop.id,
            "prop_id": prop.prop_id,
            "position": list(prop.pos),
            "rotation": list(prop.rot),
            "scale": prop.scale,
            "behavior": prop.behavior,
            "model_url": f"/assets/world/{self._world.id}/props/{prop_definition.model_name}",
            "label": prop_definition.label,
            "description": prop_definition.description,
            "animation": animation,
            "quick_actions": self._visible_prop_actions(room, prop.actions),
        }

    async def build_snapshot_with_seq(
        self, account: AccountRecord, room_id: str, *, note: str | None = None
    ) -> tuple[dict[str, object], int]:
        """Build a room snapshot and the sequence it is consistent with."""

        room = self._world.rooms[room_id]
        live_connections = await self._connections.list_room(room_id)
        occupant_ids = [connection.account_id for connection in live_connections]
        user_profile = self._profiles.user_profile_for(account.id, self._world.id, room_id)
        with self._hub.locked():
            occupant_accounts = self._profiles.get_accounts_by_ids(occupant_ids)
            room_seq, room_cards, chat_history = self._world_state.read_room_view(room_id)
            inventory = self._profiles.list_inventory(account.id, self._world.id)
        occupants: list[dict[str, object]] = []
        for connection in live_connections:
            occupant = occupant_accounts.get(connection.account_id)
            if occupant is None:
                continue
            occupants.append(
                {
                    "id": occupant.id,
                    "username": occupant.username_display,
                    "kind": "user",
                    "sticker_url": f"/assets/stickers/{occupant.sticker}" if occupant.sticker else None,
                    "quick_actions": [{"label": "Look", "command": f".look @{occupant.username_display}"}],
                }
            )
        visible_definitions = self._visible_exits(room)
        visible_exits = [self._serialize_exit(exit_definition) for exit_definition in visible_definitions]
        return {
            "id": room.id,
            "label": room.label,
            "description": room.description,
            "board": {
                "type": room.board_type,
                "image_url": f"/assets/world/{self._world.id}/rooms/{room.board_image_name}",
                "image_style": room.board_image_style,
                "palette": list(room.palette),
                "dark": room.dark,
            },
            "metadata": {"note": note},
            "exits": visible_exits,
            "props": [self._serialize_prop(room, prop) for prop in room.props.values()],
            "occupants": occupants,
            "npcs": self._room_peeps(room_id),
            "room_cards": [self._card_service.serialize_room_stack(stack) for stack in room_cards],
            "chat_history": chat_history,
            "inventory": [self._card_service.serialize_inventory_stack(stack) for stack in inventory],
            "favorites": list(user_profile.favorites),
            "quick_actions": [
                {"label": "Look around", "command": ".look"},
                *[{"label": exit_definition.label, "command": self._exit_command(exit_definition.id)} for exit_definition in visible_definitions],
            ],
        }, room_seq

    async def build_snapshot(self, account: AccountRecord, room_id: str, *, note: str | None = None) -> dict[str, object]:
        """Build a coherent room snapshot for a specific account."""

        snapshot, _ = await self.build_snapshot_with_seq(account, room_id, note=note)
        return snapshot

    def say(self, account: AccountRecord, room_id: str, raw_text: str) -> tuple[int, dict[str, object]]:
        """Persist a room chat message and return the broadcast event."""

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
        seq = self._world_state.append_chat_message(room_id, entry)
        return seq, {"type": "chat.message", "room_id": room_id, **entry}

    async def navigate(self, account: AccountRecord, source_room_id: str, exit_id: str) -> NavigationResult:
        """Move a connected user between rooms and return ordered room events."""

        source_room = self._world.rooms[source_room_id]
        if exit_id not in source_room.exits:
            raise ValueError("That exit is not available from this room.")
        exit_definition = source_room.exits[exit_id]
        if exit_definition.target_room_id not in self.MILESTONE_ROOM_IDS:
            raise ValueError("That destination is not available in Milestone 1.")
        destination_room = self._world.rooms[exit_definition.target_room_id]
        if exit_definition.locked:
            raise ValueError("That way is locked in this milestone build.")
        if exit_definition.requires_card_id is not None:
            inventory_ids = {stack.card_def_id for stack in self._profiles.list_inventory(account.id, self._world.id)}
            if exit_definition.requires_card_id not in inventory_ids:
                raise ValueError(f"You need {exit_definition.requires_card_id} to go that way.")
        with self._hub.transaction() as connection:
            source_seq = self._world_state.advance_room_seq(connection, source_room_id)
            destination_seq = self._world_state.advance_room_seq(connection, destination_room.id)
            self._profiles.set_remembered_room(connection, account.id, self._world.id, destination_room.id)
        await self._connections.set_room(account.id, destination_room.id)
        closed = self._activities.close_if_room_bound(account.id, destination_room.id)
        snapshot, snapshot_seq = await self.build_snapshot_with_seq(account, destination_room.id)
        return NavigationResult(
            source_room_id=source_room_id,
            destination_room_id=destination_room.id,
            source_seq=source_seq,
            destination_seq=destination_seq,
            destination_snapshot=snapshot,
            destination_snapshot_seq=snapshot_seq,
            source_event=presence_leave_event(
                account_id=account.id,
                username=account.username_display,
                room_id=source_room_id,
                destination_room_id=destination_room.id,
            ),
            destination_event=presence_enter_event(
                account_id=account.id,
                username=account.username_display,
                room_id=destination_room.id,
                source_room_id=source_room_id,
            ),
            closed_activity=None if closed is None else self._activities.serialize(closed),
        )
