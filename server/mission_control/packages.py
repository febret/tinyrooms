"""Shared content inventory and installed server-version management.

Mission control manages two related things from the package view: the content
shared across every server version (worlds, cardsets, and propsets installed at
the deploy root) and the installed server versions themselves. Content bundled
inside a single version checkout is not inventoried here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import shutil
import tempfile

from server.config import ConfigError, KNOWN_FEATURES, ensure_contained
from server.content.activities import ActivityDefinition, load_activity_definitions
from server.content.cards import ContentError, load_card_catalog
from server.content.common import load_yaml_file
from server.content.worlds import load_propset, load_world_definition
from server.mission_control.audit import McAuditLog
from server.mission_control.config import MCConfig
from server.mission_control.registry import (
    STATUS_RUNNING,
    STATUS_STARTING,
    InstanceRegistry,
)
from server.mods import discover_mods, load_mod_activity_definitions
from server.version import VersionFileError, latest_build_version, version_info


KIND_WORLD = "world"
KIND_CARDSET = "cardset"
KIND_PROPSET = "propset"
PACKAGE_KINDS = (KIND_WORLD, KIND_CARDSET, KIND_PROPSET)

RUNNING_VERSION_ID = "running"
MANIFEST_NAMES = ("package.json", "package.yaml")


@dataclass
class PackageRecord:
    """One shared content package installed outside any server version."""

    kind: str
    id: str
    label: str
    version: str
    path: Path
    validation_status: str = "ok"
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Serialize the record for the mission-control UI."""

        return {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "version": self.version,
            "path": str(self.path),
            "validation": {"status": self.validation_status, "messages": list(self.messages)},
        }


