"""Strict loader for prop effect definitions under ``data/fx``.

An effect is a named, ordered stack of layers applied to a rendered 3D
object. Three layer types are supported today: ``transform`` (animated
transformation of the host), ``material`` (emissive/opacity/colour changes),
and ``particle`` (a procedural overlay such as smoke, fire, or sparks).
Effect definitions are pure client-render metadata; the server only
validates and serializes them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.content.common import ContentError, load_yaml_file, require_mapping


FX_ASSET_PREFIX = "/assets/fx"
TRANSFORM_MOTIONS = frozenset({"bob", "spin", "spin-y", "pulse", "sway", "shake"})
PARTICLE_PRESETS = frozenset({"smoke", "fire", "sparks"})
PARTICLE_ANCHORS = frozenset({"base", "center", "top"})
LAYER_TYPES = frozenset({"transform", "material", "particle"})
TEXTURE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})


def effect_texture_url(texture_name: str) -> str:
    """Return the served URL for a texture that lives beside its effect YAML."""

    return f"{FX_ASSET_PREFIX}/{texture_name}"


def _number(
    raw_value: Any,
    label: str,
    *,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if raw_value is None:
        value = default
    elif isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise ContentError(f"{label} must be a number.")
    else:
        value = float(raw_value)
    if minimum is not None and value < minimum:
        raise ContentError(f"{label} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise ContentError(f"{label} must be at most {maximum}.")
    return value


def _integer(raw_value: Any, label: str, *, default: int, minimum: int = 0) -> int:
    value = _number(raw_value, label, default=float(default), minimum=float(minimum))
    return int(value)


def _color(raw_value: Any, label: str, *, default: str) -> str:
    if raw_value is None:
        return default
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ContentError(f"{label} must be a colour string.")
    return raw_value.strip()


def _range(
    raw_value: Any,
    label: str,
    *,
    default: tuple[float, float],
    minimum: float = 0.0,
) -> tuple[float, float]:
    if raw_value is None:
        return default
    if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
        return (float(raw_value), float(raw_value))
    if not isinstance(raw_value, list) or len(raw_value) != 2:
        raise ContentError(f"{label} must be a number or a [start, end] pair.")
    start = _number(raw_value[0], f"{label} start", default=0.0, minimum=minimum)
    end = _number(raw_value[1], f"{label} end", default=0.0, minimum=minimum)
    return (start, end)


def _vec3(raw_value: Any, label: str, *, default: tuple[float, float, float]) -> tuple[float, float, float]:
    if raw_value is None:
        return default
    if not isinstance(raw_value, list) or len(raw_value) != 3:
        raise ContentError(f"{label} must be a 3-item list.")
    return (
        _number(raw_value[0], f"{label} x", default=0.0),
        _number(raw_value[1], f"{label} y", default=0.0),
        _number(raw_value[2], f"{label} z", default=0.0),
    )


@dataclass(frozen=True, slots=True)
class TransformLayer:
    """Animated transformation applied to the effect host."""

    motion: str
    amplitude: float
    period: float
    phase: float
    axis: tuple[float, float, float]

    def serialize(self) -> dict[str, object]:
        return {
            "type": "transform",
            "motion": self.motion,
            "amplitude": self.amplitude,
            "period": self.period,
            "phase": self.phase,
            "axis": list(self.axis),
        }


@dataclass(frozen=True, slots=True)
class MaterialLayer:
    """Emissive/opacity/colour changes applied to the host's meshes."""

    emissive: str | None
    emissive_intensity: float
    color: str | None
    opacity: float | None
    flicker: float
    flicker_hz: float

    def serialize(self) -> dict[str, object]:
        return {
            "type": "material",
            "emissive": self.emissive,
            "emissive_intensity": self.emissive_intensity,
            "color": self.color,
            "opacity": self.opacity,
            "flicker": self.flicker,
            "flicker_hz": self.flicker_hz,
        }


