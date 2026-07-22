import pytest
import json
from pathlib import Path

import duckdb


pytestmark = pytest.mark.integration


def _go_to_playroom(client):
    client.emit("message", {"text": ":go @way:to_gateway"})
    client.wait_for(
        "update_view",
        predicate=lambda payload: payload.get("view") == "header" and payload.get("room_id") == "playroom",
        timeout=8.0,
    )


def test_room_interaction_permissions_and_broadcasts(
    owner_account,
    http_client,
    server_runtime,
    socket_client_factory,
    login_socket_user,
    unique_username,
):
    owner_username = owner_account["username"]
    owner_password = owner_account["password"]
    owner_client = socket_client_factory()
    login_socket_user(owner_client, owner_username, owner_password)
    _go_to_playroom(owner_client)

    user_password = "guest_password"
    user_name = ""
    for _ in range(6):
        candidate = unique_username("it_guest")
        response = http_client.post("/register", json={"username": candidate, "password": user_password})
        if response.status_code == 201:
            user_name = candidate
            break
    assert user_name
    guest_client = socket_client_factory()
    login_socket_user(guest_client, user_name, user_password)
    _go_to_playroom(guest_client)

    object_update = owner_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-object" and p.get("entity", {}).get("entity_type") == "object",
        timeout=8.0,
    )
    object_id = object_update["entity"]["entity_id"]

    guest_client.emit(
        "room_move_entity",
        {"entity_type": "object", "entity_id": object_id, "x": 81, "y": 101, "orientation": "left"},
    )
    owner_seen = owner_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-object"
        and p.get("entity", {}).get("entity_id") == object_id
        and p.get("entity", {}).get("position", {}).get("x") == 81,
        timeout=8.0,
    )
    guest_seen = guest_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-object"
        and p.get("entity", {}).get("entity_id") == object_id
        and p.get("entity", {}).get("position", {}).get("y") == 101,
        timeout=8.0,
    )
    assert owner_seen["entity"]["position"]["orientation"] == "left"
    assert guest_seen["entity"]["position"]["orientation"] == "left"

    guest_client.emit(
        "room_move_entity",
        {"entity_type": "peep", "entity_id": user_name, "x": 44, "y": 55, "orientation": "right"},
    )
    moved_self = guest_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-object"
        and p.get("entity", {}).get("entity_type") == "peep"
        and p.get("entity", {}).get("owner_username") == user_name
        and p.get("entity", {}).get("position", {}).get("x") == 44,
        timeout=8.0,
    )
    assert moved_self["entity"]["position"]["y"] == 55

    guest_client.emit(
        "room_move_entity",
        {"entity_type": "peep", "entity_id": owner_username, "x": 11, "y": 11, "orientation": "front"},
    )
    forbidden = guest_client.wait_for("error", predicate=lambda p: "cannot move" in p.get("error", ""), timeout=8.0)
    assert "cannot move" in forbidden["error"]

    owner_client.emit(
        "room_move_entity",
        {"entity_type": "peep", "entity_id": user_name, "x": 90, "y": 91, "orientation": "back"},
    )
    owner_move = owner_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-object"
        and p.get("entity", {}).get("entity_type") == "peep"
        and p.get("entity", {}).get("owner_username") == user_name
        and p.get("entity", {}).get("position", {}).get("x") == 90,
        timeout=8.0,
    )
    guest_move = guest_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-object"
        and p.get("entity", {}).get("entity_type") == "peep"
        and p.get("entity", {}).get("owner_username") == user_name
        and p.get("entity", {}).get("position", {}).get("y") == 91,
        timeout=8.0,
    )
    assert owner_move["entity"]["position"]["orientation"] == "back"
    assert guest_move["entity"]["position"]["orientation"] == "back"

    prop_instance_id = "playroom-floor_rug-0"

    owner_client.emit("room_edit_prop", {"prop_instance_id": prop_instance_id, "x": 123, "y": 321, "orientation": "left"})
    owner_stage = owner_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-stage"
        and any(prop.get("prop_instance_id") == prop_instance_id for prop in p.get("props", [])),
        timeout=8.0,
    )
    guest_stage = guest_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-stage"
        and any(prop.get("prop_instance_id") == prop_instance_id for prop in p.get("props", [])),
        timeout=8.0,
    )
    owner_prop = next(prop for prop in owner_stage["props"] if prop["prop_instance_id"] == prop_instance_id)
    guest_prop = next(prop for prop in guest_stage["props"] if prop["prop_instance_id"] == prop_instance_id)
    assert owner_prop["position"]["x"] == 123
    assert guest_prop["position"]["y"] == 321

    guest_client.emit("room_edit_prop", {"prop_instance_id": prop_instance_id, "x": 20, "y": 20})
    permission_err = guest_client.wait_for(
        "error",
        predicate=lambda p: "only room owner" in p.get("error", ""),
        timeout=8.0,
    )
    assert "only room owner" in permission_err["error"]

    owner_client.emit(
        "room_save_props",
        {
            "props": [
                {
                    "prop_instance_id": "playroom-standing_lamp-1",
                    "prop_id": "standing_lamp",
                    "x": 201,
                    "y": 222,
                    "orientation": "right",
                },
                {
                    "prop_id": "wall_clock",
                    "x": 55,
                    "y": 66,
                    "orientation": "back",
                },
            ]
        },
    )
    owner_saved_stage = owner_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-stage"
        and any(prop.get("prop_id") == "wall_clock" for prop in p.get("props", [])),
        timeout=8.0,
    )
    guest_saved_stage = guest_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-stage"
        and any(prop.get("prop_id") == "wall_clock" for prop in p.get("props", [])),
        timeout=8.0,
    )
    owner_prop_ids = {prop["prop_id"] for prop in owner_saved_stage["props"]}
    guest_prop_ids = {prop["prop_id"] for prop in guest_saved_stage["props"]}
    assert "wall_clock" in owner_prop_ids
    assert "wall_clock" in guest_prop_ids
    assert "floor_rug" not in owner_prop_ids
    assert "floor_rug" not in guest_prop_ids

    worldstate_path = Path(server_runtime.workspace) / "data" / "worldstate_home.duckdb"
    with duckdb.connect(str(worldstate_path), read_only=True) as wsdb:
        row = wsdb.execute("SELECT props FROM rooms WHERE id = ?", ("playroom",)).fetchone()
    assert row is not None
    persisted_props = json.loads(row[0])
    persisted_prop_ids = {entry["prop_id"] for entry in persisted_props}
    assert "wall_clock" in persisted_prop_ids
    assert "floor_rug" not in persisted_prop_ids
