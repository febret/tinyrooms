"""Content-root scanning, package index, upload validation, and install."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import io
import json
import re
import shutil
import tempfile
import zipfile

from server.config import KNOWN_FEATURES
from server.content.activities import load_activity_definitions
from server.content.cards import ContentError, load_card_catalog
from server.content.common import load_yaml_file
from server.content.worlds import load_propset, load_world_definition
from server.mission_control.audit import McAuditLog
from server.mission_control.config import MCConfig
from server.mods import discover_mods, load_mod_activity_definitions
from server.version import version_info


KIND_WORLD = "world"
KIND_CARDSET = "cardset"
KIND_PROPSET = "propset"
PACKAGE_KINDS = (KIND_WORLD, KIND_CARDSET, KIND_PROPSET)

MANIFEST_NAMES = ("package.json", "package.yaml")
MAX_UPLOAD_BYTES = 32 * 1024 * 1024
_PACKAGE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass
class PackageRecord:
    """One installed content package."""

    kind: str
    id: str
    label: str
    version: str
    path: Path
    validation_status: str = "ok"
    messages: list[str] = field(default_factory=list)
    enabled: bool = True

    def to_dict(self) -> dict[str, object]:
        """Serialize the record for the mission-control UI."""

        return {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "version": self.version,
            "path": str(self.path),
            "validation": {"status": self.validation_status, "messages": list(self.messages)},
            "enabled": self.enabled,
        }


class PackageManager:
    """Scan, validate, install, and manage content packages."""

    def __init__(self, config: MCConfig, audit: McAuditLog) -> None:
        self._config = config
        self._audit = audit
        self._disabled: set[tuple[str, str]] = set()
        self._records: dict[tuple[str, str], PackageRecord] = {}

    @property
    def worlds_root(self) -> Path:
        return self._config.repo_root / "worlds"

    @property
    def cardsets_root(self) -> Path:
        return self._config.repo_root / "data" / "cardsets"

    @property
    def propsets_root(self) -> Path:
        return self._config.repo_root / "data" / "propsets"

    def canonical_root(self, kind: str) -> Path:
        """Return the install root for a package kind."""

        if kind == KIND_WORLD:
            return self.worlds_root
        if kind == KIND_CARDSET:
            return self.cardsets_root
        if kind == KIND_PROPSET:
            return self.propsets_root
        raise ValueError(f"Unknown package kind '{kind}'.")

    def refresh(self) -> None:
        """Rebuild the package index from a content scan."""

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
            record = PackageRecord(
                kind=kind,
                id=package_dir.name,
                label=package_dir.name,
                version=self._read_version(package_dir),
                path=package_dir,
                validation_status=status,
                messages=messages,
                enabled=(kind, package_dir.name) not in self._disabled,
            )
            records.append(record)
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
        """Validate a package directory with its content loader."""

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

    def _validate_world(self, package_dir: Path) -> None:
        catalog = load_card_catalog(self.cardsets_root, package_dir)
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
        load_world_definition(
            package_dir,
            set(catalog.cards),
            core_activities=merged,
            known_features=KNOWN_FEATURES,
            propsets_root=self.propsets_root,
            mod_props=mod_props,
            enabled_mods=frozenset(mods),
        )

    def _validate_cardset(self, package_dir: Path) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            staging = Path(temp_root) / "cardsets"
            staging.mkdir()
            shutil.copytree(package_dir, staging / package_dir.name)
            load_card_catalog(staging, Path(temp_root) / "empty-world")

    def inventory(self) -> dict[str, object]:
        """Return the full package inventory grouped by kind."""

        self.refresh()
        groups: dict[str, list[dict[str, object]]] = {kind: [] for kind in PACKAGE_KINDS}
        for record in self._records.values():
            groups[record.kind].append(record.to_dict())
        for kind in groups:
            groups[kind].sort(key=lambda item: str(item["id"]))
        return {
            "server_versions": self._server_versions(),
            "worlds": groups[KIND_WORLD],
            "cardsets": groups[KIND_CARDSET],
            "propsets": groups[KIND_PROPSET],
        }

    def _server_versions(self) -> list[dict[str, object]]:
        versions = [
            {"id": "running", "label": "Running build", "path": str(self._config.repo_root), **version_info(self._config.repo_root)}
        ]
        versions_root = self._config.versions_path
        if versions_root.is_dir():
            for candidate in sorted(versions_root.iterdir()):
                if not candidate.is_dir():
                    continue
                if not (candidate / "run.py").is_file() and not (candidate / "server").is_dir():
                    continue
                versions.append(
                    {"id": candidate.name, "label": candidate.name, "path": str(candidate), **version_info(candidate)}
                )
        return versions

    def record(self, kind: str, package_id: str) -> PackageRecord | None:
        """Return a scanned package record."""

        return self._records.get((kind, package_id))

    def enabled_worlds(self) -> list[dict[str, object]]:
        """Return non-disabled world packages for the start-instance picker."""

        self.refresh()
        return [
            record.to_dict()
            for record in self._records.values()
            if record.kind == KIND_WORLD and record.enabled and record.validation_status != "error"
        ]

    def set_enabled(self, kind: str, package_id: str, enabled: bool, *, actor: str) -> None:
        """Enable or disable a package for this mission-control session."""

        key = (kind, package_id)
        if enabled:
            self._disabled.discard(key)
        else:
            self._disabled.add(key)
        record = self._records.get(key)
        if record is not None:
            record.enabled = enabled
        self._audit.record(actor, "package.enable" if enabled else "package.disable", target=f"{kind}/{package_id}")

    def install(self, kind: str, data: bytes, *, actor: str) -> PackageRecord:
        """Validate and install a package zip, writing nothing on failure."""

        if kind not in PACKAGE_KINDS:
            raise ValueError(f"Unknown package kind '{kind}'.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError(f"Package exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise ValueError("Upload is not a valid zip archive.")

        with tempfile.TemporaryDirectory() as temp_root:
            extract_root = Path(temp_root) / "extract"
            extract_root.mkdir()
            self._extract(data, extract_root)
            manifest_path, package_root = self._locate_manifest(extract_root)
            manifest = self._read_manifest(manifest_path)
            declared_kind = str(manifest.get("kind", "")).strip()
            package_id = str(manifest.get("id", "")).strip()
            if declared_kind != kind:
                raise ValueError(f"Manifest declares kind '{declared_kind}' but upload was '{kind}'.")
            if not _PACKAGE_ID.match(package_id):
                raise ValueError(f"Manifest id '{package_id}' is not a valid package id.")
            status, messages = self.validate(kind, package_root)
            if status == "error":
                raise ValueError("Package failed validation: " + "; ".join(messages))
            destination = self.canonical_root(kind) / package_id
            if destination.exists():
                raise ValueError(f"Package '{kind}/{package_id}' is already installed.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(package_root), str(destination))

        self.refresh()
        record = self._records.get((kind, package_id))
        if record is None:
            record = PackageRecord(kind=kind, id=package_id, label=package_id, version="", path=destination)
        self._audit.record(actor, "package.install", target=f"{kind}/{package_id}", detail={"version": record.version})
        return record

    def _extract(self, data: bytes, destination: Path) -> None:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                self._assert_safe_entry(name)
            archive.extractall(destination)

    @staticmethod
    def _assert_safe_entry(name: str) -> None:
        if "\\" in name:
            raise ValueError(f"Archive entry uses a backslash path: {name}")
        if len(name) > 1 and name[1] == ":":
            raise ValueError(f"Archive entry uses a drive path: {name}")
        path = PurePosixPath(name)
        if path.is_absolute():
            raise ValueError(f"Archive entry uses an absolute path: {name}")
        if ".." in path.parts:
            raise ValueError(f"Archive entry escapes the package root: {name}")

    def _locate_manifest(self, extract_root: Path) -> tuple[Path, Path]:
        for manifest_name in MANIFEST_NAMES:
            candidate = extract_root / manifest_name
            if candidate.is_file():
                return candidate, extract_root
        children = [child for child in extract_root.iterdir() if child.is_dir()]
        if len(children) == 1:
            for manifest_name in MANIFEST_NAMES:
                candidate = children[0] / manifest_name
                if candidate.is_file():
                    return candidate, children[0]
        raise ValueError("Package is missing a top-level package.json or package.yaml manifest.")

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

    def delete(self, kind: str, package_id: str, *, actor: str) -> None:
        """Delete an installed package directory."""

        root = self.canonical_root(kind).resolve()
        target = (root / package_id).resolve()
        if target.parent != root:
            raise ValueError("Refusing to delete outside the package root.")
        if not target.is_dir():
            raise ValueError("Package is not installed.")
        shutil.rmtree(target)
        self._disabled.discard((kind, package_id))
        self._records.pop((kind, package_id), None)
        self._audit.record(actor, "package.delete", target=f"{kind}/{package_id}")
