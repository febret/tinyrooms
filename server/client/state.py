"""Client-side state store ported from app/js/state.js (reducer branches used by tests)."""

from __future__ import annotations

import re
from uuid import uuid4

BUBBLE_LIMIT = 120
REDUCED_MOTION = False

QUIET_ACK_PATTERN = re.compile(r"^\.(?:say|help|look|settings)(?:\s|$)")


def _asset_or_empty(value) -> str:
    return value if isinstance(value, str) and value else ""


def _normalize_quick_actions(actions) -> list[dict]:
    return [
        {"label": item["label"], "command": item["command"]}
        for item in (actions or [])
        if isinstance(item, dict) and isinstance(item.get("command"), str) and isinstance(item.get("label"), str)
    ]


def _normalize_card_definition(definition) -> dict | None:
    if not definition:
        return None
    return {
        "id": str(definition.get("id") or ""),
        "label": str(definition.get("label") or definition.get("id") or "Card"),
        "description": str(definition.get("description") or ""),
        "type": str(definition.get("type") or ""),
        "collectible": bool(definition.get("collectible")),
        "decorative": bool(definition.get("decorative")),
        "stackLimit": int(definition.get("stack_limit") or 1),
        "oneUse": bool(definition.get("one_use")),
        "passive": bool(definition.get("passive")),
        "imageUrl": _asset_or_empty(definition.get("image_url")),
        "rarity": str(definition.get("rarity") or ""),
        "target": str(definition.get("target") or ""),
        "effect": str(definition.get("effect") or ""),
        "amount": int(definition.get("amount") or 0),
        "duration": int(definition.get("duration") or 0),
        "category": str(definition.get("category") or ""),
        "rank": str(definition.get("rank") or ""),
        "bonuses": definition.get("bonuses") if isinstance(definition.get("bonuses"), dict) else {},
        "quest": bool(definition.get("quest")),
    }


def _normalize_inventory_stack(stack) -> dict:
    stack = stack or {}
    return {
        "stackId": str(stack.get("stack_id") or ""),
        "scope": str(stack.get("scope") or ""),
        "worldId": str(stack.get("world_id") or "") if stack.get("world_id") else "",
        "quantity": int(stack.get("quantity") or 0),
        "equipped": bool(stack.get("equipped")),
        "pinned": bool(stack.get("pinned")),
        "definition": _normalize_card_definition(stack.get("definition")),
        "quickActions": _normalize_quick_actions(stack.get("quick_actions")),
    }


def _normalize_room_card(stack) -> dict:
    stack = stack or {}
    return {
        "stackId": str(stack.get("stack_id") or ""),
        "quantity": int(stack.get("quantity") or 0),
        "pinned": bool(stack.get("pinned")),
        "position": list(stack["position"]) if isinstance(stack.get("position"), list) else [50, 50, 0],
        "definition": _normalize_card_definition(stack.get("definition")),
        "quickActions": _normalize_quick_actions(stack.get("quick_actions")),
    }


def _normalize_activity(activity) -> dict | None:
    if not activity:
        return None
    return {
        "id": str(activity.get("id") or ""),
        "kind": str(activity.get("kind") or ""),
        "title": str(activity.get("title") or "Activity"),
        "iframeUrl": _asset_or_empty(activity.get("iframe_url")),
        "bridgeUrl": _asset_or_empty(activity.get("bridge_url")),
        "roomBound": bool(activity.get("room_bound")),
        "roomId": str(activity.get("room_id") or ""),
        "attention": bool(activity.get("attention")),
    }


def _normalize_chat_entry(entry) -> dict:
    entry = entry or {}
    return {
        "id": str(uuid4()),
        "speakerId": str(entry.get("speaker_id") or ""),
        "speaker": str(entry.get("speaker") or entry.get("username") or "System"),
        "style": str(entry.get("style") or "normal"),
        "text": str(entry.get("text") or ""),
        "kind": "chat" if entry.get("speaker") or entry.get("username") else "system",
    }


