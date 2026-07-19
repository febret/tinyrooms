import pytest


pytestmark = pytest.mark.integration


def _go_to_playroom(client):
    client.emit("message", {"text": ".go @way:to_gateway"})
    client.wait_for(
        "update_view",
        predicate=lambda payload: payload.get("view") == "header" and payload.get("room_id") == "playroom",
        timeout=8.0,
    )


def test_relogin_restores_last_room_and_position(
    register_user,
    socket_client_factory,
    login_socket_user,
    unique_username,
):
    username = unique_username("it_persist")
    password = "persist_password"
    register_user(username, password)

    first_client = socket_client_factory()
    login_socket_user(first_client, username, password)
    _go_to_playroom(first_client)

    first_client.emit(
        "room_move_entity",
        {"entity_type": "peep", "entity_id": username, "x": 111, "y": 222, "orientation": "right"},
    )
    first_client.wait_for(
        "update_view",
        predicate=lambda payload: payload.get("view") == "room-object"
        and payload.get("entity", {}).get("entity_type") == "peep"
        and payload.get("entity", {}).get("owner_username") == username
        and payload.get("entity", {}).get("position", {}).get("x") == 111,
        timeout=8.0,
    )
    first_client.disconnect()

    second_client = socket_client_factory()
    login_socket_user(second_client, username, password)
    restored_header = second_client.wait_for(
        "update_view",
        predicate=lambda payload: payload.get("view") == "header",
        timeout=8.0,
    )
    restored_self = second_client.wait_for(
        "update_view",
        predicate=lambda payload: payload.get("view") == "room-object"
        and payload.get("entity", {}).get("entity_type") == "peep"
        and payload.get("entity", {}).get("owner_username") == username
        and payload.get("entity", {}).get("is_self") is True,
        timeout=8.0,
    )

    assert restored_header["room_id"] == "playroom"
    assert restored_self["entity"]["position"]["x"] == 111
    assert restored_self["entity"]["position"]["y"] == 222

