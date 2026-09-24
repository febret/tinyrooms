"""Infinite Bedrooms mod: per-player bedrooms, doors, and the Bedrooms activity.

This module is self-contained and loaded by ``server.mods`` at startup. It
contributes the ``.door`` command, the door customization catalog, and the
runtime state that materializes player rooms from the world's
``player-bedroom`` template.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import re
from typing import Any

from server.commands.outcomes import (
    CommandContext,
    CommandError,
    CommandOutcome,
    PendingRoomBroadcast,
)
from server.commands.parser import ParsedCommand
from server.content.common import ContentError, load_yaml_file, require_mapping
from server.content.worlds import PropInstanceDefinition, QuickAction, RoomDefinition, WorldDefinition
from server.profiles import AccountRecord, ProfileRepository
from server.services.ownership import OwnershipService
from server.state.migrations import DatabaseHub
from server.state.world_state import PLAYER_ROOM_PREFIX, PlayerRoomRecord, WorldStateRepository


MOD_ID = "infinite-bedrooms"
DOORS_FILENAME = "content/doors.yaml"
DEFAULT_TEMPLATE_ROOM_ID = "player-bedroom"
ROOM_ID_PREFIX = PLAYER_ROOM_PREFIX

DIMENSION_KINDS = frozenset({"choice", "text"})
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_LOCK_ON = frozenset({"on", "true", "yes", "lock", "locked"})
_LOCK_OFF = frozenset({"off", "false", "no", "unlock", "unlocked"})


@dataclass(frozen=True, slots=True)
class DoorOption:
    """One selectable value for a choice dimension."""

    id: str
    label: str
    value: str | None = None
    asset: str | None = None


@dataclass(frozen=True, slots=True)
class DoorDimension:
    """A single door customization dimension."""

    id: str
    label: str
    kind: str
    options: tuple[DoorOption, ...] = ()
    max_length: int | None = None


@dataclass(frozen=True, slots=True)
class DoorCatalog:
    """Validated door customization catalog."""

    cost: int
    dimensions: tuple[DoorDimension, ...]
    tag_pattern: re.Pattern[str] = field(default_factory=lambda: re.compile(r".*"))

    def dimension(self, dimension_id: str) -> DoorDimension | None:
        """Return a dimension by id, if present."""

        for dimension in self.dimensions:
            if dimension.id == dimension_id:
                return dimension
        return None

    def default_style(self) -> dict[str, str]:
        """Return the default style value for every dimension."""

        style: dict[str, str] = {}
        for dimension in self.dimensions:
            if dimension.kind == "choice" and dimension.options:
                style[dimension.id] = dimension.options[0].id
            else:
                style[dimension.id] = ""
        return style

    def validate_patch(self, patch: dict[str, Any]) -> dict[str, str]:
        """Validate a partial style patch and return normalized string values."""

        if not isinstance(patch, dict):
            raise ValueError("The door design must be a mapping.")
        normalized: dict[str, str] = {}
        for key, raw_value in patch.items():
            dimension = self.dimension(str(key))
            if dimension is None:
                raise ValueError(f"Unknown door setting '{key}'.")
            if dimension.kind == "choice":
                option_ids = {option.id for option in dimension.options}
                value = str(raw_value)
                if value not in option_ids:
                    raise ValueError(f"'{value}' is not a valid {dimension.label.lower()}.")
                normalized[dimension.id] = value
            else:
                text = str(raw_value).strip()
                if dimension.max_length is not None and len(text) > dimension.max_length:
                    raise ValueError(
                        f"{dimension.label} must be {dimension.max_length} characters or fewer."
                    )
                if text and not self.tag_pattern.fullmatch(text):
                    raise ValueError(f"{dimension.label} contains unsupported characters.")
                normalized[dimension.id] = text
        return normalized

    def serialize(self) -> dict[str, object]:
        """Serialize the catalog for the client activity."""

        return {
            "cost": self.cost,
            "dimensions": [
                {
                    "id": dimension.id,
                    "label": dimension.label,
                    "kind": dimension.kind,
                    "max_length": dimension.max_length,
                    "options": [
                        {
                            "id": option.id,
                            "label": option.label,
                            "value": option.value,
                            "asset": option.asset,
                        }
                        for option in dimension.options
                    ],
                }
                for dimension in self.dimensions
            ],
        }


def load_door_catalog(path: Path) -> DoorCatalog:
    """Load and validate the door customization catalog."""

    payload = require_mapping(load_yaml_file(path), path)
    cost = int(payload.get("cost", 0))
    if cost <= 0:
        raise ContentError(f"{path} must define a positive cost.")

    tag_config = payload.get("tag", {}) or {}
    if not isinstance(tag_config, dict):
        raise ContentError(f"{path} tag config must be a mapping.")
    tag_max_length = int(tag_config.get("max_length", 16))
    if tag_max_length < 1:
        raise ContentError(f"{path} tag max_length must be positive.")
    tag_pattern_text = str(tag_config.get("pattern", ".{" f"0,{tag_max_length}" "}"))
    try:
        tag_pattern = re.compile(tag_pattern_text)
    except re.error as exc:
        raise ContentError(f"{path} tag pattern is invalid.") from exc

    raw_dimensions = payload.get("dimensions")
    if not isinstance(raw_dimensions, dict) or not raw_dimensions:
        raise ContentError(f"{path} must define at least one dimension.")

    dimensions: list[DoorDimension] = []
    seen_dimensions: set[str] = set()
    text_dimension_count = 0
    for dimension_id, raw_dimension in raw_dimensions.items():
        if not isinstance(dimension_id, str) or not isinstance(raw_dimension, dict):
            raise ContentError(f"{path} contains an invalid dimension entry.")
        if dimension_id in seen_dimensions:
            raise ContentError(f"{path} defines duplicate dimension '{dimension_id}'.")
        seen_dimensions.add(dimension_id)
        kind = str(raw_dimension.get("kind", "choice")).strip() or "choice"
        if kind not in DIMENSION_KINDS:
            raise ContentError(f"Dimension '{dimension_id}' has unknown kind '{kind}'.")
        label = str(raw_dimension.get("label", "")).strip()
        if not label:
            raise ContentError(f"Dimension '{dimension_id}' must define a label.")
        if kind == "text":
            text_dimension_count += 1
            max_length = int(raw_dimension.get("max_length", tag_max_length))
            if max_length < 1:
                raise ContentError(f"Dimension '{dimension_id}' has an invalid max_length.")
            dimensions.append(
                DoorDimension(id=dimension_id, label=label, kind=kind, max_length=max_length)
            )
            continue
        raw_options = raw_dimension.get("options")
        if not isinstance(raw_options, list) or not raw_options:
            raise ContentError(f"Dimension '{dimension_id}' must define a non-empty options list.")
        options: list[DoorOption] = []
        seen_options: set[str] = set()
        for raw_option in raw_options:
            if not isinstance(raw_option, dict):
                raise ContentError(f"Dimension '{dimension_id}' contains an invalid option.")
            option_id = str(raw_option.get("id", "")).strip()
            option_label = str(raw_option.get("label", "")).strip()
            if not option_id or not option_label:
                raise ContentError(f"Dimension '{dimension_id}' options need id and label.")
            if option_id in seen_options:
                raise ContentError(f"Dimension '{dimension_id}' has duplicate option '{option_id}'.")
            seen_options.add(option_id)
            value = str(raw_option["value"]).strip() if "value" in raw_option else None
            asset = str(raw_option["asset"]).strip() if "asset" in raw_option else None
            if value is None and asset is None:
                raise ContentError(f"Dimension '{dimension_id}' option '{option_id}' needs value or asset.")
            if value is not None and not _HEX_COLOR.match(value):
                raise ContentError(f"Dimension '{dimension_id}' option '{option_id}' has an invalid color.")
            options.append(DoorOption(id=option_id, label=option_label, value=value, asset=asset))
        dimensions.append(DoorDimension(id=dimension_id, label=label, kind=kind, options=tuple(options)))

    if text_dimension_count > 1:
        raise ContentError(f"{path} may define at most one text dimension.")

    return DoorCatalog(cost=cost, dimensions=tuple(dimensions), tag_pattern=tag_pattern)


@dataclass(frozen=True, slots=True)
class DoorView:
    """A serialized player door for the Bedrooms activity."""

    room_id: str
    owner_id: str
    owner_username: str
    label: str
    locked: bool
    style: dict[str, str]

    def payload(self, *, is_owner: bool) -> dict[str, object]:
        """Serialize the door for a specific viewer."""

        return {
            "room_id": self.room_id,
            "owner_id": self.owner_id,
            "owner_username": self.owner_username,
            "label": self.label,
            "locked": self.locked,
            "is_owner": is_owner,
            "style": dict(self.style),
        }


class BedroomService:
    """Owns player-room records, materialization, and door rules."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        world_state: WorldStateRepository,
        ownership: OwnershipService,
        world: WorldDefinition,
        catalog: DoorCatalog,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._world_state = world_state
        self._ownership = ownership
        self._world = world
        self._catalog = catalog

    @property
    def catalog(self) -> DoorCatalog:
        """Return the loaded door customization catalog."""

        return self._catalog

    @property
    def cost(self) -> int:
        """Return the one-time Bops cost of a door."""

        return self._catalog.cost

    @staticmethod
    def room_id_for(account_id: str) -> str:
        """Return the deterministic room id for an account."""

        return f"{ROOM_ID_PREFIX}{account_id}"

    def _template(self) -> RoomDefinition:
        template = self._world.rooms.get(DEFAULT_TEMPLATE_ROOM_ID)
        if template is None or not template.template:
            raise ValueError("The player-bedroom template is not loaded.")
        return template

    def _clone(self, room_id: str, label: str) -> RoomDefinition:
        template = self._template()
        return replace(
            template,
            id=room_id,
            label=label,
            description="A quiet little room of your very own.",
            template=False,
        )

    def _label_for(self, account_id: str) -> str:
        account = self._profiles.get_account_by_id(account_id)
        username = account.username_display if account is not None else "A peep"
        return f"{username}'s Bedroom"

    @staticmethod
    def _door_style(record: PlayerRoomRecord) -> dict[str, Any]:
        style = record.door.get("style")
        return style if isinstance(style, dict) else {}

    @staticmethod
    def _door_locked(record: PlayerRoomRecord) -> bool:
        return bool(record.door.get("locked", False))

    def _materialize(self, record: PlayerRoomRecord) -> RoomDefinition:
        template = self._template()
        return replace(
            template,
            id=record.room_id,
            label=self._label_for(record.owner_account_id),
            description="A quiet little room of your very own.",
            template=False,
        )

    def _register(self, record: PlayerRoomRecord) -> None:
        self._world.rooms[record.room_id] = self._materialize(record)

    def prepare(self) -> None:
        """Materialize every persisted player room before the world is seeded."""

        for record in self._world_state.list_player_rooms():
            self._register(record)

    def record_for_account(self, account_id: str) -> PlayerRoomRecord | None:
        """Return the account's player room record, if any."""

        return self._world_state.get_player_room_for_account(account_id)

    def record_for_room(self, room_id: str) -> PlayerRoomRecord | None:
        """Return a player room record by room id."""

        return self._world_state.get_player_room(room_id)

    def view_for_room(self, room_id: str) -> DoorView | None:
        """Build a serialized door view for a room id."""

        record = self.record_for_room(room_id)
        return None if record is None else self._view(record)

    def _view(self, record: PlayerRoomRecord) -> DoorView:
        account = self._profiles.get_account_by_id(record.owner_account_id)
        username = account.username_display if account is not None else "A peep"
        style = {**self._catalog.default_style(), **self._door_style(record)}
        return DoorView(
            room_id=record.room_id,
            owner_id=record.owner_account_id,
            owner_username=username,
            label=f"{username}'s Bedroom",
            locked=self._door_locked(record),
            style=style,
        )

    def list_doors(self, *, viewer_id: str | None = None) -> list[dict[str, object]]:
        """Serialize every door, marking the viewer's own door."""

        return [
            self._view(record).payload(is_owner=record.owner_account_id == viewer_id)
            for record in self._world_state.list_player_rooms()
        ]

    def personal_actions(
        self,
        account: AccountRecord,
        prop: PropInstanceDefinition,
    ) -> tuple[QuickAction, ...]:
        """Return account-specific quick actions for a bedroom-entry prop."""

        if prop.activity != "bedrooms":
            return ()
        record = self._world_state.get_player_room_for_account(account.id)
        if record is None:
            return ()
        return (QuickAction(label="Go to Bedroom", command=f".door enter {record.room_id}"),)

    def purchase(self, account: AccountRecord) -> DoorView:
        """Buy a bedroom door for the catalog cost (one per account)."""

        if self._world_state.get_player_room_for_account(account.id) is not None:
            raise ValueError("You already have a bedroom door.")
        room_id = self.room_id_for(account.id)
        style = self._catalog.default_style()
        label = f"{account.username_display}'s Bedroom"
        self._world.rooms[room_id] = self._clone(room_id, label)
        try:
            with self._hub.transaction() as connection:
                current = self._profiles.get_account_by_id(account.id)
                if current is None:
                    raise ValueError("That account no longer exists.")
                if self._world_state.get_player_room_for_account(account.id) is not None:
                    raise ValueError("You already have a bedroom door.")
                if current.bops < self._catalog.cost:
                    raise ValueError(f"You need {self._catalog.cost} Bops to get a door.")
                self._profiles.update_progress(connection, current, bops=current.bops - self._catalog.cost)
                record = self._world_state.insert_player_room(
                    connection,
                    room_id=room_id,
                    owner_account_id=account.id,
                    door={"style": style, "locked": False},
                )
                self._ownership.grant_in_transaction(connection, room_id, account.id)
        except Exception:
            self._world.rooms.pop(room_id, None)
            raise
        self._register(record)
        self._world_state.seed_player_room(room_id, self._world.rooms[room_id], self._world)
        return self._view(record)

    def _require_own(self, account: AccountRecord) -> PlayerRoomRecord:
        record = self._world_state.get_player_room_for_account(account.id)
        if record is None:
            raise ValueError("You do not have a bedroom door yet.")
        return record

    def set_locked(self, account: AccountRecord, locked: bool) -> DoorView:
        """Lock or unlock the account's bedroom door."""

        record = self._require_own(account)
        door = {**record.door, "locked": locked}
        with self._hub.transaction() as connection:
            self._world_state.update_player_room(connection, room_id=record.room_id, door=door)
        updated = self._world_state.get_player_room(record.room_id)
        return self._view(updated if updated is not None else record)

    def design(self, account: AccountRecord, patch: dict[str, Any]) -> DoorView:
        """Validate and persist a door customization patch."""

        record = self._require_own(account)
        normalized = self._catalog.validate_patch(patch)
        style = {**self._catalog.default_style(), **self._door_style(record), **normalized}
        door = {**record.door, "style": style}
        with self._hub.transaction() as connection:
            self._world_state.update_player_room(connection, room_id=record.room_id, door=door)
        updated = self._world_state.get_player_room(record.room_id)
        return self._view(updated if updated is not None else record)

    def require_entry(self, account: AccountRecord, room_id: str) -> PlayerRoomRecord:
        """Validate that an account may enter a player room, raising otherwise."""

        record = self._world_state.get_player_room(room_id)
        if record is None:
            raise ValueError("That bedroom does not exist.")
        if self._door_locked(record) and record.owner_account_id != account.id:
            raise ValueError("That bedroom door is locked.")
        return record


