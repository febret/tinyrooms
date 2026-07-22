"""Unit tests for the emotes system.

Tests cover:
- ``load_emotes()``  — YAML loading and key merging
- ``parse_message()`` — inline emote token parsing and implicit .say
- ``make_emote_text()`` — message generation with placeholder substitution
- ``do_emote()`` — 1st/2nd/3rd person emit dispatch
- Animation steps: ``!N``, ``#s``, ``.<emoteID>``, default animation
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_emote_yaml(path: Path, name: str, defs: dict):
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{name}.yaml").write_text(yaml.safe_dump(defs, allow_unicode=True), encoding="utf-8")


def _simple_emote(first="You smile", third="$0 smiles"):
    return {
        "msg": [{"verb": [first, third], "end": ["."]}],
        "animations": "!0",
    }


# ---------------------------------------------------------------------------
# Minimal stubs for User / Room so parse_message doesn't need the full stack
# ---------------------------------------------------------------------------

class _FakeUser:
    def __init__(self, username="alice", sid="sid-alice"):
        self.username = username
        self.sid = sid
        self.label = f"[[@{username}[[#d33 {username}]]]]"


class _FakeRoom:
    def __init__(self, users=None):
        self.users = users or {}
        self.objs = {}
        self.props = {}
        self.room_id = "test_room"
        self.peeps = {}


# ---------------------------------------------------------------------------
# load_emotes
# ---------------------------------------------------------------------------

class TestLoadEmotes:
    def test_loads_flat_and_qualified_keys(self, tmp_path):
        from tinyrooms import emotes
        emotes.emote_defs = {}

        _make_emote_yaml(tmp_path, "main", {"smile": _simple_emote(), "wave": _simple_emote("You wave", "$0 waves")})
        emotes.load_emotes(server_path=tmp_path)

        # Flat keys
        assert "smile" in emotes.emote_defs
        assert "wave" in emotes.emote_defs
        # Qualified keys
        assert "main.smile" in emotes.emote_defs
        assert "main.wave" in emotes.emote_defs

    def test_world_emote_overrides_server_emote(self, tmp_path):
        from tinyrooms import emotes
        emotes.emote_defs = {}

        server_dir = tmp_path / "server"
        world_dir = tmp_path / "world"
        _make_emote_yaml(server_dir, "main", {"smile": _simple_emote("Server smile", "$0 server-smiles")})
        _make_emote_yaml(world_dir, "main", {"smile": _simple_emote("World smile", "$0 world-smiles")})

        emotes.load_emotes(server_path=server_dir, world_path=world_dir)

        msg = emotes.emote_defs["smile"]["msg"]
        assert msg[0]["verb"][0] == "World smile"

    def test_qualified_key_always_reflects_loaded_file(self, tmp_path):
        from tinyrooms import emotes
        emotes.emote_defs = {}

        server_dir = tmp_path / "server"
        world_dir = tmp_path / "world"
        _make_emote_yaml(server_dir, "main", {"smile": _simple_emote("Server smile", "$0 s")})
        _make_emote_yaml(world_dir, "custom", {"hug": _simple_emote("You hug", "$0 hugs")})

        emotes.load_emotes(server_path=server_dir, world_path=world_dir)

        assert "main.smile" in emotes.emote_defs
        assert "custom.hug" in emotes.emote_defs
        assert "hug" in emotes.emote_defs

    def test_loads_from_default_server_path(self):
        """load_emotes() with no arguments finds data/emotes/main.yaml."""
        from tinyrooms import emotes
        emotes.emote_defs = {}
        emotes.load_emotes()
        assert "say" in emotes.emote_defs
        assert "smile" in emotes.emote_defs

    def test_missing_world_path_is_silently_ignored(self, tmp_path):
        from tinyrooms import emotes
        emotes.emote_defs = {}
        server_dir = tmp_path / "server"
        _make_emote_yaml(server_dir, "main", {"smile": _simple_emote()})

        emotes.load_emotes(server_path=server_dir, world_path=tmp_path / "nonexistent")
        assert "smile" in emotes.emote_defs


# ---------------------------------------------------------------------------
# parse_message
# ---------------------------------------------------------------------------

class TestParseMessage:
    def _parse(self, text, room_users=None):
        from tinyrooms import message, emotes
        emotes.load_emotes()   # ensure emote_defs populated for parse_message

        user = _FakeUser()
        room = _FakeRoom(users=room_users or {})

        with (
            patch("tinyrooms.message.active_world") as mock_world,
            patch("tinyrooms.message.connected_users", {}),
        ):
            mock_world.return_value.ways = {}
            mock_world.return_value.peeps = {}
            return message.parse_message(text, user, room)

    def test_plain_text_creates_implicit_say(self):
        parsed = self._parse("hello world")
        assert len(parsed.emotes) == 1
        emote = parsed.emotes[0]
        assert emote.emote_id == "say"
        assert emote.extra_text == "hello world"

    def test_inline_emote_token(self):
        parsed = self._parse(".smile")
        assert len(parsed.emotes) == 1
        assert parsed.emotes[0].emote_id == "smile"
        assert parsed.emotes[0].filename == "main"

    def test_emote_with_inline_target_and_leading_text(self):
        """'hello! .smile@alice' → implicit say('hello!') then smile targeting alice."""
        alice = _FakeUser("alice", "sid-alice")
        parsed = self._parse("hello! .smile@alice", room_users={"alice": alice})
        # First emote is implicit say with 'hello!'
        assert parsed.emotes[0].emote_id == "say"
        assert parsed.emotes[0].extra_text == "hello!"
        # Second emote is smile at alice
        assert parsed.emotes[1].emote_id == "smile"
        assert parsed.emotes[1].refs == [alice]

    def test_leading_emote_with_following_text(self):
        """.smile@alice hello → smile first, then say 'hello'."""
        alice = _FakeUser("alice", "sid-alice")
        parsed = self._parse(".smile@alice hello", room_users={"alice": alice})
        # The say emote comes first (all plain text is gathered), smile follows
        say_emotes = [e for e in parsed.emotes if e.emote_id == "say"]
        smile_emotes = [e for e in parsed.emotes if e.emote_id == "smile"]
        assert say_emotes and say_emotes[0].extra_text == "hello"
        assert smile_emotes and smile_emotes[0].refs == [alice]

    def test_qualified_filename_prefix(self):
        """.funny.dance resolves to emote_id='dance', filename='funny'."""
        parsed = self._parse(".funny.dance")
        assert parsed.emotes[0].emote_id == "dance"
        assert parsed.emotes[0].filename == "funny"

    def test_go_token_treated_as_emote(self):
        """.go is no longer a special action — it is parsed as an emote token."""
        parsed = self._parse(".go @way:somewhere")
        assert not any(e.emote_id == "go" and e.filename != "main" for e in parsed.emotes)
        # Treated as a regular emote with id 'go'
        go_emotes = [e for e in parsed.emotes if e.emote_id == "go"]
        assert go_emotes

    def test_pure_emote_message_no_implicit_say(self):
        """.smile with no plain text should not create a say emote."""
        parsed = self._parse(".smile")
        assert not any(e.emote_id == "say" for e in parsed.emotes)

    def test_multiple_inline_emotes(self):
        parsed = self._parse(".smile .wave")
        emote_ids = [e.emote_id for e in parsed.emotes]
        assert "smile" in emote_ids
        assert "wave" in emote_ids

    def test_only_one_target_attached_per_emote(self):
        alice = _FakeUser("alice", "sid-alice")
        bob = _FakeUser("bob", "sid-bob")
        parsed = self._parse(".smile@alice @bob", room_users={"alice": alice, "bob": bob})
        assert parsed.emotes[0].refs == [alice]


# ---------------------------------------------------------------------------
# make_emote_text
# ---------------------------------------------------------------------------

class TestMakeEmoteText:
    def _text(self, emote_def, refs=None, extra=""):
        from tinyrooms.text import make_emote_text
        return make_emote_text(emote_def, "Alice", refs or [], extra)

    def test_no_refs_returns_first_variant(self):
        emote = {"msg": [{"verb": ["You smile", "$0 smiles"]}]}
        first, second, third = self._text(emote)
        assert first == "You smile."
        assert second is None
        assert third == "Alice smiles."

    def test_with_ref_uses_target_clause(self):
        emote = {
            "msg": [{"verb": ["You smile", "$0 smiles"], "target": "at $1"}]
        }
        target = _FakeUser("bob")
        first, second, third = self._text(emote, refs=[target])
        assert "Bob" in first or "bob" in first.lower()
        assert "$0 smiles at you." in second.replace("Alice", "$0")
        assert "bob" in third.lower() or "Bob" in third

    def test_extra_text_appended(self):
        emote = {"msg": [{"verb": ["You say", "$0 says"], "target": ""}]}
        first, _, third = self._text(emote, extra="hello world")
        assert first == "You say: hello world."
        assert "Alice says: hello world." == third

    def test_end_text_appended(self):
        emote = {"msg": [{"verb": ["You hug", "$0 hugs"], "end": ["💕"]}]}
        first, _, third = self._text(emote)
        assert first == "You hug 💕"
        assert third == "Alice hugs 💕"

    def test_msg_index_can_select_specific_message_set(self):
        from tinyrooms.text import make_emote_text
        emote = {
            "msg": [
                {"verb": ["Set A", "$0 set A"], "target": ""},
                {"verb": ["Set B", "$0 set B"], "target": ""},
            ]
        }
        first, _, _ = make_emote_text(emote, "Alice", [], "", msg_index=1)
        assert first == "Set B."

    def test_msg_must_be_array_of_message_definitions(self):
        emote = {"msg": {"verb": ["You smile", "$0 smiles"]}}
        first, second, third = self._text(emote)
        assert first is None
        assert second is None
        assert third is None

    def test_placeholder_zero_substituted(self):
        emote = {"msg": [{"verb": ["You smile", "$0 smiles"]}]}
        _, _, third = self._text(emote)
        assert third == "Alice smiles."


# ---------------------------------------------------------------------------
# do_emote — message dispatch
# ---------------------------------------------------------------------------

class TestDoEmote:
    def _make_user(self, username="alice", sid="sid-alice"):
        u = MagicMock()
        u.username = username
        u.sid = sid
        u.label = username.title()
        return u

    def _make_room(self, room_id="room1"):
        r = MagicMock()
        r.room_id = room_id
        return r

    def test_emits_first_and_third_person(self, tmp_path):
        from tinyrooms import emotes
        emotes.emote_defs = {
            "smile": {
                "msg": [{"verb": ["You smile", "$0 smiles"]}],
                "animations": "!0",
            }
        }

        emitted: list[tuple] = []

        def fake_emit(event, data, **kwargs):
            emitted.append((event, data, kwargs))

        with patch("flask_socketio.emit", side_effect=fake_emit):
            emotes.do_emote("smile", [], self._make_user(), self._make_room())

        events = [e[0] for e in emitted]
        assert "message" in events
        texts = [e[1]["text"] for e in emitted if e[0] == "message"]
        assert any("You smile" in t for t in texts)
        assert any("smiles" in t for t in texts)

    def test_second_person_sent_to_target_user(self, tmp_path):
        from tinyrooms import emotes
        from tinyrooms.user import User as _RealUser

        target_mock = MagicMock(spec=_RealUser)
        target_mock.sid = "sid-bob"
        target_mock.label = "Bob"

        emotes.emote_defs = {
            "smile": {
                "msg": [{"verb": ["You smile", "$0 smiles"], "target": "at $1"}],
                "animations": "!0",
            }
        }

        emitted: list[tuple] = []

        def fake_emit(event, data, **kwargs):
            emitted.append((event, data, kwargs))

        with patch("flask_socketio.emit", side_effect=fake_emit):
            emotes.do_emote("smile", [target_mock], self._make_user(), self._make_room())

        # 2nd-person message must be directed to target's sid
        second_person = [e for e in emitted if e[2].get("to") == "sid-bob"]
        assert second_person, "No 2nd-person message sent to target SID"
        assert "smiles at you" in second_person[0][1]["text"]

    def test_unknown_emote_logs_and_does_not_raise(self):
        from tinyrooms import emotes
        emotes.emote_defs = {}
        # Should not raise; just prints a warning
        with patch("flask_socketio.emit"):
            emotes.do_emote("nonexistent", [], self._make_user(), self._make_room())

    def test_default_animation_is_msg_zero(self):
        """When 'animations' is absent, !0 is used as the default."""
        from tinyrooms import emotes
        emotes.emote_defs = {
            "smile": {
                "msg": [{"verb": ["You smile", "$0 smiles"]}],
                # no 'animations' key
            }
        }

        emitted: list[tuple] = []

        def fake_emit(event, data, **kwargs):
            emitted.append((event, data, kwargs))

        with patch("flask_socketio.emit", side_effect=fake_emit):
            emotes.do_emote("smile", [], self._make_user(), self._make_room())

        texts = [e[1]["text"] for e in emitted if e[0] == "message"]
        assert any("You smile" in t for t in texts)


# ---------------------------------------------------------------------------
# Animation step execution
# ---------------------------------------------------------------------------

class TestAnimationSteps:
    def _user(self):
        u = MagicMock()
        u.username = "alice"
        u.sid = "sid-alice"
        u.label = "Alice"
        return u

    def _room(self):
        r = MagicMock()
        r.room_id = "room1"
        return r

    def _emote_def(self, animations="!0"):
        return {
            "msg": [{"verb": ["You smile", "$0 smiles"]}],
            "animations": animations,
        }

    def test_msg_step_emits_message(self):
        from tinyrooms import emotes
        emotes.emote_defs = {"smile": self._emote_def("!0")}

        emitted: list = []
        with patch("flask_socketio.emit", side_effect=lambda e, d, **kw: emitted.append((e, d, kw))):
            emotes.do_emote("smile", [], self._user(), self._room())

        assert any(e[0] == "message" for e in emitted)

    def test_msg_step_index_selects_message_definition(self):
        from tinyrooms import emotes
        emotes.emote_defs = {
            "smile": {
                "msg": [
                    {"verb": ["You base", "$0 base"], "target": ""},
                    {"verb": ["You alt", "$0 alt"], "target": ""},
                ],
                "animations": "!1",
            }
        }

        emitted: list = []
        with patch("flask_socketio.emit", side_effect=lambda e, d, **kw: emitted.append((e, d, kw))):
            emotes.do_emote("smile", [], self._user(), self._room())

        texts = [e[1]["text"] for e in emitted if e[0] == "message" and e[2].get("to") == "sid-alice"]
        assert "You alt." in texts

    def test_nested_emote_step_invoked_at_depth_zero(self):
        from tinyrooms import emotes
        emotes.emote_defs = {
            "outer": {
                "msg": [{"verb": ["You outer", "$0 outer"]}],
                "animations": "!0,.inner",
            },
            "inner": {
                "msg": [{"verb": ["You inner", "$0 inner"]}],
                "animations": "!0",
            },
        }

        emitted: list = []
        with patch("flask_socketio.emit", side_effect=lambda e, d, **kw: emitted.append((e, d, kw))):
            emotes.do_emote("outer", [], self._user(), self._room())

        texts = [e[1]["text"] for e in emitted if e[0] == "message"]
        assert any("outer" in t.lower() for t in texts)
        assert any("inner" in t.lower() for t in texts)

    def test_nested_emote_silently_skipped_at_depth_one(self):
        from tinyrooms import emotes
        emotes.emote_defs = {
            "outer": {
                "msg": [{"verb": ["You outer", "$0 outer"]}],
                "animations": "!0,.inner",
            },
            "inner": {
                "msg": [{"verb": ["SHOULD NOT APPEAR", "SHOULD NOT APPEAR"]}],
                "animations": "!0",
            },
        }

        from tinyrooms.emotes import _execute_steps, _parse_animation_steps

        emitted: list = []

        def fake_emit_fn(event, data, **kwargs):
            emitted.append((event, data, kwargs))

        steps = _parse_animation_steps("!0,.inner")
        outer_def = emotes.emote_defs["outer"]

        with patch("flask_socketio.emit", side_effect=fake_emit_fn):
            _execute_steps(
                steps, outer_def,
                "sid-alice", "room1",
                [], "Alice", "",
                depth=1,  # already at depth 1 → inner should be skipped
                in_handler=True,
            )

        texts = [e[1]["text"] for e in emitted if e[0] == "message"]
        assert not any("SHOULD NOT APPEAR" in t for t in texts)

    def test_pause_step_executes_in_background_thread(self):
        """A #0.05 pause should not block the caller and runs in a background task."""
        from tinyrooms import emotes
        emotes.emote_defs = {
            "delayed": {
                "msg": [{"verb": ["You delayed", "$0 delayed"]}],
                "animations": "!0,#0.05",
            }
        }

        completed = []
        sio_mock = MagicMock()

        def fake_start_bg_task(fn, **kwargs):
            # Run the function directly in this test (synchronously).
            # in_handler=False is already in kwargs from the do_emote call.
            fn(**kwargs)
            completed.append(True)

        sio_mock.start_background_task.side_effect = fake_start_bg_task

        emitted: list = []

        with (
            patch("flask_socketio.emit", side_effect=lambda e, d, **kw: emitted.append((e, d, kw))),
            patch("tinyrooms.server.socketio", sio_mock),
        ):
            emotes.do_emote("delayed", [], self._user(), self._room())

        assert completed, "Background task was not started for a pause step"


# ---------------------------------------------------------------------------
# parse_animation_steps (unit)
# ---------------------------------------------------------------------------

class TestParseAnimationSteps:
    def _parse(self, s):
        from tinyrooms.emotes import _parse_animation_steps
        return _parse_animation_steps(s)

    def test_msg_step(self):
        steps = self._parse("!0")
        assert steps == [{"type": "message", "index": 0}]

    def test_pause_step(self):
        steps = self._parse("#1.5")
        assert steps == [{"type": "pause", "seconds": 1.5}]

    def test_emote_step(self):
        steps = self._parse(".smile")
        assert steps == [{"type": "emote", "emote_id": "smile"}]

    def test_sprite_step(self):
        steps = self._parse("idle")
        assert steps == [{"type": "sprite", "anim_id": "idle"}]

    def test_mixed_steps(self):
        steps = self._parse("!0,#0.5,.dance,run_anim")
        types = [s["type"] for s in steps]
        assert types == ["message", "pause", "emote", "sprite"]
