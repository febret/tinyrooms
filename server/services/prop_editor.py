"""Admin Prop Editor service: raw prop and effect definition editing.

The Prop Editor edits the YAML files that back the props currently loaded into
the server (world, mod, and shared propset ``props.yaml`` files) plus the
``data/fx/*.yaml`` effect layer stacks they reference. Every write is validated
with the same loaders the game uses, backed up, and applied atomically. The
running world is only rebuilt when the caller forces a reload.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import os
import re
import shutil
from typing import Any

from server.config import AppConfig, ConfigError, ensure_contained
from server.content.common import ContentError, load_yaml_file, require_mapping
from server.content.fx import (
    LAYER_TYPES,
    PARTICLE_ANCHORS,
    PARTICLE_PRESETS,
    TEXTURE_SUFFIXES,
    TRANSFORM_MOTIONS,
    EffectDefinition,
    load_effect_catalog,
    load_effect_definition,
)
from server.content.staging import dump_yaml
from server.content.worlds import (
    PROPS_CONFIG_KEY,
    PropDefinition,
    WorldDefinition,
    load_prop_definition,
    load_props_scale_adjust,
    prop_model_url,
)
from server.security import utc_now
from server.services.audit import AuditService


MODEL_SUFFIXES = frozenset({".glb", ".gltf", ".obj", ".fbx"})
SOURCE_KINDS = frozenset({"world", "mod", "propset"})
_EFFECT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
BACKUP_ROOT = "prop-editor"


class PropEditorError(ValueError):
    """Base class for Prop Editor failures."""


class PropEditorNotFound(PropEditorError):
    """Raised when a prop, effect, or source cannot be found."""


class PropEditorValidationError(PropEditorError):
    """Raised when a candidate definition fails loader validation."""


def _normalize_config(raw_config: Any, path: Path) -> float:
    try:
        return load_props_scale_adjust(raw_config, path)
    except ContentError as exc:
        raise PropEditorValidationError(str(exc)) from exc


class PropEditorService:
    """Read and write prop and effect definitions for the active world."""

    def __init__(
        self,
        config: AppConfig,
        loaded_mods: object | None,
        audit: AuditService,
    ) -> None:
        self._config = config
        self._loaded_mods = loaded_mods
        self._audit = audit

    # -- catalog ---------------------------------------------------------

    def catalog(self, world: WorldDefinition) -> dict[str, object]:
        """Return every loaded prop plus effect, source, and enum metadata."""

        props = [self._prop_summary(world, definition) for definition in world.props.values()]
        props.sort(key=lambda item: str(item["id"]))
        tags = sorted({tag for definition in world.props.values() for tag in definition.tags})
        sources = [
            self._source_descriptor(world, kind, source)
            for kind, source in sorted(
                {(definition.source_kind, definition.source) for definition in world.props.values()}
            )
        ]
        return {
            "world_id": world.id,
            "props": props,
            "tags": tags,
            "sources": sources,
            "effects": self.effects_catalog(),
            "enums": self.enums(),
        }

    def _prop_summary(self, world: WorldDefinition, definition: PropDefinition) -> dict[str, object]:
        return {
            "id": definition.id,
            "label": definition.label,
            "description": definition.description,
            "source": definition.source,
            "source_kind": definition.source_kind,
            "model": definition.model_name,
            "model_url": prop_model_url(world.id, definition),
            "scale": definition.scale,
            "decorative": definition.decorative,
            "editable": definition.editable,
            "animation": definition.animation,
            "tags": list(definition.tags),
            "price": definition.price,
            "locked": definition.locked,
            "hidden": definition.hidden,
            "editor_scale_min": definition.editor_scale_min,
            "editor_scale_max": definition.editor_scale_max,
            "effects": {name: list(ids) for name, ids in definition.effect_sets.items()},
            "active_effect": definition.active_effect,
        }

    def effects_catalog(self) -> list[dict[str, object]]:
        catalog = load_effect_catalog(self._config.fx_path)
        effects = [definition.serialize() for definition in catalog.values()]
        effects.sort(key=lambda item: str(item["id"]))
        return effects

    def enums(self) -> dict[str, object]:
        return {
            "layer_types": sorted(LAYER_TYPES),
            "transform_motions": sorted(TRANSFORM_MOTIONS),
            "particle_presets": sorted(PARTICLE_PRESETS),
            "particle_anchors": sorted(PARTICLE_ANCHORS),
            "model_suffixes": sorted(MODEL_SUFFIXES),
            "textures": self._list_textures(),
        }

    # -- source resolution ----------------------------------------------

    def _resolve_source(self, world: WorldDefinition, kind: object, source: object) -> tuple[Path, str, str]:
        """Return ``(props_dir, source_kind, source)`` for a trusted source."""

        normalized_kind = str(kind or "").strip()
        normalized_source = str(source or "").strip()
        if normalized_kind not in SOURCE_KINDS:
            raise PropEditorNotFound(f"Unknown prop source kind '{normalized_kind}'.")
        if normalized_kind == "world":
            if normalized_source != world.id:
                raise PropEditorNotFound(f"Unknown world source '{normalized_source}'.")
            return world.root_path / "props", "world", world.id
        if normalized_kind == "mod":
            for mod in getattr(self._loaded_mods, "definitions", ()) or ():
                if mod.id == normalized_source:
                    return mod.props_path, "mod", mod.id
            raise PropEditorNotFound(f"Unknown mod '{normalized_source}'.")
        try:
            directory = ensure_contained(
                self._config.propsets_path / normalized_source,
                self._config.propsets_path,
                "propset",
            )
        except ConfigError as exc:
            raise PropEditorNotFound(f"Unknown propset '{normalized_source}'.") from exc
        if not directory.is_dir():
            raise PropEditorNotFound(f"Unknown propset '{normalized_source}'.")
        return directory, "propset", normalized_source

    def _source_descriptor(self, world: WorldDefinition, kind: str, source: str) -> dict[str, object]:
        directory, resolved_kind, resolved_source = self._resolve_source(world, kind, source)
        yaml_path = directory / "props.yaml"
        raw = self._read_props(yaml_path)
        return {
            "kind": resolved_kind,
            "source": resolved_source,
            "file": f"{resolved_kind}/{resolved_source}/props.yaml",
            "models": self._list_models(directory),
            "scale_adjust": _normalize_config(raw.get(PROPS_CONFIG_KEY), yaml_path),
        }

    @staticmethod
    def _read_props(yaml_path: Path) -> dict[str, Any]:
        if not yaml_path.is_file():
            raise PropEditorNotFound(f"Missing props.yaml: {yaml_path}")
        return require_mapping(load_yaml_file(yaml_path), yaml_path)

    @staticmethod
    def _list_models(directory: Path) -> list[str]:
        if not directory.is_dir():
            return []
        return sorted(
            entry.name
            for entry in directory.iterdir()
            if entry.is_file() and entry.suffix.lower() in MODEL_SUFFIXES
        )

    def _list_textures(self) -> list[str]:
        fx_root = self._config.fx_path
        if not fx_root.is_dir():
            return []
        return sorted(
            entry.name
            for entry in fx_root.iterdir()
            if entry.is_file() and entry.suffix.lower() in TEXTURE_SUFFIXES
        )

    # -- prop read/write -------------------------------------------------

    def load_prop(self, world: WorldDefinition, kind: object, source: object, prop_id: object) -> dict[str, object]:
        """Return the raw YAML mapping for one prop plus its file context."""

        normalized_id = str(prop_id or "").strip()
        if not normalized_id or normalized_id == PROPS_CONFIG_KEY:
            raise PropEditorNotFound("Unknown prop.")
        directory, resolved_kind, resolved_source = self._resolve_source(world, kind, source)
        yaml_path = directory / "props.yaml"
        raw = self._read_props(yaml_path)
        raw_prop = raw.get(normalized_id)
        if not isinstance(raw_prop, dict):
            raise PropEditorNotFound(f"Unknown prop '{normalized_id}'.")
        scale_adjust = _normalize_config(raw.get(PROPS_CONFIG_KEY), yaml_path)
        definition = self._validate_prop(normalized_id, raw_prop, yaml_path, resolved_source, resolved_kind, scale_adjust)
        return {
            "prop": {
                "id": normalized_id,
                "kind": resolved_kind,
                "source": resolved_source,
                "raw": raw_prop,
                "model_url": prop_model_url(world.id, definition),
                "scale": definition.scale,
            },
            "file": {
                "kind": resolved_kind,
                "source": resolved_source,
                "path": f"{resolved_kind}/{resolved_source}/props.yaml",
                "models": self._list_models(directory),
                "scale_adjust": scale_adjust,
            },
        }

    def save_prop(
        self,
        world: WorldDefinition,
        kind: object,
        source: object,
        prop_id: object,
        raw_prop: object,
        *,
        scale_adjust: object = None,
        actor_id: str,
    ) -> dict[str, object]:
        """Validate, back up, and atomically write one prop back to its file."""

        normalized_id = str(prop_id or "").strip()
        if not normalized_id or normalized_id == PROPS_CONFIG_KEY:
            raise PropEditorNotFound("Unknown prop.")
        if not isinstance(raw_prop, Mapping):
            raise PropEditorValidationError("Prop definition must be a mapping.")
        directory, resolved_kind, resolved_source = self._resolve_source(world, kind, source)
        yaml_path = directory / "props.yaml"
        raw = self._read_props(yaml_path)
        if not isinstance(raw.get(normalized_id), dict):
            raise PropEditorNotFound(f"Unknown prop '{normalized_id}'.")

        candidate = dict(raw_prop)
        candidate.pop("id", None)
        next_adjust = self._resolve_scale_adjust(raw, yaml_path, scale_adjust)
        definition = self._validate_prop(
            normalized_id,
            candidate,
            yaml_path,
            resolved_source,
            resolved_kind,
            next_adjust,
        )

        updated = dict(raw)
        updated[normalized_id] = candidate
        if scale_adjust is not None:
            config = updated.get(PROPS_CONFIG_KEY)
            config = dict(config) if isinstance(config, dict) else {}
            config["scale_adjust"] = next_adjust
            if PROPS_CONFIG_KEY in updated:
                updated[PROPS_CONFIG_KEY] = config
            else:
                updated = {PROPS_CONFIG_KEY: config, **updated}

        backup = self._backup(yaml_path, resolved_kind, resolved_source)
        self._atomic_write_yaml(yaml_path, updated)
        self._audit.safe_record(
            actor_id,
            "prop.save",
            f"{resolved_kind}/{resolved_source}/{normalized_id}",
            "ok",
            {
                "kind": resolved_kind,
                "source": resolved_source,
                "prop_id": normalized_id,
                "backup": backup.name if backup else "",
            },
        )
        return {
            "prop": {
                "id": normalized_id,
                "kind": resolved_kind,
                "source": resolved_source,
                "raw": candidate,
                "model_url": prop_model_url(world.id, definition),
                "scale": definition.scale,
            },
            "file": {
                "kind": resolved_kind,
                "source": resolved_source,
                "path": f"{resolved_kind}/{resolved_source}/props.yaml",
                "models": self._list_models(directory),
                "scale_adjust": next_adjust,
            },
        }

    def _resolve_scale_adjust(self, raw: Mapping[str, Any], yaml_path: Path, override: object) -> float:
        if override is None:
            return _normalize_config(raw.get(PROPS_CONFIG_KEY), yaml_path)
        return _normalize_config({"scale_adjust": override}, yaml_path)

    def _validate_prop(
        self,
        prop_id: str,
        raw_prop: Mapping[str, Any],
        yaml_path: Path,
        source: str,
        source_kind: str,
        scale_adjust: float,
    ) -> PropDefinition:
        try:
            definition = load_prop_definition(
                prop_id,
                raw_prop,
                props_file=yaml_path,
                source=source,
                source_kind=source_kind,
                scale_adjust=scale_adjust,
            )
        except ContentError as exc:
            raise PropEditorValidationError(str(exc)) from exc
        effects = load_effect_catalog(self._config.fx_path)
        for set_name, effect_ids in definition.effect_sets.items():
            for effect_id in effect_ids:
                if effect_id not in effects:
                    raise PropEditorValidationError(
                        f"Prop '{prop_id}' effect set '{set_name}' references unknown effect '{effect_id}'."
                    )
        return definition

    # -- effect read/write ----------------------------------------------

    def load_effect(self, effect_id: object) -> dict[str, object]:
        """Return the raw YAML mapping for one effect plus file context."""

        normalized_id = self._normalize_effect_id(effect_id)
        fx_path = self._effect_path(normalized_id)
        if not fx_path.is_file():
            raise PropEditorNotFound(f"Unknown effect '{normalized_id}'.")
        raw = require_mapping(load_yaml_file(fx_path), fx_path)
        definition = self._validate_effect(fx_path, raw)
        return {
            "effect": {"id": normalized_id, "raw": raw, "serialized": definition.serialize()},
            "enums": self.enums(),
        }

    def save_effect(self, effect_id: object, raw_effect: object, *, actor_id: str) -> dict[str, object]:
        """Validate, back up, and atomically write one effect definition."""

        normalized_id = self._normalize_effect_id(effect_id)
        if not isinstance(raw_effect, Mapping):
            raise PropEditorValidationError("Effect definition must be a mapping.")
        fx_path = self._effect_path(normalized_id)
        if not fx_path.is_file():
            raise PropEditorNotFound(f"Unknown effect '{normalized_id}'.")
        candidate = dict(raw_effect)
        candidate["id"] = normalized_id
        definition = self._validate_effect(fx_path, candidate)
        backup = self._backup(fx_path, "fx", normalized_id)
        self._atomic_write_yaml(fx_path, candidate)
        self._audit.safe_record(
            actor_id,
            "effect.save",
            normalized_id,
            "ok",
            {"effect_id": normalized_id, "backup": backup.name if backup else ""},
        )
        return {
            "effect": {"id": normalized_id, "raw": candidate, "serialized": definition.serialize()},
            "enums": self.enums(),
        }

    def _normalize_effect_id(self, effect_id: object) -> str:
        normalized_id = str(effect_id or "").strip()
        if not _EFFECT_ID.match(normalized_id):
            raise PropEditorNotFound(f"Unknown effect '{normalized_id}'.")
        return normalized_id

    def _effect_path(self, effect_id: str) -> Path:
        try:
            return ensure_contained(
                self._config.fx_path / f"{effect_id}.yaml",
                self._config.fx_path,
                "effect",
            )
        except ConfigError as exc:
            raise PropEditorNotFound(f"Unknown effect '{effect_id}'.") from exc

    @staticmethod
    def _validate_effect(fx_path: Path, raw_effect: Mapping[str, Any]) -> EffectDefinition:
        try:
            return load_effect_definition(fx_path, raw_effect)
        except ContentError as exc:
            raise PropEditorValidationError(str(exc)) from exc

    # -- filesystem ------------------------------------------------------

    def _backup(self, path: Path, kind: str, source: str) -> Path | None:
        if not path.is_file():
            return None
        stamp = utc_now().strftime("%Y%m%dT%H%M%S%f")
        target_dir = self._config.revisions_path / BACKUP_ROOT / f"{kind}-{source}" / stamp
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / path.name
        shutil.copy2(path, target)
        return target

    @staticmethod
    def _atomic_write_yaml(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(dump_yaml(payload), encoding="utf-8")
        os.replace(temporary, path)
