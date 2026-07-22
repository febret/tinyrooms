"""Superuser command framework for TinyRooms.

Commands prefixed with ':' are dispatched here.  Each command requires a
specific power (or no power at all for any-user commands).

Output is delivered to the user's Activity Panel via the 'activity_panel'
socket event.  Text in the output may embed clickable command links using the
spec format: [[<display text>|<command>]]
"""
from __future__ import annotations

import shlex
from typing import Any, Callable

from flask_socketio import emit
from .world import active_world


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cmd_link(text: str, command: str) -> str:
    """Return a clickable command link string in the canonical spec format."""
    return f"[[{text}|{command}]]"


def _emit_panel(user_obj: Any, title: str, content: str) -> None:
    """Send activity-panel output to a user."""
    emit("activity_panel", {"mode": "superuser", "title": title, "content": content}, to=user_obj.sid)


def _error_panel(user_obj: Any, message: str) -> None:
    _emit_panel(user_obj, "Error", message)


def _save_world(world: Any) -> None:
    world.save_state(world.ws_id)


def _broadcast_header(room: Any) -> None:
    for room_user in room.users.values():
        room.send_header_view(room_user)


def _emit_inventory_update(user_obj: Any) -> None:
    items = []
    for obj in user_obj.peep.inventory.values():
        obj_info = getattr(obj, "info", {}) or {}
        raw_action = obj_info.get("inventory_action")
        inventory_actions = []
        if isinstance(raw_action, str):
            command_text = raw_action.strip()
            if command_text:
                inventory_actions = [{"label": "Use Item", "commands": command_text}]
        elif isinstance(raw_action, dict):
            command_text = str(raw_action.get("commands") or raw_action.get("command") or "").strip()
            if command_text:
                label = str(raw_action.get("label") or "Action").strip() or "Action"
                inventory_actions = [{"label": label, "commands": command_text}]
        elif isinstance(raw_action, list):
            for idx, entry in enumerate(raw_action, start=1):
                if isinstance(entry, str):
                    command_text = entry.strip()
                    if command_text:
                        inventory_actions.append({
                            "label": "Use Item" if idx == 1 else f"Action {idx}",
                            "commands": command_text,
                        })
                elif isinstance(entry, dict):
                    command_text = str(entry.get("commands") or entry.get("command") or "").strip()
                    if command_text:
                        label = str(entry.get("label") or f"Action {idx}").strip() or f"Action {idx}"
                        inventory_actions.append({"label": label, "commands": command_text})
        items.append({
            "obj_id": obj.obj_id,
            "label": obj.label(),
            "description": obj.description(),
            "display": dict(getattr(obj, "_display_assets", {}) or {}),
            "inventory_actions": inventory_actions,
        })
    emit("inventory_update", {"items": items}, to=user_obj.sid)


def _resolve_action_target(user_obj: Any, target_token: str):
    room = user_obj.room
    if room is None:
        return None, "You are not in a room."
    token = str(target_token or "").strip()
    if not token:
        return None, "missing target"
    if not token.startswith("@"):
        return None, f"invalid target token '{token}'"
    search = token[1:].strip()
    if not search:
        return None, "invalid target token '@'"

    if search.startswith("obj:"):
        obj_id = search[4:].strip()
        if not obj_id:
            return None, "invalid object target"
        room_obj = room.objs.get(obj_id)
        if room_obj is not None:
            return {"type": "object", "entity": room_obj, "target_ref": f"@obj:{obj_id}"}, ""
        inv_obj = user_obj.peep.inventory.get(obj_id)
        if inv_obj is not None:
            return {"type": "inventory", "entity": inv_obj, "target_ref": f"@obj:{obj_id}"}, ""
        return None, f"object '{obj_id}' not found in room or inventory"

    if search.startswith("prop:"):
        prop_id = search[5:].strip()
        if not prop_id:
            return None, "invalid prop target"
        prop_obj = room.props.get(prop_id)
        if prop_obj is None:
            return None, f"prop '{prop_id}' not found"
        return {"type": "prop", "entity": prop_obj, "target_ref": f"@prop:{prop_id}"}, ""

    if search.startswith("peep:"):
        peep_id = search[5:].strip()
        if not peep_id:
            return None, "invalid peep target"
        room_user = room.users.get(peep_id)
        if room_user is not None:
            return {"type": "peep", "entity": room_user.peep, "target_ref": f"@{room_user.username}"}, ""
        room_peep = room.peeps.get(peep_id)
        if room_peep is not None:
            return {"type": "peep", "entity": room_peep, "target_ref": f"@peep:{peep_id}"}, ""
        return None, f"peep '{peep_id}' not found"

    if search.startswith("way:"):
        return None, "ways are not valid targets for this action"

    room_user = room.users.get(search)
    if room_user is not None:
        return {"type": "peep", "entity": room_user.peep, "target_ref": f"@{room_user.username}"}, ""
    room_peep = room.peeps.get(search)
    if room_peep is not None:
        return {"type": "peep", "entity": room_peep, "target_ref": f"@peep:{search}"}, ""
    return None, f"target '{token}' not found"