def _room_id(context: CommandContext) -> str:
    if context.connection.room_id is None:
        raise CommandError("You are not currently in a room.")
    return context.connection.room_id


def _user_payload(context: CommandContext) -> dict[str, object]:
    account = context.profiles.get_account_by_id(context.account.id)
    return context.serialize_user(account)


def _service(context: CommandContext) -> BedroomService:
    service = context.mods.get(MOD_ID)
    if not isinstance(service, BedroomService):
        raise CommandError("The Bedrooms are not available here.")
    return service


async def door_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """List, buy, customize, lock, or enter player bedroom doors."""

    if not command.args:
        raise CommandError("Use '.door <list|buy|design|lock|enter> ...'.")
    action = command.args[0].lower()
    service = _service(context)

    if action == "list":
        own = service.record_for_account(context.account.id)
        own_view = service.view_for_room(own.room_id) if own is not None else None
        return CommandOutcome(
            payload={
                "doors": service.list_doors(viewer_id=context.account.id),
                "catalog": service.catalog.serialize(),
                "cost": service.cost,
                "own_door": None if own_view is None else own_view.payload(is_owner=True),
            },
            toast=False,
            log=False,
        )

    if action == "buy":
        view = service.purchase(context.account)
        return CommandOutcome(
            message="Your bedroom door is ready.",
            payload={"door": view.payload(is_owner=True), "user": _user_payload(context)},
            private_events=[{"type": "toast", "tone": "success", "text": "Your door appears in the Bedrooms."}],
        )

    if action == "design":
        tokens = list(command.args[1:])
        if not tokens or len(tokens) % 2 != 0:
            raise CommandError("Use '.door design <setting> <value> ...'.")
        patch = {tokens[index]: tokens[index + 1] for index in range(0, len(tokens), 2)}
        view = service.design(context.account, patch)
        return CommandOutcome(
            message="Door updated.",
            payload={"door": view.payload(is_owner=True)},
        )

    if action == "lock":
        if len(command.args) < 2:
            raise CommandError("Use '.door lock <on|off>'.")
        value = command.args[1].lower()
        if value in _LOCK_ON:
            locked = True
        elif value in _LOCK_OFF:
            locked = False
        else:
            raise CommandError("Lock must be on or off.")
        view = service.set_locked(context.account, locked)
        return CommandOutcome(
            message="Your door is locked." if locked else "Your door is unlocked.",
            payload={"door": view.payload(is_owner=True)},
        )

    if action == "enter":
        if len(command.args) < 2:
            raise CommandError("Use '.door enter <room_id>'.")
        room_id = command.args[1]
        service.require_entry(context.account, room_id)
        navigation = await context.rooms.enter_room(
            context.account,
            _room_id(context),
            room_id,
            direction="a bedroom door",
        )
        outcome = CommandOutcome(
            message="You step through the door.",
            payload={"room_id": navigation.destination_room_id},
            snapshot=navigation.destination_snapshot,
        )
        outcome.room_broadcasts.append(
            PendingRoomBroadcast(room_id=navigation.source_room_id, event=navigation.source_event)
        )
        outcome.room_broadcasts.append(
            PendingRoomBroadcast(room_id=navigation.destination_room_id, event=navigation.destination_event)
        )
        if navigation.closed_activity is not None:
            outcome.private_events.append(
                {"type": "activity.closed", "activity": navigation.closed_activity, "reason": "room_changed"}
            )
        from server.commands.core import _merge_behavior

        for behavior in navigation.behavior_results:
            _merge_behavior(outcome, behavior)
        return outcome

    raise CommandError("Unknown door command.")


def _build_state(runtime: object) -> BedroomService:
    catalog_path = Path(__file__).resolve().parent / DOORS_FILENAME
    catalog = load_door_catalog(catalog_path)
    return BedroomService(
        runtime.hub,
        runtime.profiles,
        runtime.world_state,
        runtime.ownership,
        runtime.world,
        catalog,
    )


def register(api: object) -> None:
    """Register the mod's command and runtime state factory."""

    api.register_command(
        "door",
        "Manage your Bedrooms door.",
        door_command,
        usage=".door <list|buy|design|lock|enter> ...",
        help="List, buy, customize, lock, or enter player bedroom doors.",
    )
    api.register_state_factory(_build_state)
