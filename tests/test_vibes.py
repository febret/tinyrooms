"""Unit tests for tinyrooms.vibes."""
from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakePeep:
    def __init__(self, peep_id: str, vibes: dict | None = None):
        self.peep_id = peep_id
        self.vibes: dict[str, float] = vibes if vibes is not None else {}

    def label(self):
        return self.peep_id


class _FakeRoom:
    def __init__(self, peeps=None, users=None):
        self.peeps = peeps or {}   # {peep_id: Peep}
        self.users = users or {}   # {username: User}
        self.room_id = "test_room"


class _FakeUser:
    def __init__(self, username, vibes=None):
        self.username = username
        self.peep = _FakePeep(username, vibes)


# ---------------------------------------------------------------------------
# clamp_visible
# ---------------------------------------------------------------------------

class TestClampVisible:
    def test_within_range_unchanged(self):
        from tinyrooms.vibes import clamp_visible
        assert clamp_visible(0.0) == 0.0
        assert clamp_visible(50.0) == 50.0
        assert clamp_visible(-50.0) == -50.0

    def test_above_max_clamped(self):
        from tinyrooms.vibes import clamp_visible
        assert clamp_visible(150.0) == 100.0

    def test_below_min_clamped(self):
        from tinyrooms.vibes import clamp_visible
        assert clamp_visible(-200.0) == -100.0

    def test_exact_bounds_unchanged(self):
        from tinyrooms.vibes import clamp_visible
        assert clamp_visible(100.0) == 100.0
        assert clamp_visible(-100.0) == -100.0


# ---------------------------------------------------------------------------
# describe_vibe
# ---------------------------------------------------------------------------

class TestDescribeVibe:
    def test_zero_returns_empty(self):
        from tinyrooms.vibes import describe_vibe
        assert describe_vibe(0.0) == ""

    def test_positive_bands(self):
        from tinyrooms.vibes import describe_vibe
        assert "Friend" in describe_vibe(1)
        assert "Friend" in describe_vibe(25)
        assert "Buddy" in describe_vibe(26)
        assert "Buddy" in describe_vibe(50)
        assert "BFF" in describe_vibe(51)
        assert "BFF" in describe_vibe(75)
        assert "Supreme BFF" in describe_vibe(76)
        assert "Supreme BFF" in describe_vibe(100)

    def test_negative_bands(self):
        from tinyrooms.vibes import describe_vibe
        assert "Annoyance" in describe_vibe(-1)
        assert "Annoyance" in describe_vibe(-25)
        assert "Enemy" in describe_vibe(-26)
        assert "Enemy" in describe_vibe(-50)
        assert "Nemesis" in describe_vibe(-51)
        assert "Nemesis" in describe_vibe(-75)
        assert "Archnemesis" in describe_vibe(-76)
        assert "Archnemesis" in describe_vibe(-100)

    def test_above_visible_max_clamped_to_supreme_bff(self):
        from tinyrooms.vibes import describe_vibe
        assert "Supreme BFF" in describe_vibe(999)

    def test_below_visible_min_clamped_to_archnemesis(self):
        from tinyrooms.vibes import describe_vibe
        assert "Archnemesis" in describe_vibe(-999)


# ---------------------------------------------------------------------------
# normalize_vibe_map
# ---------------------------------------------------------------------------

class TestNormalizeVibeMap:
    def test_empty_dict(self):
        from tinyrooms.vibes import normalize_vibe_map
        assert normalize_vibe_map({}) == {}

    def test_non_dict_returns_empty(self):
        from tinyrooms.vibes import normalize_vibe_map
        assert normalize_vibe_map(None) == {}
        assert normalize_vibe_map("foo") == {}
        assert normalize_vibe_map([1, 2]) == {}

    def test_valid_entries_preserved(self):
        from tinyrooms.vibes import normalize_vibe_map
        result = normalize_vibe_map({"alice": 30.0, "bob": -15.5})
        assert result == {"alice": 30.0, "bob": -15.5}

    def test_zero_entries_removed(self):
        from tinyrooms.vibes import normalize_vibe_map
        result = normalize_vibe_map({"alice": 0.0, "bob": 5.0})
        assert "alice" not in result
        assert result["bob"] == 5.0

    def test_non_numeric_values_dropped(self):
        from tinyrooms.vibes import normalize_vibe_map
        result = normalize_vibe_map({"alice": "notanumber", "bob": 10.0})
        assert "alice" not in result
        assert result["bob"] == 10.0

    def test_empty_string_key_dropped(self):
        from tinyrooms.vibes import normalize_vibe_map
        result = normalize_vibe_map({"": 50.0, "alice": 10.0})
        assert "" not in result
        assert result["alice"] == 10.0


