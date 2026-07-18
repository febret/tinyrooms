import pytest


pytestmark = pytest.mark.integration


def _go_to_playroom(client):
    client.emit("message", {"text": ".go @way:to_gateway"})
    header = client.wait_for(
        "update_view",
        predicate=lambda payload: payload.get("view") == "header" and payload.get("room_id") == "playroom",
        timeout=8.0,
    )
    assert header["room_id"] == "playroom"


def test_initial_room_sync_contract(auth_socket_user):
    user = auth_socket_user(prefix="it_sync")
    client = user["client"]

    header = client.wait_for("update_view", predicate=lambda p: p.get("view") == "header")
    stage = client.wait_for("update_view", predicate=lambda p: p.get("view") == "room-stage")
    obj = client.wait_for("update_view", predicate=lambda p: p.get("view") == "room-object")
    exits = client.wait_for("update_view", predicate=lambda p: p.get("view") == "room-exits")

    assert "room_id" in header
    assert "can_edit_props" in header

    assert stage["view"] == "room-stage"
    assert "stage" in stage and "props" in stage and "can_edit_props" in stage

    assert obj["entity"]["entity_type"] in {"object", "peep"}
    assert "position" in obj["entity"]

    assert exits["view"] == "room-exits"
    assert isinstance(exits["exits"], list)


def test_navigation_chat_and_look_activity(auth_socket_user):
    first = auth_socket_user(prefix="it_nav_a")
    second = auth_socket_user(prefix="it_nav_b")
    a = first["client"]
    b = second["client"]

    _go_to_playroom(a)
    _go_to_playroom(b)

    a.emit("message", {"text": "integration hello"})
    sender_msg = a.wait_for("message", predicate=lambda p: "You say" in p.get("text", ""), timeout=8.0)
    other_msg = b.wait_for(
        "message",
        predicate=lambda p: "says" in p.get("text", "") and "integration hello" in p.get("text", ""),
        timeout=8.0,
    )
    assert "integration hello" in sender_msg["text"]
    assert "integration hello" in other_msg["text"]

    a.emit("message", {"text": ".basic.look"})
    panel = a.wait_for("activity_panel", predicate=lambda p: p.get("mode") == "look", timeout=8.0)
    assert panel["title"] == "Look"

    object_update = a.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-object" and p.get("entity", {}).get("entity_type") == "object",
        timeout=8.0,
    )
    object_id = object_update["entity"]["entity_id"]
    a.emit("message", {"text": f".basic.look @obj:{object_id}"})
    target_panel = a.wait_for("activity_panel", predicate=lambda p: p.get("mode") == "look", timeout=8.0)
    assert target_panel["title"].startswith("Looking at")
