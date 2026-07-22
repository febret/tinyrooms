import pytest


pytestmark = pytest.mark.integration


def _go_to_playroom(client):
    client.emit("message", {"text": ":go @way:to_gateway"})
    client.wait_for(
        "update_view",
        predicate=lambda payload: payload.get("view") == "header" and payload.get("room_id") == "playroom",
        timeout=8.0,
    )


def _decorator_ids(payload):
    return [item.get("id") for item in payload.get("decorators", []) if isinstance(item, dict)]


def test_apply_and_remove_decorators(auth_socket_user):
    user = auth_socket_user(prefix="it_decorators")
    client = user["client"]
    _go_to_playroom(client)

    initial_object = client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-object" and p.get("entity", {}).get("entity_type") == "object",
        timeout=8.0,
    )
    object_id = initial_object["entity"]["entity_id"]

    client.emit("apply_decorator", {"entity_type": "object", "entity_id": object_id, "deco_id": "on_fire"})
    updated_object = client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-object"
        and p.get("entity", {}).get("entity_id") == object_id
        and "main:on_fire" in _decorator_ids(p.get("entity", {})),
        timeout=8.0,
    )
    assert _decorator_ids(updated_object["entity"]) == ["main:on_fire"]

    client.emit("apply_decorator", {"entity_type": "object", "entity_id": object_id, "deco_id": "on_fire"})
    updated_object_duplicate = client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-object"
        and p.get("entity", {}).get("entity_id") == object_id
        and "main:on_fire" in _decorator_ids(p.get("entity", {})),
        timeout=8.0,
    )
    assert _decorator_ids(updated_object_duplicate["entity"]).count("main:on_fire") == 1

    client.emit("remove_decorator", {"entity_type": "object", "entity_id": object_id, "deco_id": "main:on_fire"})
    updated_object_removed = client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-object"
        and p.get("entity", {}).get("entity_id") == object_id
        and "main:on_fire" not in _decorator_ids(p.get("entity", {})),
        timeout=8.0,
    )
    assert "main:on_fire" not in _decorator_ids(updated_object_removed["entity"])

    prop_instance_id = "playroom-floor_rug-0"
    client.emit("apply_decorator", {"entity_type": "prop", "entity_id": prop_instance_id, "deco_id": "sparkle"})
    stage_with_prop_decorator = client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-stage"
        and any(
            prop.get("prop_instance_id") == prop_instance_id and "main:sparkle" in _decorator_ids(prop)
            for prop in p.get("props", [])
        ),
        timeout=8.0,
    )
    target_prop = next(prop for prop in stage_with_prop_decorator["props"] if prop["prop_instance_id"] == prop_instance_id)
    assert "main:sparkle" in _decorator_ids(target_prop)
