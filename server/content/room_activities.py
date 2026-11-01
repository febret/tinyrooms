"""World-authored interactive activities bound to room controller props."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from server.content.common import ContentError


MAX_ACTIVITY_CONFIG_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True)
class RoomActivityDefinition:
    """A room activity whose controller prop owns authoritative state.

    The core validates the controller, reset powers, and JSON-serializable
    configuration. Activity scripts own movement, collisions, scores, effects,
    and rewards; the core only broadcasts their opaque public state to clients.
    """

    kind: str
    controller: str
    reset_powers: tuple[str, ...]
    config: dict[str, object]


def _load_config(raw_config: Any, *, room_id: str) -> dict[str, object]:
    if raw_config is None:
        return {}
    if not isinstance(raw_config, dict):
        raise ContentError(f"Room '{room_id}' activity config must be a mapping.")
    try:
        encoded = json.dumps(raw_config, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ContentError(f"Room '{room_id}' activity config must be JSON-serializable.") from exc
    if len(encoded.encode("utf-8")) > MAX_ACTIVITY_CONFIG_BYTES:
        raise ContentError(f"Room '{room_id}' activity config exceeds the {MAX_ACTIVITY_CONFIG_BYTES}-byte limit.")
    return dict(raw_config)


def load_room_activities(
    raw_activities: Any,
    *,
    room_id: str,
    room_props: Mapping[str, object],
    props: Mapping[str, object],
    power_names: tuple[str, ...],
) -> dict[str, RoomActivityDefinition]:
    """Load one room's activity envelopes, keyed by activity kind.

    Accepts either a mapping of kind to configuration or the legacy single
    ``activity`` mapping with an explicit ``kind`` field.
    """

    if raw_activities is None:
        return {}
    if not isinstance(raw_activities, dict):
        raise ContentError(f"Room '{room_id}' activities must be a mapping.")
    single_keys = {"kind", "controller", "config", "reset_powers"}
    if set(raw_activities) <= single_keys and ("kind" in raw_activities or "controller" in raw_activities):
        activity = load_room_activity(
            raw_activities,
            room_id=room_id,
            room_props=room_props,
            props=props,
            power_names=power_names,
        )
        return {} if activity is None else {activity.kind: activity}
    activities: dict[str, RoomActivityDefinition] = {}
    for raw_kind, raw_activity in raw_activities.items():
        kind = str(raw_kind).strip()
        if not kind:
            raise ContentError(f"Room '{room_id}' contains an empty activity kind.")
        if not isinstance(raw_activity, dict):
            raise ContentError(f"Room '{room_id}' activity '{kind}' must be a mapping.")
        entry = dict(raw_activity)
        configured_kind = str(entry.get("kind", kind)).strip()
        if configured_kind != kind:
            raise ContentError(
                f"Room '{room_id}' activity '{kind}' declares mismatched kind '{configured_kind}'."
            )
        entry["kind"] = kind
        activity = load_room_activity(
            entry,
            room_id=room_id,
            room_props=room_props,
            props=props,
            power_names=power_names,
        )
        if activity is not None:
            activities[activity.kind] = activity
    return activities


def load_room_activity(
    raw_activity: Any,
    *,
    room_id: str,
    room_props: Mapping[str, object],
    props: Mapping[str, object],
    power_names: tuple[str, ...],
) -> RoomActivityDefinition | None:
    """Validate a room's optional activity-state envelope."""

    if raw_activity is None:
        return None
    if not isinstance(raw_activity, dict):
        raise ContentError(f"Room '{room_id}' activity must be a mapping.")
    kind = str(raw_activity.get("kind", "")).strip()
    if not kind:
        raise ContentError(f"Room '{room_id}' activity is missing kind.")
    controller = str(raw_activity.get("controller", "")).strip()
    if not controller:
        raise ContentError(f"Room '{room_id}' activity is missing controller.")
    instance = room_props.get(controller)
    controller_prop = getattr(instance, "prop_id", None)
    if instance is None or not isinstance(controller_prop, str):
        raise ContentError(f"Room '{room_id}' activity controller '{controller}' is not a prop in the room.")
    definition = props.get(controller_prop)
    behavior = getattr(definition, "behavior", None)
    if definition is None or not behavior:
        raise ContentError(f"Room '{room_id}' activity controller '{controller}' has no behavior script.")
    prop_activity = getattr(definition, "activity", None)
    if isinstance(prop_activity, str) and prop_activity and prop_activity != kind:
        raise ContentError(
            f"Room '{room_id}' activity kind '{kind}' does not match controller activity '{prop_activity}'."
        )
    raw_powers = raw_activity.get("reset_powers", list(power_names))
    if not isinstance(raw_powers, list):
        raise ContentError(f"Room '{room_id}' activity reset_powers must be a list.")
    reset_powers: list[str] = []
    for raw_power in raw_powers:
        power = str(raw_power).strip()
        if power not in power_names:
            raise ContentError(f"Room '{room_id}' activity reset power '{power}' is unknown.")
        if power not in reset_powers:
            reset_powers.append(power)
    return RoomActivityDefinition(
        kind=kind,
        controller=controller,
        reset_powers=tuple(reset_powers),
        config=_load_config(raw_activity.get("config"), room_id=room_id),
    )