class PackageManager:
    """Scan shared content, inventory server versions, and delete unused versions."""

    def __init__(self, config: MCConfig, registry: InstanceRegistry, audit: McAuditLog) -> None:
        self._config = config
        self._registry = registry
        self._audit = audit
        self._records: dict[tuple[str, str], PackageRecord] = {}
        self._world_content_cache: tuple[
            dict[str, ActivityDefinition], tuple[tuple[str, Path], ...], frozenset[str]
        ] | None = None

    @property
    def worlds_root(self) -> Path:
        return self._config.shared_worlds_root

    @property
    def cardsets_root(self) -> Path:
        return self._config.shared_cardsets_root

    @property
    def propsets_root(self) -> Path:
        return self._config.shared_propsets_root

    def refresh(self) -> None:
        """Rebuild the shared-content index from a filesystem scan."""

        records: dict[tuple[str, str], PackageRecord] = {}
        for record in self._scan(KIND_WORLD, self.worlds_root, "world.yaml"):
            records[(record.kind, record.id)] = record
        for record in self._scan(KIND_CARDSET, self.cardsets_root, "cards.yaml"):
            records[(record.kind, record.id)] = record
        for record in self._scan(KIND_PROPSET, self.propsets_root, "props.yaml"):
            records[(record.kind, record.id)] = record
        self._records = records

    def _scan(self, kind: str, root: Path, marker: str) -> list[PackageRecord]:
        if not root.is_dir():
            return []
        records: list[PackageRecord] = []
        for marker_file in sorted(root.glob(f"*/{marker}")):
            package_dir = marker_file.parent
            status, messages = self.validate(kind, package_dir)
            records.append(
                PackageRecord(
                    kind=kind,
                    id=package_dir.name,
                    label=package_dir.name,
                    version=self._read_version(package_dir),
                    path=package_dir,
                    validation_status=status,
                    messages=messages,
                )
            )
        return records

    def _read_version(self, package_dir: Path) -> str:
        for manifest_name in MANIFEST_NAMES:
            candidate = package_dir / manifest_name
            if candidate.is_file():
                try:
                    manifest = self._read_manifest(candidate)
                except (ValueError, ContentError):
                    continue
                version = manifest.get("version")
                if version is not None:
                    return str(version)
        return ""

    def validate(self, kind: str, package_dir: Path) -> tuple[str, list[str]]:
        """Validate a content directory with its loader."""

        try:
            if kind == KIND_WORLD:
                self._validate_world(package_dir)
            elif kind == KIND_CARDSET:
                self._validate_cardset(package_dir)
            elif kind == KIND_PROPSET:
                load_propset(package_dir)
            else:
                return "error", [f"Unknown package kind '{kind}'."]
        except ContentError as exc:
            return "error", [str(exc)]
        except Exception as exc:  # noqa: BLE001 - surface any loader failure
            return "error", [f"{type(exc).__name__}: {exc}"]
        return "ok", []

    def _world_content(self) -> tuple[dict[str, ActivityDefinition], tuple[tuple[str, Path], ...], frozenset[str]]:
        """Return cached core+mod activity content shared by every world."""

        if self._world_content_cache is None:
            core = load_activity_definitions(
                self._config.repo_root / "data" / "core" / "activities.yaml",
                source="core",
                known_features=KNOWN_FEATURES,
            )
            mods = discover_mods(self._config.repo_root / "mods")
            merged = {**core, **load_mod_activity_definitions(mods.values(), known_features=KNOWN_FEATURES)}
            mod_props = tuple(
                (mod.id, mod.props_path) for mod in mods.values() if (mod.props_path / "props.yaml").is_file()
            )
            self._world_content_cache = (merged, mod_props, frozenset(mods))
        return self._world_content_cache

    def _validate_world(self, package_dir: Path) -> None:
        catalog = load_card_catalog(self.cardsets_root, package_dir)
        merged, mod_props, enabled_mods = self._world_content()
        load_world_definition(
            package_dir,
            set(catalog.cards),
            core_activities=merged,
            known_features=KNOWN_FEATURES,
            propsets_root=self.propsets_root,
            mod_props=mod_props,
            enabled_mods=enabled_mods,
        )

    def _validate_cardset(self, package_dir: Path) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            staging = Path(temp_root) / "cardsets"
            staging.mkdir()
            shutil.copytree(package_dir, staging / package_dir.name)
            load_card_catalog(staging, Path(temp_root) / "empty-world")

    def inventory(self) -> dict[str, object]:
        """Return the shared-content inventory and server versions."""

        self.refresh()
        groups: dict[str, list[dict[str, object]]] = {kind: [] for kind in PACKAGE_KINDS}
        for record in self._records.values():
            groups[record.kind].append(record.to_dict())
        for kind in groups:
            groups[kind].sort(key=lambda item: str(item["id"]))
        return {
            "server_versions": self.server_versions(),
            "worlds": groups[KIND_WORLD],
            "cardsets": groups[KIND_CARDSET],
            "propsets": groups[KIND_PROPSET],
        }

    def server_versions(self) -> list[dict[str, object]]:
        """Return installed server versions with running-instance counts."""

        running = self._instance_counts(running_only=True)
        registered = self._instance_counts()
        running_info = version_info(self._config.repo_root)
        running_label = str(running_info.get("build") or "")
        versions: list[dict[str, object]] = [
            {
                "id": RUNNING_VERSION_ID,
                "label": "Running build",
                "path": str(self._config.repo_root),
                "running": True,
                "instance_count": running.get(running_label, 0),
                "registered_count": registered.get(running_label, 0),
                "deletable": False,
                "delete_reason": "The running version cannot be deleted.",
                **running_info,
            }
        ]
        versions_root = self._config.versions_path
        if versions_root.is_dir():
            running_resolved = self._config.repo_root.resolve()
            for candidate in sorted(versions_root.iterdir()):
                if not candidate.is_dir() or candidate.name == "latest":
                    continue
                try:
                    if candidate.resolve() == running_resolved:
                        continue
                except OSError:
                    pass
                if not (candidate / "run.py").is_file() and not (candidate / "server").is_dir():
                    continue
                info = version_info(candidate)
                label = str(info.get("build") or candidate.name)
                aliases = {label, candidate.name}
                running_count = sum(running.get(alias, 0) for alias in aliases)
                registered_count = sum(registered.get(alias, 0) for alias in aliases)
                deletable = registered_count == 0
                versions.append(
                    {
                        "id": candidate.name,
                        "label": candidate.name,
                        "path": str(candidate),
                        "running": False,
                        "instance_count": running_count,
                        "registered_count": registered_count,
                        "deletable": deletable,
                        "delete_reason": "" if deletable else f"{registered_count} registered instance(s) on this version.",
                        **info,
                    }
                )
        return versions

    def _instance_counts(self, *, running_only: bool = False) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self._registry.list():
            if not record.version:
                continue
            if running_only and record.status not in {STATUS_RUNNING, STATUS_STARTING}:
                continue
            counts[record.version] = counts.get(record.version, 0) + 1
        return counts

    def worlds_for(self, version_id: str | None) -> list[dict[str, object]]:
        """Return worlds available for a version: shared first, then bundled."""

        self.refresh()
        result: dict[str, dict[str, object]] = {}
        for record in self._records.values():
            if record.kind != KIND_WORLD:
                continue
            result[record.id] = {
                "id": record.id,
                "label": record.label,
                "source": "shared",
                "path": str(record.path),
                "validation": {"status": record.validation_status, "messages": list(record.messages)},
            }
        version_root = self.resolve_version(version_id)
        version_worlds = version_root / "worlds"
        if version_worlds.is_dir():
            for world_file in sorted(version_worlds.glob("*/world.yaml")):
                world_dir = world_file.parent
                if world_dir.name in result:
                    continue
                result[world_dir.name] = {
                    "id": world_dir.name,
                    "label": world_dir.name,
                    "source": version_id or RUNNING_VERSION_ID,
                    "path": str(world_dir),
                    "validation": {"status": "ok", "messages": []},
                }
        return sorted(result.values(), key=lambda item: str(item["id"]))

    def resolve_version(self, version_id: str | None) -> Path:
        """Resolve a version id to its checkout path, or the running build."""

        if not version_id or version_id == RUNNING_VERSION_ID:
            return self._config.repo_root
        try:
            candidate = ensure_contained(
                self._config.versions_path / version_id,
                self._config.versions_path,
                "server version",
            )
        except ConfigError as exc:
            raise ValueError(f"Unknown server version '{version_id}'.") from exc
        if candidate == self._config.versions_path.resolve():
            raise ValueError("Unknown server version.")
        if candidate == self._config.repo_root.resolve():
            return self._config.repo_root
        if not candidate.is_dir() or (
            not (candidate / "run.py").is_file() and not (candidate / "server").is_dir()
        ):
            raise ValueError(f"Server version '{version_id}' is not installed.")
        return candidate

    def resolve_world(self, version_id: str | None, world_id: str) -> Path:
        """Resolve a world id to a shared or version-bundled world directory."""

        try:
            shared_root = self._config.shared_worlds_root.resolve()
            shared = ensure_contained(self._config.shared_worlds_root / world_id, self._config.shared_worlds_root, "world")
        except ConfigError as exc:
            raise ValueError(f"Unknown world '{world_id}'.") from exc
        if shared != shared_root and (shared / "world.yaml").is_file():
            return shared
        version_root = self.resolve_version(version_id)
        worlds_root = version_root / "worlds"
        try:
            candidate = ensure_contained(worlds_root / world_id, worlds_root, "world")
        except ConfigError as exc:
            raise ValueError(f"Unknown world '{world_id}'.") from exc
        if candidate != worlds_root.resolve() and (candidate / "world.yaml").is_file():
            return candidate
        raise ValueError(f"World '{world_id}' is not installed for this version.")

    def delete_version(self, version_id: str, *, actor: str) -> None:
        """Delete an unused server version directory and its release artifact."""

        if version_id in {RUNNING_VERSION_ID, "latest", ""}:
            raise ValueError("The running version cannot be deleted.")
        try:
            target = ensure_contained(
                self._config.versions_path / version_id,
                self._config.versions_path,
                "server version",
            )
        except ConfigError as exc:
            raise ValueError("Unknown server version.") from exc
        if target == self._config.versions_path.resolve() or target == self._config.repo_root.resolve():
            raise ValueError("The running version cannot be deleted.")
        if not target.is_dir():
            raise ValueError("Server version is not installed.")
        count = self._instance_count_for(target, version_id)
        if count:
            raise ValueError(f"Cannot delete a version with {count} registered instance(s).")
        shutil.rmtree(target)
        tarball = self._config.releases_path / f"tinyrooms-{version_id}.tar.gz"
        if tarball.is_file():
            try:
                tarball.unlink()
            except OSError:
                pass
        self._audit.record(actor, "version.delete", target=version_id)

    def _instance_count_for(self, version_root: Path, fallback: str) -> int:
        try:
            label = latest_build_version(version_root / "version.json")
        except VersionFileError:
            label = fallback
        labels = {label, fallback}
        return sum(1 for record in self._registry.list() if record.version in labels)

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, object]:
        if path.suffix == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid manifest JSON: {exc}") from exc
        else:
            payload = load_yaml_file(path)
        if not isinstance(payload, dict):
            raise ValueError("Manifest must be a mapping.")
        return payload
