"""Prop-set schema, repository indexing, and prop-reference resolution."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# #<filename>/<propId>[/<frameNum>][.x<n>][.y<n>][.r<n>]
_REF_RE = re.compile(
    r"^#(?P<filename>[^/.\s]+)"
    r"/(?P<prop_id>[^/.\s]+)"
    r"(?:/(?P<frame_num>\d+))?"
    r"(?P<modifiers>(?:\.[xyr]-?\d+(?:\.\d+)*)*)$"
)
_MOD_RE = re.compile(r"\.(?P<key>[xyr])(?P<val>-?\d+(?:\.\d+)?)")


class PropValidationError(ValueError):
    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or [message]


@dataclass
class PropEntry:
    prop_id: str
    width: int
    height: int
    frames: list[tuple[int, int]]
    anim_speed: float | None = None


@dataclass
class PropSet:
    scope: str
    filename: str
    image_path: Path
    yaml_path: Path
    label: str
    description: str
    background_color: str | None
    props: dict[str, PropEntry]


@dataclass(frozen=True)
class PropReference:
    raw: str
    filename: str
    prop_id: str
    frame_num: int | None
    offset_x: float
    offset_y: float
    rotation_deg: float


@dataclass
class PropSetRecord:
    scope: str
    filename: str
    image_path: Path | None
    yaml_path: Path | None
    prop_set: PropSet | None
    load_error: str | None = None

    @property
    def has_image(self) -> bool:
        return self.image_path is not None and self.image_path.exists()

    @property
    def has_yaml(self) -> bool:
        return self.yaml_path is not None and self.yaml_path.exists()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_positive_int(value: Any, field_name: str, errors: list[str], default: int = 32) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        errors.append(f"{field_name} must be a positive integer")
        return default
    if out <= 0:
        errors.append(f"{field_name} must be > 0")
        return default
    return out


def _normalize_background_color(value: Any, errors: list[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append("background_color must be a string")
        return None
    normalized = value.strip()
    return normalized if normalized else None


def _normalize_frames(prop_id: str, raw: Any, errors: list[str]) -> list[tuple[int, int]]:
    if not isinstance(raw, list) or not raw:
        errors.append(f"props.{prop_id}.frames must be a non-empty list")
        return [[0, 0]]
    out: list[tuple[int, int]] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            errors.append(f"props.{prop_id}.frames[{idx}] must be a two-element list [x, y]")
            out.append((0, 0))
            continue
        try:
            x, y = int(item[0]), int(item[1])
        except (TypeError, ValueError):
            errors.append(f"props.{prop_id}.frames[{idx}] coordinates must be integers")
            out.append((0, 0))
            continue
        if x < 0 or y < 0:
            errors.append(f"props.{prop_id}.frames[{idx}] coordinates must be non-negative")
        out.append((x, y))
    return out


def _normalize_prop(prop_id: str, raw: Any, errors: list[str]) -> PropEntry:
    if not isinstance(raw, dict):
        errors.append(f"props.{prop_id} must be an object")
        return PropEntry(prop_id=prop_id, width=32, height=32, frames=[(0, 0)])
    width = _validate_positive_int(raw.get("width"), f"props.{prop_id}.width", errors)
    height = _validate_positive_int(raw.get("height"), f"props.{prop_id}.height", errors)
    frames = _normalize_frames(prop_id, raw.get("frames", [[0, 0]]), errors)
    anim_speed = None
    if "anim_speed" in raw and raw["anim_speed"] is not None:
        try:
            anim_speed = float(raw["anim_speed"])
        except (TypeError, ValueError):
            errors.append(f"props.{prop_id}.anim_speed must be a positive number")
        else:
            if anim_speed <= 0:
                errors.append(f"props.{prop_id}.anim_speed must be > 0")
                anim_speed = None
    return PropEntry(prop_id=prop_id, width=width, height=height, frames=frames, anim_speed=anim_speed)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_prop_set(scope: str, filename: str, image_path: Path, yaml_path: Path) -> PropSet:
    errors: list[str] = []
    if not image_path.exists():
        errors.append(f"missing image file: {image_path}")
    if not yaml_path.exists():
        errors.append(f"missing yaml file: {yaml_path}")
    if errors:
        raise PropValidationError("invalid prop set", errors=errors)
    with yaml_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise PropValidationError("prop definition must be a mapping")
    props_raw = loaded.get("props", {})
    if not isinstance(props_raw, dict) or not props_raw:
        errors.append("props must be a non-empty mapping")
        props_raw = {}
    props: dict[str, PropEntry] = {}
    for pid, praw in props_raw.items():
        normalized = _normalize_prop(str(pid), praw, errors)
        props[str(pid)] = normalized
    background_color = _normalize_background_color(loaded.get("background_color"), errors)
    if errors:
        raise PropValidationError("prop schema validation failed", errors=errors)
    return PropSet(
        scope=scope,
        filename=filename,
        image_path=image_path,
        yaml_path=yaml_path,
        label=str(loaded.get("label", "") or ""),
        description=str(loaded.get("description", "") or ""),
        background_color=background_color,
        props=props,
    )


def parse_prop_reference(asset_value: str) -> PropReference | None:
    """Parse a prop reference string like #filename/propId[/frameNum][.x<n>][.y<n>][.r<n>]."""
    if not isinstance(asset_value, str) or not asset_value.startswith("#"):
        return None
    m = _REF_RE.match(asset_value)
    if not m:
        return None
    filename = m.group("filename")
    prop_id = m.group("prop_id")
    frame_num_str = m.group("frame_num")
    frame_num = int(frame_num_str) if frame_num_str is not None else None
    modifiers = m.group("modifiers") or ""
    offset_x = 0.0
    offset_y = 0.0
    rotation_deg = 0.0
    for mod_match in _MOD_RE.finditer(modifiers):
        key = mod_match.group("key")
        val = float(mod_match.group("val"))
        if key == "x":
            offset_x = val
        elif key == "y":
            offset_y = val
        elif key == "r":
            rotation_deg = val
    return PropReference(
        raw=asset_value,
        filename=filename,
        prop_id=prop_id,
        frame_num=frame_num,
        offset_x=offset_x,
        offset_y=offset_y,
        rotation_deg=rotation_deg,
    )


