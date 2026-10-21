"""Generic persistent decals attached to peep profiles."""

from __future__ import annotations

from collections.abc import Mapping


MAX_DECALS = 8
MAX_DECAL_COUNT = 99
MAX_DECAL_COLOR_LENGTH = 32


def _normalize_decal(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, Mapping):
        return None
    decal_id = str(raw.get("id", "")).strip()
    kind = str(raw.get("kind", "")).strip()
    if not decal_id or not kind:
        return None
    try:
        count = max(1, min(MAX_DECAL_COUNT, int(raw.get("count", 1) or 1)))
    except (TypeError, ValueError):
        count = 1
    color = str(raw.get("color", "")).strip()[:MAX_DECAL_COLOR_LENGTH]
    data = raw.get("data")
    payload: dict[str, object] = {
        "id": decal_id,
        "kind": kind,
        "count": count,
        "color": color,
    }
    if isinstance(data, Mapping):
        payload["data"] = {str(key): value for key, value in data.items()}
    return payload


def normalize_decals(raw: object) -> tuple[dict[str, object], ...]:
    """Return a bounded, deduplicated decal list safe for JSON persistence."""

    if not isinstance(raw, (list, tuple)):
        return ()
    decals: list[dict[str, object]] = []
    seen: set[str] = set()
    for entry in raw:
        decal = _normalize_decal(entry)
        if decal is None or decal["id"] in seen:
            continue
        seen.add(str(decal["id"]))
        decals.append(decal)
        if len(decals) >= MAX_DECALS:
            break
    return tuple(decals)


def upsert_decal(raw: object, incoming: object) -> tuple[dict[str, object], ...]:
    """Replace a decal with the same id or append it, keeping the newest eight."""

    decal = _normalize_decal(incoming)
    if decal is None:
        return normalize_decals(raw)
    existing = [entry for entry in normalize_decals(raw) if entry["id"] != decal["id"]]
    existing.append(decal)
    return tuple(existing[-MAX_DECALS:])


def clear_decals(raw: object, *, kind: str | None = None) -> tuple[dict[str, object], ...]:
    """Remove every decal, or only decals matching *kind*."""

    decals = normalize_decals(raw)
    if kind is None:
        return ()
    return tuple(entry for entry in decals if entry["kind"] != kind)


def decals_payload(raw: object) -> list[dict[str, object]]:
    """Serialize a decal collection for snapshots and events."""

    return [dict(entry) for entry in normalize_decals(raw)]
