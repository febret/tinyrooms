"""Unit tests for the superuser command dispatcher and permission framework."""
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers to build mock objects
# ---------------------------------------------------------------------------

def _make_user(username="testuser", powers=None):
    user = MagicMock()
    user.username = username
    user.sid = f"sid_{username}"
    user.skin = "base"
    user.powers = set(powers or [])
    user.has_power = lambda p: p in user.powers
    user.room = None
    user.peep = MagicMock()
    user.peep.x = 32
    user.peep.y = 32
    user.world = MagicMock()
    user.world.ws_id = "home"
    return user


def _make_world(room_ids=("DEFAULT_ROOM", "playroom"), thing_ids=()):
    world = MagicMock()
    world.ws_id = "home"
    world.rooms = {}
    for rid in room_ids:
        room = MagicMock()
        room.room_id = rid
        room.owner_id = ""
        room.label_override = None
        room.description_override = None
        room.users = {}
        room.peeps = {}
        room.objs = {}
        room.props = {}
        room.room_defs = {}
        room.ways = {}
        room.label = MagicMock(return_value=rid)
        world.rooms[rid] = room
    world.thing_defs = {}
    for tid in thing_ids:
        world.thing_defs[tid] = {"label": f"Thing {tid}", "type": "object"}
    world.prop_defs = {}
    world.room_defs = {}
    world.default_room = list(world.rooms.values())[0]
    world.objs = {}
    world.peeps = {}
    world.root_path = "."
    world.save_state = MagicMock()
    return world


# ---------------------------------------------------------------------------
# Test command pattern matching
# ---------------------------------------------------------------------------

from tinyrooms.commands import _matches, _extract_args


def test_matches_simple_keyword():
    assert _matches(["?"], "?")
    assert not _matches(["goto"], "?")


def test_matches_multi_keyword():
    assert _matches(["room", "owner", "show"], "room owner show")
    assert not _matches(["room", "owner"], "room owner show")


def test_matches_keyword_with_arg():
    assert _matches(["goto", "playroom"], "goto <room_id>")
    assert not _matches(["goto"], "goto <room_id>")


def test_matches_greedy_rest():
    assert _matches(["room", "rename", "The", "Cool", "Room"], "room rename ...")
    assert _matches(["room", "rename", "x"], "room rename ...")


def test_extract_args_simple():
    args = _extract_args(["goto", "playroom"], "goto <room_id>")
    assert args == ["playroom"]


def test_extract_args_two_args():
    args = _extract_args(["move", "alice", "playroom"], "move <username> <room_id>")
    assert args == ["alice", "playroom"]


def test_extract_args_greedy():
    args = _extract_args(["room", "rename", "The", "Cool", "Room"], "room rename ...")
    assert args == ["The", "Cool", "Room"]


# ---------------------------------------------------------------------------
# Test dispatch routing
# ---------------------------------------------------------------------------

from tinyrooms.commands import dispatch, dispatch_admin


def _dispatch_and_capture(text, powers=None, room_id="DEFAULT_ROOM"):
    """Run dispatch and capture the activity_panel emission."""
    user = _make_user(powers=powers or [])
    world = _make_world()
    user.room = world.rooms.get(room_id) or world.rooms["DEFAULT_ROOM"]
    captured = {}

    def fake_emit(event, payload, **kwargs):
        if event == "activity_panel":
            captured.update(payload)

    with patch("tinyrooms.commands.emit", side_effect=fake_emit):
        result = dispatch(user, text, world)

    return result, captured, user, world


def test_dispatch_returns_false_for_non_command():
    result, captured, _, _ = _dispatch_and_capture("hello world")
    assert result is False
    assert not captured


def test_dispatch_returns_true_for_command():
    result, captured, _, _ = _dispatch_and_capture(":?")
    assert result is True


def test_dispatch_help_returns_activity_panel():
    result, captured, _, _ = _dispatch_and_capture(":?")
    assert captured.get("mode") == "superuser"
    assert "Help" in captured.get("title", "")


def test_dispatch_unknown_command_shows_error():
    result, captured, _, _ = _dispatch_and_capture(":nonexistent_cmd_xyz")
    assert result is True
    assert "Unknown command" in captured.get("content", "")


def test_dispatch_missing_power_shows_error():
    result, captured, _, _ = _dispatch_and_capture(":room owner show", powers=[])
    assert result is True
    assert "don't have" in captured.get("content", "").lower() or "realtor" in captured.get("content", "")


def test_dispatch_room_owner_show_with_realtor():
    result, captured, user, world = _dispatch_and_capture(
        ":room owner show", powers=["realtor"]
    )
    assert result is True
    assert "owned by" in captured.get("content", "").lower()


def test_dispatch_goto_requires_game_master():
    result, captured, _, _ = _dispatch_and_capture(":goto playroom", powers=[])
    assert result is True
    assert "game-master" in captured.get("content", "") or "don't have" in captured.get("content", "").lower()