def resolve_prop_reference(ref: PropReference, repo: "PropRepository") -> dict[str, Any]:
    record = repo.lookup(ref.filename)
    if record is None:
        raise PropValidationError(f"prop set '{ref.filename}' not found")
    if record.prop_set is None:
        if record.load_error:
            raise PropValidationError(record.load_error)
        raise PropValidationError(f"prop set '{ref.filename}' has no valid yaml definition")
    prop_set = record.prop_set
    prop = prop_set.props.get(ref.prop_id)
    if prop is None:
        raise PropValidationError(f"prop '{ref.prop_id}' not found in '{ref.filename}'")
    frame_idx = ref.frame_num if ref.frame_num is not None else 0
    if frame_idx < 0 or frame_idx >= len(prop.frames):
        frame_idx = 0
    frame_x, frame_y = prop.frames[frame_idx]
    payload: dict[str, Any] = {
        "ref": ref.raw,
        "scope": prop_set.scope,
        "filename": prop_set.filename,
        "prop_id": ref.prop_id,
        "image_url": f"/props/{prop_set.scope}/{prop_set.image_path.name}",
        "frame": {"x": frame_x, "y": frame_y, "width": prop.width, "height": prop.height},
        "offset_x": ref.offset_x,
        "offset_y": ref.offset_y,
        "rotation_deg": ref.rotation_deg,
    }
    if prop.anim_speed is not None:
        payload["animation"] = {
            "speed": prop.anim_speed,
            "frames": [{"x": fx, "y": fy, "width": prop.width, "height": prop.height} for fx, fy in prop.frames],
        }
    return payload


