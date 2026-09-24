"""Loads the complete content bundle for a world path.

The bundle keeps the card catalog, gameplay content, and world definition
together so the runtime and the World Editor can load an arbitrary directory
(the live world or a staged draft) with identical validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from server.config import AppConfig, KNOWN_FEATURES
from server.content.activities import load_activity_definitions
from server.content.cards import CardCatalog, load_card_catalog
from server.content.gameplay import GameplayContent, load_gameplay_content
from server.content.worlds import WorldDefinition, load_world_definition

if TYPE_CHECKING:
    from server.mods import LoadedMods


@dataclass(frozen=True, slots=True)
class WorldBundle:
    """Loaded content for one world directory."""

    catalog: CardCatalog
    content: GameplayContent
    world: WorldDefinition


def load_world_bundle(
    config: AppConfig,
    loaded_mods: LoadedMods | None,
    world_path: Path,
) -> WorldBundle:
    """Load catalog, gameplay content, and world definition for *world_path*."""

    catalog = load_card_catalog(config.cardsets_path, world_path)
    content = load_gameplay_content(config.repo_root / "data" / "core")
    core_activities = load_activity_definitions(
        config.repo_root / "data" / "core" / "activities.yaml",
        source="core",
        known_features=KNOWN_FEATURES,
    )
    mod_activities = loaded_mods.activity_definitions if loaded_mods is not None else {}
    world = load_world_definition(
        world_path,
        set(catalog.cards),
        core_activities={**core_activities, **mod_activities},
        known_features=KNOWN_FEATURES,
        propsets_root=config.propsets_path,
        mod_props=loaded_mods.mod_props() if loaded_mods is not None else (),
        enabled_mods=loaded_mods.ids if loaded_mods is not None else None,
    )
    return WorldBundle(catalog=catalog, content=content, world=world)
