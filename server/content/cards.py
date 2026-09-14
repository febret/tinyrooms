"""Strict card and pack definition loaders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml


CORE_CARD_IDS = frozenset({"room", "emotes", "inventory", "journal", "skills", "self", "friends", "edit-room"})
BASE_EMOTE_IDS = frozenset({"smile", "sigh", "goof", "growl", "wave", "happy-dance", "heart", "starlight"})


class ContentError(ValueError):
    """Raised when content definitions are malformed."""


@dataclass(frozen=True, slots=True)
class CardDefinition:
    """Immutable card definition."""

    id: str
    label: str
    description: str
    image_name: str
    image_path: Path
    type: str
    rarity: str | None
    stack_limit: int
    one_use: bool
    passive: bool
    decorative: bool
    bonuses: dict[str, int]
    energy_cost: int
    target: str | None
    effect: str | None
    amount: int | None
    duration: int | None
    category: str | None
    rank: str | None
    quest: bool
    source: str

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


@dataclass(frozen=True, slots=True)
class CardCatalog:
    """Loaded catalog of cards and packs."""

    cards: dict[str, CardDefinition]
    packs: dict[str, PackDefinition]


def _load_yaml_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _require_mapping(payload: Any, path: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ContentError(f"{path} must contain a top-level mapping.")
    return payload


def _detect_type(card_id: str, raw_card: dict[str, Any]) -> str:
    if isinstance(raw_card.get("type"), str):
        return raw_card["type"]
    if card_id in CORE_CARD_IDS:
        return "core"
    if card_id in BASE_EMOTE_IDS or raw_card.get("animation"):
        return "emote"
    return "item"


def _load_cards_from_file(path: Path, source: str) -> dict[str, CardDefinition]:
    payload = _require_mapping(_load_yaml_file(path), path)
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
        label = str(raw_card.get("label", "")).strip()
        description = str(raw_card.get("description", "")).strip()
        if not label or not description:
            raise ContentError(f"Card '{card_id}' must define label and description.")
        stack_limit = int(raw_card.get("stack_limit", 1))
        if stack_limit < 1:
            raise ContentError(f"Card '{card_id}' has invalid stack_limit {stack_limit}.")
        bonuses_raw = raw_card.get("bonuses", {}) or {}
        if not isinstance(bonuses_raw, dict):
            raise ContentError(f"Card '{card_id}' bonuses must be a mapping.")
        bonuses = {str(name): int(value) for name, value in bonuses_raw.items()}
        cards[card_id] = CardDefinition(
            id=card_id,
            label=label,
            description=description,
            image_name=image_name,
            image_path=image_path,
            type=_detect_type(card_id, raw_card),
            rarity=str(raw_card["rarity"]) if "rarity" in raw_card else None,
            stack_limit=stack_limit,
            one_use=bool(raw_card.get("one_use", False)),
            passive=bool(raw_card.get("passive", False)),
            decorative=bool(raw_card.get("decorative", False)),
            bonuses=bonuses,
            energy_cost=int(raw_card.get("energy_cost", 0)),
            target=str(raw_card["target"]) if "target" in raw_card else None,
            effect=str(raw_card["effect"]) if "effect" in raw_card else None,
            amount=int(raw_card["amount"]) if "amount" in raw_card else None,
            duration=int(raw_card["duration"]) if "duration" in raw_card else None,
            category=str(raw_card["category"]) if "category" in raw_card else None,
            rank=str(raw_card["rank"]) if "rank" in raw_card else None,
            quest=bool(raw_card.get("quest", False)),
            source=source,
        )
    return cards


def _load_pack_from_file(path: Path, pack_id: str, cards: dict[str, CardDefinition], source: str) -> PackDefinition:
    payload = _require_mapping(_load_yaml_file(path), path)
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
    return PackDefinition(
        id=pack_id,
        label=label,
        description=description,
        back_image_name=back_image_name,
        back_image_path=back_image_path,
        price=int(payload.get("price", 0)),
        size=int(payload.get("size", 0)),
        cards=tuple(str(card_id) for card_id in card_ids),
        source=source,
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

    return CardCatalog(cards=cards, packs=packs)