def _build_look_panel(user_obj: Any, resolved_target):
    from . import text as text_utils

    room = user_obj.room
    if room is None:
        return "Look", "You are not in a room."
    if resolved_target is None:
        return room.label(), text_utils.make_room_description_text(room, user_obj)

    target_type = resolved_target["type"]
    target_entity = resolved_target["entity"]
    target_ref = resolved_target["target_ref"]
    label = target_entity.label() if callable(getattr(target_entity, "label", None)) else target_ref
    description = target_entity.description() if callable(getattr(target_entity, "description", None)) else ""
    description = description or f"You look at {label}."

    if target_type == "object":
        return label, f"Object: {target_ref}\n\n{description}"
    if target_type == "inventory":
        return label, f"Inventory item: {target_ref}\n\n{description}"
    if target_type == "peep":
        peep_type = getattr(target_entity, "type", "user")
        return label, f"Peep ({peep_type}): {target_ref}\n\n{description}"
    if target_type == "prop":
        room = user_obj.room
        exit_way_id = target_entity.metadata.get("exit_way_id")
        exit_text = ""
        if exit_way_id and room is not None:
            exit_way = room.ways.get(exit_way_id)
            exit_label = exit_way.label if exit_way is not None else exit_way_id
            exit_text = f"\n\nExit: {exit_label}"
        return label, f"Prop: {target_ref}\n\n{description}{exit_text}"
    return "Look", description


def _resolve_way_target(user_obj: Any, target_token: str):
    room = user_obj.room
    if room is None:
        return None, "You are not in a room."
    token = str(target_token or "").strip()
    if not token:
        return None, "Go where?"
    raw = token[1:] if token.startswith("@") else token
    if raw.startswith("way:"):
        way_id = raw[4:].strip()
    else:
        way_id = raw.strip()
    if not way_id:
        return None, "Go where?"
    way = room.ways.get(way_id)
    if way is None:
        world_way = active_world().ways.get(way_id)
        if world_way is None or way_id not in room.ways:
            return None, "You can't go that way."
        way = world_way
    return way, ""

# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

# Each entry: (required_power_or_None, handler_fn)
# handler signature: handler(user_obj, args: list[str], world) -> None
_REGISTRY: list[tuple[str, str | None, Callable]] = []


def _cmd(pattern: str, power: str | None = None):
    """Decorator that registers a command handler."""
    def decorator(fn: Callable) -> Callable:
        _REGISTRY.append((pattern, power, fn))
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Command dispatcher
# ---------------------------------------------------------------------------

def dispatch(user_obj: Any, text: str, world: Any) -> bool:
    """Dispatch a ':'-prefixed superuser command.

    Returns True if the text was recognised as a command (even if it errored),
    False if it was not a superuser command at all.
    """
    if not text.startswith(":"):
        return False
    cmd_text = text[1:].strip()

    try:
        tokens = shlex.split(cmd_text)
    except ValueError:
        tokens = cmd_text.split()

    if not tokens:
        _error_panel(user_obj, "Empty command. Type [[:?|:?]] for help.")
        return True

    for pattern, required_power, handler in _REGISTRY:
        if _matches(tokens, pattern):
            if required_power and not user_obj.has_power(required_power):
                _error_panel(user_obj, f"You don't have the '{required_power}' power required for this command.")
                return True
            args = _extract_args(tokens, pattern)
            handler(user_obj, args, world)
            return True

    _error_panel(user_obj, f"Unknown command: :{cmd_text}\nType [[:?|:?]] for help.")
    return True


def _pattern_words(pattern: str) -> list[str]:
    """Split a command pattern into fixed keyword words."""
    return pattern.split()


def _matches(tokens: list[str], pattern: str) -> bool:
    """Check whether tokens match a command pattern.

    A pattern is a space-separated sequence of keywords followed by optional
    <arg> placeholders.  Example: 'room owner set <username>'
    Keywords are matched case-insensitively; placeholders match any token.
    A trailing '...' placeholder consumes all remaining tokens.
    """
    words = _pattern_words(pattern)
    token_idx = 0
    for word in words:
        if word.startswith("<") and word.endswith(">"):
            if token_idx >= len(tokens):
                return False  # required arg missing
            token_idx += 1
        elif word == "...":
            return True  # greedy match of rest
        else:
            if token_idx >= len(tokens):
                return False
            if tokens[token_idx].lower() != word.lower():
                return False
            token_idx += 1
    return token_idx == len(tokens)


def _extract_args(tokens: list[str], pattern: str) -> list[str]:
    """Return only the argument tokens (non-keyword parts) from tokens."""
    words = _pattern_words(pattern)
    args: list[str] = []
    token_idx = 0
    for word in words:
        if word.startswith("<") and word.endswith(">"):
            if token_idx < len(tokens):
                args.append(tokens[token_idx])
            token_idx += 1
        elif word == "...":
            args.extend(tokens[token_idx:])
            break
        else:
            token_idx += 1
    return args


