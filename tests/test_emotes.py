"""Unit tests for the emotes system.

Tests cover:
- ``load_emotes()``  — YAML loading and key merging
- ``parse_message()`` — inline emote token parsing and implicit .say
- ``make_emote_text()`` — message generation with placeholder substitution
- ``do_emote()`` — 1st/2nd/3rd person emit dispatch
- Animation steps: ``!N``, ``#s``, ``.<emoteID>``, default animation
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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
    def test_loads_keys_and_ignores_missing_world_path(self, tmp_path):
        """Flat + qualified keys are registered; nonexistent world_path is silently skipped."""
        from tinyrooms import emotes
        emotes.emote_defs = {}

        _make_emote_yaml(tmp_path, "main", {"smile": _simple_emote(), "wave": _simple_emote("You wave", "$0 waves")})
        emotes.load_emotes(server_path=tmp_path, world_path=tmp_path / "nonexistent")

        assert "smile" in emotes.emote_defs
        assert "wave" in emotes.emote_defs
        assert "main.smile" in emotes.emote_defs
        assert "main.wave" in emotes.emote_defs

    def test_world_overrides_server_and_qualified_keys_reflect_file(self, tmp_path):
        """World emotes take precedence; qualified keys are created per source file."""
        from tinyrooms import emotes
        emotes.emote_defs = {}

        server_dir = tmp_path / "server"
        world_dir = tmp_path / "world"
        _make_emote_yaml(server_dir, "main", {"smile": _simple_emote("Server smile", "$0 server-smiles")})
        _make_emote_yaml(world_dir, "main", {"smile": _simple_emote("World smile", "$0 world-smiles")})
        _make_emote_yaml(world_dir, "custom", {"hug": _simple_emote("You hug", "$0 hugs")})

        emotes.load_emotes(server_path=server_dir, world_path=world_dir)

        assert emotes.emote_defs["smile"]["msg"][0]["verb"][0] == "World smile"
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

    def test_inline_emote_token(self):
        """plain text → implicit say; .go parsed as emote; pure emote has no implicit say; multiple work."""
        e = self._parse("hello world").emotes
        assert len(e) == 1 and e[0].emote_id == "say" and e[0].extra_text == "hello world"

        assert any(e.emote_id == "go" for e in self._parse(".go @way:somewhere").emotes)

        parsed = self._parse(".smile")
        assert parsed.emotes[0].emote_id == "smile" and parsed.emotes[0].filename == "main"
        assert not any(e.emote_id == "say" for e in parsed.emotes), "pure emote should not create say"

        ids = [e.emote_id for e in self._parse(".smile .wave").emotes]
        assert "smile" in ids and "wave" in ids

    def test_emote_with_inline_target(self):
        """'hello! .smile@alice' → say('hello!') then smile targeting alice only."""
        alice = _FakeUser("alice", "sid-alice")
        bob = _FakeUser("bob", "sid-bob")
        parsed = self._parse("hello! .smile@alice @bob", room_users={"alice": alice, "bob": bob})
        assert parsed.emotes[0].emote_id == "say"
        assert parsed.emotes[0].extra_text == "hello!"
        smile = next(e for e in parsed.emotes if e.emote_id == "smile")
        assert smile.refs == [alice], "only the @alice ref should attach to .smile"

    def test_leading_emote_with_following_text(self):
        """.smile@alice hello → smile first, then say 'hello'."""
        alice = _FakeUser("alice", "sid-alice")
        parsed = self._parse(".smile@alice hello", room_users={"alice": alice})
        say_emotes = [e for e in parsed.emotes if e.emote_id == "say"]
        smile_emotes = [e for e in parsed.emotes if e.emote_id == "smile"]
        assert say_emotes and say_emotes[0].extra_text == "hello"
        assert smile_emotes and smile_emotes[0].refs == [alice]

    def test_qualified_filename_prefix(self):
        """.funny.dance resolves to emote_id='dance', filename='funny'."""
        parsed = self._parse(".funny.dance")
        assert parsed.emotes[0].emote_id == "dance"
        assert parsed.emotes[0].filename == "funny"


# ---------------------------------------------------------------------------
# make_emote_text
# ---------------------------------------------------------------------------

class TestMakeEmoteText:
    def _text(self, emote_def, refs=None, extra=""):
        from tinyrooms.text import make_emote_text
        return make_emote_text(emote_def, "Alice", refs or [], extra)

    def test_no_refs_returns_first_variant(self):
        """$0 placeholder substituted; end text appended; malformed msg returns Nones."""
        emote = {"msg": [{"verb": ["You smile", "$0 smiles"]}]}
        first, second, third = self._text(emote)
        assert first == "You smile."
        assert second is None
        assert third == "Alice smiles."

        emote_end = {"msg": [{"verb": ["You hug", "$0 hugs"], "end": ["💕"]}]}
        f2, _, t2 = self._text(emote_end)
        assert f2 == "You hug 💕"
        assert t2 == "Alice hugs 💕"

        bad = {"msg": {"verb": ["You smile", "$0 smiles"]}}
        assert self._text(bad) == (None, None, None)

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


# Module-level mock factories shared by TestDoEmote and TestAnimationSteps
def _mock_user(username="alice", sid=None):
    u = MagicMock()
    u.username = username
    u.sid = sid or f"sid-{username}"
    u.label = username.title()
    return u


def _mock_room(room_id="room1"):
    r = MagicMock()
    r.room_id = room_id
    return r


# ---------------------------------------------------------------------------
# do_emote — message dispatch
# ---------------------------------------------------------------------------

class TestDoEmote:
    def test_emits_first_and_third_person(self):
        """Normal emote dispatches 1st/3rd person; missing animations defaults to !0; unknown emote does not raise."""
        from tinyrooms import emotes
        emotes.emote_defs = {
            "smile": {"msg": [{"verb": ["You smile", "$0 smiles"]}], "animations": "!0"},
        }

        emitted: list[tuple] = []
        with patch("flask_socketio.emit", side_effect=lambda e, d, **kw: emitted.append((e, d, kw))):
            emotes.do_emote("smile", [], _mock_user(), _mock_room())

        texts = [e[1]["text"] for e in emitted if e[0] == "message"]
        assert any("You smile" in t for t in texts)
        assert any("smiles" in t for t in texts)

        # No 'animations' key → same result
        emotes.emote_defs["smile"].pop("animations")
        emitted2: list[tuple] = []
        with patch("flask_socketio.emit", side_effect=lambda e, d, **kw: emitted2.append((e, d, kw))):
            emotes.do_emote("smile", [], _mock_user(), _mock_room())
        assert any("You smile" in e[1]["text"] for e in emitted2 if e[0] == "message")

        # Unknown emote → no raise
        emotes.emote_defs = {}
        with patch("flask_socketio.emit"):
            emotes.do_emote("nonexistent", [], _mock_user(), _mock_room())

    def test_second_person_sent_to_target_user(self):
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
        with patch("flask_socketio.emit", side_effect=lambda e, d, **kw: emitted.append((e, d, kw))):
            emotes.do_emote("smile", [target_mock], _mock_user(), _mock_room())

        second_person = [e for e in emitted if e[2].get("to") == "sid-bob"]
        assert second_person, "No 2nd-person message sent to target SID"
        assert "smiles at you" in second_person[0][1]["text"]


# ---------------------------------------------------------------------------
# Animation step execution
# ---------------------------------------------------------------------------

class TestAnimationSteps:
    def test_msg_step_index_selects_message_definition(self):
        """!0 emits a message; !1 selects the second message definition."""
        from tinyrooms import emotes
        emotes.emote_defs = {"smile": {"msg": [{"verb": ["You smile", "$0 smiles"]}], "animations": "!0"}}

        emitted: list = []
        with patch("flask_socketio.emit", side_effect=lambda e, d, **kw: emitted.append((e, d, kw))):
            emotes.do_emote("smile", [], _mock_user(), _mock_room())
        assert any(e[0] == "message" for e in emitted)

        emotes.emote_defs = {
            "smile": {
                "msg": [
                    {"verb": ["You base", "$0 base"], "target": ""},
                    {"verb": ["You alt", "$0 alt"], "target": ""},
                ],
                "animations": "!1",
            }
        }
        emitted2: list = []
        with patch("flask_socketio.emit", side_effect=lambda e, d, **kw: emitted2.append((e, d, kw))):
            emotes.do_emote("smile", [], _mock_user(), _mock_room())
        texts = [e[1]["text"] for e in emitted2 if e[0] == "message" and e[2].get("to") == "sid-alice"]
        assert "You alt." in texts

    def test_nested_emote_depth_guard(self):
        """At depth 0, inner emote is invoked; at depth 1 it is silently skipped."""
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
            emotes.do_emote("outer", [], _mock_user(), _mock_room())

        texts = [e[1]["text"] for e in emitted if e[0] == "message"]
        assert any("outer" in t.lower() for t in texts)
        assert any("inner" in t.lower() for t in texts)

        # At depth 1, inner is skipped
        from tinyrooms.emotes import _execute_steps, _parse_animation_steps
        emotes.emote_defs["inner"]["msg"][0]["verb"] = ["SHOULD NOT APPEAR", "SHOULD NOT APPEAR"]
        emitted2: list = []
        steps = _parse_animation_steps("!0,.inner")
        with patch("flask_socketio.emit", side_effect=lambda e, d, **kw: emitted2.append((e, d, kw))):
            _execute_steps(
                steps, emotes.emote_defs["outer"],
                "sid-alice", "room1", [], "Alice", "",
                depth=1, in_handler=True,
            )
        assert not any("SHOULD NOT APPEAR" in e[1]["text"] for e in emitted2 if e[0] == "message")

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
            fn(**kwargs)
            completed.append(True)

        sio_mock.start_background_task.side_effect = fake_start_bg_task

        emitted: list = []

        with (
            patch("flask_socketio.emit", side_effect=lambda e, d, **kw: emitted.append((e, d, kw))),
            patch("tinyrooms.server.socketio", sio_mock),
        ):
            emotes.do_emote("delayed", [], _mock_user(), _mock_room())

        assert completed, "Background task was not started for a pause step"


# ---------------------------------------------------------------------------
# parse_animation_steps (unit)
# ---------------------------------------------------------------------------

class TestParseAnimationSteps:
    def test_all_step_types(self):
        from tinyrooms.emotes import _parse_animation_steps
        assert _parse_animation_steps("!0") == [{"type": "message", "index": 0}]
        assert _parse_animation_steps("#1.5") == [{"type": "pause", "seconds": 1.5}]
        assert _parse_animation_steps(".smile") == [{"type": "emote", "emote_id": "smile"}]
        assert _parse_animation_steps("idle") == [{"type": "sprite", "anim_id": "idle"}]
        types = [s["type"] for s in _parse_animation_steps("!0,#0.5,.dance,run_anim")]
        assert types == ["message", "pause", "emote", "sprite"]
