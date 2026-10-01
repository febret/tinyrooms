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
from server.content.cards import CardCatalog, cutscene_card_references, load_card_catalog
from server.content.cutscenes import load_cutscene_definitions
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

    extra_cardsets = (config.shared_cardsets_path,) if config.shared_cardsets_path is not None else ()
    catalog = load_card_catalog(config.cardsets_path, world_path, extra_cardsets_roots=extra_cardsets)
    content = load_gameplay_content(config.repo_root / "data" / "core")
    core_activities = load_activity_definitions(
        config.repo_root / "data" / "core" / "activities.yaml",
        source="core",
        known_features=KNOWN_FEATURES,
    )
    mod_activities = loaded_mods.activity_definitions if loaded_mods is not None else {}
    core_cutscenes = load_cutscene_definitions(
        config.repo_root / "data" / "core" / "cutscenes.yaml",
        source="core",
        script_roots=(config.repo_root / "data" / "cutscenes",),
        known_features=KNOWN_FEATURES,
    )
    mod_cutscenes = loaded_mods.cutscene_definitions if loaded_mods is not None else {}
    mod_cutscene_roots = loaded_mods.cutscene_roots() if loaded_mods is not None else ()
    world = load_world_definition(
        world_path,
        set(catalog.cards),
        core_activities={**core_activities, **mod_activities},
        core_cutscenes={**core_cutscenes, **mod_cutscenes},
        cutscene_cards=cutscene_card_references(catalog),
        cutscene_roots=mod_cutscene_roots,
        known_features=KNOWN_FEATURES,
        propsets_root=config.propsets_path,
        shared_propsets_root=config.shared_propsets_path,
        mod_props=loaded_mods.mod_props() if loaded_mods is not None else (),
        enabled_mods=loaded_mods.ids if loaded_mods is not None else None,
        fx_root=config.fx_path,
    )
    return WorldBundle(catalog=catalog, content=content, world=world)
