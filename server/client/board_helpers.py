"""Board helper math ported from app/js/board-helpers.js (pure functions only)."""

from __future__ import annotations

import json


def board_position(coordinates=None) -> list[float]:
    """Convert authoritative [horizontal %, depth %, elevation] into board-space XYZ."""
    x, y, z = (list(coordinates) + [50, 50, 0])[:3] if coordinates else [50, 50, 0]
    return [(x - 50) * 0.105, z * 0.1, (y - 50) * 0.085]


def board_signature(room: dict) -> str:
    """Identify visual layout changes only; chat, occupants, actions, and selection are excluded."""
    props = [
        [prop.get("id"), prop.get("propId"), prop.get("label"), prop.get("position"), prop.get("rotation"), prop.get("scale"), prop.get("modelUrl")]
        for prop in (room.get("props") or [])
    ]
    room_cards = [
        [card.get("stackId"), card.get("position"), (card.get("definition") or {}).get("label"), (card.get("definition") or {}).get("imageUrl")]
        for card in (room.get("roomCards") or [])
    ]
    return json.dumps([room.get("id"), room.get("label"), room.get("board"), props, room_cards], separators=(",", ":"))