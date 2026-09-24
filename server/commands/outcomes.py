"""Shared command context and result types used by all command handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from server.commands.registry import CommandRegistry
from server.connections import LiveConnection
from server.content.gameplay import GameplayContent
from server.content.worlds import WorldDefinition
from server.profiles import AccountRecord, ProfileRepository
from server.services.actions import ActionsService
from server.connections import ConnectionRegistry
from server.content.recipes import RecipeDefinition
from server.services.activities import ActivityService
from server.services.activity_results import ActivityResultService
from server.services.audit import AuditService
from server.services.cards import CardService
from server.services.crafting import CraftingService
from server.services.dialogs import DialogService
from server.services.dispensers import DispenserService
from server.services.environment import EnvironmentService
from server.services.friends import FriendsService
from server.services.inventory import InventoryService
from server.services.memories import MemoryService
from server.services.ownership import OwnershipService
from server.services.powers import PowersService
from server.services.pricing import CardPricingService
from server.services.progression import ProgressionService
from server.services.rooms import RoomService
from server.services.shop import ShopService
from server.services.stats import StatsService
from server.services.tasks import TaskService
from server.state.world_state import WorldStateRepository


class CommandError(ValueError):
    """Raised when a command is rejected."""


@dataclass(frozen=True, slots=True)
class PendingRoomBroadcast:
    """A room event waiting to be broadcast."""

    room_id: str
    event: dict[str, object]


@dataclass(slots=True)
class CommandOutcome:
    """Result of executing a command handler."""

    message: str | None = None
    code: str | None = None
    payload: dict[str, object] | None = None
    private_events: list[dict[str, object]] = field(default_factory=list)
    room_broadcasts: list[PendingRoomBroadcast] = field(default_factory=list)
    snapshot: dict[str, object] | None = None
    toast: bool = True
    log: bool = True


@dataclass(frozen=True, slots=True)
class CommandContext:
    """Runtime context passed to command handlers."""

    account: AccountRecord
    connection: LiveConnection
    profiles: ProfileRepository
    world_state: WorldStateRepository
    rooms: RoomService
    cards: CardService
    activities: ActivityService
    activity_results: ActivityResultService
    registry: CommandRegistry
    stats: StatsService
    inventory: InventoryService
    progression: ProgressionService
    actions: ActionsService
    friends: FriendsService
    shop: ShopService
    pricing: CardPricingService
    content: GameplayContent
    world: WorldDefinition
    valid_stickers: frozenset[str]
    serialize_user: Callable[[AccountRecord], dict[str, object]]
    behaviors: object
    dialogs: DialogService
    tasks: TaskService
    memories: MemoryService
    powers: PowersService
    ownership: OwnershipService
    environment: EnvironmentService
    audit: AuditService
    connections: ConnectionRegistry
    dispensers: DispenserService
    crafting: CraftingService
    recipes: dict[str, RecipeDefinition]
    mods: dict[str, object]
