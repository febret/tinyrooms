"""Resolve the content bundled into one Tinyrooms deployment.

A deployment content file (``multiworld.json`` by default) names the worlds a
fleet serves. This module selects enabled worlds, follows their ``world.yaml``
requirements, and returns the exact world/mod/cardset/propset directories that
belong in the versioned package. Its content digest identifies identical
deployments even when they were built at different times.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os

from server.content.common import ContentError, load_yaml_file, require_mapping
from server.fleet_config import entry_enabled, entry_path, entry_world_id
from server.version import (
    DEPLOY_MANIFEST_FILE,
    package_filename,
    split_package_stem,
)


DEFAULT_CONTENT_FILE = "multiworld.json"
KIND_WORLD = "world"
KIND_MOD = "mod"
KIND_CARDSET = "cardset"
KIND_PROPSET = "propset"
CONTENT_KINDS = (KIND_WORLD, KIND_MOD, KIND_CARDSET, KIND_PROPSET)
CONTENT_PREFIXES = {
    KIND_WORLD: "worlds",
    KIND_MOD: "mods",
    KIND_CARDSET: "data/cardsets",
    KIND_PROPSET: "data/propsets",
}
EXCLUDED_DIRS = frozenset({"__pycache__", ".git", ".pytest_cache", "node_modules"})
EXCLUDED_SUFFIXES = (".pyc", ".sqlite", ".sqlite3", ".db")


class ContentConfigError(ValueError):
    """Raised when a deployment content file cannot be resolved."""


@dataclass(frozen=True, slots=True)
class ContentEntry:
    """One content directory and the path it occupies in a release."""

    kind: str
    id: str
    path: Path

    @property
    def arcname(self) -> str:
        """Return the release-relative directory for this entry."""

        return f"{CONTENT_PREFIXES[self.kind]}/{self.id}"


@dataclass(frozen=True, slots=True)
class ContentSelection:
    """The content directories selected for one deployment."""

    worlds: tuple[ContentEntry, ...]
    mods: tuple[ContentEntry, ...]
    cardsets: tuple[ContentEntry, ...]
    propsets: tuple[ContentEntry, ...]

    def entries(self) -> tuple[ContentEntry, ...]:
        """Return every selected entry in package order."""

        return (*self.worlds, *self.mods, *self.cardsets, *self.propsets)

    def prefixes(self) -> tuple[str, ...]:
        """Return release paths owned by this selection, not runtime files."""

        return tuple(CONTENT_PREFIXES.values())

    def manifest(self, version: str, version_hash: str) -> dict[str, object]:
        """Return the deployment manifest written into the package."""

        return {
            "version": version,
            "version_hash": version_hash,
            "worlds": [entry.id for entry in self.worlds],
            "mods": [entry.id for entry in self.mods],
            "cardsets": [entry.id for entry in self.cardsets],
            "propsets": [entry.id for entry in self.propsets],
        }


@dataclass(frozen=True, slots=True)
class _WorldRequirement:
    id: str
    directory: Path
    mods: tuple[str, ...]
    cardsets: tuple[str, ...] | None
    propsets: tuple[str, ...] | None
    shared_content: Path | None


def _path_candidates(value: str, bases: Iterable[Path]) -> list[Path]:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return [candidate]
    return [base / candidate for base in bases]


def _resolve_path(value: str, bases: Iterable[Path], label: str) -> Path:
    candidates = _path_candidates(value, bases)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    if candidates:
        return candidates[0].resolve()
    raise ContentConfigError(f"{label} has no resolvable path.")


def _resolve_default_world(world_id: str, roots: Iterable[Path]) -> Path:
    return _resolve_path(f"worlds/{world_id}", roots, f"World '{world_id}'")


def _read_config(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ContentConfigError(f"Cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ContentConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContentConfigError("The deployment content file must contain a JSON object.")
    return payload


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ContentConfigError(f"{label} must be a list.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ContentConfigError(f"{label} must contain non-empty strings.")
        if item.strip() not in result:
            result.append(item.strip())
    return tuple(result)


def _optional_string_list(value: object, label: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    return _string_list(value, label)


def _world_requirement(
    world_id: str,
    directory: Path,
    *,
    index: int,
    bases: Iterable[Path],
    shared: str | None,
) -> _WorldRequirement:
    manifest = directory / "world.yaml"
    if not manifest.is_file():
        raise ContentConfigError(f"worlds[{index}] is missing {manifest}.")
    try:
        payload = require_mapping(load_yaml_file(manifest), manifest)
    except ContentError as exc:
        raise ContentConfigError(str(exc)) from exc
    label = f"World '{directory.name}'"
    if shared is not None:
        shared_content = _resolve_path(shared, bases, f"{label} shared_content")
        if not shared_content.is_dir():
            raise ContentConfigError(f"{label} shared_content '{shared}' is not a directory.")
    else:
        shared_content = None
    cardsets = payload.get("requires_cardsets", payload.get("cardsets"))
    propsets = payload.get("requires_propsets", payload.get("propsets"))
    return _WorldRequirement(
        id=world_id,
        directory=directory,
        mods=_string_list(payload.get("requires_mods"), f"{label} requires_mods"),
        cardsets=_optional_string_list(cardsets, f"{label} requires_cardsets"),
        propsets=_optional_string_list(propsets, f"{label} requires_propsets"),
        shared_content=shared_content,
    )


def _discover(root: Path, marker: str) -> dict[str, Path]:
    found: dict[str, Path] = {}
    if not root.is_dir():
        return found
    for candidate in sorted(root.iterdir()):
        if candidate.is_dir() and (candidate / marker).is_file():
            found[candidate.name] = candidate.resolve()
    return found


def _discover_mods(root: Path) -> dict[str, tuple[Path, tuple[str, ...]]]:
    found: dict[str, tuple[Path, tuple[str, ...]]] = {}
    if not root.is_dir():
        return found
    for candidate in sorted(root.iterdir()):
        manifest = candidate / "mod.yaml"
        if not candidate.is_dir() or not manifest.is_file():
            continue
        try:
            payload = require_mapping(load_yaml_file(manifest), manifest)
        except ContentError as exc:
            raise ContentConfigError(str(exc)) from exc
        mod_id = str(payload.get("id", candidate.name)).strip() or candidate.name
        requires = _string_list(payload.get("requires"), f"Mod '{mod_id}' requires")
        found[mod_id] = (candidate.resolve(), requires)
    return found


def _all_cardsets(root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    if not root.is_dir():
        return found
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir():
            continue
        if any((candidate / name).is_file() for name in ("cards.yaml", "pack.yaml", "recipes.yaml")):
            found[candidate.name] = candidate.resolve()
    return found


def _prop_references(world: Path) -> set[str]:
    """Return prop ids placed by a world's rooms."""

    references: set[str] = set()
    rooms_file = world / "rooms" / "rooms.yaml"
    if not rooms_file.is_file():
        return references
    try:
        payload = load_yaml_file(rooms_file)
    except ContentError as exc:
        raise ContentConfigError(f"World '{world.name}' has invalid rooms: {exc}") from exc

    def visit(value: object) -> None:
        if isinstance(value, dict):
            prop_id = value.get("prop")
            if isinstance(prop_id, str) and prop_id.strip():
                references.add(prop_id.strip())
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return references


