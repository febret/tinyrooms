"""Shared per-container card storage for container props."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from server.content.levels import DEFAULT_MAX_EQUIPPED
from server.content.worlds import PropInstanceDefinition, WorldDefinition
from server.profiles import AccountRecord, InventoryStack, ProfileRepository
from server.services.cards import auto_equip_new_stacks, grant_card_to_inventory
from server.state.migrations import DatabaseHub
from server.state.world_state import WorldStateRepository

if TYPE_CHECKING:
    from server.content.cards import CardCatalog
    from server.services.cards import CardService


@dataclass(frozen=True, slots=True)
class ContainerDepositResult:
    """Outcome of storing one inventory copy inside a container."""

    card_id: str
    label: str
    stacks: tuple[InventoryStack, ...]
    contents: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class ContainerTakeResult:
    """Outcome of taking cards back out of a container."""

    card_id: str
    label: str
    quantity: int
    stacks: tuple[InventoryStack, ...]
    contents: tuple[dict[str, object], ...]


class ContainerService:
    """Owns shared, per-container card storage for container props."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        world_state: WorldStateRepository,
        catalog: CardCatalog,
        cards: CardService,
        world: WorldDefinition,
        equipped_caps: dict[int, int] | None = None,
        environment: object | None = None,
        layout: object | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._world_state = world_state
        self._catalog = catalog
        self._cards = cards
        self._world = world
        self._equipped_caps = equipped_caps or {}
        self._environment = environment
        self._layout = layout

    def _container(self, room_id: str, prop_instance_id: str) -> PropInstanceDefinition:
        room = self._world.rooms.get(room_id)
        if room is None:
            raise ValueError("That room does not exist.")
        prop = None
        if self._layout is not None:
            prop = next(
                (
                    candidate
                    for candidate in self._layout.effective_props(room_id)
                    if candidate.id == prop_instance_id
                ),
                None,
            )
        if prop is None:
            prop = room.props.get(prop_instance_id)
        if prop is None:
            raise ValueError("That container is not in this room.")
        if self._environment is not None:
            self._environment.require_prop_target(room_id, prop.id, prop.prop_id)
        definition = self._world.props[prop.prop_id]
        if definition.behavior != "container":
            raise ValueError("That prop is not a container.")
        return prop

    def contents(self, room_id: str, prop_instance_id: str) -> dict[str, object]:
        """Return a container's label and serialized card stacks."""

        prop = self._container(room_id, prop_instance_id)
        definition = self._world.props[prop.prop_id]
        stacks = self._world_state.list_container_cards(room_id, prop.id)
        return {
            "instance_id": prop.id,
            "room_id": room_id,
            "label": prop.label or definition.label,
            "cards": self._cards.serialize_container_stacks(stacks),
        }

    def deposit(
        self,
        account: AccountRecord,
        room_id: str,
        prop_instance_id: str,
        stack_id: str,
        quantity: int = 1,
    ) -> ContainerDepositResult:
        """Move inventory copies into a container without charging or consuming them.

        Storing is not "using" a card: Energy is untouched and one-use cards are
        kept intact inside the container instead of being consumed.
        """

        if quantity < 1:
            raise ValueError("Invalid quantity for that container.")
        prop = self._container(room_id, prop_instance_id)
        with self._hub.transaction() as connection:
            stack, _deleted = self._profiles.remove_inventory_quantity(
                connection,
                account_id=account.id,
                world_id=self._world.id,
                stack_id=stack_id,
                quantity=quantity,
            )
            self._world_state.add_container_card(
                connection,
                room_id=room_id,
                instance_id=prop.id,
                card_def_id=stack.card_def_id,
                quantity=quantity,
                placed_by_account_id=account.id,
            )
            rows = tuple(self._profiles.list_inventory(account.id, self._world.id))
            stored = self._world_state.list_container_cards(room_id, prop.id)
        definition = self._cards.definition(stack.card_def_id)
        return ContainerDepositResult(
            card_id=stack.card_def_id,
            label=definition.label,
            stacks=rows,
            contents=tuple(self._cards.serialize_container_stacks(stored)),
        )

    def take(
        self,
        account: AccountRecord,
        room_id: str,
        prop_instance_id: str,
        stack_id: str,
        quantity: int = 1,
    ) -> ContainerTakeResult:
        """Move container copies back into an account's inventory."""

        if quantity < 1:
            raise ValueError("Invalid quantity for that container.")
        prop = self._container(room_id, prop_instance_id)
        with self._hub.transaction() as connection:
            stack, _deleted = self._world_state.take_container_card(
                connection,
                room_id=room_id,
                instance_id=prop.id,
                stack_id=stack_id,
                quantity=quantity,
            )
            definition = self._cards.definition(stack.card_def_id)
            created_stacks: list[InventoryStack] = []
            for _ in range(quantity):
                created_stacks.extend(
                    grant_card_to_inventory(
                        self._profiles,
                        connection,
                        account_id=account.id,
                        definition=definition,
                        world_id=self._world.id,
                    )
                )
            auto_equip_new_stacks(
                self._profiles,
                connection,
                account_id=account.id,
                world_id=self._world.id,
                definition=definition,
                created_stacks=created_stacks,
                equipped_cap=self._equipped_caps.get(account.level, DEFAULT_MAX_EQUIPPED),
            )
            rows = tuple(self._profiles.list_inventory(account.id, self._world.id))
            stored = self._world_state.list_container_cards(room_id, prop.id)
        return ContainerTakeResult(
            card_id=stack.card_def_id,
            label=definition.label,
            quantity=quantity,
            stacks=rows,
            contents=tuple(self._cards.serialize_container_stacks(stored)),
        )
