"""Emote system: loading, parsing, and executing emote definitions.

Emotes are defined in ``data/emotes/`` (server-wide) and optionally in a
world-local ``emotes/`` directory.  Each YAML file contributes emotes keyed
both as a flat ``emote_id`` and as ``filename.emote_id``.

Animation steps
---------------
The ``animations`` field of an emote definition is a comma-separated string of
steps.  Each step is one of:

- ``!<msg_id>``    — emit the message at index *msg_id* in the emote's message
  set (0-based).  The default animation ``!0`` emits the first (and typically
  only) message.
- ``#<seconds>``   — pause execution for *seconds* seconds without blocking the
  socket-handler thread.  A background task is spawned automatically when any
  pause step is present.
- ``.<emoteID>``   — run another emote (one level of nesting; silently skipped
  when ``_depth >= 1``).
- Anything else    — treated as a sprite animation ID; emitted to the room as
  an ``"emote_anim"`` socket event.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import yaml

from .types import ParsedEmote
from . import text as _text


# ---------------------------------------------------------------------------
# Module-level emote registry
# ---------------------------------------------------------------------------

emote_defs: dict = {}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _load_yaml_file(path: Path) -> dict:
    with open(path, 'r', encoding='utf-8') as fh:
        loaded = yaml.safe_load(fh)
    return loaded if isinstance(loaded, dict) else {}


def load_emotes(server_path=None, world_path=None) -> dict:
    """Load emote definitions from *server_path* and optionally *world_path*.

    Keys are stored both as plain ``emote_id`` and as ``stem.emote_id``.
    World emotes override server emotes that share the same key.
    """
    global emote_defs

    if server_path is None:
        server_path = Path(__file__).parent.parent / "data" / "emotes"
    server_path = Path(server_path)

    new_defs: dict = {}

    def _ingest(yaml_dir: Path, override: bool):
        if not yaml_dir.exists():
            return
        for yaml_file in sorted(yaml_dir.glob("*.yaml")):
            stem = yaml_file.stem
            loaded = _load_yaml_file(yaml_file)
            for eid, edef in loaded.items():
                flat_key = eid
                qual_key = f"{stem}.{eid}"
                if override or flat_key not in new_defs:
                    new_defs[flat_key] = edef
                new_defs[qual_key] = edef   # qualified key always wins on reload

    _ingest(server_path, override=False)
    if world_path is not None:
        _ingest(Path(world_path), override=True)

    emote_defs = new_defs
    print(f"Loaded {len(emote_defs)} emote entries "
          f"({sum(1 for k in new_defs if '.' not in k)} unique emote IDs)")

    # Mark all connected users as stale so heartbeat resends emotes_def
    try:
        from .user import connected_users
        for u in connected_users.values():
            u.actions_stale = True
    except Exception:
        pass

    return emote_defs


# ---------------------------------------------------------------------------
# Animation step parsing
# ---------------------------------------------------------------------------

def _parse_animation_steps(animations_str: str) -> list[dict]:
    """Parse a comma-separated animation string into a list of step dicts.

    Each dict has a ``"type"`` key with one of:
    ``"message"`` (``!N``), ``"pause"`` (``#S``), ``"emote"`` (``.<id>``),
    ``"sprite"`` (anything else).
    """
    steps: list[dict] = []
    for raw in (s.strip() for s in str(animations_str).split(',') if s.strip()):
        if raw.startswith('!'):
            try:
                steps.append({'type': 'message', 'index': int(raw[1:])})
            except ValueError:
                print(f"emotes: invalid animation step '{raw}' — skipped")
        elif raw.startswith('#'):
            try:
                steps.append({'type': 'pause', 'seconds': float(raw[1:])})
            except ValueError:
                print(f"emotes: invalid animation step '{raw}' — skipped")
        elif raw.startswith('.'):
            steps.append({'type': 'emote', 'emote_id': raw[1:]})
        else:
            steps.append({'type': 'sprite', 'anim_id': raw})
    return steps


# ---------------------------------------------------------------------------
# Message emission helpers (work both inside and outside a socket handler)
# ---------------------------------------------------------------------------

def _emit(event: str, data: dict, *, to: str | None = None,
          room: str | None = None, skip_sid: str | None = None,
          in_handler: bool = True):
    """Emit a socket event, adapting to handler vs. background-thread context."""
    if in_handler:
        from flask_socketio import emit
        if to is not None:
            emit(event, data, to=to)
        elif room is not None:
            emit(event, data, room=room, skip_sid=skip_sid)
    else:
        from . import server as _server
        sio = _server.socketio
        if to is not None:
            sio.emit(event, data, to=to)
        elif room is not None:
            sio.emit(event, data, room=room, skip_sid=skip_sid)


# ---------------------------------------------------------------------------
# Step execution
# ---------------------------------------------------------------------------

def _execute_steps(
    steps: list[dict],
    emote_def: dict,
    user_sid: str,
    room_id: str,
    first_msg: str | None,
    second_msg: str | None,
    second_sid: str | None,
    third_msg: str | None,
    nested_emote_refs: list,
    nested_user_sid: str,
    nested_room_id: str,
    nested_user_label: str,
    nested_extra_text: str,
    depth: int,
    in_handler: bool,
):
    """Execute a parsed list of animation steps.

    Pre-computed first/second/third messages are passed in so we only call
    ``make_emote_text`` once regardless of which ``!N`` steps are present.
    """
    # Build a list of message variants for !N indexing.
    # For emotes with a single message set this is straightforwardly [first, …]
    # We expose up to three messages (first, second, third) as indices 0/1/2.
    msg_variants = []
    if first_msg is not None:
        msg_variants.append(first_msg)
    if third_msg is not None:
        msg_variants.append(third_msg)

    for step in steps:
        stype = step['type']

        if stype == 'message':
            idx = step['index']
            if idx < len(msg_variants):
                # Emit to the originating user (first-person view)
                _emit("message", {"text": msg_variants[idx]}, to=user_sid,
                      in_handler=in_handler)
                # Emit 2nd person to target user
                if second_msg is not None and second_sid is not None:
                    _emit("message", {"text": second_msg}, to=second_sid,
                          in_handler=in_handler)
                # Emit 3rd person to rest of the room
                skip = user_sid if second_sid is None else None
                _emit("message", {"text": third_msg or msg_variants[idx]},
                      room=room_id, skip_sid=skip, in_handler=in_handler)
                # Also skip second_sid from 3rd-person broadcast explicitly
                if second_sid is not None:
                    # socketio room-skipping supports only one skip_sid, so
                    # send individually to room members and skip both sids.
                    # For simplicity we skip only the sender; the target gets
                    # the 2nd-person message which is more appropriate.
                    _emit("message", {"text": third_msg or msg_variants[idx]},
                          room=room_id, skip_sid=user_sid, in_handler=in_handler)

        elif stype == 'pause':
            time.sleep(step['seconds'])

        elif stype == 'emote':
            if depth >= 1:
                continue  # one-level nesting only
            nested_def = emote_defs.get(step['emote_id'])
            if nested_def is None:
                print(f"emotes: nested emote '{step['emote_id']}' not found — skipped")
                continue
            nf, ns, nt = _text.make_emote_text(
                nested_def, nested_user_label, nested_emote_refs, nested_extra_text
            )
            nested_steps = _parse_animation_steps(nested_def.get('animations', '!0'))
            _execute_steps(
                nested_steps, nested_def,
                nested_user_sid, nested_room_id,
                nf, ns, None, nt,
                nested_emote_refs,
                nested_user_sid, nested_room_id, nested_user_label, nested_extra_text,
                depth=depth + 1, in_handler=in_handler,
            )

        elif stype == 'sprite':
            _emit("emote_anim", {
                "entity": "peep",
                "entity_id": _sid_to_username(user_sid),
                "anim_id": step['anim_id'],
            }, room=room_id, in_handler=in_handler)


def _sid_to_username(sid: str) -> str:
    try:
        from .user import connected_users
        u = connected_users.get(sid)
        return u.username if u else sid
    except Exception:
        return sid


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def do_emote(
    emote_id: str,
    refs: list,
    user,        # tinyrooms.user.User
    room,        # tinyrooms.room.Room
    extra_text: str = '',
    _depth: int = 0,
):
    """Execute an emote for *user* in *room*.

    Generates 1st-, 2nd- (when target is a connected User), and 3rd-person
    messages, then plays the emote's animation steps.  Animation steps
    containing ``#<seconds>`` pauses are executed in a background thread to
    avoid blocking the socket-handler thread.
    """
    global emote_defs
    if not emote_defs:
        load_emotes()

    emote_def = emote_defs.get(emote_id)
    if emote_def is None:
        print(f"do_emote: Unknown emote '{emote_id}'")
        return

    # Resolve 2nd-person target (first User ref, if any)
    from .user import User as _User
    target_user = next((r for r in refs if isinstance(r, _User)), None)

    first_msg, second_msg, third_msg = _text.make_emote_text(
        emote_def, user.label, refs, extra_text
    )
    second_sid = target_user.sid if target_user is not None else None

    animations = emote_def.get('animations', '!0')
    steps = _parse_animation_steps(animations)
    has_pause = any(s['type'] == 'pause' for s in steps)

    step_kwargs = dict(
        steps=steps,
        emote_def=emote_def,
        user_sid=user.sid,
        room_id=room.room_id,
        first_msg=first_msg,
        second_msg=second_msg,
        second_sid=second_sid,
        third_msg=third_msg,
        nested_emote_refs=refs,
        nested_user_sid=user.sid,
        nested_room_id=room.room_id,
        nested_user_label=user.label,
        nested_extra_text=extra_text,
        depth=_depth,
    )

    if has_pause:
        # Run in a background thread so we don't block the socket handler.
        from . import server as _server
        _server.socketio.start_background_task(
            _execute_steps, **step_kwargs, in_handler=False
        )
    else:
        _execute_steps(**step_kwargs, in_handler=True)
