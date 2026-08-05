"""Shared validation and file handling for image-backed asset sets."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any, Generic, Protocol, TypeVar

import yaml


IMAGE_EXTENSIONS = (".png", ".gif", ".webp")
YAML_EXTENSIONS = (".yaml", ".yml")
DEFAULT_ASSET_IMAGES_PATH = Path(__file__).parent.parent / "data" / "assets" / "sprites"


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


def normalize_relative_asset_name(value: Any, field_name: str, errors: list[str], default: str | None = None) -> str | None:
    """Normalize an asset path value to a relative, slash-separated string.

    Returns the original value for valid relative paths, rejects absolute paths and
    parent-directory traversal, and falls back to the provided default otherwise.
    """
    if value is None:
        return default
    if not isinstance(value, str):
        errors.append(f"{field_name} must be a string")
        return default
    normalized = value.strip().replace("\\", "/")
    if not normalized:
        return default
    path = Path(normalized)
    if path.is_absolute() or ".." in path.parts:
        errors.append(f"{field_name} must be a relative path within the asset directory")
        return default
    return normalized


def _load_yaml_mapping(path: Path) -> dict[str, Any] | None:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _resolve_image_path(image_root: Path, image_value: Any, stem: str) -> Path | None:
    candidates: list[Path] = []
    normalized = normalize_relative_asset_name(image_value, "image", [], default=None)
    if normalized:
        rel = Path(normalized)
        candidates.append(image_root / rel)
        if rel.suffix == "":
            candidates.extend(image_root / f"{normalized}{ext}" for ext in IMAGE_EXTENSIONS)
    candidates.extend(image_root / f"{stem}{ext}" for ext in IMAGE_EXTENSIONS)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def discover_asset_set_files(
    definitions_root: Path,
    image_root: Path,
    *,
    include_orphan_images: bool = True,
) -> list[tuple[str, Path | None, Path | None]]:
    discovered: list[tuple[str, Path | None, Path | None]] = []
    referenced_images: set[str] = set()

    if definitions_root.exists():
        yaml_files = sorted(
            item
            for item in definitions_root.iterdir()
            if item.is_file() and item.suffix.lower() in YAML_EXTENSIONS
        )
        for yaml_path in yaml_files:
            loaded = _load_yaml_mapping(yaml_path)
            image_value = loaded.get("image") if loaded is not None else None
            image_path = _resolve_image_path(image_root, image_value, yaml_path.stem)
            if image_path is not None:
                referenced_images.add(image_path.resolve().as_posix())
            discovered.append((yaml_path.stem, image_path, yaml_path))

    if include_orphan_images and image_root.exists():
        image_files = sorted(
            item
            for item in image_root.iterdir()
            if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS
        )
        for image_path in image_files:
            if image_path.resolve().as_posix() in referenced_images:
                continue
            discovered.append((image_path.stem, image_path, None))

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
    def __init__(
        self,
        world_root_path: Path,
        server_root_path: Path,
        world_directory_name: str,
        image_root_path: Path | None = None,
    ):
        self.world_root_path = Path(world_root_path)
        self.server_root_path = Path(server_root_path)
        self.world_assets_path = self.world_root_path / world_directory_name
        self.image_root_path = Path(image_root_path) if image_root_path else DEFAULT_ASSET_IMAGES_PATH
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
        for stem, image_path, yaml_path in discover_asset_set_files(
            root,
            self.image_root_path,
            include_orphan_images=scope == "server",
        ):
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
