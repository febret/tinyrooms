"""Peep behavior script loading, execution, and tick loop."""
from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .peep import Peep
    from .room import Room
    from .world import World

# Cache of compiled behavior code objects keyed by absolute script path
_behavior_cache: dict[str, object] = {}

_tick_thread: threading.Thread | None = None
_tick_stop_event: threading.Event = threading.Event()


# ---------------------------------------------------------------------------
# Behavior loading
# ---------------------------------------------------------------------------

def load_behavior(script_path: Path) -> object | None:
    """Read, compile, and cache a behavior script. Returns the code object or None."""
    script_path = Path(script_path)
    key = str(script_path.resolve())
    if key in _behavior_cache:
        return _behavior_cache[key]
    if not script_path.exists():
        print(f"peep_behavior: script not found: {script_path}")
        return None
    try:
        source = script_path.read_text(encoding='utf-8')
        code = compile(source, str(script_path), 'exec')
        _behavior_cache[key] = code
        return code
    except SyntaxError as exc:
        print(f"peep_behavior: syntax error in '{script_path}': {exc}")
        return None


def _make_say(peep: 'Peep', get_room: Callable[[], 'Room | None']):
    def say(*args, **kwargs):
        """say([target], txt) — broadcast a chat message from the peep."""
        if len(args) == 1:
            target = None
            txt = str(args[0])
        elif len(args) >= 2:
            target = args[0]
            txt = str(args[1])
        else:
            txt = str(kwargs.get('txt', ''))
            target = kwargs.get('target', None)
        room = get_room()
        if room is None:
            return
        label = peep.label() if callable(peep.label) else str(peep.label)
        if target is not None:
            target_label = _entity_label(target)
            text = f"{label} says to {target_label}: {txt}"
        else:
            text = f"{label} says: {txt}"
        room.send_text(text)
    return say


def _make_emote(peep: 'Peep', get_room: Callable[[], 'Room | None']):
    def emote(*args, **kwargs):
        """emote([target], action, [text]) — broadcast an emote from the peep."""
        if len(args) == 1:
            target = None
            action = str(args[0])
            extra = ''
        elif len(args) == 2:
            # Could be (target, action) or (action, text)
            if isinstance(args[0], str) and not _is_entity(args[0]):
                target = None
                action = str(args[0])
                extra = str(args[1])
            else:
                target = args[0]
                action = str(args[1])
                extra = ''
        elif len(args) >= 3:
            target = args[0]
            action = str(args[1])
            extra = str(args[2])
        else:
            target = kwargs.get('target', None)
            action = str(kwargs.get('action', ''))
            extra = str(kwargs.get('text', ''))
        room = get_room()
        if room is None:
            return
        label = peep.label() if callable(peep.label) else str(peep.label)
        if target is not None:
            target_label = _entity_label(target)
            text = f"{label} {action} {target_label}" + (f" {extra}" if extra else "")
        else:
            text = f"{label} {action}" + (f" {extra}" if extra else "")
        room.send_text(text)
    return emote


def _is_entity(value) -> bool:
    return hasattr(value, 'label') or hasattr(value, 'peep_id') or hasattr(value, 'username')


def _entity_label(entity) -> str:
    if entity is None:
        return ''
    label = getattr(entity, 'label', None)
    if callable(label):
        return str(label())
    if label is not None:
        return str(label)
    return str(getattr(entity, 'username', '') or getattr(entity, 'peep_id', '') or entity)


def _make_get_users(get_room: Callable[[], 'Room | None']):
    def get_users():
        """Return list of User objects in the current room."""
        room = get_room()
        return list(room.users.values()) if room else []
    return get_users


def _make_get_peeps(get_room: Callable[[], 'Room | None']):
    def get_peeps():
        """Return list of Peep objects in the current room."""
        room = get_room()
        return list(room.peeps.values()) if room else []
    return get_peeps


def _make_get_objects(get_room: Callable[[], 'Room | None']):
    def get_objects():
        """Return list of Object instances in the current room."""
        room = get_room()
        return list(room.objs.values()) if room else []
    return get_objects


def _make_get_props(get_room: Callable[[], 'Room | None']):
    def get_props():
        """Return list of Prop instances in the current room."""
        room = get_room()
        return list(room.props.values()) if room else []
    return get_props


