"""Sprite-set schema, repository indexing, and sprite-reference resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tempfile
from typing import Any

import yaml


FRAME_TOKEN_RE = re.compile(r"^(\d+)x(\d+)$")
ANIM_TYPES = {"loop", "bounce", "random"}


class SpriteValidationError(ValueError):
    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or [message]


@dataclass(frozen=True)
class FrameCoord:
    x: int
    y: int

    @property
    def token(self) -> str:
        return f"{self.x}x{self.y}"


@dataclass
class SpriteAnimation:
    anim_id: str
    speed: float
    anim_type: str
    frames: list[FrameCoord]


@dataclass
class SpriteEntry:
    sprite_id: str
    default_frame: FrameCoord | None
    anims: dict[str, SpriteAnimation]


@dataclass
class SpriteSet:
    scope: str
    filename: str
    image_path: Path
    yaml_path: Path
    frame_width: int
    frame_height: int
    background_color: str | None
    sprites: dict[str, SpriteEntry]
    label: str
    description: str

    def frame_rect(self, coord: FrameCoord) -> dict[str, int | str]:
        return {
            "token": coord.token,
            "x": coord.x * self.frame_width,
            "y": coord.y * self.frame_height,
            "width": self.frame_width,
            "height": self.frame_height,
            "grid_x": coord.x,
            "grid_y": coord.y,
        }


@dataclass(frozen=True)
class SpriteReference:
    raw: str
    scope_hint: str | None
    filename: str
    sprite_id: str | None
    anim_id: str | None
    frame_selector: str | None


@dataclass
class SpriteSetRecord:
    scope: str
    filename: str
    image_path: Path | None
    yaml_path: Path | None
    sprite_set: SpriteSet | None
    load_error: str | None = None

    @property
    def has_image(self) -> bool:
        return self.image_path is not None and self.image_path.exists()

    @property
    def has_yaml(self) -> bool:
        return self.yaml_path is not None and self.yaml_path.exists()


def parse_frame_token(raw: str) -> FrameCoord:
    token = str(raw or "").strip()
    m = FRAME_TOKEN_RE.match(token)
    if not m:
        raise SpriteValidationError(f"invalid frame token '{raw}'")
    return FrameCoord(int(m.group(1)), int(m.group(2)))


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
    if not normalized:
        return None
    return normalized


def _normalize_anim(anim_id: str, raw: Any, errors: list[str]) -> SpriteAnimation:
    if not isinstance(raw, dict):
        errors.append(f"sprites.*.anims.{anim_id} must be an object")
        return SpriteAnimation(anim_id=anim_id, speed=0.5, anim_type="loop", frames=[])
    speed_raw = raw.get("speed", 0.5)
    try:
        speed = float(speed_raw)
    except (TypeError, ValueError):
        errors.append(f"sprites.*.anims.{anim_id}.speed must be numeric")
        speed = 0.5
    if speed <= 0:
        errors.append(f"sprites.*.anims.{anim_id}.speed must be > 0")
        speed = 0.5
    anim_type = str(raw.get("type", "loop")).strip().lower()
    if anim_type not in ANIM_TYPES:
        errors.append(f"sprites.*.anims.{anim_id}.type must be one of {sorted(ANIM_TYPES)}")
        anim_type = "loop"
    frames_raw = raw.get("frames", [])
    if not isinstance(frames_raw, list) or not frames_raw:
        errors.append(f"sprites.*.anims.{anim_id}.frames must be a non-empty list")
        return SpriteAnimation(anim_id=anim_id, speed=speed, anim_type=anim_type, frames=[])
    frames: list[FrameCoord] = []
    for idx, frame in enumerate(frames_raw):
        try:
            frames.append(parse_frame_token(str(frame)))
        except SpriteValidationError:
            errors.append(f"sprites.*.anims.{anim_id}.frames[{idx}] invalid token '{frame}'")
    return SpriteAnimation(anim_id=anim_id, speed=speed, anim_type=anim_type, frames=frames)


def _normalize_sprite(sprite_id: str, raw: Any, errors: list[str]) -> SpriteEntry:
    if not isinstance(raw, dict):
        errors.append(f"sprites.{sprite_id} must be an object")
        return SpriteEntry(sprite_id=sprite_id, default_frame=None, anims={})
    default_frame_raw = raw.get("default_frame")
    default_frame = None
    if default_frame_raw is not None:
        try:
            default_frame = parse_frame_token(str(default_frame_raw))
        except SpriteValidationError:
            errors.append(f"sprites.{sprite_id}.default_frame invalid token '{default_frame_raw}'")
    anims_raw = raw.get("anims", {}) or {}
    if not isinstance(anims_raw, dict):
        errors.append(f"sprites.{sprite_id}.anims must be an object")
        anims_raw = {}
    anims: dict[str, SpriteAnimation] = {}
    for anim_id, anim_raw in anims_raw.items():
        normalized = _normalize_anim(str(anim_id), anim_raw, errors)
        anims[str(anim_id)] = normalized
    if default_frame is None and anims:
        first_anim = next(iter(anims.values()))
        if first_anim.frames:
            default_frame = first_anim.frames[0]
    return SpriteEntry(sprite_id=sprite_id, default_frame=default_frame, anims=anims)


def load_sprite_set(scope: str, filename: str, image_path: Path, yaml_path: Path) -> SpriteSet:
    errors: list[str] = []
    if not image_path.exists():
        errors.append(f"missing image file: {image_path}")
    if not yaml_path.exists():
        errors.append(f"missing yaml file: {yaml_path}")
    if errors:
        raise SpriteValidationError("invalid sprite set", errors=errors)
    with yaml_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise SpriteValidationError("sprite definition must be a mapping")
    frame_width = _validate_positive_int(loaded.get("frame_width"), "frame_width", errors)
    frame_height = _validate_positive_int(loaded.get("frame_height"), "frame_height", errors)
    background_color = _normalize_background_color(loaded.get("background_color"), errors)
    sprites_raw = loaded.get("sprites", {})
    if not isinstance(sprites_raw, dict) or not sprites_raw:
        errors.append("sprites must be a non-empty mapping")
        sprites_raw = {}
    sprites: dict[str, SpriteEntry] = {}
    for sprite_id, sprite_raw in sprites_raw.items():
        normalized = _normalize_sprite(str(sprite_id), sprite_raw, errors)
        sprites[str(sprite_id)] = normalized
    if errors:
        raise SpriteValidationError("sprite schema validation failed", errors=errors)
    return SpriteSet(
        scope=scope,
        filename=filename,
        image_path=image_path,
        yaml_path=yaml_path,
        frame_width=frame_width,
        frame_height=frame_height,
        background_color=background_color,
        sprites=sprites,
        label=str(loaded.get("label", "") or ""),
        description=str(loaded.get("description", "") or ""),
    )


def parse_sprite_reference(asset_value: str) -> SpriteReference | None:
    if not isinstance(asset_value, str) or not asset_value.startswith("$"):
        return None
    body = asset_value[1:]
    scope_hint = None
    if body.startswith("/"):
        scope_hint = "server"
        body = body[1:]
    parts = body.split("/")
    if not parts[0]:
        raise SpriteValidationError("sprite reference missing filename")
    if len(parts) > 4:
        raise SpriteValidationError("sprite reference has too many segments")
    p = parts + [""] * (4 - len(parts))
    return SpriteReference(
        raw=asset_value,
        scope_hint=scope_hint,
        filename=p[0],
        sprite_id=p[1] or None,
        anim_id=p[2] or None,
        frame_selector=p[3] or None,
    )


def _selected_frame(
    sprite_set: SpriteSet,
    sprite: SpriteEntry,
    anim: SpriteAnimation | None,
    frame_selector: str | None,
) -> FrameCoord:
    if frame_selector:
        if FRAME_TOKEN_RE.match(frame_selector):
            return parse_frame_token(frame_selector)
        if anim is None:
            raise SpriteValidationError("frame index selector requires an animation")
        try:
            frame_idx = int(frame_selector)
        except ValueError as err:
            raise SpriteValidationError(f"invalid frame selector '{frame_selector}'") from err
        if frame_idx < 0 or frame_idx >= len(anim.frames):
            raise SpriteValidationError(f"animation frame index out of range: {frame_selector}")
        return anim.frames[frame_idx]
    if anim is not None and anim.frames:
        return anim.frames[0]
    if sprite.default_frame is not None:
        return sprite.default_frame
    return FrameCoord(0, 0)


class SpriteRepository:
    def __init__(self, world_root_path: Path, server_root_path: Path | None = None):
        self.world_root_path = Path(world_root_path)
        self.server_root_path = Path(server_root_path) if server_root_path else Path(__file__).parent.parent / "data" / "sprites"
        self.world_sprites_path = self.world_root_path / "sprites"
        self._index: dict[tuple[str, str], SpriteSetRecord] = {}

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
            record = SpriteSetRecord(scope=scope, filename=stem, image_path=image_path, yaml_path=yaml_path, sprite_set=None)
            if record.has_image and record.has_yaml and image_path is not None and yaml_path is not None:
                try:
                    record.sprite_set = load_sprite_set(scope, stem, image_path, yaml_path)
                except SpriteValidationError as err:
                    record.load_error = "; ".join(err.errors)
            self._index[(scope, stem)] = record

    def reindex(self) -> None:
        self._index = {}
        self._scan_scope("server", self.server_root_path)
        self._scan_scope("world", self.world_sprites_path)

    def list_sets(self) -> list[SpriteSetRecord]:
        out = list(self._index.values())
        out.sort(key=lambda rec: (rec.filename, 0 if rec.scope == "world" else 1, rec.scope))
        return out

    def get(self, scope: str, filename: str) -> SpriteSetRecord | None:
        return self._index.get((scope, filename))

    def lookup(self, filename: str, scope_hint: str | None = None) -> SpriteSetRecord | None:
        if scope_hint in {"world", "server"}:
            return self.get(scope_hint, filename)
        return self.get("world", filename) or self.get("server", filename)


def resolve_sprite_reference(reference: SpriteReference, repository: SpriteRepository) -> dict[str, Any]:
    record = repository.lookup(reference.filename, scope_hint=reference.scope_hint)
    if record is None:
        raise SpriteValidationError(f"sprite set '{reference.filename}' not found")
    if record.sprite_set is None:
        if record.load_error:
            raise SpriteValidationError(record.load_error)
        raise SpriteValidationError(f"sprite set '{reference.filename}' has no valid yaml definition")
    sprite_set = record.sprite_set
    sprite_id = reference.sprite_id or next(iter(sprite_set.sprites))
    sprite = sprite_set.sprites.get(sprite_id)
    if sprite is None:
        raise SpriteValidationError(f"sprite '{sprite_id}' not found in '{record.filename}'")
    anim = None
    if reference.anim_id:
        anim = sprite.anims.get(reference.anim_id)
        if anim is None:
            raise SpriteValidationError(f"animation '{reference.anim_id}' not found for sprite '{sprite_id}'")
    selected = _selected_frame(sprite_set, sprite, anim, reference.frame_selector)
    payload: dict[str, Any] = {
        "ref": reference.raw,
        "scope": sprite_set.scope,
        "filename": sprite_set.filename,
        "sprite_id": sprite_id,
        "image_url": f"/sprites/{sprite_set.scope}/{sprite_set.image_path.name}",
        "frame_width": sprite_set.frame_width,
        "frame_height": sprite_set.frame_height,
        "background_color": sprite_set.background_color,
        "frame": sprite_set.frame_rect(selected),
    }
    if anim is not None:
        payload["animation"] = {
            "id": anim.anim_id,
            "speed": anim.speed,
            "type": anim.anim_type,
            "frames": [sprite_set.frame_rect(frame) for frame in anim.frames],
        }
    return payload


def to_definition_dict(sprite_set: SpriteSet) -> dict[str, Any]:
    sprites_payload: dict[str, Any] = {}
    for sprite_id, sprite in sprite_set.sprites.items():
        anims_payload: dict[str, Any] = {}
        for anim_id, anim in sprite.anims.items():
            anims_payload[anim_id] = {
                "speed": anim.speed,
                "type": anim.anim_type,
                "frames": [frame.token for frame in anim.frames],
            }
        sprites_payload[sprite_id] = {
            "default_frame": sprite.default_frame.token if sprite.default_frame else "0x0",
            "anims": anims_payload,
        }
    payload = {
        "label": sprite_set.label,
        "description": sprite_set.description,
        "frame_width": sprite_set.frame_width,
        "frame_height": sprite_set.frame_height,
        "sprites": sprites_payload,
    }
    if sprite_set.background_color is not None:
        payload["background_color"] = sprite_set.background_color
    return payload


def validate_definition_document(doc: dict[str, Any], image_path: Path) -> dict[str, Any]:
    if not isinstance(doc, dict):
        raise SpriteValidationError("definition must be an object")
    with tempfile.TemporaryDirectory(prefix="tinyrooms-sprite-validate-") as tmp:
        tmp_path = Path(tmp)
        yaml_path = tmp_path / "validate.yaml"
        yaml_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
        normalized = load_sprite_set("world", "validate", image_path=image_path, yaml_path=yaml_path)
    return to_definition_dict(normalized)


def write_definition_document(yaml_path: Path, definition: dict[str, Any]) -> None:
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = yaml.safe_dump(definition, sort_keys=False, allow_unicode=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(yaml_path.parent), prefix=".tmp_sprite_", suffix=".yaml") as handle:
        handle.write(serialized)
        tmp_name = handle.name
    Path(tmp_name).replace(yaml_path)
