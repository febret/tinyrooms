"""Strict card and pack definition loaders."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from server.content.common import (
    LOGGER,
    ContentError,
    drop_unknown_card_ids,
    load_yaml_file,
    require_mapping,
    warn_unknown_card,
)
from server.content.recipes import RecipeDefinition, load_recipes_file

CORE_CARD_IDS = frozenset({"emotes", "inventory", "journal"})
BASE_EMOTE_IDS = frozenset({"smile", "sigh", "goof", "growl", "wave", "happy-dance", "heart"})
PACK_CARD_TYPE = "pack"
NON_EQUIP_TYPES = frozenset({"emote", "core", "skill", PACK_CARD_TYPE})
STACKABLE_TYPES = frozenset({"item", "emote", "skill", PACK_CARD_TYPE})
DEFAULT_STACKABLE_LIMIT = 99

CARD_ART_PLACEHOLDER_PATH = (
    Path(__file__).resolve().parents[2] / "app" / "assets" / "card-placeholder.svg"
)
CARD_ART_PLACEHOLDER_URL = "/app/assets/card-placeholder.svg"


def card_asset_url(
    world_id: str,
    source: str,
    image_name: str,
    *,
    missing: bool = False,
) -> str:
    """Return the served URL for card or pack art, or its placeholder."""

    if missing:
        return CARD_ART_PLACEHOLDER_URL
    asset_kind = source if source != world_id else f"world/{world_id}/cards"
    return f"/assets/{asset_kind}/{image_name}"


@dataclass(frozen=True, slots=True)
class CardDefinition:
    """Immutable card definition."""

    # image is the required card illustration only (no frame, title, or stats):
    # clients compose full faces from metadata (client/app/js/card-face.js). Sealed
    # packs use their back art; animation is optional bubble art. Both resolve
    # beside cards.yaml. See doc/card-art.md.
    # one_use consumes a copy only on successful use. Passive cards work while
    # equipped; decorative keepsakes have no Use action. bonuses are per-copy
    # equipment/skill modifiers, not effects applied by actively playing a card.
    # An explicit energy_cost wins over the ordinary/emote-category default.
    # effect health/energy and room light are core-resolved; duration for light
    # is seconds. Other prop interactions are delegated to world behaviors.
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
    # Emotes with cutscene launch presentation instead of a speech bubble, using
    # normal ownership/stacking and card Energy costs (Cutscene default: 5).
    # Parsing forbids core cards only; non-emote cutscene fields are retained too.
    cutscene: str | None
    rank: str | None
    quest: bool
    order: int | None
    source: str
    # BehaviorContext exposes id/tags/consume_card to world scripts. These are
    # script-interpreted hints, not automatic core consumption or reward rules.
    tags: frozenset[str] = frozenset()
    consume_card: str | None = None
    soils: bool = False
    opens_pack: str | None = None
    image_missing: bool = False

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
    back_image_missing: bool = False


@dataclass(frozen=True, slots=True)
class CardCatalog:
    """Loaded catalog of cards, packs, and cardset recipes."""

    cards: dict[str, CardDefinition]
    packs: dict[str, PackDefinition]
    recipes: dict[str, RecipeDefinition] = field(default_factory=dict)


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
        image_missing = not image_path.is_file()
        if image_missing:
            LOGGER.warning(
                "Card '%s' references missing image '%s'; using a placeholder.",
                card_id,
                image_name,
            )
            image_path = CARD_ART_PLACEHOLDER_PATH
        animation_name = str(raw_card.get("animation", "")).strip() or None
        if animation_name is not None:
            animation_path = (path.parent / animation_name).resolve()
            if not animation_path.is_file():
                LOGGER.warning(
                    "Card '%s' references missing animation '%s'; using its still image.",
                    card_id,
                    animation_name,
                )
                animation_name = None
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
            soils=bool(raw_card.get("soils", False)),
            image_missing=image_missing,
        )
    return cards


def cutscene_card_references(catalog: CardCatalog) -> tuple[tuple[str, str], ...]:
    """Return every ``(card_id, cutscene)`` reference in a catalog."""

    # Validation waits for the merged world's cutscene catalog; it currently
    # requires direct ids even though launch-time resolution also accepts aliases.
    # Cutscene feature/room/power access checks belong to the launch path.
    return tuple(
        (definition.id, definition.cutscene)
        for definition in catalog.cards.values()
        if definition.cutscene
    )


def _load_pack_from_file(
    path: Path,
    pack_id: str,
    cards: dict[str, CardDefinition],
    source: str,
) -> PackDefinition | None:
    payload = require_mapping(load_yaml_file(path), path)
    return _load_pack_payload(path, pack_id, payload, cards, source)


def _load_pack_payload(
    path: Path,
    pack_id: str,
    payload: dict[str, Any],
    cards: dict[str, CardDefinition],
    source: str,
) -> PackDefinition | None:
    label = str(payload.get("label", "")).strip()
    description = str(payload.get("description", "")).strip()
    if not label or not description:
        raise ContentError(f"Pack '{pack_id}' must define label and description.")
    back_image_name = str(payload.get("back_image", "")).strip()
    if not back_image_name:
        raise ContentError(f"Pack '{pack_id}' is missing back_image.")
    back_image_path = (path.parent / back_image_name).resolve()
    back_image_missing = not back_image_path.is_file()
    if back_image_missing:
        LOGGER.warning(
            "Pack '%s' references missing image '%s'; using a placeholder.",
            pack_id,
            back_image_name,
        )
        back_image_path = CARD_ART_PLACEHOLDER_PATH
    card_ids = payload.get("cards")
    if not isinstance(card_ids, list) or not card_ids:
        raise ContentError(f"Pack '{pack_id}' must define a non-empty cards list.")
    card_ids = drop_unknown_card_ids(
        (str(card_id) for card_id in card_ids), set(cards), f"Pack '{pack_id}'"
    )
    if not card_ids:
        warn_unknown_card(f"Pack '{pack_id}'", "every listed card")
        return None
    size = int(payload.get("size", 0))
    raw_guaranteed = payload.get("guaranteed") or []
    if not isinstance(raw_guaranteed, list):
        raise ContentError(f"Pack '{pack_id}' guaranteed must be a list of card ids.")
    guaranteed: list[str] = []
    for card_id in raw_guaranteed:
        if not isinstance(card_id, str) or not card_id:
            raise ContentError(f"Pack '{pack_id}' guaranteed entries must be card ids.")
        if card_id not in card_ids:
            warn_unknown_card(f"Pack '{pack_id}' guaranteed", card_id)
            continue
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
        cards=tuple(card_ids),
        source=source,
        guaranteed=tuple(guaranteed),
        back_image_missing=back_image_missing,
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
        image_missing=pack.back_image_missing,
    )


def load_card_catalog(
    cardsets_root: Path,
    world_path: Path,
    *,
    extra_cardsets_roots: Sequence[Path] = (),
) -> CardCatalog:
    """Load all global and world-specific card and pack definitions.

    ``extra_cardsets_roots`` are layered on top of ``cardsets_root`` in ascending
    priority: a definition in a later root overrides an earlier one on id
    collisions. Duplicate ids inside a single root remain an error.
    """

    cards: dict[str, CardDefinition] = {}
    packs: dict[str, PackDefinition] = {}
    recipes: dict[str, RecipeDefinition] = {}

    for root in (cardsets_root, *extra_cardsets_roots):
        root_cards: dict[str, CardDefinition] = {}
        for cards_file in sorted(root.glob("*/cards.yaml")):
            source = cards_file.parent.name
            for card_id, definition in _load_cards_from_file(cards_file, source).items():
                if card_id in root_cards:
                    raise ContentError(f"Duplicate card id '{card_id}'.")
                root_cards[card_id] = definition
        cards.update(root_cards)

    world_cards_file = world_path / "cards" / "cards.yaml"
    if world_cards_file.is_file():
        for card_id, definition in _load_cards_from_file(world_cards_file, world_path.name).items():
            if card_id in cards:
                raise ContentError(f"Duplicate card id '{card_id}'.")
            cards[card_id] = definition

    for root in (cardsets_root, *extra_cardsets_roots):
        root_packs: dict[str, PackDefinition] = {}
        for pack_file in sorted(root.glob("*/pack.yaml")):
            pack_id = pack_file.parent.name
            if pack_id in root_packs:
                raise ContentError(f"Duplicate pack id '{pack_id}'.")
            pack = _load_pack_from_file(pack_file, pack_id, cards, pack_file.parent.name)
            if pack is not None:
                root_packs[pack_id] = pack
        packs.update(root_packs)

    for root in (cardsets_root, *extra_cardsets_roots):
        root_recipes: dict[str, RecipeDefinition] = {}
        for recipes_file in sorted(root.glob("*/recipes.yaml")):
            source = recipes_file.parent.name
            for recipe_id, recipe in load_recipes_file(
                recipes_file, set(cards), source=source
            ).items():
                if recipe_id in root_recipes:
                    raise ContentError(f"Duplicate recipe id '{recipe_id}'.")
                root_recipes[recipe_id] = recipe
        recipes.update(root_recipes)

    world_pack_file = world_path / "cards" / "pack.yaml"
    if world_pack_file.is_file():
        pack_id = world_path.name
        if pack_id in packs:
            raise ContentError(f"Duplicate pack id '{pack_id}'.")
        pack = _load_pack_from_file(world_pack_file, pack_id, cards, world_path.name)
        if pack is not None:
            packs[pack_id] = pack

    # A world may also define several named packs in one mapping file.
    world_packs_file = world_path / "cards" / "packs.yaml"
    if world_packs_file.is_file():
        packs_payload = require_mapping(load_yaml_file(world_packs_file), world_packs_file)
        for raw_pack_id, raw_pack in packs_payload.items():
            pack_id = str(raw_pack_id)
            if pack_id in packs:
                raise ContentError(f"Duplicate pack id '{pack_id}'.")
            pack = _load_pack_payload(
                world_packs_file,
                pack_id,
                require_mapping(raw_pack, world_packs_file),
                cards,
                world_path.name,
            )
            if pack is not None:
                packs[pack_id] = pack

    for pack in packs.values():
        sealed = _sealed_pack_card(pack)
        if sealed.id in cards:
            raise ContentError(f"Sealed-pack card id '{sealed.id}' collides with an authored card.")
        cards[sealed.id] = sealed

    return CardCatalog(cards=cards, packs=packs, recipes=recipes)

