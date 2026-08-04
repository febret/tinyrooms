"""Object crafting domain: recipe parsing, validation, context resolution, and execution."""
from __future__ import annotations

import random
from typing import Any

DEFAULT_STACK_SIZE = 99


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_craftable_mode(raw: Any) -> str | list[str] | None:
    """Parse ``craftable_mode`` field value.

    Returns ``'ALWAYS'``, a non-empty list of thing-id strings, or ``None``
    when the value is absent or empty.
    """
    if raw is None:
        return None
    val = str(raw).strip()
    if not val:
        return None
    if val.upper() == "ALWAYS":
        return "ALWAYS"
    parts = [p.strip() for p in val.split(",") if p.strip()]
    return parts if parts else None


def parse_craftable_inputs(raw: Any) -> list[tuple[str, int]]:
    """Parse ``craftable_inputs`` field value.

    Returns a list of ``(thing_id, count)`` tuples.  Duplicate ``thing_id``
    entries are merged by summing counts.
    """
    if raw is None:
        return []
    merged: dict[str, int] = {}
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            thing_id, _, count_str = part.partition(":")
            thing_id = thing_id.strip()
            try:
                count = int(count_str.strip())
            except (TypeError, ValueError):
                count = 1
        else:
            thing_id = part
            count = 1
        if thing_id:
            merged[thing_id] = merged.get(thing_id, 0) + count
    return list(merged.items())


# ---------------------------------------------------------------------------
# Stackable-size support
# ---------------------------------------------------------------------------

def get_stackable_size(thing_def: dict, server_default: int = DEFAULT_STACK_SIZE) -> int | None:
    """Return the maximum stack size for a thing definition, or ``None`` if not stackable.

    ``stackable_size: auto`` resolves to *server_default* (default 99).
    A positive integer value is used as-is.
    Missing or null ``stackable_size`` means the thing is not stackable.
    """
    raw = thing_def.get("stackable_size")
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip().lower() == "auto":
        return server_default
    try:
        val = int(raw)
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Recipe accessors
# ---------------------------------------------------------------------------

def get_craftable_level(thing_def: dict) -> int:
    """Return minimum user level required to craft this thing (default 0)."""
    raw = thing_def.get("craftable_level")
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def get_craftable_inputs(thing_def: dict) -> list[tuple[str, int]]:
    """Return parsed ``(thing_id, count)`` inputs for a thing definition."""
    return parse_craftable_inputs(thing_def.get("craftable_inputs"))


def get_output_count(thing_def: dict) -> int:
    """Return crafting output count for a thing definition (default 1)."""
    raw = thing_def.get("craftable_stack_size")
    if raw is None:
        return 1
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_recipe(thing_id: str, thing_def: dict, thing_defs: dict) -> list[str]:
    """Validate all crafting metadata for a thing definition.

    Returns a list of human-readable error strings; an empty list means the
    recipe is valid and craftable.
    """
    errors: list[str] = []

    raw_mode = thing_def.get("craftable_mode")
    if raw_mode is None:
        errors.append(f"'{thing_id}' has no craftable_mode — not craftable")
        return errors

    mode = parse_craftable_mode(raw_mode)
    if mode is None:
        errors.append(f"'{thing_id}' has an empty craftable_mode")

    raw_level = thing_def.get("craftable_level")
    if raw_level is not None:
        try:
            level = int(raw_level)
            if not (0 <= level <= 10):
                errors.append(f"craftable_level must be 0–10, got {level}")
        except (TypeError, ValueError):
            errors.append(f"craftable_level must be an integer, got '{raw_level}'")

    raw_inputs = thing_def.get("craftable_inputs")
    if raw_inputs is not None:
        for inp_id, count in parse_craftable_inputs(raw_inputs):
            if count <= 0:
                errors.append(f"input count for '{inp_id}' must be positive, got {count}")
            if inp_id not in thing_defs:
                errors.append(f"input thing '{inp_id}' not found in thing definitions")

    raw_stack = thing_def.get("craftable_stack_size")
    if raw_stack is not None:
        if get_stackable_size(thing_def) is None:
            errors.append(
                f"craftable_stack_size is set on '{thing_id}' but the thing is not stackable "
                f"(add 'stackable_size' to the thing definition)"
            )
        try:
            cstack = int(raw_stack)
            if cstack <= 0:
                errors.append(f"craftable_stack_size must be positive, got {cstack}")
        except (TypeError, ValueError):
            errors.append(f"craftable_stack_size must be an integer, got '{raw_stack}'")

    return errors


def is_recipe_valid(thing_id: str, thing_def: dict, thing_defs: dict) -> bool:
    """Return True when all recipe metadata is valid."""
    return len(validate_recipe(thing_id, thing_def, thing_defs)) == 0


# ---------------------------------------------------------------------------
# Context / availability
# ---------------------------------------------------------------------------

def recipe_available_in_context(thing_def: dict, station_thing_id: str | None) -> bool:
    """Return True when the recipe is available for the current crafting context.

    *station_thing_id* is the ``thing_id`` of the active crafting-station object,
    or ``None`` when the user has no active station.
    """
    mode = parse_craftable_mode(thing_def.get("craftable_mode"))
    if mode is None:
        return False
    if mode == "ALWAYS":
        return True
    # mode is a list of allowed station thing_ids
    return bool(station_thing_id and station_thing_id in mode)


