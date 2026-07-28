"""Shared validation and file handling for image-backed asset sets."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any, Generic, Protocol, TypeVar

import yaml


IMAGE_EXTENSIONS = (".png", ".gif", ".webp")
YAML_EXTENSIONS = (".yaml", ".yml")


class SetRecord(Protocol):
    scope: str
    filename: str


RecordT = TypeVar("RecordT", bound=SetRecord)


def validate_positive_int(value: Any, field_name: str, errors: list[str], default: int = 32) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        errors.append(f"{field_name} must be a positive integer")
        return default
    if normalized <= 0:
        errors.append(f"{field_name} must be > 0")
        return default
    return normalized


def normalize_background_color(value: Any, errors: list[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append("background_color must be a string")
        return None
    normalized = value.strip()
    return normalized or None


def normalize_tags(value: Any, field_name: str, errors: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{field_name} must be a list of strings")
        return []

    tags: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(value):
        if not isinstance(value, str):
            errors.append(f"{field_name}[{index}] must be a string")
            continue
        tag = value.strip().lower()
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tags


def discover_asset_set_files(root: Path) -> list[tuple[str, Path | None, Path | None]]:
    if not root.exists():
        return []

    stems = {
        item.stem
        for item in root.iterdir()
        if item.is_file() and item.suffix.lower() in {*IMAGE_EXTENSIONS, *YAML_EXTENSIONS}
    }
    discovered = []
    for stem in sorted(stems):
        image_path = next(
            (candidate for ext in IMAGE_EXTENSIONS if (candidate := root / f"{stem}{ext}").exists()),
            None,
        )
        yaml_path = next(
            (candidate for ext in YAML_EXTENSIONS if (candidate := root / f"{stem}{ext}").exists()),
            None,
        )
        discovered.append((stem, image_path, yaml_path))
    return discovered


def sorted_set_records(records: list[RecordT]) -> list[RecordT]:
    return sorted(records, key=lambda record: (record.filename, 0 if record.scope == "world" else 1, record.scope))


def lookup_set_record(
    index: dict[tuple[str, str], RecordT],
    filename: str,
    scope_hint: str | None = None,
) -> RecordT | None:
    if scope_hint in {"world", "server"}:
        return index.get((scope_hint, filename))
    return index.get(("world", filename)) or index.get(("server", filename))


class AssetSetRepository(Generic[RecordT]):
    def __init__(self, world_root_path: Path, server_root_path: Path, world_directory_name: str):
        self.world_root_path = Path(world_root_path)
        self.server_root_path = Path(server_root_path)
        self.world_assets_path = self.world_root_path / world_directory_name
        self._index: dict[tuple[str, str], RecordT] = {}

    def _load_record(
        self,
        scope: str,
        stem: str,
        image_path: Path | None,
        yaml_path: Path | None,
    ) -> RecordT:
        raise NotImplementedError

    def _scan_scope(self, scope: str, root: Path) -> None:
        for stem, image_path, yaml_path in discover_asset_set_files(root):
            self._index[(scope, stem)] = self._load_record(scope, stem, image_path, yaml_path)

    def reindex(self) -> None:
        self._index = {}
        self._scan_scope("server", self.server_root_path)
        self._scan_scope("world", self.world_assets_path)

    def list_sets(self) -> list[RecordT]:
        return sorted_set_records(list(self._index.values()))

    def get(self, scope: str, filename: str) -> RecordT | None:
        return self._index.get((scope, filename))

    def lookup(self, filename: str, scope_hint: str | None = None) -> RecordT | None:
        return lookup_set_record(self._index, filename, scope_hint)


def write_definition_document(
    yaml_path: Path,
    definition: dict[str, Any],
    *,
    temp_prefix: str,
) -> None:
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = yaml.safe_dump(definition, sort_keys=False, allow_unicode=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=str(yaml_path.parent),
        prefix=temp_prefix,
        suffix=".yaml",
    ) as handle:
        handle.write(serialized)
        temp_name = handle.name
    Path(temp_name).replace(yaml_path)
