"""Runtime-minted cards: override-only definitions stored in the profile DB.

A dynamic card reuses an authored base card's art, sounds, type, stack limit,
and gameplay fields while carrying a custom label, description, and rarity.
Definitions live in the shared ``dynamic_card_defs`` profile table so every
world process resolves the same id; only the id travels in inventory and room
stacks, exactly like authored card ids.

Art caveat: a base from a world-local cardset (``source == <world-id>``) is
served at ``/assets/world/<home-world>/cards/...``, which 404s in other
worlds. The client already draws the card frame without art on fetch failure,
so such cards stay functional everywhere but look complete only at home.
Prefer bases from shared ``data/cardsets`` for cross-world dynamics.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import logging
import random
import sqlite3
from typing import TYPE_CHECKING
import uuid

from server.content.cards import CardCatalog, CardDefinition
from server.profiles import DynamicCardRecord, ProfileRepository
from server.security import utc_now
from server.state.migrations import DatabaseHub
from server.state.world_state import RoomCardStack, WorldStateRepository

if TYPE_CHECKING:
    from server.commands.outcomes import PendingRoomBroadcast
    from server.services.cards import CardService


logger = logging.getLogger(__name__)


DYNAMIC_CARD_ID_PREFIX = "dyn_"
DYNAMIC_CARD_ID_SUFFIX_LENGTH = 12
MAX_DYNAMIC_LABEL_LENGTH = 60
MAX_DYNAMIC_DESCRIPTION_LENGTH = 280
MAX_DYNAMIC_CARDS_PER_CREATOR = 200

ALLOWED_DYNAMIC_RARITIES = frozenset({"Common", "Uncommon", "Rare", "Epic", "Legendary"})


def is_dynamic_card_id(card_id: object) -> bool:
    """Return whether *card_id* names a runtime-minted dynamic card."""

    return isinstance(card_id, str) and card_id.startswith(DYNAMIC_CARD_ID_PREFIX)


def generate_dynamic_card_id() -> str:
    """Return a fresh dynamic card id."""

    return f"{DYNAMIC_CARD_ID_PREFIX}{uuid.uuid4().hex[:DYNAMIC_CARD_ID_SUFFIX_LENGTH]}"


def normalize_dynamic_rarity(rarity: str | None) -> str | None:
    """Validate and canonicalize a dynamic card rarity override."""

    if rarity is None:
        return None
    canonical = str(rarity).strip().capitalize()
    if canonical not in ALLOWED_DYNAMIC_RARITIES:
        raise ValueError(
            f"Rarity must be one of {sorted(ALLOWED_DYNAMIC_RARITIES)}."
        )
    return canonical


def sanitize_dynamic_text(value: object, *, max_length: int, field: str) -> str:
    """Collapse whitespace, enforce a length cap, and reject blank values."""

    text = " ".join(str(value or "").split())
    if not text:
        raise ValueError(f"Dynamic card {field} must not be blank.")
    if len(text) > max_length:
        raise ValueError(f"Dynamic card {field} must be at most {max_length} characters.")
    return text


def synthesize_dynamic_definition(
    base: CardDefinition,
    record: DynamicCardRecord,
) -> CardDefinition:
    """Build the effective definition for a stored dynamic card override."""

    return replace(
        base,
        id=record.id,
        label=record.label,
        description=record.description,
        rarity=record.rarity if record.rarity is not None else base.rarity,
    )


def get_dynamic_definition(
    catalog: CardCatalog,
    profiles: ProfileRepository,
    card_id: str,
) -> CardDefinition | None:
    """Return the synthesized definition for *card_id*, or None when unknown.

    Authored ids never consult the profile store; dynamic ids never consult
    only the catalog. A dynamic row whose base no longer exists resolves to
    None so callers keep the same skip semantics as missing authored cards.
    """

    if not is_dynamic_card_id(card_id):
        return None
    record = profiles.get_dynamic_card(card_id)
    if record is None:
        return None
    base = catalog.cards.get(record.base_card_id)
    if base is None:
        return None
    return synthesize_dynamic_definition(base, record)


def batch_dynamic_definitions(
    catalog: CardCatalog,
    profiles: ProfileRepository,
    card_ids: list[str],
) -> dict[str, CardDefinition]:
    """Resolve many dynamic ids with a single profile-store query."""

    dynamic_ids = [card_id for card_id in dict.fromkeys(card_ids) if is_dynamic_card_id(card_id)]
    if not dynamic_ids:
        return {}
    records = profiles.list_dynamic_cards(dynamic_ids)
    resolved: dict[str, CardDefinition] = {}
    for card_id in dynamic_ids:
        record = records.get(card_id)
        if record is None:
            continue
        base = catalog.cards.get(record.base_card_id)
        if base is None:
            continue
        resolved[card_id] = synthesize_dynamic_definition(base, record)
    return resolved


def has_definition(
    catalog: CardCatalog,
    profiles: ProfileRepository,
    card_id: str,
) -> bool:
    """Return whether *card_id* resolves to an authored or dynamic definition."""

    if card_id in catalog.cards:
        return True
    return get_dynamic_definition(catalog, profiles, card_id) is not None


def require_definition(
    catalog: CardCatalog,
    profiles: ProfileRepository,
    card_id: str,
) -> CardDefinition:
    """Return the authored or dynamic definition for *card_id*."""

    definition = catalog.cards.get(card_id)
    if definition is not None:
        return definition
    dynamic = get_dynamic_definition(catalog, profiles, card_id)
    if dynamic is None:
        raise ValueError(f"Unknown card '{card_id}'.")
    return dynamic


def mint_dynamic_card(
    catalog: CardCatalog,
    profiles: ProfileRepository,
    connection: sqlite3.Connection,
    *,
    base_card_id: str,
    label: str,
    description: str,
    rarity: str | None = None,
    creator_account_id: str | None = None,
) -> CardDefinition:
    """Validate overrides, persist a dynamic definition, and return it.

    Must run inside the caller's transaction; the row commits with whatever
    inventory or room stack the caller creates for the new id.
    """

    base = catalog.cards.get(base_card_id)
    if base is None:
        raise ValueError(f"Unknown base card '{base_card_id}'.")
    if not base.collectible:
        raise ValueError(f"Base card '{base_card_id}' cannot back a dynamic card.")
    clean_label = sanitize_dynamic_text(label, max_length=MAX_DYNAMIC_LABEL_LENGTH, field="label")
    clean_description = sanitize_dynamic_text(
        description, max_length=MAX_DYNAMIC_DESCRIPTION_LENGTH, field="description"
    )
    clean_rarity = normalize_dynamic_rarity(rarity)
    if creator_account_id is not None:
        existing = connection.execute(
            "SELECT COUNT(*) AS total FROM dynamic_card_defs WHERE creator_account_id = ?",
            (creator_account_id,),
        ).fetchone()
        if existing is not None and int(existing["total"]) >= MAX_DYNAMIC_CARDS_PER_CREATOR:
            raise ValueError("Too many dynamic cards minted by this account.")
    for _ in range(3):
        card_id = generate_dynamic_card_id()
        try:
            record = profiles.create_dynamic_card(
                connection,
                card_id=card_id,
                base_card_id=base.id,
                label=clean_label,
                description=clean_description,
                rarity=clean_rarity,
                creator_account_id=creator_account_id,
            )
        except sqlite3.IntegrityError:
            continue
        return synthesize_dynamic_definition(base, record)
    raise ValueError("Could not mint a dynamic card id; try again.")


@dataclass(frozen=True, slots=True)
class DropVariant:
    """One personalized card variant a status drop can mint.

    ``base_candidates`` are tried in order against the world catalog so the
    same status works across worlds with different cardsets; ``label_template``
    and ``descriptions`` interpolate ``{name}`` with the dropping peep's
    display name.
    """

    base_candidates: tuple[str, ...]
    label_template: str
    descriptions: tuple[str, ...]
    rarity: str = "Common"


@dataclass(frozen=True, slots=True)
class StatusDropSpec:
    """Drop policy for one status: per-minute chance plus card variants."""

    status: str
    chance: float
    variants: tuple[DropVariant, ...]


STATUS_DROP_SPECS: tuple[StatusDropSpec, ...] = (
    StatusDropSpec(
        status="stinky",
        chance=0.10,
        variants=(
            DropVariant(
                base_candidates=("juicy-drink", "tasty-toast", "tomato-sauce"),
                label_template="{name}'s pee",
                descriptions=(
                    "Still warm. {name} was here, and their bladder filed a complaint.",
                    "A mysterious puddle with {name}'s name on it. Do not ask how it got there.",
                    "{name} couldn't hold it. The floor remembers.",
                    "Liquid evidence that {name} drinks a lot of juicy-drink.",
                ),
            ),
            DropVariant(
                base_candidates=("poop", "poop-in-a-bag", "plastic-bag"),
                label_template="{name}'s poop",
                descriptions=(
                    "Fresh from {name}. Do not ask about the journey.",
                    "{name} dropped this and kept walking. Bold. Stinky. Unforgivable.",
                    "A tribute from {name}'s troubled tummy. Handle with gloves and regret.",
                    "{name} swears the dog did it. There is no dog in this room.",
                ),
            ),
        ),
    ),
)

DROP_CHECK_PERIOD_SECONDS = 60
MAX_DYNAMIC_ROOM_STACKS = 10


class DynamicCardDrops:
    """Status-triggered room drops of personalized dynamic cards.

    Generic policy engine driven by ``STATUS_DROP_SPECS``: given account ids
    already known to carry a mapped status, roll each one's chance, mint a
    personalized dynamic card, and place it in the room.     Callers (today
    ``VibesService.update_room``) own occupancy, status detection, and the
    surrounding tick throttle; the dropper keeps its own per-room stamp so
    solo rooms without pair updates still check at most once a minute. The
    returned broadcasts are only ``room.card.added`` events; the caller adds
    its own ``room.refresh`` when anything changed.
    """

    def __init__(
        self,
        *,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        world_state: WorldStateRepository,
        cards: CardService,
        catalog: CardCatalog,
        rng: random.Random | None = None,
        random_func: Callable[[], float] | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._world_state = world_state
        self._cards = cards
        self._catalog = catalog
        self._rng = rng or random.Random()
        self._random_func = random_func or self._rng.random
        self._last_room_drop: dict[str, datetime] = {}

    def _base_for(self, variant: DropVariant) -> str | None:
        for base_card_id in variant.base_candidates:
            if base_card_id in self._catalog.cards:
                return base_card_id
        return None

    def _display_name(self, account_id: str) -> str:
        account = self._profiles.get_account_by_id(account_id)
        if account is None:
            return "a mysterious peep"
        return " ".join(str(account.username_display or "").split())[:24] or "a mysterious peep"

    def maybe_drop(
        self,
        room_id: str,
        account_ids: list[str],
        *,
        now: datetime | None = None,
    ) -> list[PendingRoomBroadcast]:
        """Roll one minute-cadence drop check for status-carrying occupants."""

        from server.commands.outcomes import PendingRoomBroadcast

        moment = now or utc_now()
        previous = self._last_room_drop.get(room_id)
        if previous is not None and moment - previous < timedelta(seconds=DROP_CHECK_PERIOD_SECONDS):
            return []
        users = [str(account_id) for account_id in dict.fromkeys(account_ids) if str(account_id)]
        if not users:
            return []
        room_stacks = self._world_state.list_room_cards(room_id)
        dynamic_count = sum(1 for stack in room_stacks if is_dynamic_card_id(stack.card_def_id))
        if dynamic_count >= MAX_DYNAMIC_ROOM_STACKS:
            self._last_room_drop[room_id] = moment
            return []
        broadcasts: list[PendingRoomBroadcast] = []
        for account_id in users:
            broadcast = self._mint_drop_for_specs(room_id, account_id)
            if broadcast is not None:
                broadcasts.append(broadcast)
                dynamic_count += 1
                if dynamic_count >= MAX_DYNAMIC_ROOM_STACKS:
                    break
        self._last_room_drop[room_id] = moment
        return broadcasts

    def _mint_drop_for_specs(
        self, room_id: str, account_id: str
    ) -> PendingRoomBroadcast | None:
        from server.commands.outcomes import PendingRoomBroadcast

        for spec in STATUS_DROP_SPECS:
            if self._random_func() >= spec.chance:
                continue
            variant = self._rng.choice(spec.variants)
            return self._mint_drop(room_id, account_id, variant)
        return None

    def _mint_drop(
        self, room_id: str, account_id: str, variant: DropVariant
    ) -> PendingRoomBroadcast | None:
        from server.commands.outcomes import PendingRoomBroadcast

        base_card_id = self._base_for(variant)
        if base_card_id is None:
            logger.warning("Dynamic drop skipped in %s: no base card available.", room_id)
            return None
        name = self._display_name(account_id)
        try:
            label = variant.label_template.format(name=name)
            description = self._rng.choice(variant.descriptions).format(name=name)
        except (IndexError, KeyError) as exc:
            logger.warning("Dynamic drop skipped in %s: bad drop text (%s).", room_id, exc)
            return None
        try:
            with self._hub.transaction() as connection:
                definition = mint_dynamic_card(
                    self._catalog,
                    self._profiles,
                    connection,
                    base_card_id=base_card_id,
                    label=label,
                    description=description,
                    rarity=variant.rarity,
                    creator_account_id=account_id,
                )
                room_stack = self._world_state.add_room_card(
                    connection,
                    room_id=room_id,
                    card_def_id=definition.id,
                    quantity=1,
                    pos=(
                        self._rng.uniform(5.0, 95.0),
                        self._rng.uniform(5.0, 95.0),
                        0.0,
                    ),
                    placed_by_account_id=account_id,
                )
        except ValueError as exc:
            logger.warning("Dynamic drop skipped in %s: %s", room_id, exc)
            return None
        return PendingRoomBroadcast(
            room_id=room_id,
            event={
                "type": "room.card.added",
                "room_id": room_id,
                "stack": self._cards.serialize_room_stack(room_stack),
                "dropped_by": name,
                "message": f"{name} dropped {definition.label}.",
            },
        )