def get_recipes_for_context(
    thing_defs: dict,
    station_thing_id: str | None,
) -> list[tuple[str, dict]]:
    """Return all valid, context-available recipes sorted by ``thing_id``."""
    result = []
    for tid, tdef in thing_defs.items():
        if recipe_available_in_context(tdef, station_thing_id):
            result.append((tid, tdef))
    return sorted(result, key=lambda x: x[0])


# ---------------------------------------------------------------------------
# Craft availability check
# ---------------------------------------------------------------------------

def count_owned_by_thing_id(inventory: dict, thing_id: str) -> int:
    """Count inventory objects with the given ``thing_id``."""
    return sum(1 for obj in inventory.values() if getattr(obj, "thing_id", None) == thing_id)


def check_craft_availability(
    thing_id: str,
    thing_def: dict,
    thing_defs: dict,
    user_level: int,
    station_thing_id: str | None,
    inventory: dict,
) -> list[str]:
    """Return a list of error strings blocking a craft attempt (empty = can craft).

    Validates in spec order:
    1. recipe metadata valid
    2. user level check
    3. mode/context availability
    4. inventory input availability
    """
    errors = validate_recipe(thing_id, thing_def, thing_defs)
    if errors:
        return errors

    required_level = get_craftable_level(thing_def)
    if user_level < required_level:
        return [f"requires level {required_level} (you are level {user_level})"]

    if not recipe_available_in_context(thing_def, station_thing_id):
        if station_thing_id:
            return ["recipe not available at this crafting station"]
        return ["recipe requires a crafting station — :use an appropriate object first"]

    shortfalls: list[str] = []
    for inp_id, required_count in get_craftable_inputs(thing_def):
        owned = count_owned_by_thing_id(inventory, inp_id)
        if owned < required_count:
            inp_label = thing_defs.get(inp_id, {}).get("label", inp_id)
            shortfalls.append(f"need {required_count - owned} more {inp_label}")
    return shortfalls


# ---------------------------------------------------------------------------
# Craft execution
# ---------------------------------------------------------------------------

def consume_inputs(
    thing_def: dict,
    inventory: dict,
    world_objs: dict,
) -> None:
    """Remove required input objects from *inventory* (and *world_objs*) in-place."""
    for inp_id, required_count in get_craftable_inputs(thing_def):
        remaining = required_count
        for obj_id in list(inventory.keys()):
            if remaining <= 0:
                break
            if getattr(inventory[obj_id], "thing_id", None) == inp_id:
                del inventory[obj_id]
                world_objs.pop(obj_id, None)
                remaining -= 1


def create_output_objects(
    thing_id: str,
    thing_def: dict,
    username: str,
    world_objs: dict,
    icon_module: Any,
    world_root_path: Any,
) -> list:
    """Create output ``Object`` instances, register them in *world_objs*, and return them."""
    from .object import Object

    output_count = get_output_count(thing_def)
    created = []
    for _ in range(output_count):
        random_hex = "".join(random.choices("0123456789abcdef", k=5))
        obj_id = f"{thing_id}-{random_hex}"
        obj = Object(obj_id, thing_id, dict(thing_def), f"@{username}", username)
        obj._display_assets = icon_module.build_display_assets(thing_def, world_root_path)
        world_objs[obj_id] = obj
        created.append(obj)
    return created


# ---------------------------------------------------------------------------
# Activity-panel content builder
# ---------------------------------------------------------------------------

def build_recipe_panel_content(
    thing_defs: dict,
    station_thing_id: str | None,
    user_level: int,
    inventory: dict,
    station_label: str | None = None,
) -> str:
    """Build the activity-panel content string for a crafting recipe list.

    Shows all context-available recipes with level info, required inputs, owned
    counts, and clickable ``[[Craft|:craft ...]]`` links.
    """
    recipes = get_recipes_for_context(thing_defs, station_thing_id)

    if not recipes:
        context_hint = f" at {station_label}" if station_label else ""
        return f"No recipes available{context_hint}."

    lines: list[str] = []
    if station_label:
        lines.append(f"**Crafting at {station_label}:**\n")
    else:
        lines.append("**Available recipes (always):**\n")

    for thing_id, thing_def in recipes:
        output_label = thing_def.get("label", thing_id)
        output_count = get_output_count(thing_def)
        required_level = get_craftable_level(thing_def)

        count_suffix = f" ×{output_count}" if output_count > 1 else ""
        level_note = (
            f" [L{required_level} required]"
            if required_level > 0
            else ""
        )
        can_craft = not check_craft_availability(
            thing_id, thing_def, thing_defs, user_level, station_thing_id, inventory
        )
        craft_link = f"[[Craft|:craft {thing_id}]]" if can_craft else "[[Craft (blocked)|:craft {thing_id}]]"

        lines.append(f"**{output_label}**{count_suffix}{level_note}  {craft_link}")

        inputs = get_craftable_inputs(thing_def)
        if inputs:
            for inp_id, required_count in inputs:
                owned = count_owned_by_thing_id(inventory, inp_id)
                inp_label = thing_defs.get(inp_id, {}).get("label", inp_id)
                have_marker = "✓" if owned >= required_count else "✗"
                lines.append(f"  {have_marker} {inp_label}: {owned}/{required_count}")
        else:
            lines.append("  (no inputs required)")
        lines.append("")

    return "\n".join(lines).rstrip()