def test_dispatch_goto_with_game_master_moves_user():
    user = _make_user(powers=["game-master"])
    world = _make_world()
    user.room = world.rooms["DEFAULT_ROOM"]
    playroom = world.rooms["playroom"]
    playroom.users = {}
    playroom.peeps = {}
    playroom.objs = {}
    default_room = world.rooms["DEFAULT_ROOM"]
    default_room.users = {"testuser": user}

    captured = {}

    def fake_emit(event, payload, **kwargs):
        if event == "activity_panel":
            captured.update(payload)

    with patch("tinyrooms.commands.emit", side_effect=fake_emit):
        with patch("tinyrooms.commands._save_world"):
            dispatch(user, ":goto playroom", world)

    assert "playroom" in captured.get("content", "")


def test_dispatch_room_rename_requires_builder():
    result, captured, _, _ = _dispatch_and_capture(":room rename New Name", powers=[])
    assert result is True
    assert "builder" in captured.get("content", "") or "don't have" in captured.get("content", "").lower()


def test_dispatch_kick_requires_moderator():
    result, captured, _, _ = _dispatch_and_capture(":kick alice", powers=[])
    assert result is True
    assert "moderator" in captured.get("content", "") or "don't have" in captured.get("content", "").lower()


def test_dispatch_list_users_any_user():
    result, captured, _, _ = _dispatch_and_capture(":list users", powers=[])
    assert result is True
    assert "User" in captured.get("content", "") or "user" in captured.get("content", "").lower()


def test_help_shows_power_specific_commands():
    result, captured, _, _ = _dispatch_and_capture(":?", powers=["realtor", "builder"])
    assert result is True
    content = captured.get("content", "")
    assert "Realtor" in content or "realtor" in content
    assert "Builder" in content or "builder" in content


def test_help_shows_no_extra_sections_for_no_powers():
    result, captured, _, _ = _dispatch_and_capture(":?", powers=[])
    assert result is True
    content = captured.get("content", "")
    assert "Realtor" not in content
    assert "Builder" not in content
    assert "Moderator" not in content
    assert "Game-master" not in content


def test_help_shows_admin_power_commands_for_admin_user():
    result, captured, _, _ = _dispatch_and_capture(":?", powers=["admin"])
    assert result is True
    content = captured.get("content", "")
    assert "Admin power commands" in content
    assert ":power list <username>" in content
    assert ":power set <username> <power> <grant|remove>" in content


def test_dispatch_admin_requires_admin_power():
    user = _make_user(powers=[])
    captured = {}

    def fake_emit(event, payload, **kwargs):
        if event == "error":
            captured.update(payload)

    with patch("tinyrooms.commands.emit", side_effect=fake_emit):
        handled = dispatch_admin(user, "/r")

    assert handled is True
    assert "admin" in captured.get("error", "").lower()


def test_dispatch_admin_rejects_console_only_commands():
    user = _make_user(powers=["admin"])
    captured = {}

    def fake_emit(event, payload, **kwargs):
        if event == "error":
            captured.update(payload)

    with patch("tinyrooms.commands.emit", side_effect=fake_emit):
        handled = dispatch_admin(user, "/r")

    assert handled is True
    assert "console-only" in captured.get("error", "").lower()


def test_dispatch_admin_routes_known_command():
    user = _make_user(powers=["admin"])
    with patch("tinyrooms.console.run_admin_cmd") as mock_run:
        handled = dispatch_admin(user, "/rc")
    assert handled is True
    mock_run.assert_called_once()


def test_power_list_requires_admin_power():
    result, captured, _, _ = _dispatch_and_capture(":power list alice", powers=[])
    assert result is True
    assert "don't have" in captured.get("content", "").lower()


def test_power_list_reports_not_found_user():
    user = _make_user(powers=["admin"])
    world = _make_world()
    user.room = world.rooms["DEFAULT_ROOM"]
    captured = {}

    def fake_emit(event, payload, **kwargs):
        if event == "activity_panel":
            captured.update(payload)

    with patch("tinyrooms.commands.emit", side_effect=fake_emit):
        with patch("tinyrooms.user_data.read_profile", return_value=None):
            dispatch(user, ":power list missing_user", world)

    assert captured.get("title") == "Error"
    assert "not found" in captured.get("content", "").lower()


def test_power_list_reports_current_powers():
    user = _make_user(powers=["admin"])
    world = _make_world()
    user.room = world.rooms["DEFAULT_ROOM"]
    captured = {}

    def fake_emit(event, payload, **kwargs):
        if event == "activity_panel":
            captured.update(payload)

    with patch("tinyrooms.commands.emit", side_effect=fake_emit):
        with patch(
            "tinyrooms.user_data.read_profile",
            return_value={"powers": ["builder", "moderator"]},
        ):
            with patch("tinyrooms.user.find_online", return_value=None):
                dispatch(user, ":power list alice", world)

    assert captured.get("title") == "Power List"
    assert "builder" in captured.get("content", "")
    assert "moderator" in captured.get("content", "")