def _normalize_room(room) -> dict | None:
    if not room:
        return None
    return {
        "id": str(room.get("id") or ""),
        "label": str(room.get("label") or "Room"),
        "description": str(room.get("description") or ""),
        "board": {
            "type": str((room.get("board") or {}).get("type") or ""),
            "imageUrl": _asset_or_empty((room.get("board") or {}).get("image_url")),
            "imageStyle": str((room.get("board") or {}).get("image_style") or ""),
            "palette": list((room.get("board") or {}).get("palette") or []),
            "dark": bool((room.get("board") or {}).get("dark")),
        },
        "note": str((room.get("metadata") or {}).get("note") or ""),
        "exits": list(room.get("exits") or []),
        "props": list(room.get("props") or []),
        "occupants": list(room.get("occupants") or []),
        "npcs": list(room.get("npcs") or []),
        "roomCards": [_normalize_room_card(stack) for stack in (room.get("room_cards") or [])],
        "chatHistory": [_normalize_chat_entry(entry) for entry in (room.get("chat_history") or [])],
        "inventory": [_normalize_inventory_stack(stack) for stack in (room.get("inventory") or [])],
        "favorites": list(room.get("favorites") or []),
        "quickActions": _normalize_quick_actions(room.get("quick_actions")),
        "seq": int(room.get("seq") or 0),
    }


def _core_card(card_id: str, label: str, description: str, image_name: str) -> dict:
    return {"id": card_id, "label": label, "description": description, "type": "core", "imageUrl": f"/assets/base/{image_name}"}


CORE_CARDS = {
    "room": _core_card("room", "Room", "List the cards placed in the current room.", "room.webp"),
    "inventory": _core_card("inventory", "Inventory", "Browse the cards you own in this world.", "inventory.webp"),
    "emotes": _core_card("emotes", "Emotes", "See expression and animation cards you own.", "emotes.webp"),
    "skills": _core_card("skills", "Skills", "Your skill collection. Skill slots are not available yet.", "skills.webp"),
    "journal": _core_card("journal", "Journal", "A place for your tasks and memories. Coming in a later milestone.", "journal.webp"),
    "self": _core_card("self", "Self", "Check your current counters, Bops, and Kudos.", "self.webp"),
    "friends": _core_card("friends", "Friends", "A place to keep in touch. Friend lists are not available yet.", "friends.webp"),
}

CORE_ORDER = ["room", "emotes", "inventory", "skills", "journal", "self", "friends"]


def _toast_record(message: str, tone: str = "info") -> dict:
    return {"id": str(uuid4()), "message": str(message or ""), "tone": tone}


def _apply_bubble(peeps: list[dict], key: str, label: str, text: str, style: str) -> list[dict]:
    updated: list[dict] = []
    for peep in peeps:
        match = peep["id"] == key or str(peep.get("username") or "").lower() == str(label or "").lower()
        if not match:
            updated.append(peep)
            continue
        combined = f"{peep['bubble']['text']}\n{text}" if peep.get("bubble") and not peep.get("bubbleDismissed") else text
        trimmed = combined[-BUBBLE_LIMIT:] if len(combined) > BUBBLE_LIMIT else combined
        updated.append({**peep, "bubble": {"text": trimmed, "style": style}, "bubbleDismissed": False})
    return updated


def _as_system_history(text: str) -> dict:
    return {"id": str(uuid4()), "kind": "system", "speaker": "", "speakerId": "", "style": "normal", "text": text}


