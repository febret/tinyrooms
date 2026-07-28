"""Unit tests for the superuser command dispatcher and permission framework."""
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


def test_pattern_matching():
    assert _matches(["?"], "?")
    assert not _matches(["goto"], "?")
    assert _matches(["room", "owner", "show"], "room owner show")
    assert not _matches(["room", "owner"], "room owner show")
    assert _matches(["goto", "playroom"], "goto <room_id>")
    assert not _matches(["goto"], "goto <room_id>")
    assert _matches(["room", "rename", "The", "Cool", "Room"], "room rename ...")
    assert _matches(["room", "rename", "x"], "room rename ...")


def test_extract_args():
    assert _extract_args(["goto", "playroom"], "goto <room_id>") == ["playroom"]
    assert _extract_args(["move", "alice", "playroom"], "move <username> <room_id>") == ["alice", "playroom"]
    assert _extract_args(["room", "rename", "The", "Cool", "Room"], "room rename ...") == ["The", "Cool", "Room"]


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


def test_dispatch_help_returns_activity_panel():
    result, captured, _, _ = _dispatch_and_capture(":?")
    assert result is True
    assert captured.get("mode") == "superuser"
    assert "Help" in captured.get("title", "")


def test_dispatch_unknown_command_shows_error():
    result, captured, _, _ = _dispatch_and_capture(":nonexistent_cmd_xyz")
    assert result is True
    assert "Unknown command" in captured.get("content", "")


def test_dispatch_requires_power():
    """Commands with missing powers all produce a permission-error response."""
    for cmd, expected_power in [
        (":room owner show", "realtor"),
        (":goto playroom", "game-master"),
        (":room rename New Name", "builder"),
        (":kick alice", "moderator"),
    ]:
        result, captured, _, _ = _dispatch_and_capture(cmd, powers=[])
        assert result is True, f"Expected dispatch to return True for {cmd!r}"
        content = captured.get("content", "").lower()
        assert "don't have" in content or expected_power in content, (
            f"Expected permission error for {cmd!r}, got: {content!r}"
        )


def test_dispatch_room_owner_show_with_realtor():
    result, captured, user, world = _dispatch_and_capture(
        ":room owner show", powers=["realtor"]
    )
    assert result is True
    assert "owned by" in captured.get("content", "").lower()


def test_dispatch_goto_with_game_master_moves_user():
    user = _make_user(powers=["game-master"])
    world = _make_world()
    user.room = world.rooms["DEFAULT_ROOM"]
    world.rooms["playroom"].users = world.rooms["playroom"].peeps = world.rooms["playroom"].objs = {}
    world.rooms["DEFAULT_ROOM"].users = {"testuser": user}
    cap = {}
    with patch("tinyrooms.commands.emit", side_effect=lambda e, p, **kw: cap.update(p) if e == "activity_panel" else None):
        with patch("tinyrooms.commands._save_world"):
            dispatch(user, ":goto playroom", world)
    assert "playroom" in cap.get("content", "")


def test_dispatch_list_users_any_user():
    result, captured, _, _ = _dispatch_and_capture(":list users", powers=[])
    assert result is True
    assert "User" in captured.get("content", "") or "user" in captured.get("content", "").lower()


def test_dispatch_use_and_look():
    """':use' emits a message; ':look' emits an activity_panel."""
    user = _make_user(powers=[])
    world = _make_world()
    user.room = world.rooms["DEFAULT_ROOM"]
    user.room.label = MagicMock(return_value="Default Room")
    msg_cap, panel_cap = {}, {}

    def fake_emit(event, payload, **kwargs):
        if event == "message":
            msg_cap.update(payload)
        elif event == "activity_panel":
            panel_cap.update(payload)

    with patch("tinyrooms.commands.emit", side_effect=fake_emit):
        dispatch(user, ":use @obj:test-item", world)
        dispatch(user, ":look", world)

    assert msg_cap.get("text") == "You use @obj:test-item."
    assert panel_cap.get("mode") == "look"
    assert panel_cap.get("title") and panel_cap.get("content")


def test_help_content():
    """Help sections are shown only for the user's actual powers."""
    result, captured, _, _ = _dispatch_and_capture(":?", powers=["realtor", "builder"])
    content = captured.get("content", "")
    assert result is True
    assert "Realtor" in content or "realtor" in content
    assert "Builder" in content or "builder" in content

    _, captured2, _, _ = _dispatch_and_capture(":?", powers=[])
    content2 = captured2.get("content", "")
    assert "Realtor" not in content2
    assert "Builder" not in content2
    assert "Moderator" not in content2
    assert "Game-master" not in content2


def test_help_shows_admin_power_commands_for_admin_user():
    result, captured, _, _ = _dispatch_and_capture(":?", powers=["admin"])
    assert result is True
    content = captured.get("content", "")
    assert "Admin power commands" in content
    assert ":power list <username>" in content
    assert ":power set <username> <power> <grant|remove>" in content


def test_dispatch_admin():
    """dispatch_admin rejects non-admin users and blocks console-only commands."""
    # No admin power → error
    user_no_admin = _make_user(powers=[])
    cap1 = {}
    with patch("tinyrooms.commands.emit", side_effect=lambda e, p, **kw: cap1.update(p) if e == "error" else None):
        assert dispatch_admin(user_no_admin, "/r") is True
    assert "admin" in cap1.get("error", "").lower()

    # Admin power but console-only command → error
    user_admin = _make_user(powers=["admin"])
    cap2 = {}
    with patch("tinyrooms.commands.emit", side_effect=lambda e, p, **kw: cap2.update(p) if e == "error" else None):
        assert dispatch_admin(user_admin, "/r") is True
    assert "console-only" in cap2.get("error", "").lower()