# ---------------------------------------------------------------------------
# Any-user commands
# ---------------------------------------------------------------------------

@_cmd("?")
def _cmd_help(user_obj: Any, args: list[str], world: Any) -> None:
    powers = sorted(user_obj.powers) if user_obj.powers else []
    lines = [
        f"**User:** {user_obj.username}",
        f"**Powers:** {', '.join(powers) if powers else '(none)'}",
        "",
        "**Available commands:**",
        "  [[:?|:?]] — this help",
        "  [[:list users|:list users]] — list all users",
        "  [:go <target>] — go through an exit (@way:<id>)",
        "  [:look [target]] — inspect room or target",
        "  [:pick <target>] — pick up object from room",
        "  [:drop <target> [x y]] — drop inventory object",
        "  [:equip] — show equip panel",
        "  [:self] — show self panel",
        "  [:claim room] — claim current unowned room",
        "  [:use <target>] — default use action feedback",
    ]
    if user_obj.has_power("realtor"):
        lines += [
            "",
            "**Realtor commands:**",
            "  :room owner set <username> — set room owner",
            "  :room owner clear — clear room owner",
            "  :room owner show — show room owner",
            "  :room list — list all rooms",
        ]
    if user_obj.has_power("builder"):
        lines += [
            "",
            "**Builder commands:**",
            "  :room rename <name> — rename current room",
            "  :room describe <text> — set room description",
            "  :room reset — reset room to defaults",
        ]
    if user_obj.has_power("admin"):
        lines += [
            "",
            "**Admin power commands:**",
            "  :power list <username> — show a user's powers",
            "  :power set <username> <power> <grant|remove> — grant/remove a power",
        ]
    if user_obj.has_power("moderator"):
        lines += [
            "",
            "**Moderator commands:**",
            "  :kick <username> — kick user to default room",
            "  :bring <username> — bring user to your room",
            "  :move <username> <room_id> — move user to room",
        ]
    if user_obj.has_power("game-master"):
        lines += [
            "",
            "**Game-master commands:**",
            "  :goto <room_id> — teleport to room",
            "  :spawn <thing_id> — spawn object in current room",
            "  :despawn <obj_id> — remove object from room",
            "  :reset-world — reset all rooms to defaults",
            "  :obj list — list objects in room",
            "  :peep list — list peeps in room",
            "  :prop list — list props in room",
            "  :thing list — list available thing definitions",
        ]
    _emit_panel(user_obj, "Help", "\n".join(lines))


@_cmd("list users")
def _cmd_list_users(user_obj: Any, args: list[str], world: Any) -> None:
    from . import user as user_module
    search = args[0].lower() if args else ""
    lines = ["**Connected users:**"]
    for u in user_module.connected_users.values():
        uname = u.username
        if search and search not in uname.lower():
            continue
        room_id = u.room.room_id if u.room else "?"
        powers = ", ".join(sorted(u.powers)) if u.powers else "none"
        lines.append(f"  {uname} (room: {room_id}, powers: {powers})")
    if len(lines) == 1:
        lines.append("  (no users found)")
    _emit_panel(user_obj, "User List", "\n".join(lines))


@_cmd("list users <search>")
def _cmd_list_users_search(user_obj: Any, args: list[str], world: Any) -> None:
    _cmd_list_users(user_obj, args, world)


@_cmd("look")
def _cmd_look_room(user_obj: Any, args: list[str], world: Any) -> None:
    title, content = _build_look_panel(user_obj, None)
    emit("activity_panel", {"mode": "look", "title": title, "content": content}, to=user_obj.sid)


@_cmd("look <target>")
def _cmd_look_target(user_obj: Any, args: list[str], world: Any) -> None:
    target = (args[0] if args else "").strip()
    resolved_target, error = _resolve_action_target(user_obj, target)
    if error:
        emit("error", {"error": f"look: {error}"}, to=user_obj.sid)
        return
    title, content = _build_look_panel(user_obj, resolved_target)
    emit("activity_panel", {"mode": "look", "title": title, "content": content}, to=user_obj.sid)


@_cmd("go")
def _cmd_go_missing_target(user_obj: Any, args: list[str], world: Any) -> None:
    emit("message", {"text": "Go where?"}, to=user_obj.sid)


@_cmd("go <target>")
def _cmd_go(user_obj: Any, args: list[str], world: Any) -> None:
    from . import user_data
    room = user_obj.room
    if room is None:
        emit("error", {"error": "not in room"}, to=user_obj.sid)
        return
    way, error = _resolve_way_target(user_obj, args[0] if args else "")
    if error:
        emit("message", {"text": error}, to=user_obj.sid)
        return
    to = getattr(way, "info", {}).get("to")
    if to is None or to not in world.rooms:
        emit("message", {"text": "You can't go that way."}, to=user_obj.sid)
        return
    next_room = world.rooms[to]
    user_obj.room.remove_user(user_obj)
    next_room.add_user(user_obj)
    user_data.save_user_state(user_obj)
    emit("message", {"text": f"You go {way.label}."}, to=user_obj.sid)
    emit("message", {"text": f"{user_obj.label} leaves {way.label}."}, room=room.room_id, skip_sid=user_obj.sid)
    emit("message", {"text": f"{user_obj.label} arrives from {room.label()}."}, room=next_room.room_id, skip_sid=user_obj.sid)