def to_definition_dict(prop_set: PropSet) -> dict[str, Any]:
    props_payload: dict[str, Any] = {}
    for pid, prop in prop_set.props.items():
        entry: dict[str, Any] = {
            "width": prop.width,
            "height": prop.height,
            "frames": [[x, y] for x, y in prop.frames],
        }
        if prop.anim_speed is not None:
            entry["anim_speed"] = prop.anim_speed
        props_payload[pid] = entry
    payload: dict[str, Any] = {
        "label": prop_set.label,
        "description": prop_set.description,
        "image": prop_set.image_path.name,
        "props": props_payload,
    }
    if prop_set.background_color is not None:
        payload["background_color"] = prop_set.background_color
    return payload


def validate_definition_document(doc: dict[str, Any], image_path: Path) -> dict[str, Any]:
    if not isinstance(doc, dict):
        raise PropValidationError("definition must be an object")
    with tempfile.TemporaryDirectory(prefix="tinyrooms-prop-validate-") as tmp:
        tmp_path = Path(tmp)
        yaml_path = tmp_path / "validate.yaml"
        yaml_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
        normalized = load_prop_set("world", "validate", image_path=image_path, yaml_path=yaml_path)
    return to_definition_dict(normalized)


def write_definition_document(yaml_path: Path, definition: dict[str, Any]) -> None:
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = yaml.safe_dump(definition, sort_keys=False, allow_unicode=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False,
        dir=str(yaml_path.parent), prefix=".tmp_prop_", suffix=".yaml"
    ) as handle:
        handle.write(serialized)
        tmp_name = handle.name
    Path(tmp_name).replace(yaml_path)


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class PropRepository:
    def __init__(self, world_root_path: Path, server_root_path: Path | None = None):
        self.world_root_path = Path(world_root_path)
        self.server_root_path = (
            Path(server_root_path) if server_root_path
            else Path(__file__).parent.parent / "data" / "props"
        )
        self.world_props_path = self.world_root_path / "props"
        self._index: dict[tuple[str, str], PropSetRecord] = {}

    def _scan_scope(self, scope: str, root: Path) -> None:
        if not root.exists():
            return
        stems: set[str] = set()
        for item in root.iterdir():
            if not item.is_file():
                continue
            suffix = item.suffix.lower()
            if suffix in {".png", ".gif", ".webp"}:
                stems.add(item.stem)
            elif suffix in {".yaml", ".yml"}:
                stems.add(item.stem)
        for stem in sorted(stems):
            image_path = None
            for ext in (".png", ".gif", ".webp"):
                candidate = root / f"{stem}{ext}"
                if candidate.exists():
                    image_path = candidate
                    break
            yaml_path = None
            for ext in (".yaml", ".yml"):
                candidate = root / f"{stem}{ext}"
                if candidate.exists():
                    yaml_path = candidate
                    break
            record = PropSetRecord(scope=scope, filename=stem, image_path=image_path, yaml_path=yaml_path, prop_set=None)
            if record.has_image and record.has_yaml and image_path is not None and yaml_path is not None:
                try:
                    record.prop_set = load_prop_set(scope, stem, image_path, yaml_path)
                except PropValidationError as err:
                    record.load_error = "; ".join(err.errors)
            self._index[(scope, stem)] = record

    def reindex(self) -> None:
        self._index = {}
        self._scan_scope("server", self.server_root_path)
        self._scan_scope("world", self.world_props_path)

    def list_sets(self) -> list[PropSetRecord]:
        out = list(self._index.values())
        out.sort(key=lambda rec: (rec.filename, 0 if rec.scope == "world" else 1, rec.scope))
        return out

    def get(self, scope: str, filename: str) -> PropSetRecord | None:
        return self._index.get((scope, filename))

    def lookup(self, filename: str, scope_hint: str | None = None) -> PropSetRecord | None:
        if scope_hint in {"world", "server"}:
            return self.get(scope_hint, filename)
        return self.get("world", filename) or self.get("server", filename)