def test_power_set_grant_updates_profile_and_online_user():
    user = _make_user(powers=["admin"])
    world = _make_world()
    user.room = world.rooms["DEFAULT_ROOM"]
    online_target = _make_user(username="alice", powers=["builder"])
    captured = {}

    def fake_emit(event, payload, **kwargs):
        if event == "activity_panel":
            captured.update(payload)

    with patch("tinyrooms.commands.emit", side_effect=fake_emit):
        with patch("tinyrooms.user_data.read_profile", return_value={"powers": ["builder"]}):
            with patch("tinyrooms.user_data.write_profile") as mock_write:
                with patch("tinyrooms.user.find_online", return_value=online_target):
                    dispatch(user, ":power set alice moderator grant", world)

    assert captured.get("title") == "Power Set"
    assert "granted" in captured.get("content", "")
    mock_write.assert_called_once()
    _, kwargs = mock_write.call_args
    assert sorted(kwargs["powers"]) == ["builder", "moderator"]
    assert online_target.powers == {"builder", "moderator"}


def test_power_set_remove_updates_profile():
    user = _make_user(powers=["admin"])
    world = _make_world()
    user.room = world.rooms["DEFAULT_ROOM"]
    captured = {}

    def fake_emit(event, payload, **kwargs):
        if event == "activity_panel":
            captured.update(payload)

    with patch("tinyrooms.commands.emit", side_effect=fake_emit):
        with patch("tinyrooms.user_data.read_profile", return_value={"powers": ["builder", "moderator"]}):
            with patch("tinyrooms.user_data.write_profile") as mock_write:
                with patch("tinyrooms.user.find_online", return_value=None):
                    dispatch(user, ":power set alice moderator remove", world)

    assert captured.get("title") == "Power Set"
    assert "removed" in captured.get("content", "")
    _, kwargs = mock_write.call_args
    assert kwargs["powers"] == ["builder"]


# ---------------------------------------------------------------------------
# Test thing list command
# ---------------------------------------------------------------------------

def test_thing_list_shows_all_things():
    user = _make_user(powers=["game-master"])
    world = _make_world(thing_ids=["test_apple", "test_sword"])
    user.room = world.rooms["DEFAULT_ROOM"]
    captured = {}

    def fake_emit(event, payload, **kwargs):
        if event == "activity_panel":
            captured.update(payload)

    with patch("tinyrooms.commands.emit", side_effect=fake_emit):
        dispatch(user, ":thing list", world)

    content = captured.get("content", "")
    assert "test_apple" in content
    assert "test_sword" in content


def test_thing_list_filter():
    user = _make_user(powers=["game-master"])
    world = _make_world(thing_ids=["test_apple", "test_sword"])
    user.room = world.rooms["DEFAULT_ROOM"]
    captured = {}

    def fake_emit(event, payload, **kwargs):
        if event == "activity_panel":
            captured.update(payload)

    with patch("tinyrooms.commands.emit", side_effect=fake_emit):
        dispatch(user, ":thing list apple", world)

    content = captured.get("content", "")
    assert "test_apple" in content
    assert "test_sword" not in content


# ---------------------------------------------------------------------------
# Test room commands
# ---------------------------------------------------------------------------

def test_room_owner_set_updates_owner():
    user = _make_user(powers=["realtor"])
    world = _make_world()
    room = world.rooms["DEFAULT_ROOM"]
    room.users = {"testuser": user}
    user.room = room
    captured = {}

    def fake_emit(event, payload, **kwargs):
        if event == "activity_panel":
            captured.update(payload)

    with patch("tinyrooms.commands.emit", side_effect=fake_emit):
        dispatch(user, ":room owner set alice", world)

    assert room.owner_id == "alice"
    assert "alice" in captured.get("content", "")


def test_room_owner_clear():
    user = _make_user(powers=["realtor"])
    world = _make_world()
    room = world.rooms["DEFAULT_ROOM"]
    room.owner_id = "alice"
    room.users = {"testuser": user}
    user.room = room
    captured = {}

    def fake_emit(event, payload, **kwargs):
        if event == "activity_panel":
            captured.update(payload)

    with patch("tinyrooms.commands.emit", side_effect=fake_emit):
        dispatch(user, ":room owner clear", world)

    assert room.owner_id == ""
    assert "cleared" in captured.get("content", "").lower()


def test_room_rename_updates_label():
    user = _make_user(powers=["builder"])
    world = _make_world()
    room = world.rooms["DEFAULT_ROOM"]
    room.users = {"testuser": user}
    user.room = room
    captured = {}

    def fake_emit(event, payload, **kwargs):
        if event == "activity_panel":
            captured.update(payload)

    with patch("tinyrooms.commands.emit", side_effect=fake_emit):
        dispatch(user, ":room rename The New Room Name", world)

    assert room.label_override == "The New Room Name"
    assert "New Room Name" in captured.get("content", "")