@_cmd("pick")
def _cmd_pick_missing_target(user_obj: Any, args: list[str], world: Any) -> None:
    emit("error", {"error": "pick: missing target"}, to=user_obj.sid)


@_cmd("pick <target>")
def _cmd_pick(user_obj: Any, args: list[str], world: Any) -> None:
    resolved_target, error = _resolve_action_target(user_obj, args[0] if args else "")
    if error:
        emit("error", {"error": f"pick: {error}"}, to=user_obj.sid)
        return
    if resolved_target is None or resolved_target["type"] != "object":
        emit("error", {"error": "pick: target must be a room object"}, to=user_obj.sid)
        return
    room = user_obj.room
    if room is None:
        emit("error", {"error": "not in room"}, to=user_obj.sid)
        return
    obj = resolved_target["entity"]
    obj_id = obj.obj_id
    if obj_id not in room.objs:
        emit("error", {"error": "object not found in room"}, to=user_obj.sid)
        return
    del room.objs[obj_id]
    obj.location_id = f"@{user_obj.username}"
    user_obj.peep.inventory[obj_id] = obj
    room.broadcast_room_object_update(obj, change_type="remove", entity_type="object")
    world.save_state(world.ws_id)
    _emit_inventory_update(user_obj)
    emit("message", {"text": f"You pick up {obj.label()}."}, to=user_obj.sid)
    emit("message", {"text": f"{user_obj.label} picks up {obj.label()}."}, room=room.room_id, skip_sid=user_obj.sid)


@_cmd("drop")
def _cmd_drop_missing_target(user_obj: Any, args: list[str], world: Any) -> None:
    emit("error", {"error": "drop: missing target"}, to=user_obj.sid)


@_cmd("drop <target>")
def _cmd_drop(user_obj: Any, args: list[str], world: Any) -> None:
    _cmd_drop_with_coords(user_obj, args, world)


@_cmd("drop <target> <x> <y>")
def _cmd_drop_with_coords(user_obj: Any, args: list[str], world: Any) -> None:
    resolved_target, error = _resolve_action_target(user_obj, args[0] if args else "")
    if error:
        emit("error", {"error": f"drop: {error}"}, to=user_obj.sid)
        return
    if resolved_target is None or resolved_target["type"] != "inventory":
        emit("error", {"error": "drop: target must be an inventory object"}, to=user_obj.sid)
        return
    room = user_obj.room
    if room is None:
        emit("error", {"error": "not in room"}, to=user_obj.sid)
        return
    obj = resolved_target["entity"]
    obj_id = obj.obj_id
    if obj_id not in user_obj.peep.inventory:
        emit("error", {"error": "object not in inventory"}, to=user_obj.sid)
        return
    x = user_obj.peep.x
    y = user_obj.peep.y
    if len(args) >= 3:
        try:
            x = int(args[1])
            y = int(args[2])
        except (TypeError, ValueError):
            emit("error", {"error": "drop: x and y must be integers"}, to=user_obj.sid)
            return
    del user_obj.peep.inventory[obj_id]
    obj.location_id = room.id()
    obj.x = x
    obj.y = y
    obj.z_order = room.next_z()
    room.objs[obj_id] = obj
    room.broadcast_room_object_update(obj, change_type="upsert", entity_type="object")
    world.save_state(world.ws_id)
    _emit_inventory_update(user_obj)
    emit("message", {"text": f"You drop {obj.label()}."}, to=user_obj.sid)
    emit("message", {"text": f"{user_obj.label} drops {obj.label()}."}, room=room.room_id, skip_sid=user_obj.sid)


@_cmd("equip")
def _cmd_equip(user_obj: Any, args: list[str], world: Any) -> None:
    inventory_count = len(user_obj.peep.inventory)
    if inventory_count:
        lines = [f"You are carrying {inventory_count} item(s).", "Select an inventory item and use contextual actions."]
    else:
        lines = ["Your inventory is empty.", "Pick up an object to equip or use it."]
    emit("activity_panel", {"mode": "equip", "title": "Equip", "content": "\n".join(lines)}, to=user_obj.sid)


@_cmd("self")
def _cmd_self(user_obj: Any, args: list[str], world: Any) -> None:
    room_label = user_obj.room.label() if user_obj.room is not None else "Nowhere"
    description = user_obj.peep.description() if callable(getattr(user_obj.peep, "description", None)) else ""
    description = description or "No character description."
    emit(
        "activity_panel",
        {"mode": "self", "title": "Self", "content": f"User: {user_obj.username}\nRoom: {room_label}\n\n{description}"},
        to=user_obj.sid,
    )