def _make_get_ways(get_room: Callable[[], 'Room | None']):
    def get_ways():
        """Return list of Way objects in the current room."""
        room = get_room()
        return list(room.ways.values()) if room else []
    return get_ways


def _make_move(peep: 'Peep', get_room: Callable[[], 'Room | None']):
    def move(x: int, y: int):
        """Update the peep's position and broadcast to room clients."""
        room = get_room()
        if room is None:
            return
        peep.x = int(x)
        peep.y = int(y)
        peep.z_order = room.next_z()
        room.broadcast_room_object_update(peep, change_type='upsert', entity_type='peep', owner_username=peep.peep_id)
    return move


def _make_go_to(peep: 'Peep', get_room: Callable[[], 'Room | None'], get_world: Callable[[], 'World | None']):
    def go_to(way):
        """Move the NPC peep through the specified way to another room."""
        room = get_room()
        world = get_world()
        if room is None or world is None:
            return
        if isinstance(way, str):
            way_obj = room.ways.get(way) or world.ways.get(way)
        else:
            way_obj = way
        if way_obj is None:
            print(f"peep_behavior go_to: way not found for peep '{peep.peep_id}'")
            return
        to_room_id = way_obj.info.get('to')
        if not to_room_id or to_room_id not in world.rooms:
            print(f"peep_behavior go_to: destination room '{to_room_id}' not found for peep '{peep.peep_id}'")
            return
        next_room = world.rooms[to_room_id]
        # Remove from current room
        if peep.peep_id in room.peeps:
            del room.peeps[peep.peep_id]
            from flask_socketio import emit as _emit
            _emit('update_view', {
                'view': 'room-object',
                'change': 'remove',
                'entity': {'entity_type': 'peep', 'entity_id': peep.peep_id},
            }, room=room.room_id, namespace='/')
        # Add to next room
        peep.location_id = next_room.id()
        next_room.peeps[peep.peep_id] = peep
        next_room.broadcast_room_object_update(peep, change_type='upsert', entity_type='peep', owner_username=peep.peep_id)
    return go_to


def _make_look(get_room: Callable[[], 'Room | None']):
    def look(entity) -> dict:
        """Return label and description for the given entity."""
        label = _entity_label(entity)
        info = getattr(entity, 'info', {}) or {}
        description = info.get('description', '')
        if not description:
            desc_fn = getattr(entity, 'description', None)
            if callable(desc_fn):
                description = desc_fn()
        return {'label': label, 'description': description}
    return look


def _make_set_sprite(peep: 'Peep', get_room: Callable[[], 'Room | None'], world_root_path):
    def set_sprite(sprite_string: str):
        """Update the peep's display sprite and broadcast to room clients."""
        from . import icons as icon_module
        try:
            peep._display_assets = icon_module.build_display_assets(
                {'sprite': sprite_string, 'img': sprite_string},
                world_root_path,
            )
        except Exception:
            peep._display_assets = {'img': sprite_string, 'icon': sprite_string, 'sprite': sprite_string}
        room = get_room()
        if room is not None:
            room.broadcast_room_object_update(peep, change_type='upsert', entity_type='peep', owner_username=peep.peep_id)
    return set_sprite


def _make_show(peep: 'Peep', get_room: Callable[[], 'Room | None']):
    def show(animation_id: str, frame=None):
        """Send an animation update for the peep to all room clients."""
        from flask_socketio import emit as _emit
        room = get_room()
        if room is None:
            return
        payload = {
            'view': 'room-object-animation',
            'entity_id': peep.peep_id,
            'entity_type': 'peep',
            'animation_id': animation_id,
        }
        if frame is not None:
            payload['frame'] = frame
        _emit('update_view', payload, room=room.room_id, namespace='/')
    return show


# ---------------------------------------------------------------------------
# Behavior namespace initialization
# ---------------------------------------------------------------------------