def _apply_server_event(state: dict, event) -> dict:
    if not event or not state.get("room"):
        return state
    event_type = event.get("type")
    if event_type == "chat.message":
        updated_occupants = _apply_bubble(
            state["room"]["occupants"],
            str(event.get("speaker_id") or ""),
            event.get("speaker"),
            str(event.get("text") or ""),
            str(event.get("style") or "normal"),
        )
        updated_npcs = _apply_bubble(
            state["room"]["npcs"],
            str(event.get("speaker_id") or ""),
            event.get("speaker"),
            str(event.get("text") or ""),
            str(event.get("style") or "normal"),
        )
        return {
            **state,
            "room": {
                **state["room"],
                "occupants": updated_occupants,
                "npcs": updated_npcs,
                "chatHistory": (state["room"]["chatHistory"] + [_normalize_chat_entry(event)])[-50:],
            },
        }
    if event_type == "presence.enter":
        return {
            **state,
            "room": {
                **state["room"],
                "chatHistory": (state["room"]["chatHistory"] + [_as_system_history(f"{event['username']} entered.")])[-50:],
            },
        }
    if event_type == "presence.leave":
        return {
            **state,
            "room": {
                **state["room"],
                "chatHistory": (state["room"]["chatHistory"] + [_as_system_history(f"{event['username']} left.")])[-50:],
            },
        }
    if event_type == "room.card.added" and event.get("stack"):
        return {
            **state,
            "room": {
                **state["room"],
                "roomCards": state["room"]["roomCards"] + [_normalize_room_card(event["stack"])],
                "chatHistory": (state["room"]["chatHistory"] + [_as_system_history(f"{event.get('dropped_by') or 'Someone'} dropped a card.")])[-50:],
            },
        }
    if event_type == "room.card.updated":
        return {
            **state,
            "room": {
                **state["room"],
                "roomCards": [
                    {**card, "quantity": int(event.get("quantity") or 0)} if card["stackId"] == event.get("stack_id") else card
                    for card in state["room"]["roomCards"]
                ],
                "chatHistory": (state["room"]["chatHistory"] + [_as_system_history(f"{event.get('picked_up_by') or 'Someone'} picked up a card.")])[-50:],
            },
        }
    if event_type == "room.card.removed":
        return {
            **state,
            "room": {
                **state["room"],
                "roomCards": [card for card in state["room"]["roomCards"] if card["stackId"] != event.get("stack_id")],
                "chatHistory": (state["room"]["chatHistory"] + [_as_system_history(f"{event.get('picked_up_by') or 'Someone'} picked up the last card.")])[-50:],
            },
        }
    return state


def _merge_result_payload(state: dict, payload) -> dict:
    if not payload:
        return state
    next_state = state
    if isinstance(payload.get("commands"), list):
        catalog = []
        for item in payload["commands"]:
            name = str(item.get("name") or "")
            catalog.append({
                "name": name if name.startswith(".") or name.startswith("\\") else f".{name}",
                "summary": str(item.get("summary") or ""),
            })
        next_state = {**next_state, "commandCatalog": catalog}
    if isinstance(payload.get("inventory"), list):
        inventory = [_normalize_inventory_stack(stack) for stack in payload["inventory"]]
        next_state = {
            **next_state,
            "user": {**next_state["user"], "inventory": inventory} if next_state.get("user") else next_state["user"],
            "room": {**next_state["room"], "inventory": inventory} if next_state.get("room") else next_state["room"],
        }
    if isinstance(payload.get("favorites"), list):
        favorites = list(payload["favorites"])
        next_state = {
            **next_state,
            "user": {**next_state["user"], "favorites": favorites} if next_state.get("user") else next_state["user"],
            "room": {**next_state["room"], "favorites": favorites} if next_state.get("room") else next_state["room"],
        }
    return next_state


def _dismiss_invalid_selection(state: dict) -> dict:
    if not state.get("room"):
        return state
    room_cards = state["room"]["roomCards"]
    inventory = state["room"]["inventory"]
    all_cards = room_cards + inventory
    if state["views"].get("details") and not any(card["stackId"] == state["views"]["details"] for card in all_cards):
        state = {**state, "views": {**state["views"], "details": None}}
    if state["selection"].get("kind") == "room-card" and not any(card["stackId"] == state["selection"]["id"] for card in room_cards):
        return {**state, "selection": {"kind": "room", "id": state["room"]["id"]}, "views": {**state["views"], "details": None}}
    if state["selection"].get("kind") == "inventory-card" and not any(card["stackId"] == state["selection"]["id"] for card in inventory):
        return {**state, "selection": {"kind": "room", "id": state["room"]["id"]}, "views": {**state["views"], "details": None}}
    if state["selection"].get("kind") == "peep" and not any(
        peep["id"] == state["selection"]["id"] for peep in state["room"]["occupants"] + state["room"]["npcs"]
    ):
        return {**state, "selection": {"kind": "room", "id": state["room"]["id"]}}
    if state["selection"].get("kind") == "prop" and not any(prop["id"] == state["selection"]["id"] for prop in state["room"]["props"]):
        return {**state, "selection": {"kind": "room", "id": state["room"]["id"]}}
    return state