@_cmd("claim room")
def _cmd_claim_room(user_obj: Any, args: list[str], world: Any) -> None:
    room = user_obj.room
    if room is None:
        emit("error", {"error": "not in room"}, to=user_obj.sid)
        return
    if not room.can_user_claim(user_obj):
        emit("error", {"error": "room already has an owner"}, to=user_obj.sid)
        return
    room.owner_id = user_obj.username
    room.send_header_view(user_obj)
    for room_user in room.users.values():
        if room_user.sid != user_obj.sid:
            room.send_header_view(room_user)
    world.save_state(world.ws_id)


@_cmd("use")
def _cmd_use_missing_target(user_obj: Any, args: list[str], world: Any) -> None:
    emit("message", {"text": "Use what?"}, to=user_obj.sid)


@_cmd("use <target>")
def _cmd_use(user_obj: Any, args: list[str], world: Any) -> None:
    target = (args[0] if args else "").strip()
    if not target:
        emit("message", {"text": "Use what?"}, to=user_obj.sid)
        return
    emit("message", {"text": f"You use {target}."}, to=user_obj.sid)


# ---------------------------------------------------------------------------
# Admin power-management commands
# ---------------------------------------------------------------------------

_MANAGED_POWERS = {"admin", "realtor", "builder", "moderator", "game-master"}
_POWER_ENABLE_ACTIONS = {"grant", "add", "on", "true", "1"}
_POWER_DISABLE_ACTIONS = {"remove", "revoke", "off", "false", "0"}


@_cmd("power list <username>", power="admin")
def _cmd_power_list(user_obj: Any, args: list[str], world: Any) -> None:
    from . import user as user_module, user_data

    target_name = args[0] if args else ""
    if not target_name:
        _error_panel(user_obj, "Usage: :power list <username>")
        return

    profile = user_data.read_profile(target_name)
    if profile is None:
        _error_panel(user_obj, f"User '{target_name}' not found.")
        return

    persisted_powers = sorted({str(p).strip() for p in profile.get("powers", []) if str(p).strip()})
    online = user_module.find_online(target_name)
    online_text = "online" if online is not None else "offline"
    lines = [
        f"User: {target_name} ({online_text})",
        f"Powers: {', '.join(persisted_powers) if persisted_powers else '(none)'}",
    ]
    _emit_panel(user_obj, "Power List", "\n".join(lines))


@_cmd("power set <username> <power> <mode>", power="admin")
def _cmd_power_set(user_obj: Any, args: list[str], world: Any) -> None:
    from . import user as user_module, user_data

    target_name = args[0] if len(args) > 0 else ""
    power_name = (args[1] if len(args) > 1 else "").strip().lower()
    mode_name = (args[2] if len(args) > 2 else "").strip().lower()
    if not target_name or not power_name or not mode_name:
        _error_panel(user_obj, "Usage: :power set <username> <power> <grant|remove>")
        return

    if power_name not in _MANAGED_POWERS:
        _error_panel(
            user_obj,
            f"Unknown power '{power_name}'. Valid powers: {', '.join(sorted(_MANAGED_POWERS))}.",
        )
        return

    profile = user_data.read_profile(target_name)
    if profile is None:
        _error_panel(user_obj, f"User '{target_name}' not found.")
        return

    powers = {str(p).strip() for p in profile.get("powers", []) if str(p).strip()}
    if mode_name in _POWER_ENABLE_ACTIONS:
        powers.add(power_name)
        action_text = "granted"
    elif mode_name in _POWER_DISABLE_ACTIONS:
        powers.discard(power_name)
        action_text = "removed"
    else:
        _error_panel(user_obj, "Usage: :power set <username> <power> <grant|remove>")
        return

    final_powers = sorted(powers)
    user_data.write_profile(target_name, powers=final_powers)

    online_target = user_module.find_online(target_name)
    if online_target is not None:
        online_target.powers = set(final_powers)

    lines = [
        f"Power '{power_name}' {action_text} for user '{target_name}'.",
        f"Current powers: {', '.join(final_powers) if final_powers else '(none)'}",
    ]
    _emit_panel(user_obj, "Power Set", "\n".join(lines))


# ---------------------------------------------------------------------------
# Realtor commands
# ---------------------------------------------------------------------------

@_cmd("room owner set <username>", power="realtor")
def _cmd_room_owner_set(user_obj: Any, args: list[str], world: Any) -> None:
    room = user_obj.room
    if room is None:
        _error_panel(user_obj, "You are not in a room.")
        return
    target = args[0] if args else ""
    if not target:
        _error_panel(user_obj, "Usage: :room owner set <username>")
        return
    room.owner_id = target
    _save_world(world)
    _emit_panel(user_obj, "Room Owner", f"Room '{room.room_id}' owner set to '{target}'.")
    _broadcast_header(room)


@_cmd("room owner clear", power="realtor")
def _cmd_room_owner_clear(user_obj: Any, args: list[str], world: Any) -> None:
    room = user_obj.room
    if room is None:
        _error_panel(user_obj, "You are not in a room.")
        return
    room.owner_id = ""
    _save_world(world)
    _emit_panel(user_obj, "Room Owner", f"Room '{room.room_id}' ownership cleared.")
    _broadcast_header(room)