# ---------------------------------------------------------------------------
# get_baseline / set_baseline / apply_baseline_delta
# ---------------------------------------------------------------------------

class TestBaselineOperations:
    def test_get_baseline_unknown_returns_zero(self):
        from tinyrooms.vibes import get_baseline
        peep = _FakePeep("alice")
        assert get_baseline(peep, "bob") == 0.0

    def test_set_and_get_baseline(self):
        from tinyrooms.vibes import set_baseline, get_baseline
        peep = _FakePeep("alice")
        set_baseline(peep, "bob", 42.0)
        assert get_baseline(peep, "bob") == 42.0

    def test_set_baseline_zero_removes_entry(self):
        from tinyrooms.vibes import set_baseline, get_baseline
        peep = _FakePeep("alice", {"bob": 20.0})
        set_baseline(peep, "bob", 0.0)
        assert "bob" not in peep.vibes
        assert get_baseline(peep, "bob") == 0.0

    def test_apply_baseline_delta(self):
        from tinyrooms.vibes import apply_baseline_delta, get_baseline
        peep = _FakePeep("alice", {"bob": 10.0})
        result = apply_baseline_delta(peep, "bob", 5.0)
        assert result == 15.0
        assert get_baseline(peep, "bob") == 15.0

    def test_apply_baseline_delta_from_zero(self):
        from tinyrooms.vibes import apply_baseline_delta, get_baseline
        peep = _FakePeep("alice")
        result = apply_baseline_delta(peep, "bob", 7.5)
        assert result == 7.5
        assert get_baseline(peep, "bob") == 7.5

    def test_apply_baseline_delta_negative(self):
        from tinyrooms.vibes import apply_baseline_delta, get_baseline
        peep = _FakePeep("alice", {"bob": 5.0})
        result = apply_baseline_delta(peep, "bob", -10.0)
        assert result == -5.0
        assert get_baseline(peep, "bob") == -5.0


# ---------------------------------------------------------------------------
# get_target_vibe
# ---------------------------------------------------------------------------

class TestGetTargetVibe:
    def test_returns_baseline(self):
        from tinyrooms.vibes import get_target_vibe
        alice = _FakePeep("alice", {"bob": 30.0})
        bob = _FakePeep("bob")
        assert get_target_vibe(alice, bob) == 30.0

    def test_unknown_target_returns_zero(self):
        from tinyrooms.vibes import get_target_vibe
        alice = _FakePeep("alice")
        bob = _FakePeep("bob")
        assert get_target_vibe(alice, bob) == 0.0


# ---------------------------------------------------------------------------
# get_room_vibe
# ---------------------------------------------------------------------------