def _normalize_user(user) -> dict | None:
    if not user:
        return None
    return {
        "id": str(user.get("id") or ""),
        "username": str(user.get("username") or "Guest"),
        "sticker": str(user.get("sticker") or ""),
        "stickerUrl": f"/assets/stickers/{user['sticker']}" if user.get("sticker") else "",
        "initialStickerComplete": bool(user.get("initial_sticker_complete")),
        "favorites": list(user.get("favorites") or []),
        "inventory": [_normalize_inventory_stack(stack) for stack in (user.get("inventory") or [])],
        "activity": _normalize_activity(user.get("activity")),
        "showActivityLog": bool(user.get("show_activity_log")),
        "level": int(user.get("level") or 0),
        "kudos": int(user.get("kudos") or 0),
        "bops": int(user.get("bops") or 0),
        "sharedEnergy": int(user.get("shared_energy") or 0),
        "worldId": str(user.get("world_id") or ""),
        "rememberedRoom": str(user.get("remembered_room") or ""),
        "canEnterWorld": user.get("can_enter_world") is not False,
    }


def create_initial_state() -> dict:
    return {
        "sessionChecked": False,
        "loggedIn": False,
        "csrfToken": "",
        "auth": {"mode": "login", "busy": False, "error": ""},
        "transport": {"connected": False, "status": "idle", "message": ""},
        "user": None,
        "room": None,
        "stickers": [],
        "activities": [],
        "selection": {"kind": "none", "id": ""},
        "views": {"auth": True, "main": None, "details": None, "commandPalette": False, "coreExpanded": False},
        "ui": {"actionLogVisible": False, "soundEnabled": True, "reducedMotion": REDUCED_MOTION, "toasts": []},
        "commandCatalog": [],
        "describedEntity": None,
    }


def _reduce(state: dict, action: dict) -> dict:
    action_type = action.get("type")
    if action_type == "session":
        user = _normalize_user(action.get("user"))
        logged_in = bool(action.get("loggedIn"))
        return {
            **state,
            "sessionChecked": True,
            "loggedIn": logged_in,
            "csrfToken": str(action.get("csrfToken") or ""),
            "user": user,
            "room": state["room"] if logged_in else None,
            "activities": [user["activity"]] if user and user.get("activity") else [],
            "ui": {**state["ui"], "actionLogVisible": bool(user and user["showActivityLog"]), "soundEnabled": state["ui"]["soundEnabled"]},
            "views": {"auth": not logged_in, "main": None, "details": None, "commandPalette": False, "coreExpanded": False},
            "auth": {**state["auth"], "busy": False, "error": ""},
            "selection": state["selection"] if logged_in else {"kind": "none", "id": ""},
            "commandCatalog": state["commandCatalog"] if logged_in else [],
            "describedEntity": None,
        }
    if action_type == "select":
        return {**state, "selection": action["selection"]}
    if action_type == "open-view":
        view = action["view"]
        return {**state, "selection": {"kind": "core", "id": view}, "views": {**state["views"], "main": view, "details": None}}
    if action_type == "close-view":
        selection = {"kind": "room", "id": state["room"]["id"]} if state.get("room") else state["selection"]
        return {**state, "selection": selection, "views": {**state["views"], "main": None, "details": None}}
    if action_type == "open-details":
        return {**state, "views": {**state["views"], "details": action["stackId"]}}
    if action_type == "close-details":
        return {**state, "views": {**state["views"], "details": None}}
    if action_type == "dismiss-bubble":
        if not state.get("room"):
            return state

        def mutate(peep: dict) -> dict:
            return {**peep, "bubbleDismissed": True} if peep["id"] == action.get("id") else peep

        return {
            **state,
            "room": {
                **state["room"],
                "occupants": [mutate(peep) for peep in state["room"]["occupants"]],
                "npcs": [mutate(peep) for peep in state["room"]["npcs"]],
            },
        }
    if action_type == "snapshot":
        room = _normalize_room(action.get("room"))
        same_room = bool(room and state.get("room") and room["id"] == state["room"]["id"])
        if same_room:
            previous_peeps = {peep["id"]: peep for peep in state["room"]["occupants"] + state["room"]["npcs"]}
            preserve = lambda peep: {**peep, "bubble": previous_peeps[peep["id"]]["bubble"], "bubbleDismissed": previous_peeps[peep["id"]]["bubbleDismissed"]} if peep["id"] in previous_peeps else peep
            room["occupants"] = [preserve(peep) for peep in room["occupants"]]
            room["npcs"] = [preserve(peep) for peep in room["npcs"]]
            chat_key = lambda entries: tuple(
                (entry.get("speakerId"), entry.get("speaker"), entry.get("style"), entry.get("text"))
                for entry in entries
                if entry.get("kind") == "chat"
            )
            if chat_key(room["chatHistory"]) == chat_key(state["room"]["chatHistory"]):
                room["chatHistory"] = state["room"]["chatHistory"]
        next_state = {
            **state,
            "room": room,
            "selection": state["selection"] if same_room else ({"kind": "room", "id": room["id"]} if room else state["selection"]),
            "views": state["views"] if same_room else {**state["views"], "main": None, "details": None},
            "user": (
                {
                    **state["user"],
                    "rememberedRoom": room["id"] if room else state["user"]["rememberedRoom"],
                    "inventory": room["inventory"] if room else state["user"]["inventory"],
                    "favorites": room["favorites"] if room else state["user"]["favorites"],
                }
                if state.get("user")
                else state["user"]
            ),
        }
        return _dismiss_invalid_selection(next_state)
    if action_type == "result":
        next_state = _merge_result_payload(state, action.get("payload"))
        for event in action.get("events") or []:
            next_state = _apply_server_event(next_state, event)
        message = action.get("message")
        if message and next_state.get("room") and (not next_state["room"]["chatHistory"] or next_state["room"]["chatHistory"][-1]["text"] != message):
            next_state = {**next_state, "room": {**next_state["room"], "chatHistory": (next_state["room"]["chatHistory"] + [_as_system_history(message)])[-50:]}}
        quiet_ack = bool(QUIET_ACK_PATTERN.match(str(action.get("command") or "")))
        if action.get("ok") and message and not quiet_ack:
            next_state = {**next_state, "ui": {**next_state["ui"], "toasts": (next_state["ui"]["toasts"][-2:] + [_toast_record(message, "success")])}}
        if not action.get("ok") and message and not any(item["tone"] == "error" and item["message"] == message for item in next_state["ui"]["toasts"]):
            next_state = {**next_state, "ui": {**next_state["ui"], "toasts": (next_state["ui"]["toasts"][-2:] + [_toast_record(message, "error")])}}
        return _dismiss_invalid_selection(next_state)
    if action_type == "room-event":
        return _dismiss_invalid_selection(_apply_server_event(state, action.get("event")))
    return state