@_cmd("room owner show", power="realtor")
def _cmd_room_owner_show(user_obj: Any, args: list[str], world: Any) -> None:
    room = user_obj.room
    if room is None:
        _error_panel(user_obj, "You are not in a room.")
        return
    owner = room.owner_id or "(none)"
    _emit_panel(user_obj, "Room Owner", f"Room '{room.room_id}' is owned by: {owner}")


@_cmd("room list", power="realtor")
def _cmd_room_list(user_obj: Any, args: list[str], world: Any) -> None:
    _cmd_room_list_filtered(user_obj, [], world)


@_cmd("room list <filter>", power="realtor")
def _cmd_room_list_filtered(user_obj: Any, args: list[str], world: Any) -> None:
    flt = args[0].lower() if args else ""
    lines = ["**Rooms:**"]
    for rid, room in sorted(world.rooms.items()):
        label = room.label()
        if flt and flt not in rid.lower() and flt not in label.lower():
            continue
        owner = room.owner_id or "(none)"
        link = _cmd_link(label, f":goto {rid}")
        lines.append(f"  {link} [{rid}] owner: {owner}")
    if len(lines) == 1:
        lines.append("  (no rooms found)")
    _emit_panel(user_obj, "Room List", "\n".join(lines))


# ---------------------------------------------------------------------------
# Builder commands
# ---------------------------------------------------------------------------

@_cmd("room rename ...", power="builder")
def _cmd_room_rename(user_obj: Any, args: list[str], world: Any) -> None:
    room = user_obj.room
    if room is None:
        _error_panel(user_obj, "You are not in a room.")
        return
    name = " ".join(args).strip()
    if not name:
        _error_panel(user_obj, "Usage: :room rename <name>")
        return
    room.label_override = name
    _save_world(world)
    _emit_panel(user_obj, "Room Rename", f"Room '{room.room_id}' renamed to '{name}'.")
    _broadcast_header(room)


@_cmd("room describe ...", power="builder")
def _cmd_room_describe(user_obj: Any, args: list[str], world: Any) -> None:
    room = user_obj.room
    if room is None:
        _error_panel(user_obj, "You are not in a room.")
        return
    text = " ".join(args).strip()
    if not text:
        _error_panel(user_obj, "Usage: :room describe <text>")
        return
    room.description_override = text
    _save_world(world)
    _emit_panel(user_obj, "Room Describe", f"Room '{room.room_id}' description updated.")
    _broadcast_header(room)


@_cmd("room reset", power="builder")
def _cmd_room_reset(user_obj: Any, args: list[str], world: Any) -> None:
    room = user_obj.room
    if room is None:
        _error_panel(user_obj, "You are not in a room.")
        return
    room.label_override = None
    room.description_override = None
    # Reset props to YAML-defined defaults
    room_def = world.room_defs.get(room.room_id, {})
    room_props_spec = room_def.get("props", [])
    new_props: dict = {}
    for idx, prop_ref in enumerate(room_props_spec):
        if isinstance(prop_ref, str):
            prop_spec: dict = {"prop": prop_ref}
        else:
            prop_spec = dict(prop_ref)
        prop_id = prop_spec.get("prop") or prop_spec.get("id")
        if not prop_id:
            continue
        prop_info = world.prop_defs.get(prop_id, {})
        merged = {**prop_info, **prop_spec}
        prop_instance_id = prop_spec.get("prop_instance_id") or f"{room.room_id}-{prop_id}-{idx}"
        from .prop import Prop
        new_props[prop_instance_id] = Prop(prop_instance_id, prop_id, merged, room.room_id)
    room.props = new_props
    _save_world(world)
    _emit_panel(user_obj, "Room Reset", f"Room '{room.room_id}' reset to defaults.")
    for room_user in room.users.values():
        room.send_header_view(room_user)
        room.send_room_stage_view(room_user)


# ---------------------------------------------------------------------------
# Moderator commands
# ---------------------------------------------------------------------------

@_cmd("kick <username>", power="moderator")
def _cmd_kick(user_obj: Any, args: list[str], world: Any) -> None:
    from . import user as user_module, user_data
    target_name = args[0] if args else ""
    if not target_name:
        _error_panel(user_obj, "Usage: :kick <username>")
        return
    target = user_module.find_online(target_name)
    if target is None:
        _error_panel(user_obj, f"User '{target_name}' is not online.")
        return
    old_room = target.room
    if old_room:
        old_room.remove_user(target)
    default_room = world.default_room
    default_room.add_user(target)
    user_data.save_user_state(target)
    emit("message", {"text": f"You have been kicked to the default room."}, to=target.sid)
    _emit_panel(user_obj, "Kick", f"Kicked '{target_name}' to default room.")