class TestGetRoomVibe:
    def test_empty_room_returns_zero(self):
        from tinyrooms.vibes import get_room_vibe
        npc = _FakePeep("npc1")
        room = _FakeRoom()
        assert get_room_vibe(npc, room) == 0.0

    def test_excludes_target_peep_itself(self):
        from tinyrooms.vibes import get_room_vibe
        npc = _FakePeep("npc1")
        room = _FakeRoom(peeps={"npc1": npc})
        assert get_room_vibe(npc, room) == 0.0

    def test_averages_npc_baselines(self):
        from tinyrooms.vibes import get_room_vibe
        target = _FakePeep("target")
        peep_a = _FakePeep("a", {"target": 20.0})
        peep_b = _FakePeep("b", {"target": 60.0})
        room = _FakeRoom(peeps={"target": target, "a": peep_a, "b": peep_b})
        assert get_room_vibe(target, room) == pytest.approx(40.0)

    def test_averages_user_baselines(self):
        from tinyrooms.vibes import get_room_vibe
        target = _FakePeep("target")
        user_a = _FakeUser("ua", {"target": 10.0})
        user_b = _FakeUser("ub", {"target": -10.0})
        room = _FakeRoom(peeps={"target": target}, users={"ua": user_a, "ub": user_b})
        assert get_room_vibe(target, room) == pytest.approx(0.0)

    def test_averages_mixed_peeps_and_users(self):
        from tinyrooms.vibes import get_room_vibe
        target = _FakePeep("target")
        npc = _FakePeep("npc", {"target": 30.0})
        user_a = _FakeUser("ua", {"target": 50.0})
        room = _FakeRoom(peeps={"target": target, "npc": npc}, users={"ua": user_a})
        assert get_room_vibe(target, room) == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# decay_active_baselines
# ---------------------------------------------------------------------------

class TestDecayActiveBaselines:
    def _make_world(self, peeps: dict):
        world = type("World", (), {"peeps": peeps})()
        return world

    def test_decay_reduces_positive_vibes(self):
        from tinyrooms.vibes import decay_active_baselines
        alice = _FakePeep("alice", {"bob": 10.0})
        world = self._make_world({"alice": alice})
        decay_active_baselines(world, amount_per_minute=1.0)
        assert alice.vibes["bob"] == pytest.approx(9.0)

    def test_decay_increases_negative_vibes_toward_zero(self):
        from tinyrooms.vibes import decay_active_baselines
        alice = _FakePeep("alice", {"bob": -10.0})
        world = self._make_world({"alice": alice})
        decay_active_baselines(world, amount_per_minute=1.0)
        assert alice.vibes["bob"] == pytest.approx(-9.0)

    def test_decay_removes_near_zero_entries(self):
        from tinyrooms.vibes import decay_active_baselines
        alice = _FakePeep("alice", {"bob": 0.05})
        world = self._make_world({"alice": alice})
        decay_active_baselines(world, amount_per_minute=0.1)
        assert "bob" not in alice.vibes

    def test_decay_removes_near_zero_negative_entries(self):
        from tinyrooms.vibes import decay_active_baselines
        alice = _FakePeep("alice", {"bob": -0.05})
        world = self._make_world({"alice": alice})
        decay_active_baselines(world, amount_per_minute=0.1)
        assert "bob" not in alice.vibes

    def test_decay_no_op_on_empty_vibes(self):
        from tinyrooms.vibes import decay_active_baselines
        alice = _FakePeep("alice")
        world = self._make_world({"alice": alice})
        decay_active_baselines(world, amount_per_minute=1.0)
        assert alice.vibes == {}

    def test_decay_default_amount(self):
        from tinyrooms.vibes import decay_active_baselines, DEFAULT_DECAY_PER_MINUTE
        alice = _FakePeep("alice", {"bob": 5.0})
        world = self._make_world({"alice": alice})
        decay_active_baselines(world)
        assert alice.vibes["bob"] == pytest.approx(5.0 - DEFAULT_DECAY_PER_MINUTE)


# ---------------------------------------------------------------------------
# DB round-trip tests
# ---------------------------------------------------------------------------

