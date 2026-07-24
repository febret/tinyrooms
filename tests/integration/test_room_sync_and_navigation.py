import pytest


pytestmark = pytest.mark.integration


def _go_to_playroom(client):
    client.emit("message", {"text": ":go @way:to_gateway"})
    header = client.wait_for(
        "update_view",
        predicate=lambda payload: payload.get("view") == "header" and payload.get("room_id") == "playroom",
        timeout=8.0,
    )
    assert header["room_id"] == "playroom"


def test_initial_room_sync_contract(auth_socket_user, http_client):
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

    prop_library = http_client.get("/api/props/library", headers=user["headers"])
    assert prop_library.status_code == 200, prop_library.text
    payload = prop_library.json()
    assert payload["ok"] is True
    assert isinstance(payload["props"], list)
    assert any(item.get("prop_id") == "floor_rug" for item in payload["props"])


def test_navigation_and_chat(auth_socket_user):
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


def test_unclaimed_room_editable_and_claim(auth_socket_user):
    """Non-owner users can edit and claim rooms that have no owner."""
    user = auth_socket_user(prefix="it_claim")
    client = user["client"]

    # Wait for initial room header — DEFAULT_ROOM has no owner
    header = client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "header",
        timeout=8.0,
    )
    # Unclaimed room: anyone can edit and claim
    assert header.get("can_edit_props") is True
    assert header.get("can_claim_room") is True

    # Claiming an already-owned room should fail; here we claim the ownerless one
    client.emit("message", {"text": ":claim room"})
    claimed_header = client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "header" and bool(p.get("owner_id")),
        timeout=8.0,
    )
    assert claimed_header["owner_id"] == user["username"]
    assert claimed_header.get("can_edit_props") is True
    assert claimed_header.get("can_claim_room") is False


def test_peep_move_does_not_toggle_walk_decorator(auth_socket_user):
    user = auth_socket_user(prefix="it_walk")
    client = user["client"]

    peep_upsert = client.wait_for(
        "update_view",
        predicate=lambda p: (
            p.get("view") == "room-object"
            and p.get("entity", {}).get("entity_type") == "peep"
            and p.get("entity", {}).get("entity_id") == user["username"]
        ),
        timeout=8.0,
    )
    current_x = int(peep_upsert["entity"]["position"]["x"])
    current_y = int(peep_upsert["entity"]["position"]["y"])
    initial_has_walk = "main:walk" in [
        d.get("id") for d in peep_upsert["entity"].get("decorators", []) if isinstance(d, dict)
    ]

    client.emit(
        "room_move_entity",
        {
            "entity_type": "peep",
            "entity_id": user["username"],
            "x": current_x + 20,
            "y": current_y + 5,
            "orientation": "front",
        },
    )

    moved_upsert = client.wait_for(
        "update_view",
        predicate=lambda p: (
            p.get("view") == "room-object"
            and p.get("entity", {}).get("entity_type") == "peep"
            and p.get("entity", {}).get("entity_id") == user["username"]
            and int(p.get("entity", {}).get("position", {}).get("x", current_x)) == current_x + 20
            and int(p.get("entity", {}).get("position", {}).get("y", current_y)) == current_y + 5
        ),
        timeout=8.0,
    )
    moved_has_walk = "main:walk" in [
        d.get("id") for d in moved_upsert["entity"].get("decorators", []) if isinstance(d, dict)
    ]
    assert moved_has_walk is initial_has_walk