def _authored_prop_ids(world: Path) -> set[str]:
    """Return prop ids defined by the world itself (outside any propset)."""

    props_file = world / "props" / "props.yaml"
    if not props_file.is_file():
        return set()
    try:
        payload = load_yaml_file(props_file)
    except ContentError as exc:
        raise ContentConfigError(f"World '{world.name}' has invalid props: {exc}") from exc
    if not isinstance(payload, dict):
        return set()
    return {str(key) for key in payload if isinstance(key, str) and key != "CONFIG"}


def _propset_ids(root: Path) -> dict[str, set[str]]:
    """Return ``{propset_id: prop_ids}`` for one propset root."""

    result: dict[str, set[str]] = {}
    if not root.is_dir():
        return result
    for candidate in sorted(root.iterdir()):
        props_file = candidate / "props.yaml"
        if not candidate.is_dir() or not props_file.is_file():
            continue
        try:
            payload = require_mapping(load_yaml_file(props_file), props_file)
        except ContentError as exc:
            raise ContentConfigError(str(exc)) from exc
        result[candidate.name] = {
            str(key) for key in payload if isinstance(key, str) and key != "CONFIG"
        }
    return result


def _roots_for(base_roots: Iterable[Path], shared_roots: Iterable[Path], kind: str) -> list[Path]:
    roots: list[Path] = []
    for base in base_roots:
        candidate = base / "data" / kind if kind in {"cardsets", "propsets"} else base / kind
        if candidate not in roots:
            roots.append(candidate.resolve())
    for shared in shared_roots:
        candidate = shared / kind
        if candidate not in roots:
            roots.append(candidate.resolve())
    return roots


