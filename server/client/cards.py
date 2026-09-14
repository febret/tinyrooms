"""Card selection logic ported from app/js/cards.js (pure functions only)."""

from __future__ import annotations

from server.client.commands import build_favorite_command
from server.client.state import CORE_CARDS, find_inventory_card, find_room_card, find_selected_entity


def _rarity_label(definition) -> str:
    if not definition:
        return "Card"
    return definition.get("rarity") or ("Core" if definition.get("type") == "core" else definition.get("type") or "Card")


def describe_selection(state: dict) -> dict:
    if not state.get("room"):
        return {"tag": "Tinyrooms", "title": "Sign in", "description": "Create an account or log in to enter the world.", "imageUrl": ""}
    selected = find_selected_entity(state)
    if not selected or state.get("selection", {}).get("kind") == "room":
        room = state["room"]
        return {"tag": "Room", "title": room["label"], "description": room["description"] or room.get("note") or "Current room.", "imageUrl": room["board"]["imageUrl"]}
    kind = state["selection"]["kind"]
    if kind == "core":
        return {
            "tag": "Core",
            "title": selected["label"],
            "description": "Your tasks and memories. Not available yet." if state["selection"]["id"] == "journal" else selected["description"],
            "imageUrl": selected["imageUrl"],
        }
    if kind in ("room-card", "inventory-card"):
        return {
            "tag": _rarity_label(selected["definition"]),
            "title": selected["definition"]["label"],
            "description": selected["definition"]["description"],
            "imageUrl": selected["definition"]["imageUrl"],
        }
    if kind == "prop":
        return {"tag": "Prop", "title": selected["label"], "description": selected["description"], "imageUrl": ""}
    if kind == "peep":
        return {
            "tag": "NPC" if selected.get("kind") == "npc" else "Peep",
            "title": selected["label"],
            "description": selected.get("description") or "A peep in this room.",
            "imageUrl": selected.get("stickerUrl", ""),
        }
    return {"tag": "Selection", "title": "Tinyrooms", "description": "", "imageUrl": ""}


def selection_actions(state: dict) -> list[dict]:
    if not state.get("room"):
        return []
    selection = state["selection"]
    kind = selection["kind"]
    if kind == "room":
        room = state["room"]
        actions = [{"label": "Open Room View", "local": {"type": "open-view", "view": "room"}, "tone": "primary"}]
        for action in room.get("quickActions") or []:
            actions.append({**action, "tone": "positive" if action["command"].startswith(".go ") else "neutral"})
        return actions
    if kind == "core":
        if state["selection"]["id"] not in CORE_CARDS:
            return []
        card = CORE_CARDS[state["selection"]["id"]]
        open_label = "Close" if state["views"].get("main") == state["selection"]["id"] else f"Open {card['label']}"
        favorites: list = []
        if state.get("user"):
            favorites = state["user"].get("favorites") or []
        favorite = state["selection"]["id"] in favorites
        return [
            {"label": open_label, "local": {"type": "open-view", "view": state["selection"]["id"]}, "tone": "primary"},
            {"label": "Unfavorite" if favorite else "Favorite", "command": build_favorite_command(state["selection"]["id"]), "tone": "positive"},
        ]
    if kind in ("prop", "peep"):
        entity = find_selected_entity(state)
        return [{**action, "tone": "neutral"} for action in (entity.get("quickActions") or [])] if entity else []
    if kind in ("room-card", "inventory-card"):
        is_room = kind == "room-card"
        stack = find_room_card(state, selection["id"]) if is_room else find_inventory_card(state, selection["id"])
        if not stack:
            return []
        intent = "pickup" if is_room else "drop"
        actions = [{"label": "Inspect", "local": {"type": "open-details", "stackId": stack["stackId"]}, "tone": "primary"}]
        for action in stack.get("quickActions") or []:
            if action["command"].startswith(f".{intent} "):
                actions.append({
                    "label": "Pick up…" if is_room else "Drop…",
                    "local": {"type": "quantity", "stackId": stack["stackId"], "max": stack["quantity"], "intent": intent},
                    "tone": "positive" if is_room else "negative",
                    "disabled": (is_room and stack.get("pinned")) or stack["quantity"] < 1,
                })
            else:
                actions.append({**action, "tone": "neutral"})
        return actions
    return []