@_cmd("bring <username>", power="moderator")
def _cmd_bring(user_obj: Any, args: list[str], world: Any) -> None:
    from . import user as user_module, user_data
    target_name = args[0] if args else ""
    if not target_name:
        _error_panel(user_obj, "Usage: :bring <username>")
        return
    target = user_module.find_online(target_name)
    if target is None:
        _error_panel(user_obj, f"User '{target_name}' is not online.")
        return
    dest_room = user_obj.room
    if dest_room is None:
        _error_panel(user_obj, "You are not in a room.")
        return
    old_room = target.room
    if old_room:
        old_room.remove_user(target)
    dest_room.add_user(target)
    user_data.save_user_state(target)
    emit("message", {"text": f"You have been brought to '{dest_room.label()}'."}, to=target.sid)
    _emit_panel(user_obj, "Bring", f"Brought '{target_name}' to '{dest_room.room_id}'.")


@_cmd("move <username> <room_id>", power="moderator")
def _cmd_move(user_obj: Any, args: list[str], world: Any) -> None:
    from . import user as user_module, user_data
    target_name = args[0] if len(args) > 0 else ""
    room_id = args[1] if len(args) > 1 else ""
    if not target_name or not room_id:
        _error_panel(user_obj, "Usage: :move <username> <room_id>")
        return
    target = user_module.find_online(target_name)
    if target is None:
        _error_panel(user_obj, f"User '{target_name}' is not online.")
        return
    dest_room = world.rooms.get(room_id)
    if dest_room is None:
        _error_panel(user_obj, f"Room '{room_id}' not found.")
        return
    old_room = target.room
    if old_room:
        old_room.remove_user(target)
    dest_room.add_user(target)
    user_data.save_user_state(target)
    emit("message", {"text": f"You have been moved to '{dest_room.label()}'."}, to=target.sid)
    _emit_panel(user_obj, "Move", f"Moved '{target_name}' to '{room_id}'.")


# ---------------------------------------------------------------------------
# Game-master commands
# ---------------------------------------------------------------------------

@_cmd("goto <room_id>", power="game-master")
def _cmd_goto(user_obj: Any, args: list[str], world: Any) -> None:
    from . import user_data
    room_id = args[0] if args else ""
    if not room_id:
        _error_panel(user_obj, "Usage: :goto <room_id>")
        return
    dest_room = world.rooms.get(room_id)
    if dest_room is None:
        _error_panel(user_obj, f"Room '{room_id}' not found.")
        return
    old_room = user_obj.room
    if old_room:
        old_room.remove_user(user_obj)
    dest_room.add_user(user_obj)
    user_data.save_user_state(user_obj)
    _emit_panel(user_obj, "Goto", f"Teleported to '{room_id}'.")


@_cmd("spawn <thing_id>", power="game-master")
def _cmd_spawn(user_obj: Any, args: list[str], world: Any) -> None:
    import random
    from .object import Object
    thing_id = args[0] if args else ""
    if not thing_id:
        _error_panel(user_obj, "Usage: :spawn <thing_id>")
        return
    thing_def = world.thing_defs.get(thing_id)
    if thing_def is None:
        _error_panel(user_obj, f"Thing '{thing_id}' not found.")
        return
    room = user_obj.room
    if room is None:
        _error_panel(user_obj, "You are not in a room.")
        return
    random_hex = "".join(random.choices("0123456789abcdef", k=5))
    obj_id = f"{thing_id}-{random_hex}"
    obj = Object(obj_id, thing_id, dict(thing_def), room.id(), user_obj.username)
    obj.x = getattr(user_obj.peep, "x", 32)
    obj.y = getattr(user_obj.peep, "y", 32)
    obj.z_order = room.next_z()
    from . import icons
    obj._display_assets = icons.build_display_assets(thing_def, world.root_path)
    world.objs[obj_id] = obj
    room.objs[obj_id] = obj
    room.broadcast_room_object_update(obj, change_type="upsert", entity_type="object")
    world.save_state(world.ws_id)
    _emit_panel(user_obj, "Spawn", f"Spawned '{thing_id}' as '{obj_id}'.")


@_cmd("despawn <obj_id>", power="game-master")
def _cmd_despawn(user_obj: Any, args: list[str], world: Any) -> None:
    obj_id = args[0] if args else ""
    if not obj_id:
        _error_panel(user_obj, "Usage: :despawn <obj_id>")
        return
    room = user_obj.room
    if room is None:
        _error_panel(user_obj, "You are not in a room.")
        return
    obj = room.objs.get(obj_id)
    if obj is None:
        _error_panel(user_obj, f"Object '{obj_id}' not found in current room.")
        return
    del room.objs[obj_id]
    world.objs.pop(obj_id, None)
    room.broadcast_room_object_update(obj, change_type="remove", entity_type="object")
    world.save_state(world.ws_id)
    _emit_panel(user_obj, "Despawn", f"Removed '{obj_id}' from room.")


@_cmd("reset-world", power="game-master")
def _cmd_reset_world(user_obj: Any, args: list[str], world: Any) -> None:
    from . import world as world_module
    world_module.reset_rooms()
    _emit_panel(user_obj, "Reset World", "World has been reset to YAML defaults.")


