"""Strict card and pack definition loaders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.content.common import ContentError, load_yaml_file, require_mapping

CORE_CARD_IDS = frozenset({"emotes", "inventory", "journal"})
BASE_EMOTE_IDS = frozenset({"smile", "sigh", "goof", "growl", "wave", "happy-dance", "heart"})
PACK_CARD_TYPE = "pack"
NON_EQUIP_TYPES = frozenset({"emote", "core", "skill", PACK_CARD_TYPE})
STACKABLE_TYPES = frozenset({"item", "emote", "skill", PACK_CARD_TYPE})
DEFAULT_STACKABLE_LIMIT = 99


@dataclass(frozen=True, slots=True)
class CardDefinition:
    """Immutable card definition."""

    id: str
    label: str
    description: str
    image_name: str
    image_path: Path
    animation_name: str | None
    type: str
    rarity: str | None
    stack_limit: int
    one_use: bool
    passive: bool
    decorative: bool
    bonuses: dict[str, int]
    energy_cost: int | None
    target: str | None
    effect: str | None
    amount: int | None
    duration: int | None
    category: str | None
    cutscene: str | None
    rank: str | None
    quest: bool
    order: int | None
    source: str
    tags: frozenset[str] = frozenset()
    consume_card: str | None = None
    output_card: str | None = None
    bagged_output_card: str | None = None
    hide_seconds: int | None = None
    clears_source: str | None = None
    soils: bool = False
    opens_pack: str | None = None

    @property
    def collectible(self) -> bool:
        """Return whether the card can be collected."""

        return self.id not in CORE_CARD_IDS and self.type != "core"


@dataclass(frozen=True, slots=True)
class PackDefinition:
    """Immutable pack definition."""

    id: str
    label: str
    description: str
    back_image_name: str
    back_image_path: Path
    price: int
    size: int
    cards: tuple[str, ...]
    source: str
    guaranteed: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CardCatalog:
    """Loaded catalog of cards and packs."""

    cards: dict[str, CardDefinition]
    packs: dict[str, PackDefinition]


def _detect_type(card_id: str, raw_card: dict[str, Any]) -> str:
    if isinstance(raw_card.get("type"), str):
        return raw_card["type"]
    if card_id in CORE_CARD_IDS:
        return "core"
    if card_id in BASE_EMOTE_IDS or raw_card.get("animation"):
        return "emote"
    return "item"


def _load_cards_from_file(path: Path, source: str) -> dict[str, CardDefinition]:
    payload = require_mapping(load_yaml_file(path), path)
    cards: dict[str, CardDefinition] = {}
    for card_id, raw_card in payload.items():
        if not isinstance(card_id, str) or not isinstance(raw_card, dict):
            raise ContentError(f"{path} contains an invalid card entry.")
        if card_id in cards:
            raise ContentError(f"Duplicate card id '{card_id}' in {path}.")
        image_name = str(raw_card.get("image", "")).strip()
        if not image_name:
            raise ContentError(f"Card '{card_id}' is missing an image in {path}.")
        image_path = (path.parent / image_name).resolve()
        if not image_path.is_file():
            raise ContentError(f"Card '{card_id}' references missing image '{image_name}'.")
        animation_name = str(raw_card.get("animation", "")).strip() or None
        if animation_name is not None:
            animation_path = (path.parent / animation_name).resolve()
            if not animation_path.is_file():
                raise ContentError(f"Card '{card_id}' references missing animation '{animation_name}'.")
        label = str(raw_card.get("label", "")).strip()
        description = str(raw_card.get("description", "")).strip()
        if not label or not description:
            raise ContentError(f"Card '{card_id}' must define label and description.")
        card_type = _detect_type(card_id, raw_card)
        cutscene = str(raw_card["cutscene"]).strip() if raw_card.get("cutscene") else None
        if cutscene is not None and card_type == "core":
            raise ContentError(f"Card '{card_id}' may not define cutscene on a core card.")
        # An emote's category is derived from its fields, never authored: a card
        # that runs a cutscene is a Cutscene emote, one with an animation is an
        # Animation emote, and everything else is an Expression.
        if card_type == "emote":
            if cutscene is not None:
                category = "Cutscene"
            elif animation_name is not None:
                category = "Animation"
            else:
                category = "Expression"
        else:
            category = str(raw_card["category"]) if "category" in raw_card else None
        raw_stack_limit = raw_card.get("stack_limit")
        if raw_stack_limit is None:
            stack_limit = DEFAULT_STACKABLE_LIMIT if card_type in STACKABLE_TYPES else 1
        else:
            stack_limit = int(raw_stack_limit)
        if stack_limit < 1:
            raise ContentError(f"Card '{card_id}' has invalid stack_limit {stack_limit}.")
        bonuses_raw = raw_card.get("bonuses", {}) or {}
        if not isinstance(bonuses_raw, dict):
            raise ContentError(f"Card '{card_id}' bonuses must be a mapping.")
        bonuses = {str(name): int(value) for name, value in bonuses_raw.items()}
        order = int(raw_card["order"]) if "order" in raw_card else None
        if order is not None and order < 1:
            raise ContentError(f"Card '{card_id}' has invalid order {order}.")
        if order is not None and card_type != "core":
            raise ContentError(f"Card '{card_id}' can only define order when it is a core card.")
        tags_raw = raw_card.get("tags", []) or []
        if not isinstance(tags_raw, list):
            raise ContentError(f"Card '{card_id}' tags must be a list.")
        tags = frozenset(str(tag).strip() for tag in tags_raw if str(tag).strip())
        cards[card_id] = CardDefinition(
            id=card_id,
            label=label,
            description=description,
            image_name=image_name,
            image_path=image_path,
            animation_name=animation_name,
            type=card_type,
            rarity=str(raw_card["rarity"]) if "rarity" in raw_card else None,
            stack_limit=stack_limit,
            one_use=bool(raw_card.get("one_use", False)),
            passive=bool(raw_card.get("passive", False)),
            decorative=bool(raw_card.get("decorative", False)),
            bonuses=bonuses,
            energy_cost=int(raw_card["energy_cost"]) if "energy_cost" in raw_card else None,
            target=str(raw_card["target"]) if "target" in raw_card else None,
            effect=str(raw_card["effect"]) if "effect" in raw_card else None,
            amount=int(raw_card["amount"]) if "amount" in raw_card else None,
            duration=int(raw_card["duration"]) if "duration" in raw_card else None,
            category=category,
            cutscene=cutscene,
            rank=str(raw_card["rank"]) if "rank" in raw_card else None,
            quest=bool(raw_card.get("quest", False)),
            order=order,
            source=source,
            tags=tags,
            consume_card=str(raw_card["consume_card"]) if "consume_card" in raw_card else None,
            output_card=str(raw_card["output_card"]) if "output_card" in raw_card else None,
            bagged_output_card=str(raw_card["bagged_output_card"]) if "bagged_output_card" in raw_card else None,
            hide_seconds=int(raw_card["hide_seconds"]) if "hide_seconds" in raw_card else None,
            clears_source=str(raw_card["clears_source"]) if "clears_source" in raw_card else None,
            soils=bool(raw_card.get("soils", False)),
        )
    return cards


def cutscene_card_references(catalog: CardCatalog) -> tuple[tuple[str, str], ...]:
    """Return every ``(card_id, cutscene)`` reference in a catalog."""

    return tuple(
        (definition.id, definition.cutscene)
        for definition in catalog.cards.values()
        if definition.cutscene
    )


def _load_pack_from_file(path: Path, pack_id: str, cards: dict[str, CardDefinition], source: str) -> PackDefinition:
    payload = require_mapping(load_yaml_file(path), path)
    label = str(payload.get("label", "")).strip()
    description = str(payload.get("description", "")).strip()
    if not label or not description:
        raise ContentError(f"Pack '{pack_id}' must define label and description.")
    back_image_name = str(payload.get("back_image", "")).strip()
    if not back_image_name:
        raise ContentError(f"Pack '{pack_id}' is missing back_image.")
    back_image_path = (path.parent / back_image_name).resolve()
    if not back_image_path.is_file():
        raise ContentError(f"Pack '{pack_id}' references missing image '{back_image_name}'.")
    card_ids = payload.get("cards")
    if not isinstance(card_ids, list) or not card_ids:
        raise ContentError(f"Pack '{pack_id}' must define a non-empty cards list.")
    for card_id in card_ids:
        if card_id not in cards:
            raise ContentError(f"Pack '{pack_id}' references unknown card '{card_id}'.")
    size = int(payload.get("size", 0))
    raw_guaranteed = payload.get("guaranteed") or []
    if not isinstance(raw_guaranteed, list):
        raise ContentError(f"Pack '{pack_id}' guaranteed must be a list of card ids.")
    guaranteed: list[str] = []
    for card_id in raw_guaranteed:
        if not isinstance(card_id, str) or not card_id:
            raise ContentError(f"Pack '{pack_id}' guaranteed entries must be card ids.")
        if card_id not in card_ids:
            raise ContentError(f"Pack '{pack_id}' guarantees card '{card_id}' that is not in the pack.")
        if card_id in guaranteed:
            raise ContentError(f"Pack '{pack_id}' repeats guaranteed card '{card_id}'.")
        guaranteed.append(card_id)
    if len(guaranteed) > size:
        raise ContentError(f"Pack '{pack_id}' guarantees more cards than it draws.")
    return PackDefinition(
        id=pack_id,
        label=label,
        description=description,
        back_image_name=back_image_name,
        back_image_path=back_image_path,
        price=int(payload.get("price", 0)),
        size=size,
        cards=tuple(str(card_id) for card_id in card_ids),
        source=source,
        guaranteed=tuple(guaranteed),
    )


def closed_pack_card_id(pack_id: str) -> str:
    """Return the synthetic inventory card id for a sealed pack."""

    return f"pack_{pack_id}"


def _sealed_pack_card(pack: PackDefinition) -> CardDefinition:
    """Build the inventory card that represents one sealed copy of *pack*."""

    return CardDefinition(
        id=closed_pack_card_id(pack.id),
        label=pack.label,
        description=pack.description,
        image_name=pack.back_image_name,
        image_path=pack.back_image_path,
        animation_name=None,
        type=PACK_CARD_TYPE,
        rarity=None,
        stack_limit=DEFAULT_STACKABLE_LIMIT,
        one_use=False,
        passive=True,
        decorative=False,
        bonuses={},
        energy_cost=None,
        target=None,
        effect=None,
        amount=None,
        duration=None,
        category=None,
        cutscene=None,
        rank=None,
        quest=False,
        order=None,
        source=pack.source,
        opens_pack=pack.id,
    )


def load_card_catalog(cardsets_root: Path, world_path: Path) -> CardCatalog:
    """Load all global and world-specific card and pack definitions."""

    cards: dict[str, CardDefinition] = {}
    packs: dict[str, PackDefinition] = {}

    for cards_file in sorted(cardsets_root.glob("*/cards.yaml")):
        source = cards_file.parent.name
        for card_id, definition in _load_cards_from_file(cards_file, source).items():
            if card_id in cards:
                raise ContentError(f"Duplicate card id '{card_id}'.")
            cards[card_id] = definition

    world_cards_file = world_path / "cards" / "cards.yaml"
    if world_cards_file.is_file():
        for card_id, definition in _load_cards_from_file(world_cards_file, world_path.name).items():
            if card_id in cards:
                raise ContentError(f"Duplicate card id '{card_id}'.")
            cards[card_id] = definition

    for pack_file in sorted(cardsets_root.glob("*/pack.yaml")):
        pack_id = pack_file.parent.name
        if pack_id in packs:
            raise ContentError(f"Duplicate pack id '{pack_id}'.")
        packs[pack_id] = _load_pack_from_file(pack_file, pack_id, cards, pack_file.parent.name)

    world_pack_file = world_path / "cards" / "pack.yaml"
    if world_pack_file.is_file():
        pack_id = world_path.name
        if pack_id in packs:
            raise ContentError(f"Duplicate pack id '{pack_id}'.")
        packs[pack_id] = _load_pack_from_file(world_pack_file, pack_id, cards, world_path.name)

    for pack in packs.values():
        sealed = _sealed_pack_card(pack)
        if sealed.id in cards:
            raise ContentError(f"Sealed-pack card id '{sealed.id}' collides with an authored card.")
        cards[sealed.id] = sealed

    return CardCatalog(cards=cards, packs=packs)

