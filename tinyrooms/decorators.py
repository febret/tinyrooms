from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import sprites

SUPPORTED_ANIMATIONS = {"wobble", "spin", "pulse"}

_sprite_repo_cache: dict[str, sprites.SpriteRepository] = {}


def parse_decorator_reference(reference: str) -> tuple[str, str]:
    raw = str(reference or "").strip()
    if not raw:
        raise ValueError("decorator reference is required")
    if ":" in raw:
        filename, decorator_id = raw.split(":", 1)
        filename = filename.strip()
        decorator_id = decorator_id.strip()
    else:
        filename = "main"
        decorator_id = raw
    if not filename or not decorator_id:
        raise ValueError("decorator reference must be [filename:]decorator_id")
    return filename, decorator_id


def normalize_decorator_reference(reference: str) -> str:
    filename, decorator_id = parse_decorator_reference(reference)
    return f"{filename}:{decorator_id}"


def normalize_decorator_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = raw
    else:
        return []
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        try:
            canonical = normalize_decorator_reference(value)
        except ValueError:
            continue
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


def load_decorator_definitions(paths: list[Path]) -> dict[str, dict]:
    loaded_defs: dict[str, dict] = {}
    for path in paths:
        root = Path(path)
        if not root.exists() or not root.is_dir():
            continue
        for yaml_file in sorted(root.glob("*.yaml")):
            with yaml_file.open("r", encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle) or {}
            if not isinstance(loaded, dict):
                print(f"Warning: decorator file '{yaml_file}' must contain a mapping. Skipping.")
                continue
            filename = yaml_file.stem
            for decorator_id, raw_def in loaded.items():
                if not isinstance(raw_def, dict):
                    print(f"Warning: decorator '{decorator_id}' in '{yaml_file}' must be an object. Skipping.")
                    continue
                canonical = normalize_decorator_reference(f"{filename}:{decorator_id}")
                normalized_def = dict(raw_def)
                animation = normalized_def.get("animation")
                if animation is not None:
                    animation_name = str(animation).strip()
                    if animation_name not in SUPPORTED_ANIMATIONS:
                        print(
                            f"Warning: decorator '{canonical}' animation '{animation_name}' is not supported; "
                            f"supported values are {sorted(SUPPORTED_ANIMATIONS)}. Ignoring animation."
                        )
                        normalized_def.pop("animation", None)
                    else:
                        normalized_def["animation"] = animation_name
                loaded_defs[canonical] = normalized_def
    return loaded_defs


def _get_sprite_repo(world_root_path) -> sprites.SpriteRepository:
    root = Path(world_root_path).resolve()
    cache_key = str(root)
    repo = _sprite_repo_cache.get(cache_key)
    if repo is None:
        repo = sprites.SpriteRepository(root)
        repo.reindex()
        _sprite_repo_cache[cache_key] = repo
    return repo


def resolve_decorator_payloads(
    decorator_refs: list[str],
    decorator_defs: dict[str, dict],
    world_root_path,
    sprite_repo: sprites.SpriteRepository | None = None,
) -> list[dict]:
    if not decorator_refs:
        return []
    payloads: list[dict] = []
    for raw_ref in decorator_refs:
        try:
            canonical_ref = normalize_decorator_reference(raw_ref)
            filename, decorator_id = parse_decorator_reference(canonical_ref)
        except ValueError:
            continue
        definition = decorator_defs.get(canonical_ref)
        if definition is None:
            continue
        payload = {"id": canonical_ref, "filename": filename, "decorator_id": decorator_id, **definition}
        sprite_ref = definition.get("sprite")
        if isinstance(sprite_ref, str) and sprite_ref.strip():
            from . import icons

            try:
                resolved_assets = icons.build_display_assets(
                    {"img": sprite_ref, "icon": sprite_ref, "sprite": sprite_ref},
                    world_root_path,
                    sprite_repo=sprite_repo or _get_sprite_repo(world_root_path),
                )
                payload["sprite_display"] = resolved_assets
            except (ValueError, sprites.SpriteValidationError) as err:
                payload["sprite_error"] = str(err)
        payloads.append(payload)
    return payloads