def test_dispatch_admin_routes_known_command():
    user = _make_user(powers=["admin"])
    with patch("tinyrooms.console.run_admin_cmd") as mock_run:
        handled = dispatch_admin(user, "/rc")
    assert handled is True
    mock_run.assert_called_once()


def test_power_list():
    """Requires admin; reports not-found for missing profiles; shows current powers."""
    result, captured, _, _ = _dispatch_and_capture(":power list alice", powers=[])
    assert result is True and "don't have" in captured.get("content", "").lower()

    user = _make_user(powers=["admin"])
    world = _make_world()
    user.room = world.rooms["DEFAULT_ROOM"]
    cap = {}
    emit_fn = lambda e, p, **kw: cap.update(p) if e == "activity_panel" else None  # noqa: E731

    with patch("tinyrooms.commands.emit", side_effect=emit_fn):
        with patch("tinyrooms.user_data.read_profile", return_value=None):
            dispatch(user, ":power list missing_user", world)
    assert cap.get("title") == "Error" and "not found" in cap.get("content", "").lower()

    cap.clear()
    with patch("tinyrooms.commands.emit", side_effect=emit_fn):
        with patch("tinyrooms.user_data.read_profile", return_value={"powers": ["builder", "moderator"]}):
            with patch("tinyrooms.user.find_online", return_value=None):
                dispatch(user, ":power list alice", world)
    assert cap.get("title") == "Power List"
    assert "builder" in cap.get("content", "") and "moderator" in cap.get("content", "")


def test_power_set_operations():
    """Power set: grant adds a power (updating online user); remove subtracts a power."""
    user = _make_user(powers=["admin"])
    world = _make_world()
    user.room = world.rooms["DEFAULT_ROOM"]
    online_target = _make_user(username="alice", powers=["builder"])

    def _run(cmd, initial_powers, find_online_result):
        cap = {}
        emit_fn = lambda e, p, **kw: cap.update(p) if e == "activity_panel" else None  # noqa: E731
        with patch("tinyrooms.commands.emit", side_effect=emit_fn):
            with patch("tinyrooms.user_data.read_profile", return_value={"powers": initial_powers}):
                with patch("tinyrooms.user_data.write_profile") as mock_write:
                    with patch("tinyrooms.user.find_online", return_value=find_online_result):
                        dispatch(user, cmd, world)
        return cap, mock_write

    cap, mw = _run(":power set alice moderator grant", ["builder"], online_target)
    assert cap.get("title") == "Power Set" and "granted" in cap.get("content", "")
    mw.assert_called_once()
    _, kw = mw.call_args
    assert sorted(kw["powers"]) == ["builder", "moderator"]
    assert online_target.powers == {"builder", "moderator"}

    cap2, mw2 = _run(":power set alice moderator remove", ["builder", "moderator"], None)
    assert cap2.get("title") == "Power Set" and "removed" in cap2.get("content", "")
    _, kw2 = mw2.call_args
    assert kw2["powers"] == ["builder"]


# ---------------------------------------------------------------------------
# Test thing list command
# ---------------------------------------------------------------------------

def test_thing_list():
    """thing list shows all things and can filter by name fragment."""
    user = _make_user(powers=["game-master"])
    world = _make_world(thing_ids=["test_apple", "test_sword"])
    user.room = world.rooms["DEFAULT_ROOM"]

    def _capture(cmd):
        cap = {}
        with patch("tinyrooms.commands.emit", side_effect=lambda e, p, **kw: cap.update(p) if e == "activity_panel" else None):
            dispatch(user, cmd, world)
        return cap.get("content", "")

    all_content = _capture(":thing list")
    assert "test_apple" in all_content
    assert "test_sword" in all_content

    filtered_content = _capture(":thing list apple")
    assert "test_apple" in filtered_content
    assert "test_sword" not in filtered_content


# ---------------------------------------------------------------------------
# Test room commands
# ---------------------------------------------------------------------------

def test_room_owner_operations():
    """Room owner can be set and cleared."""
    user = _make_user(powers=["realtor"])
    world = _make_world()
    room = world.rooms["DEFAULT_ROOM"]
    room.users = {"testuser": user}
    user.room = room

    def _capture(cmd):
        cap = {}
        with patch("tinyrooms.commands.emit", side_effect=lambda e, p, **kw: cap.update(p) if e == "activity_panel" else None):
            dispatch(user, cmd, world)
        return cap.get("content", "")

    set_content = _capture(":room owner set alice")
    assert room.owner_id == "alice"
    assert "alice" in set_content

    room.owner_id = "alice"
    clear_content = _capture(":room owner clear")
    assert room.owner_id == ""
    assert "cleared" in clear_content.lower()


def test_room_rename_updates_label():
    user = _make_user(powers=["builder"])
    world = _make_world()
    room = world.rooms["DEFAULT_ROOM"]
    room.users = {"testuser": user}
    user.room = room
    cap = {}
    with patch("tinyrooms.commands.emit", side_effect=lambda e, p, **kw: cap.update(p) if e == "activity_panel" else None):
        dispatch(user, ":room rename The New Room Name", world)
    assert room.label_override == "The New Room Name"
    assert "New Room Name" in cap.get("content", "")