@_cmd("obj list", power="game-master")
def _cmd_obj_list(user_obj: Any, args: list[str], world: Any) -> None:
    _cmd_obj_list_filtered(user_obj, [], world)


@_cmd("obj list <filter>", power="game-master")
def _cmd_obj_list_filtered(user_obj: Any, args: list[str], world: Any) -> None:
    room = user_obj.room
    if room is None:
        _error_panel(user_obj, "You are not in a room.")
        return
    flt = args[0].lower() if args else ""
    lines = ["**Objects in room:**"]
    for obj_id, obj in sorted(room.objs.items()):
        label = obj.label() if callable(getattr(obj, "label", None)) else obj_id
        if flt and flt not in obj_id.lower() and flt not in label.lower():
            continue
        thing_id = getattr(obj, "thing_id", "?")
        lines.append(f"  {_cmd_link(obj_id, f':despawn {obj_id}')} [{thing_id}] {label}")
    if len(lines) == 1:
        lines.append("  (no objects)")
    _emit_panel(user_obj, "Object List", "\n".join(lines))


@_cmd("peep list", power="game-master")
def _cmd_peep_list(user_obj: Any, args: list[str], world: Any) -> None:
    _cmd_peep_list_filtered(user_obj, [], world)


@_cmd("peep list <filter>", power="game-master")
def _cmd_peep_list_filtered(user_obj: Any, args: list[str], world: Any) -> None:
    room = user_obj.room
    if room is None:
        _error_panel(user_obj, "You are not in a room.")
        return
    flt = args[0].lower() if args else ""
    lines = ["**Peeps in room:**"]
    for peep_id, peep_obj in sorted(room.peeps.items()):
        label = peep_obj.label() if callable(getattr(peep_obj, "label", None)) else peep_id
        ptype = getattr(peep_obj, "type", "user")
        if flt and flt not in peep_id.lower() and flt not in label.lower():
            continue
        lines.append(f"  {peep_id} [{ptype}] {label}")
    if len(lines) == 1:
        lines.append("  (no peeps)")
    _emit_panel(user_obj, "Peep List", "\n".join(lines))


@_cmd("prop list", power="game-master")
def _cmd_prop_list(user_obj: Any, args: list[str], world: Any) -> None:
    _cmd_prop_list_filtered(user_obj, [], world)


@_cmd("prop list <filter>", power="game-master")
def _cmd_prop_list_filtered(user_obj: Any, args: list[str], world: Any) -> None:
    room = user_obj.room
    if room is None:
        _error_panel(user_obj, "You are not in a room.")
        return
    flt = args[0].lower() if args else ""
    lines = ["**Props in room:**"]
    for iid, prop in sorted(room.props.items()):
        prop_id = getattr(prop, "prop_id", iid)
        if flt and flt not in iid.lower() and flt not in prop_id.lower():
            continue
        lines.append(f"  {iid} [{prop_id}] x={getattr(prop, 'x', 0)} y={getattr(prop, 'y', 0)}")
    if len(lines) == 1:
        lines.append("  (no props)")
    _emit_panel(user_obj, "Prop List", "\n".join(lines))


@_cmd("thing list", power="game-master")
def _cmd_thing_list(user_obj: Any, args: list[str], world: Any) -> None:
    _cmd_thing_list_filtered(user_obj, [], world)


@_cmd("thing list <filter>", power="game-master")
def _cmd_thing_list_filtered(user_obj: Any, args: list[str], world: Any) -> None:
    flt = args[0].lower() if args else ""
    lines = ["**Available things:**"]
    for thing_id, thing_def in sorted(world.thing_defs.items()):
        label = thing_def.get("label") or thing_id
        if flt and flt not in thing_id.lower() and flt not in label.lower():
            continue
        link = _cmd_link(thing_id, f":spawn {thing_id}")
        lines.append(f"  {link} — {label}")
    if len(lines) == 1:
        lines.append("  (no things defined)")
    _emit_panel(user_obj, "Thing List", "\n".join(lines))


# ---------------------------------------------------------------------------
# Admin command gateway (client-side '/' commands for users with 'admin' power)
# ---------------------------------------------------------------------------

def dispatch_admin(user_obj: Any, text: str) -> bool:
    """Route a '/' command from a client with 'admin' power to the server console.

    Returns True if handled, False if the user lacks the power or the text
    does not start with '/'.
    """
    if not text.startswith("/"):
        return False
    if not user_obj.has_power("admin"):
        emit("error", {"error": "You don't have 'admin' power."}, to=user_obj.sid)
        return True
    from . import console
    cmd = text[1:].strip()
    if cmd in {"r", "k"}:
        emit("error", {"error": f"/{cmd} is console-only and cannot be run from client."}, to=user_obj.sid)
        return True
    from . import user as user_module, world as world_module, server as server_module
    locals_dict = {
        "user": user_module,
        "world": world_module,
        "server": server_module,
    }
    console.run_admin_cmd(cmd, locals_dict)
    return True
