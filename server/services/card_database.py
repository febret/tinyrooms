"""Read-only Card Database payload builder."""

from __future__ import annotations

from pathlib import Path

from server.content.cards import CORE_CARD_IDS, CardCatalog, CardDefinition
from server.content.recipes import RecipeDefinition


def _asset_kind(world_id: str, source: str) -> str:
    return source if source != world_id else f"world/{world_id}/cards"


def _image_url(world_id: str, definition: CardDefinition) -> str:
    return f"/assets/{_asset_kind(world_id, definition.source)}/{definition.image_name}"


def _scope(world_id: str, definition: CardDefinition) -> str:
    return "world" if definition.source == world_id else "base"


class CardDatabaseService:
    """Build the read-only Card Database catalog payload."""

    def __init__(
        self,
        catalog: CardCatalog,
        recipes: dict[str, RecipeDefinition],
        world_id: str,
        world_path: Path,
    ) -> None:
        self._catalog = catalog
        self._recipes = recipes
        self._world_id = world_id
        self._world_path = world_path

    def payload(self) -> dict[str, object]:
        """Return the complete catalog with packs, recipes, and reference notes."""

        packs_by_card: dict[str, list[str]] = {card_id: [] for card_id in self._catalog.cards}
        for pack in self._catalog.packs.values():
            for card_id in pack.cards:
                packs_by_card.setdefault(card_id, []).append(pack.id)
        recipes_by_card: dict[str, list[str]] = {card_id: [] for card_id in self._catalog.cards}
        for recipe in self._recipes.values():
            referenced = {ingredient.card_id for ingredient in recipe.ingredients}
            referenced.update(ingredient.card_id for ingredient in recipe.output)
            for card_id in referenced:
                recipes_by_card.setdefault(card_id, []).append(recipe.id)

        cards = [
            self._serialize_card(definition, packs_by_card, recipes_by_card)
            for definition in sorted(self._catalog.cards.values(), key=lambda item: item.id)
        ]
        packs = [
            {
                "id": pack.id,
                "label": pack.label,
                "description": pack.description,
                "price": pack.price,
                "size": pack.size,
                "source": pack.source,
                "back_image_url": f"/assets/{_asset_kind(self._world_id, pack.source)}/{pack.back_image_name}",
                "cards": list(pack.cards),
            }
            for pack in sorted(self._catalog.packs.values(), key=lambda item: item.id)
        ]
        recipes = [
            {
                "id": recipe.id,
                "label": recipe.label,
                "description": recipe.description,
                "energy_cost": recipe.energy_cost,
                "ingredients": [
                    {"card_id": item.card_id, "quantity": item.quantity}
                    for item in recipe.ingredients
                ],
                "output": [
                    {"card_id": item.card_id, "quantity": item.quantity}
                    for item in recipe.output
                ],
            }
            for recipe in sorted(self._recipes.values(), key=lambda item: item.id)
        ]
        return {
            "world_id": self._world_id,
            "cards": cards,
            "packs": packs,
            "recipes": recipes,
            "errors": self._reference_errors(packs_by_card, recipes_by_card),
        }

    def _serialize_card(
        self,
        definition: CardDefinition,
        packs_by_card: dict[str, list[str]],
        recipes_by_card: dict[str, list[str]],
    ) -> dict[str, object]:
        return {
            "id": definition.id,
            "label": definition.label,
            "description": definition.description,
            "image_url": _image_url(self._world_id, definition),
            "scope": _scope(self._world_id, definition),
            "source": definition.source,
            "type": definition.type,
            "rarity": definition.rarity,
            "collectible": definition.collectible,
            "decorative": definition.decorative,
            "stack_limit": definition.stack_limit,
            "one_use": definition.one_use,
            "passive": definition.passive,
            "energy_cost": definition.energy_cost,
            "bonuses": definition.bonuses,
            "effect": definition.effect,
            "amount": definition.amount,
            "duration": definition.duration,
            "target": definition.target,
            "category": definition.category,
            "rank": definition.rank,
            "quest": definition.quest,
            "packs": sorted(packs_by_card.get(definition.id, [])),
            "recipes": sorted(recipes_by_card.get(definition.id, [])),
        }

    def _reference_errors(
        self,
        packs_by_card: dict[str, list[str]],
        recipes_by_card: dict[str, list[str]],
    ) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        for definition in self._catalog.cards.values():
            if definition.id in CORE_CARD_IDS or definition.type == "core":
                continue
            if not packs_by_card.get(definition.id):
                errors.append(
                    {
                        "scope": "card",
                        "id": definition.id,
                        "message": "Not included in any card pack.",
                    }
                )
            if not (self._world_path / "cards" / definition.image_name).is_file() and definition.source == self._world_id:
                errors.append(
                    {
                        "scope": "card",
                        "id": definition.id,
                        "message": f"Missing artwork '{definition.image_name}'.",
                    }
                )
        for recipe in self._recipes.values():
            for ingredient in (*recipe.ingredients, *recipe.output):
                if ingredient.card_id not in self._catalog.cards:
                    errors.append(
                        {
                            "scope": "recipe",
                            "id": recipe.id,
                            "message": f"References unknown card '{ingredient.card_id}'.",
                        }
                    )
        return errors
