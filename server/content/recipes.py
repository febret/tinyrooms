"""Strict crafting recipe definition loader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.content.common import (
    LOGGER,
    ContentError,
    load_yaml_file,
    require_mapping,
    warn_unknown_card,
)


@dataclass(frozen=True, slots=True)
class Ingredient:
    """One required or produced card with a positive quantity."""

    card_id: str
    quantity: int = 1


@dataclass(frozen=True, slots=True)
class RecipeDefinition:
    """A validated crafting recipe."""

    id: str
    label: str
    description: str
    ingredients: tuple[Ingredient, ...]
    output: tuple[Ingredient, ...]
    energy_cost: int = 0
    # Station tags bind a recipe to any crafting prop carrying the same tag.
    station: str | None = None
    # Cardset recipes are learned from recipe books; world recipes are known.
    source: str = ""


def _load_ingredients(raw_value: Any, recipe_id: str, field: str, card_ids: set[str]) -> tuple[Ingredient, ...]:
    if isinstance(raw_value, dict):
        entries = list(raw_value.items())
    elif isinstance(raw_value, list):
        entries = []
        for entry in raw_value:
            if not isinstance(entry, dict):
                raise ContentError(f"Recipe '{recipe_id}' {field} entries must be mappings.")
            entries.extend(entry.items())
    else:
        raise ContentError(f"Recipe '{recipe_id}' must define a {field} mapping.")
    ingredients: list[Ingredient] = []
    for card_id, quantity in entries:
        if not isinstance(card_id, str):
            raise ContentError(f"Recipe '{recipe_id}' {field} references unknown card '{card_id}'.")
        if card_id not in card_ids:
            warn_unknown_card(f"Recipe '{recipe_id}' {field}", card_id)
            continue
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ContentError(f"Recipe '{recipe_id}' {field} for '{card_id}' must be a positive integer.")
        ingredients.append(Ingredient(card_id=card_id, quantity=int(quantity)))
    return tuple(ingredients)


def load_recipes_file(
    recipes_file: Path,
    card_ids: set[str],
    *,
    source: str = "",
) -> dict[str, RecipeDefinition]:
    """Load and validate one recipe file."""

    if not recipes_file.is_file():
        return {}
    payload = require_mapping(load_yaml_file(recipes_file), recipes_file)
    recipes: dict[str, RecipeDefinition] = {}
    for recipe_id, raw_recipe in payload.items():
        if not isinstance(recipe_id, str) or not isinstance(raw_recipe, dict):
            raise ContentError(f"{recipes_file} contains an invalid recipe entry.")
        if recipe_id in recipes:
            raise ContentError(f"{recipes_file} defines duplicate recipe '{recipe_id}'.")
        ingredients = _load_ingredients(raw_recipe.get("ingredients"), recipe_id, "ingredients", card_ids)
        if not ingredients:
            LOGGER.warning("Recipe '%s' has no resolvable ingredients; skipping it.", recipe_id)
            continue
        output = _load_ingredients(raw_recipe.get("output"), recipe_id, "output", card_ids)
        if not output:
            LOGGER.warning("Recipe '%s' has no resolvable output; skipping it.", recipe_id)
            continue
        raw_cost = raw_recipe.get("energy_cost", 0)
        if isinstance(raw_cost, bool) or not isinstance(raw_cost, (int, float)) or float(raw_cost) < 0:
            raise ContentError(f"Recipe '{recipe_id}' energy_cost must be a non-negative number.")
        raw_station = raw_recipe.get("station", raw_recipe.get("tag"))
        station = str(raw_station).strip().lower() if raw_station is not None else None
        if raw_station is not None and not station:
            raise ContentError(f"Recipe '{recipe_id}' station must be a non-empty string.")
        recipes[recipe_id] = RecipeDefinition(
            id=recipe_id,
            label=str(raw_recipe.get("label", "")).strip() or recipe_id,
            description=str(raw_recipe.get("description", "")).strip(),
            ingredients=ingredients,
            output=output,
            energy_cost=int(raw_cost),
            station=station,
            source=source,
        )
    return recipes


def load_recipes(
    world_path: Path,
    card_ids: set[str],
    *,
    source: str | None = None,
) -> dict[str, RecipeDefinition]:
    """Load and validate ``recipes.yaml`` beside a world definition."""

    return load_recipes_file(
        world_path / "recipes.yaml",
        card_ids,
        source=source if source is not None else world_path.name,
    )