def init_behavior_ns(peep: 'Peep', world: 'World') -> dict | None:
    """Build and exec the behavior script into an isolated namespace bound to this peep.

    Returns the populated namespace dict, or None if no behavior is configured.
    """
    class_id = getattr(peep, 'class_id', '') or peep.info.get('class', '')
    if not class_id:
        return None
    class_def = world.peep_class_defs.get(class_id, {})
    behavior_stem = class_def.get('behavior', '')
    if not behavior_stem:
        return None

    class_dir = class_def.get('_dir', '')
    if not class_dir:
        return None
    script_path = Path(class_dir) / f"{behavior_stem}.py"
    code = load_behavior(script_path)
    if code is None:
        return None

    # Build a room resolver closure (room may change at runtime via go_to)
    def get_room():
        loc = peep.location_id
        return world.rooms.get(loc.replace('@room:', '')) or world.rooms.get(loc)

    def get_world():
        return world

    # Restricted builtins: math-safe, no import
    safe_builtins = {
        'abs': abs, 'all': all, 'any': any, 'bool': bool, 'dict': dict,
        'enumerate': enumerate, 'float': float, 'getattr': getattr,
        'hasattr': hasattr, 'int': int, 'isinstance': isinstance,
        'iter': iter, 'len': len, 'list': list, 'max': max, 'min': min,
        'next': next, 'print': print, 'range': range, 'round': round,
        'set': set, 'sorted': sorted, 'str': str, 'sum': sum,
        'tuple': tuple, 'zip': zip,
    }
    import random as _random
    import math as _math

    ns: dict = {
        '__builtins__': safe_builtins,
        'random': _random,
        'math': _math,
        # Utility functions
        'say':       _make_say(peep, get_room),
        'emote':     _make_emote(peep, get_room),
        'get_users': _make_get_users(get_room),
        'get_peeps': _make_get_peeps(get_room),
        'get_objects': _make_get_objects(get_room),
        'get_props': _make_get_props(get_room),
        'get_ways':  _make_get_ways(get_room),
        'move':      _make_move(peep, get_room),
        'go_to':     _make_go_to(peep, get_room, get_world),
        'look':      _make_look(get_room),
        'set_sprite': _make_set_sprite(peep, get_room, world.root_path),
        'show':      _make_show(peep, get_room),
        # Peep self-reference
        'peep':      peep,
    }
    try:
        exec(code, ns)  # noqa: S102
    except Exception as exc:
        print(f"peep_behavior: error initializing behavior for '{peep.peep_id}': {exc}")
        traceback.print_exc()
        return None
    return ns


# ---------------------------------------------------------------------------
# Safe handler invocation
# ---------------------------------------------------------------------------

def call_handler(peep: 'Peep', handler_name: str, *args) -> None:
    """Call a named handler in the peep's behavior namespace, catching all errors."""
    ns = peep.behavior_ns
    if ns is None:
        return
    handler = ns.get(handler_name)
    if not callable(handler):
        return
    try:
        handler(*args)
    except Exception as exc:
        print(f"peep_behavior: error in '{handler_name}' for peep '{peep.peep_id}': {exc}")
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Behavior initialization for a world
# ---------------------------------------------------------------------------

def init_world_behaviors(world: 'World') -> None:
    """Initialize behavior namespaces for all NPC peeps in the world."""
    for peep in world.peeps.values():
        if getattr(peep, 'type', 'user') == 'npc':
            peep.behavior_ns = init_behavior_ns(peep, world)


# ---------------------------------------------------------------------------
# Tick loop
# ---------------------------------------------------------------------------

def start_tick_loop(get_world: Callable[[], 'World'], interval: float = 1.0) -> None:
    """Start the background tick loop for NPC peep behaviors."""
    global _tick_thread, _tick_stop_event
    _tick_stop_event.clear()

    def _loop():
        last_tick = time.monotonic()
        while not _tick_stop_event.is_set():
            _tick_stop_event.wait(timeout=interval)
            if _tick_stop_event.is_set():
                break
            now = time.monotonic()
            secs = now - last_tick
            last_tick = now
            try:
                world = get_world()
                if world is None:
                    continue
                for peep in list(world.peeps.values()):
                    if getattr(peep, 'type', 'user') == 'npc':
                        call_handler(peep, 'on_tick', secs)
            except Exception as exc:
                print(f"peep_behavior: tick loop error: {exc}")
                traceback.print_exc()

    _tick_thread = threading.Thread(target=_loop, name='peep-tick', daemon=True)
    _tick_thread.start()
    print(f"peep_behavior: tick loop started (interval={interval}s)")


def stop_tick_loop() -> None:
    """Stop the background tick loop."""
    global _tick_thread
    _tick_stop_event.set()
    if _tick_thread is not None:
        _tick_thread.join(timeout=5.0)
        _tick_thread = None
    print("peep_behavior: tick loop stopped")