class TestDbVibesRoundTrip:
    def test_write_and_read_back_npc_vibes(self, tmp_path):
        """Vibes JSON written for an NPC peep is read back correctly."""
        import duckdb
        from tinyrooms import db
        db_path = tmp_path / "test.duckdb"
        conn = duckdb.connect(str(db_path))
        db.init_workstate_schema(conn)

        npc = _FakePeep("npc1", {"alice": 35.0, "bob": -20.0})
        npc.type = "npc"
        npc.location_id = "@room:lobby"
        npc.class_id = "test_class"
        npc.x = 100
        npc.y = 200
        npc.orientation = "right"
        npc.layer = 1
        npc.z_order = 1

        db.write_peep_data(conn, {"npc1": npc})
        result = db.read_peep_data(conn)
        conn.close()

        assert "npc1" in result
        saved_vibes = result["npc1"]["vibes"]
        assert saved_vibes["alice"] == pytest.approx(35.0)
        assert saved_vibes["bob"] == pytest.approx(-20.0)

    def test_write_and_read_user_vibes(self, tmp_path):
        """Vibes JSON written for a user peep is read back via read_peep_vibes."""
        import duckdb
        from tinyrooms import db
        db_path = tmp_path / "test.duckdb"
        conn = duckdb.connect(str(db_path))
        db.init_workstate_schema(conn)

        user_peep = _FakePeep("alice_user", {"npc1": 55.0})
        user_peep.type = "user"

        db.write_peep_data(conn, {"alice_user": user_peep})
        vibes = db.read_peep_vibes(conn, "alice_user")
        conn.close()

        assert vibes["npc1"] == pytest.approx(55.0)

    def test_read_peep_vibes_missing_returns_empty(self, tmp_path):
        """read_peep_vibes returns {} when the peep row does not exist."""
        import duckdb
        from tinyrooms import db
        db_path = tmp_path / "test.duckdb"
        conn = duckdb.connect(str(db_path))
        db.init_workstate_schema(conn)
        vibes = db.read_peep_vibes(conn, "nonexistent")
        conn.close()
        assert vibes == {}

    def test_user_vibe_upsert_only_updates_vibes(self, tmp_path):
        """A second write for a user peep only changes vibes, preserving existing row data."""
        import duckdb
        from tinyrooms import db
        db_path = tmp_path / "test.duckdb"
        conn = duckdb.connect(str(db_path))
        db.init_workstate_schema(conn)

        user_peep = _FakePeep("charlie", {"npc1": 10.0})
        user_peep.type = "user"
        db.write_peep_data(conn, {"charlie": user_peep})

        # Update vibes and write again
        user_peep.vibes["npc1"] = 25.0
        user_peep.vibes["npc2"] = -5.0
        db.write_peep_data(conn, {"charlie": user_peep})

        vibes = db.read_peep_vibes(conn, "charlie")
        conn.close()
        assert vibes["npc1"] == pytest.approx(25.0)
        assert vibes["npc2"] == pytest.approx(-5.0)


# ---------------------------------------------------------------------------
# Emote vibe delta tests
# ---------------------------------------------------------------------------

class TestEmoteVibeHook:
    def _make_mock_user(self, username="alice", peep_id=None):
        from unittest.mock import MagicMock
        u = MagicMock()
        u.username = username
        u.sid = f"sid-{username}"
        u.label = username
        peep = _FakePeep(peep_id or username)
        u.peep = peep
        return u

    def _make_mock_room(self, room_id="room1"):
        from unittest.mock import MagicMock
        r = MagicMock()
        r.room_id = room_id
        return r

    def test_emote_with_vibe_field_applies_delta_to_target_peep(self):
        """An emote with a positive 'vibe' field increases target's vibe toward source."""
        from unittest.mock import patch
        from tinyrooms import emotes

        source_user = self._make_mock_user("alice")
        target_peep = _FakePeep("npc1")

        emotes.emote_defs = {
            "smile": {
                "msg": [{"verb": ["You smile", "$0 smiles"]}],
                "animations": "!0",
                "vibe": 5.0,
            }
        }

        with patch("flask_socketio.emit"):
            emotes.do_emote("smile", [target_peep], source_user, self._make_mock_room())

        from tinyrooms.vibes import get_baseline
        assert get_baseline(target_peep, "alice") == pytest.approx(5.0)

    def test_emote_with_vibe_field_applies_delta_to_user_ref(self):
        """An emote applies the vibe delta when the target ref is a User (not a bare Peep)."""
        from unittest.mock import patch
        from tinyrooms import emotes

        source_user = self._make_mock_user("alice")

        target_user = self._make_mock_user("bob")
        from tinyrooms.user import User as _RealUser
        from unittest.mock import MagicMock
        target_user_mock = MagicMock(spec=_RealUser)
        target_user_mock.sid = "sid-bob"
        target_user_mock.label = "Bob"
        target_user_mock.peep = _FakePeep("bob")

        emotes.emote_defs = {
            "smile": {
                "msg": [{"verb": ["You smile", "$0 smiles"], "target": "at $1"}],
                "animations": "!0",
                "vibe": 3.0,
            }
        }

        with patch("flask_socketio.emit"):
            emotes.do_emote("smile", [target_user_mock], source_user, self._make_mock_room())

        from tinyrooms.vibes import get_baseline
        assert get_baseline(target_user_mock.peep, "alice") == pytest.approx(3.0)

    def test_emote_without_vibe_field_does_not_change_vibes(self):
        """An emote without a 'vibe' field should not affect any baselines."""
        from unittest.mock import patch
        from tinyrooms import emotes

        source_user = self._make_mock_user("alice")
        target_peep = _FakePeep("npc1")

        emotes.emote_defs = {
            "wave": {
                "msg": [{"verb": ["You wave", "$0 waves"]}],
                "animations": "!0",
            }
        }

        with patch("flask_socketio.emit"):
            emotes.do_emote("wave", [target_peep], source_user, self._make_mock_room())

        assert target_peep.vibes == {}

    def test_emote_with_no_refs_does_not_raise(self):
        """Emote with vibe field but no refs should not raise."""
        from unittest.mock import patch
        from tinyrooms import emotes

        source_user = self._make_mock_user("alice")

        emotes.emote_defs = {
            "smile": {
                "msg": [{"verb": ["You smile", "$0 smiles"]}],
                "animations": "!0",
                "vibe": 5.0,
            }
        }

        with patch("flask_socketio.emit"):
            emotes.do_emote("smile", [], source_user, self._make_mock_room())