def _resolve_required(
    available: Mapping[str, object],
    required: Iterable[str],
    kind: str,
) -> list[str]:
    ids = sorted(set(required))
    missing = [item for item in ids if item not in available]
    if missing:
        raise ContentConfigError(f"Missing required {kind}(s): {', '.join(missing)}.")
    return ids


def _resolve_mod_closure(
    available: Mapping[str, tuple[Path, tuple[str, ...]]],
    required: Iterable[str],
) -> list[str]:
    resolved: set[str] = set()
    pending = list(required)
    while pending:
        mod_id = pending.pop()
        if mod_id in resolved:
            continue
        if mod_id not in available:
            raise ContentConfigError(f"Missing required mod '{mod_id}'.")
        resolved.add(mod_id)
        pending.extend(available[mod_id][1])
    return sorted(resolved)


def load_content_selection(
    content_path: Path | str = DEFAULT_CONTENT_FILE,
    *,
    repo_root: Path | None = None,
) -> ContentSelection:
    """Resolve enabled worlds and the content their definitions require."""

    root = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
    path = Path(content_path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    payload = _read_config(path)
    entries = payload.get("worlds")
    if not isinstance(entries, list) or not entries:
        raise ContentConfigError("'worlds' must be a non-empty list.")

    config_root = path.parent
    base_roots = [root]
    if config_root != root:
        base_roots.append(config_root)
    bases = [config_root, root]
    requirements: list[_WorldRequirement] = []
    seen_worlds: set[str] = set()
    for index, entry in enumerate(entries):
        if not entry_enabled(entry, index, error=ContentConfigError):
            continue
        world_id = entry_world_id(entry, index, error=ContentConfigError)
        if world_id in seen_worlds:
            raise ContentConfigError(f"World '{world_id}' appears more than once.")
        seen_worlds.add(world_id)
        world_path = entry_path(entry, index, "path", error=ContentConfigError)
        directory = (
            _resolve_path(world_path, bases, f"World '{world_id}' path")
            if world_path is not None
            else _resolve_default_world(world_id, bases)
        )
        shared = entry_path(entry, index, "shared_content", error=ContentConfigError)
        requirements.append(
            _world_requirement(
                world_id, directory, index=index, bases=bases, shared=shared
            )
        )
    if not requirements:
        raise ContentConfigError("No worlds are enabled in the deployment content file.")

    shared_roots = [
        requirement.shared_content
        for requirement in requirements
        if requirement.shared_content is not None
    ]
    mod_roots = _roots_for(base_roots, shared_roots, "mods")
    cardset_roots = _roots_for(base_roots, shared_roots, "cardsets")
    propset_roots = _roots_for(base_roots, shared_roots, "propsets")

    mods_available: dict[str, tuple[Path, tuple[str, ...]]] = {}
    cardsets_available: dict[str, Path] = {}
    propsets_available: dict[str, Path] = {}
    propset_contents: dict[str, set[str]] = {}
    for mod_root in mod_roots:
        mods_available.update(_discover_mods(mod_root))
    for cardset_root in cardset_roots:
        cardsets_available.update(_all_cardsets(cardset_root))
    for propset_root in propset_roots:
        propsets_available.update(_discover(propset_root, "props.yaml"))
        propset_contents.update(_propset_ids(propset_root))

    for special in ("base", "card-backgrounds"):
        for cardset_root in cardset_roots:
            candidate = cardset_root / special
            if candidate.is_dir():
                cardsets_available.setdefault(special, candidate.resolve())

    required_mods: set[str] = set()
    required_cardsets: set[str] = set()
    required_propsets: set[str] = set()
    include_all_cardsets = False
    inferred_props: set[str] = set()
    inferred_by_world: dict[str, set[str]] = {}
    for requirement in requirements:
        required_mods.update(requirement.mods)
        if requirement.cardsets is None:
            include_all_cardsets = True
        else:
            required_cardsets.update(requirement.cardsets)
        if requirement.propsets is None:
            references = _prop_references(requirement.directory)
            inferred_by_world[requirement.id] = references
            inferred_props.update(references)
        else:
            required_propsets.update(requirement.propsets)

    mod_ids = _resolve_mod_closure(mods_available, required_mods)
    if include_all_cardsets:
        required_cardsets.update(cardsets_available)
    cardset_ids = _resolve_required(cardsets_available, required_cardsets, "cardset")
    known_props: set[str] = set()
    for prop_ids in propset_contents.values():
        known_props.update(prop_ids)
    for requirement in requirements:
        known_props.update(_authored_prop_ids(requirement.directory))
    unresolved: list[str] = []
    for requirement in requirements:
        missing = sorted(
            reference
            for reference in inferred_by_world.get(requirement.id, set())
            if reference not in known_props
            and not reference.startswith(("builtin:", "custom:"))
        )
        if missing:
            unresolved.append(f"World '{requirement.id}': {', '.join(missing)}")
    if unresolved:
        raise ContentConfigError(
            "Unknown prop reference(s) with no defining propset: " + "; ".join(unresolved)
        )
    for propset_id, prop_ids in propset_contents.items():
        if prop_ids & inferred_props:
            required_propsets.add(propset_id)
    propset_ids = _resolve_required(propsets_available, required_propsets, "propset")

    return ContentSelection(
        worlds=tuple(
            ContentEntry(KIND_WORLD, requirement.id, requirement.directory)
            for requirement in requirements
        ),
        mods=tuple(ContentEntry(KIND_MOD, mod_id, mods_available[mod_id][0]) for mod_id in mod_ids),
        cardsets=tuple(
            ContentEntry(KIND_CARDSET, cardset_id, cardsets_available[cardset_id])
            for cardset_id in cardset_ids
        ),
        propsets=tuple(
            ContentEntry(KIND_PROPSET, propset_id, propsets_available[propset_id])
            for propset_id in propset_ids
        ),
    )


def iter_content_members(entry: ContentEntry) -> Iterator[tuple[Path, str]]:
    """Yield ``(path, arcname)`` for every packageable file in *entry*."""

    for current, dirs, files in os.walk(entry.path):
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED_DIRS)
        base = Path(current)
        for name in sorted(files):
            if name.endswith(EXCLUDED_SUFFIXES):
                continue
            path = base / name
            relative = path.relative_to(entry.path).as_posix()
            yield path, f"{entry.arcname}/{relative}"


def content_hash(selection: ContentSelection) -> str:
    """Return a stable SHA-256 digest of the selected content files."""

    digest = hashlib.sha256()
    members = [member for entry in selection.entries() for member in iter_content_members(entry)]
    for path, arcname in sorted(members, key=lambda member: member[1]):
        digest.update(arcname.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()