def create_store() -> dict:
    state = create_initial_state()
    listeners = set()

    def get_state() -> dict:
        return state

    def subscribe(listener) -> callable:
        listeners.add(listener)
        listener(state)
        return lambda: listeners.discard(listener)

    def dispatch(action: dict) -> dict:
        nonlocal state
        state = _reduce(state, action)
        for listener in list(listeners):
            listener(state, action)
        return state

    return {"getState": get_state, "subscribe": subscribe, "dispatch": dispatch}


def normalize_room(room) -> dict | None:
    return _normalize_room(room)


def normalize_user(user) -> dict | None:
    return _normalize_user(user)


def find_room_card(state: dict, stack_id: str) -> dict | None:
    room = state.get("room")
    if not room:
        return None
    for card in room.get("roomCards", []):
        if card["stackId"] == stack_id:
            return card
    return None


def find_inventory_card(state: dict, stack_id: str) -> dict | None:
    room = state.get("room")
    if room:
        for card in room.get("inventory", []):
            if card["stackId"] == stack_id:
                return card
    user = state.get("user")
    if user:
        for card in user.get("inventory", []):
            if card["stackId"] == stack_id:
                return card
    return None


def find_selected_entity(state: dict):
    room = state.get("room")
    if not room:
        return None
    selection = state.get("selection", {})
    kind = selection.get("kind")
    if kind == "room":
        return room
    if kind == "core":
        return CORE_CARDS.get(selection.get("id"))
    if kind == "room-card":
        return find_room_card(state, selection.get("id"))
    if kind == "inventory-card":
        return find_inventory_card(state, selection.get("id"))
    if kind == "prop":
        for prop in room.get("props", []):
            if prop["id"] == selection.get("id"):
                return prop
        return None
    if kind == "peep":
        for peep in room.get("occupants", []) + room.get("npcs", []):
            if peep["id"] == selection.get("id"):
                return peep
        return None
    return None