# ---------------------------------------------------------------------------
# Look panel vibe display
# ---------------------------------------------------------------------------

class TestLookPanelVibes:
    def _make_user_obj(self, username="alice", peep_vibes=None):
        from unittest.mock import MagicMock
        u = MagicMock()
        u.username = username
        u.sid = f"sid-{username}"
        u.peep = _FakePeep(username, peep_vibes)
        room = MagicMock()
        room.room_id = "test_room"
        room.users = {}
        room.peeps = {}
        room.objs = {}
        room.props = {}
        room.ways = {}
        u.room = room
        return u

    def _make_peep_target(self, peep_id, peep_type="npc", vibes=None):
        peep = _FakePeep(peep_id, vibes)
        peep.type = peep_type
        return peep

    def test_look_panel_includes_vibe_descriptor(self):
        """Look panel for a peep target should include vibe descriptor text."""
        from tinyrooms.commands import _build_look_panel

        user_obj = self._make_user_obj("alice", {"bob_npc": 30.0})
        target_peep = self._make_peep_target("bob_npc", vibes={"alice": 50.0})

        resolved = {
            "type": "peep",
            "entity": target_peep,
            "target_ref": "@peep:bob_npc",
        }
        title, content = _build_look_panel(user_obj, resolved)
        assert "Buddy" in content or "BFF" in content or "vibe" in content.lower()

    def test_look_panel_shows_both_directions(self):
        """Look panel should show your vibe toward target AND target's vibe toward you."""
        from tinyrooms.commands import _build_look_panel

        user_obj = self._make_user_obj("alice", {"bob_npc": 10.0})
        target_peep = self._make_peep_target("bob_npc", vibes={"alice": -25.0})

        resolved = {
            "type": "peep",
            "entity": target_peep,
            "target_ref": "@peep:bob_npc",
        }
        title, content = _build_look_panel(user_obj, resolved)
        # Should mention both the user's positive vibe (Friend) and target's negative (Annoyance)
        assert "Friend" in content
        assert "Annoyance" in content

    def test_look_panel_shows_unknown_for_zero_vibe(self):
        """Zero vibe should appear as 'Unknown' in the look panel."""
        from tinyrooms.commands import _build_look_panel

        user_obj = self._make_user_obj("alice")
        target_peep = self._make_peep_target("bob_npc")

        resolved = {
            "type": "peep",
            "entity": target_peep,
            "target_ref": "@peep:bob_npc",
        }
        title, content = _build_look_panel(user_obj, resolved)
        assert "Unknown" in content