@dataclass(frozen=True, slots=True)
class ParticleLayer:
    """A procedural particle overlay emitted from an anchor on the host."""

    preset: str
    texture_name: str
    rate: float
    lifetime: tuple[float, float]
    size: tuple[float, float]
    speed: float
    spread: float
    gravity: float
    color: str
    opacity: tuple[float, float]
    additive: bool
    max_particles: int
    anchor: str
    offset: tuple[float, float, float]

    def serialize(self) -> dict[str, object]:
        return {
            "type": "particle",
            "preset": self.preset,
            "texture_url": effect_texture_url(self.texture_name),
            "rate": self.rate,
            "lifetime": list(self.lifetime),
            "size": list(self.size),
            "speed": self.speed,
            "spread": self.spread,
            "gravity": self.gravity,
            "color": self.color,
            "opacity": list(self.opacity),
            "additive": self.additive,
            "max_particles": self.max_particles,
            "anchor": self.anchor,
            "offset": list(self.offset),
        }


EffectLayer = TransformLayer | MaterialLayer | ParticleLayer


@dataclass(frozen=True, slots=True)
class EffectDefinition:
    """One named effect made of ordered layers."""

    id: str
    label: str
    layers: tuple[EffectLayer, ...]

    def serialize(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "layers": [layer.serialize() for layer in self.layers],
        }


def _load_transform_layer(raw_layer: Mapping[str, Any], effect_id: str, index: int) -> TransformLayer:
    label = f"Effect '{effect_id}' layer {index} transform"
    motion = str(raw_layer.get("motion", "")).strip()
    if motion not in TRANSFORM_MOTIONS:
        raise ContentError(
            f"{label} has unknown motion '{motion}'. Expected one of {', '.join(sorted(TRANSFORM_MOTIONS))}."
        )
    default_amplitude = 0.35 if motion in {"pulse"} else 0.08
    return TransformLayer(
        motion=motion,
        amplitude=_number(raw_layer.get("amplitude"), f"{label} amplitude", default=default_amplitude, minimum=0.0),
        period=_number(raw_layer.get("period"), f"{label} period", default=3.0, minimum=0.05),
        phase=_number(raw_layer.get("phase"), f"{label} phase", default=0.0),
        axis=_vec3(raw_layer.get("axis"), f"{label} axis", default=(0.0, 1.0, 0.0)),
    )


def _load_material_layer(raw_layer: Mapping[str, Any], effect_id: str, index: int) -> MaterialLayer:
    label = f"Effect '{effect_id}' layer {index} material"
    raw_emissive = raw_layer.get("emissive")
    raw_opacity = raw_layer.get("opacity")
    opacity = None if raw_opacity is None else _number(raw_opacity, f"{label} opacity", default=1.0, minimum=0.0, maximum=1.0)
    return MaterialLayer(
        emissive=_color(raw_emissive, f"{label} emissive", default="") or None,
        emissive_intensity=_number(
            raw_layer.get("emissive_intensity"), f"{label} emissive_intensity", default=1.0, minimum=0.0
        ),
        color=_color(raw_layer.get("color"), f"{label} color", default="") or None,
        opacity=opacity,
        flicker=_number(raw_layer.get("flicker"), f"{label} flicker", default=0.0, minimum=0.0, maximum=1.0),
        flicker_hz=_number(raw_layer.get("flicker_hz"), f"{label} flicker_hz", default=6.0, minimum=0.0),
    )


