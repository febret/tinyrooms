"""Unlimited weighted card dispensers with one shared in-memory cooldown."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import random

from server.content.cards import CardCatalog
from server.content.levels import DEFAULT_MAX_EQUIPPED
from server.content.worlds import PropInstanceDefinition, WorldDefinition
from server.profiles import AccountRecord, InventoryStack, ProfileRepository
from server.security import utc_now
from server.services.cards import auto_equip_new_stacks, grant_card_to_inventory
from server.state.migrations import DatabaseHub


DEFAULT_DISPENSE_COOLDOWN_SECONDS = 600


@dataclass(frozen=True, slots=True)
class DispenseResult:
    """Outcome of one dispenser attempt."""

    granted: bool
    card_id: str | None = None
    label: str = ""
    remaining_seconds: float = 0.0
    ready_at: str | None = None
    stacks: tuple[InventoryStack, ...] = field(default_factory=tuple)


class DispenserService:
    """Owns weighted draws and the shared per-prop in-memory recharge cooldown."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        catalog: CardCatalog,
        world: WorldDefinition,
        rng: random.Random | None = None,
        equipped_caps: dict[int, int] | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._catalog = catalog
        self._world = world
        self._rng = rng or random.Random()
        self._equipped_caps = equipped_caps or {}
        self._cooldowns: dict[tuple[str, str], datetime] = {}

    def _prop(self, room_id: str, prop_instance_id: str) -> PropInstanceDefinition:
        room = self._world.rooms.get(room_id)
        if room is None:
            raise ValueError("That room does not exist.")
        prop = room.props.get(prop_instance_id)
        if prop is None:
            raise ValueError("That dispenser is not in this room.")
        if prop.behavior != "dispenser":
            raise ValueError("That prop is not a dispenser.")
        if not prop.content:
            raise ValueError("That dispenser has nothing to give.")
        return prop

    def _choose(self, prop: PropInstanceDefinition) -> str:
        population = list(prop.content)
        draw_weight = [prop.draw_weight.get(card_id, 1.0) for card_id in population]
        if not any(draw_weight):
            return self._rng.choice(population)
        return self._rng.choices(population, weights=draw_weight, k=1)[0]

    def dispense(self, account: AccountRecord, room_id: str, prop_instance_id: str) -> DispenseResult:
        """Attempt a dispense, honoring the shared cooldown without charging on rejection."""

        prop = self._prop(room_id, prop_instance_id)
        cooldown = prop.cooldown if prop.cooldown is not None else DEFAULT_DISPENSE_COOLDOWN_SECONDS
        now = utc_now()
        key = (self._world.id, prop_instance_id)
        with self._hub.transaction() as connection:
            ready = self._cooldowns.get(key)
            if ready is not None and ready > now:
                return DispenseResult(
                    granted=False,
                    remaining_seconds=max(0.0, (ready - now).total_seconds()),
                    ready_at=ready.isoformat(),
                )
            card_id = self._choose(prop)
            definition = self._catalog.cards.get(card_id)
            if definition is None:
                raise ValueError(f"Unknown dispenser card '{card_id}'.")
            created_stacks = grant_card_to_inventory(
                self._profiles,
                connection,
                account_id=account.id,
                definition=definition,
                world_id=self._world.id,
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
            next_ready = now + timedelta(seconds=max(0, int(cooldown)))
            self._cooldowns[key] = next_ready
            stacks = tuple(self._profiles.list_inventory(account.id, self._world.id))
        return DispenseResult(
            granted=True,
            card_id=card_id,
            label=definition.label,
            remaining_seconds=0.0,
            ready_at=next_ready.isoformat(),
            stacks=stacks,
        )
