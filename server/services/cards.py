"""Card interaction and serialization helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace
import sqlite3

from server.content.cards import NON_EQUIP_TYPES, CardCatalog, CardDefinition
from server.content.levels import DEFAULT_MAX_EQUIPPED
from server.profiles import AccountRecord, InventoryStack, ProfileRepository
from server.state.migrations import DatabaseHub
from server.state.world_state import RoomCardStack, WorldStateRepository


@dataclass(frozen=True, slots=True)
class CardMutationResult:
    """Outcome of a pickup or drop command."""

    inventory: list[dict[str, object]]
    room_event: dict[str, object]


def require_definition(catalog: CardCatalog, card_def_id: str) -> CardDefinition:
    """Return a loaded card definition, rejecting unknown ids."""

    definition = catalog.cards.get(card_def_id)
    if definition is None:
        raise ValueError(f"Unknown card '{card_def_id}'.")
    return definition


def require_inventory_stack(
    profiles: ProfileRepository,
    world_id: str,
    account_id: str,
    stack_id: str,
) -> InventoryStack:
    """Return an owned inventory stack, rejecting unknown ids."""

    stack = profiles.get_inventory_stack(account_id, world_id, stack_id)
    if stack is None:
        raise ValueError("That card stack is not in your inventory.")
    return stack


def grant_card_to_inventory(
    profiles: ProfileRepository,
    connection: sqlite3.Connection,
    *,
    account_id: str,
    definition: CardDefinition,
    world_id: str,
) -> list[InventoryStack]:
    """Add one copy of a collectible, scoping world cards to the active world."""

    scope = "world" if definition.source == world_id else "global"
    return profiles.add_inventory_card(
        connection,
        account_id=account_id,
        world_id=world_id if scope == "world" else None,
        card_def_id=definition.id,
        quantity=1,
        scope=scope,
        stack_limit=definition.stack_limit,
    )


def should_auto_equip(definition: CardDefinition) -> bool:
    """Return whether a picked-up card should occupy an equipped slot."""

    return definition.type not in NON_EQUIP_TYPES


def auto_equip_new_stacks(
    profiles: ProfileRepository,
    connection: sqlite3.Connection,
    *,
    account_id: str,
    world_id: str,
    definition: CardDefinition,
    created_stacks: list[InventoryStack],
    equipped_cap: int,
) -> list[InventoryStack]:
    """Equip one newly received stack when the equipped hand has room.

    Called by room pickups and dispenser draws. Admin/GM grants and crafted
    outputs intentionally leave new stacks unequipped.

    Returns the account's visible inventory stacks after any equip change.
    """

    inventory_rows = profiles.list_inventory(account_id, world_id)
    if not should_auto_equip(definition):
        return inventory_rows
    if sum(1 for item in inventory_rows if item.equipped) >= equipped_cap:
        return inventory_rows
    for created_stack in created_stacks:
        if created_stack.equipped:
            continue
        profiles.set_stack_equipped(
            connection,
            account_id=account_id,
            world_id=world_id,
            stack_id=created_stack.stack_id,
            equipped=True,
        )
        inventory_rows = [
            replace(item, equipped=True) if item.stack_id == created_stack.stack_id else item
            for item in inventory_rows
        ]
        break
    return inventory_rows


class CardService:
    """Own serialization and mutation of room/inventory card stacks."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        world_state: WorldStateRepository,
        catalog: CardCatalog,
        world_id: str,
        equipped_caps: dict[int, int] | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._world_state = world_state
        self._catalog = catalog
        self._world_id = world_id
        self._equipped_caps = equipped_caps or {}

    def definition(self, card_def_id: str) -> CardDefinition:
        """Return a loaded card definition by ID."""

        return self._catalog.cards[card_def_id]

    def serialize_definition(self, definition: CardDefinition) -> dict[str, object]:
        """Serialize a card definition for clients."""

        asset_kind = definition.source if definition.source != self._world_id else f"world/{self._world_id}/cards"
        payload = {
            "id": definition.id,
            "label": definition.label,
            "description": definition.description,
            "type": definition.type,
            "collectible": definition.collectible,
            "decorative": definition.decorative,
            "stack_limit": definition.stack_limit,
            "one_use": definition.one_use,
            "passive": definition.passive,
            "image_url": f"/assets/{asset_kind}/{definition.image_name}",
            "rarity": definition.rarity,
            "target": definition.target,
            "effect": definition.effect,
            "amount": definition.amount,
            "duration": definition.duration,
            "category": definition.category,
            "rank": definition.rank,
            "bonuses": definition.bonuses,
            "quest": definition.quest,
        }
        return payload

    def serialize_core_cards(self) -> list[dict[str, object]]:
        """Serialize core card definitions in authored order."""

        ordered = sorted(
            (
                definition
                for definition in self._catalog.cards.values()
                if definition.type == "core"
            ),
            key=lambda definition: definition.order if definition.order is not None else 0,
        )
        return [
            {**self.serialize_definition(definition), "order": definition.order}
            for definition in ordered
        ]

    def _serialize_stack_base(
        self,
        stack_id: str,
        card_def_id: str,
        quantity: int,
        pinned: bool,
        extra_action: dict[str, str],
    ) -> dict[str, object]:
        return {
            "stack_id": stack_id,
            "quantity": quantity,
            "pinned": pinned,
            "definition": self.serialize_definition(self.definition(card_def_id)),
            "quick_actions": [extra_action],
        }

    def serialize_inventory_stack(self, stack: InventoryStack) -> dict[str, object]:
        """Serialize an inventory stack for the client."""

        payload = self._serialize_stack_base(
            stack.stack_id,
            stack.card_def_id,
            stack.quantity,
            stack.pinned,
            {"label": "Drop 1", "command": f".drop @card:{stack.stack_id} 1"},
        )
        payload["scope"] = stack.scope
        payload["world_id"] = stack.world_id
        payload["equipped"] = stack.equipped
        return payload

    def serialize_room_stack(self, stack: RoomCardStack) -> dict[str, object]:
        """Serialize a room card stack for the client."""

        payload = self._serialize_stack_base(
            stack.stack_id,
            stack.card_def_id,
            stack.quantity,
            stack.pinned,
            {"label": "Pick up 1", "command": f".pickup @card:{stack.stack_id} 1"},
        )
        payload["position"] = [stack.position[0], stack.position[1], stack.position[2]]
        return payload

    def list_inventory_payload(self, account_id: str) -> list[dict[str, object]]:
        """Serialize all visible inventory for the current world."""

        return [
            self.serialize_inventory_stack(stack)
            for stack in self._profiles.list_inventory(account_id, self._world_id)
        ]

    def pickup(self, account: AccountRecord, room_id: str, stack_id: str, quantity: int) -> CardMutationResult:
        """Move cards from a room stack into inventory atomically."""

        with self._hub.transaction() as connection:
            stack, deleted = self._world_state.take_room_card(
                connection,
                room_id=room_id,
                stack_id=stack_id,
                quantity=quantity,
            )
            definition = self.definition(stack.card_def_id)
            created_stacks = self._profiles.add_inventory_card(
                connection,
                account_id=account.id,
                world_id=self._world_id if definition.collectible else None,
                card_def_id=stack.card_def_id,
                quantity=quantity,
                scope="world" if definition.collectible else "global",
                stack_limit=definition.stack_limit,
            )
            inventory_rows = auto_equip_new_stacks(
                self._profiles,
                connection,
                account_id=account.id,
                world_id=self._world_id,
                definition=definition,
                created_stacks=created_stacks,
                equipped_cap=self._equipped_caps.get(account.level, DEFAULT_MAX_EQUIPPED),
            )
        event = {
            "type": "room.card.removed" if deleted else "room.card.updated",
            "stack_id": stack.stack_id,
            "room_id": room_id,
            "quantity": 0 if deleted else stack.quantity - quantity,
            "picked_up_by": account.username_display,
            "inventory_stack_ids": [created_stack.stack_id for created_stack in created_stacks],
        }
        return CardMutationResult(
            inventory=[self.serialize_inventory_stack(item) for item in inventory_rows],
            room_event=event,
        )

    def drop(
        self,
        account: AccountRecord,
        room_id: str,
        stack_id: str,
        quantity: int,
        pos: tuple[float, float, float],
    ) -> CardMutationResult:
        """Move cards from inventory into a room atomically."""

        with self._hub.transaction() as connection:
            inventory_stack, _deleted = self._profiles.remove_inventory_quantity(
                connection,
                account_id=account.id,
                world_id=self._world_id,
                stack_id=stack_id,
                quantity=quantity,
            )
            room_stack = self._world_state.add_room_card(
                connection,
                room_id=room_id,
                card_def_id=inventory_stack.card_def_id,
                quantity=quantity,
                pos=pos,
            )
            inventory_rows = self._profiles.list_inventory(account.id, self._world_id)
        event = {
            "type": "room.card.added",
            "room_id": room_id,
            "stack": self.serialize_room_stack(room_stack),
            "dropped_by": account.username_display,
        }
        return CardMutationResult(
            inventory=[self.serialize_inventory_stack(item) for item in inventory_rows],
            room_event=event,
        )