def _load_particle_layer(
    raw_layer: Mapping[str, Any],
    effect_id: str,
    index: int,
    base_dir: Path,
) -> ParticleLayer:
    label = f"Effect '{effect_id}' layer {index} particle"
    preset = str(raw_layer.get("preset", "")).strip()
    if preset not in PARTICLE_PRESETS:
        raise ContentError(
            f"{label} has unknown preset '{preset}'. Expected one of {', '.join(sorted(PARTICLE_PRESETS))}."
        )
    texture_name = str(raw_layer.get("texture", "")).strip()
    if not texture_name:
        raise ContentError(f"{label} is missing its texture.")
    if not (base_dir / texture_name).is_file():
        raise ContentError(f"{label} references missing texture '{texture_name}'.")
    anchor = str(raw_layer.get("anchor", "top")).strip() or "top"
    if anchor not in PARTICLE_ANCHORS:
        raise ContentError(
            f"{label} has unknown anchor '{anchor}'. Expected one of {', '.join(sorted(PARTICLE_ANCHORS))}."
        )
    return ParticleLayer(
        preset=preset,
        texture_name=texture_name,
        rate=_number(raw_layer.get("rate"), f"{label} rate", default=6.0, minimum=0.0),
        lifetime=_range(raw_layer.get("lifetime"), f"{label} lifetime", default=(1.5, 2.5), minimum=0.05),
        size=_range(raw_layer.get("size"), f"{label} size", default=(0.3, 0.8), minimum=0.0),
        speed=_number(raw_layer.get("speed"), f"{label} speed", default=0.3, minimum=0.0),
        spread=_number(raw_layer.get("spread"), f"{label} spread", default=30.0, minimum=0.0, maximum=180.0),
        gravity=_number(raw_layer.get("gravity"), f"{label} gravity", default=0.0),
        color=_color(raw_layer.get("color"), f"{label} color", default="#ffffff"),
        opacity=_range(raw_layer.get("opacity"), f"{label} opacity", default=(0.7, 0.0), minimum=0.0),
        additive=bool(raw_layer.get("additive", False)),
        max_particles=_integer(raw_layer.get("max_particles"), f"{label} max_particles", default=40, minimum=1),
        anchor=anchor,
        offset=_vec3(raw_layer.get("offset"), f"{label} offset", default=(0.0, 0.0, 0.0)),
    )


def _load_layer(raw_layer: Any, effect_id: str, index: int, base_dir: Path) -> EffectLayer:
    if not isinstance(raw_layer, dict):
        raise ContentError(f"Effect '{effect_id}' layer {index} must be a mapping.")
    layer_type = str(raw_layer.get("type", "")).strip()
    if layer_type not in LAYER_TYPES:
        raise ContentError(
            f"Effect '{effect_id}' layer {index} has unknown type '{layer_type}'. "
            f"Expected one of {', '.join(sorted(LAYER_TYPES))}."
        )
    if layer_type == "transform":
        return _load_transform_layer(raw_layer, effect_id, index)
    if layer_type == "material":
        return _load_material_layer(raw_layer, effect_id, index)
    return _load_particle_layer(raw_layer, effect_id, index, base_dir)


def load_effect_definition(fx_file: Path, payload: Mapping[str, Any]) -> EffectDefinition:
    """Validate and build one effect definition from a raw YAML mapping.

    The effect id must match the YAML filename stem; particle textures resolve
    relative to the file's directory. Shared by the content loader and the Prop
    Editor so both enforce identical rules.
    """

    effect_id = str(payload.get("id", "")).strip() or fx_file.stem
    if effect_id != fx_file.stem:
        raise ContentError(f"{fx_file} id '{effect_id}' must match its filename '{fx_file.stem}'.")
    raw_layers = payload.get("layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        raise ContentError(f"Effect '{effect_id}' must define a non-empty layers list.")
    layers = tuple(
        _load_layer(raw_layer, effect_id, index, fx_file.parent)
        for index, raw_layer in enumerate(raw_layers)
    )
    return EffectDefinition(
        id=effect_id,
        label=str(payload.get("label", effect_id)).strip() or effect_id,
        layers=layers,
    )


def load_effect_catalog(root: Path | None) -> dict[str, EffectDefinition]:
    """Load every ``data/fx/*.yaml`` effect definition, keyed by id."""

    if root is None:
        return {}
    fx_root = Path(root)
    if not fx_root.is_dir():
        return {}
    effects: dict[str, EffectDefinition] = {}
    for fx_file in sorted(fx_root.glob("*.yaml")):
        payload = require_mapping(load_yaml_file(fx_file), fx_file)
        effect_id = str(payload.get("id", "")).strip() or fx_file.stem
        if effect_id in effects:
            raise ContentError(f"Duplicate effect id '{effect_id}'.")
        effects[effect_id] = load_effect_definition(fx_file, payload)
    return effects
