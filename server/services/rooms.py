"""Room snapshots, presence, chat, and navigation helpers."""

from __future__ import annotations

from dataclasses import dataclass

from server.connections import ConnectionRegistry
from server.content.cards import CardCatalog
from server.content.worlds import PeepDefinition, QuickAction, RoomDefinition, WorldDefinition
from server.profiles import AccountRecord, ProfileRepository
from server.protocol import MAX_CHAT_SIZE
from server.services.activities import ActivityService
from server.services.cards import CardService
from server.state.migrations import DatabaseHub
from server.state.world_state import WorldStateRepository


@dataclass(frozen=True, slots=True)
class NavigationResult:
    """Outcome of a room navigation command."""

    source_room_id: str
    destination_room_id: str
    destination_seq: int
    destination_snapshot: dict[str, object]
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
        catalog: CardCatalog,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._world_state = world_state
        self._connections = connections
        self._card_service = card_service
        self._activities = activities
        self._world = world
        self._catalog = catalog

    def current_room_for_account(self, account_id: str) -> str:
        """Return the remembered room for the given account."""

        profile = self._profiles.ensure_world_profile(account_id, self._world.id, self._world.entry_room_id)
        remembered = profile.remembered_room
        if remembered in self._world.rooms:
            return remembered
        return self._world.entry_room_id

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
                command = f".go @way:{remainder}"
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

        occupants: list[dict[str, object]] = []
        for connection in await self._connections.list_room(room_id):
            account = self._profiles.get_account_by_id(connection.account_id)
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

    async def build_snapshot(self, account: AccountRecord, room_id: str, *, note: str | None = None) -> dict[str, object]:
        """Build a coherent room snapshot for a specific account."""

        room = self._world.rooms[room_id]
        occupants = await self.room_occupants(room_id)
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
            "exits": [
                {
                    "id": exit_definition.id,
                    "label": exit_definition.label,
                    "target_room_id": exit_definition.target_room_id,
                    "locked": exit_definition.locked,
                    "requires_card_id": exit_definition.requires_card_id,
                    "quick_action": {"label": exit_definition.label, "command": f".go @way:{exit_definition.id}"},
                }
                for exit_definition in self._visible_exits(room)
            ],
            "props": [
                {
                    "id": prop.id,
                    "prop_id": prop.prop_id,
                    "position": list(prop.pos),
                    "rotation": list(prop.rot),
                    "scale": prop.scale,
                    "behavior": prop.behavior,
                    "model_url": f"/assets/world/{self._world.id}/props/{self._world.props[prop.prop_id].model_name}",
                    "label": self._world.props[prop.prop_id].label,
                    "description": self._world.props[prop.prop_id].description,
                    "quick_actions": self._visible_prop_actions(room, prop.actions),
                }
                for prop in room.props.values()
            ],
            "occupants": occupants,
            "npcs": self._room_peeps(room_id),
            "room_cards": [self._card_service.serialize_room_stack(stack) for stack in self._world_state.list_room_cards(room_id)],
            "chat_history": self._world_state.get_chat_history(room_id),
            "inventory": self._card_service.list_inventory_payload(account.id),
            "favorites": list(account.favorites),
            "quick_actions": [
                {"label": "Look around", "command": ".look"},
                *[
                    {
                        "label": exit_definition.label,
                        "command": f".go @way:{exit_definition.id}",
                    }
                    for exit_definition in self._visible_exits(room)
                ],
            ],
        }

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
        snapshot = await self.build_snapshot(account, destination_room.id)
        return NavigationResult(
            source_room_id=source_room_id,
            destination_room_id=destination_room.id,
            destination_seq=destination_seq,
            destination_snapshot=snapshot,
            source_event={
                "type": "presence.leave",
                "room_id": source_room_id,
                "account_id": account.id,
                "username": account.username_display,
                "destination_room_id": destination_room.id,
                "seq": source_seq,
            },
            destination_event={
                "type": "presence.enter",
                "room_id": destination_room.id,
                "account_id": account.id,
                "username": account.username_display,
                "source_room_id": source_room_id,
            },
            closed_activity=None if closed is None else self._activities.serialize(closed),
        )
