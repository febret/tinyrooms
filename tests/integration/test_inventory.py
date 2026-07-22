import pytest


pytestmark = [pytest.mark.integration]


def test_inventory_pick_and_drop_lifecycle(auth_socket_user, http_client):
    user = auth_socket_user(prefix="it_inv_pick")
    headers = user["headers"]
    client = user["client"]

    # Create a thing to pick up
    profile = http_client.get("/api/object-editor/profile", headers=headers)
    payload = profile.json()
    sprite = payload["available_sprites"][0]

    created = http_client.post(
        "/api/object-editor/create",
        headers=headers,
        json={
            "description": "a shiny test coin",
            "current_sprite": sprite["sprite_ref"],
        },
    )
    assert created.status_code == 201, created.text
    object_id = created.json()["object_id"]
    client.drain("update_view")
    client.drain("inventory_update")

    # Pick it up
    client.emit("message", {"text": f":pick @obj:{object_id}"})

    # Should receive a room-object remove broadcast
    remove_event = client.wait_for(
        "update_view",
        predicate=lambda p: (
            p.get("view") == "room-object"
            and p.get("change") == "remove"
            and p.get("entity", {}).get("entity_id") == object_id
        ),
        timeout=6.0,
    )
    assert remove_event is not None

    # Inventory should now contain the picked item
    inv_event = client.wait_for(
        "inventory_update",
        predicate=lambda p: any(item["obj_id"] == object_id for item in (p.get("items") or [])),
        timeout=6.0,
    )
    assert inv_event is not None
    item = next(i for i in inv_event["items"] if i["obj_id"] == object_id)
    assert item["label"]

    # Drop it back
    client.emit("message", {"text": f":drop @obj:{object_id}"})

    # Should receive a room-object upsert
    upsert_event = client.wait_for(
        "update_view",
        predicate=lambda p: (
            p.get("view") == "room-object"
            and p.get("change") == "upsert"
            and p.get("entity", {}).get("entity_id") == object_id
        ),
        timeout=6.0,
    )
    assert upsert_event is not None

    # Inventory should now be empty
    empty_inv = client.wait_for(
        "inventory_update",
        predicate=lambda p: not any(item["obj_id"] == object_id for item in (p.get("items") or [])),
        timeout=6.0,
    )
    assert empty_inv is not None


def test_inventory_is_sent_on_login(auth_socket_user, http_client, socket_client_factory, login_socket_user, unique_username, register_user):
    """Objects in inventory are broadcast as inventory_update immediately after login."""
    # Create a user and give them an item via the object editor
    user = auth_socket_user(prefix="it_inv_login")
    headers = user["headers"]
    username = user["username"]
    password = user["password"]
    client = user["client"]

    profile = http_client.get("/api/object-editor/profile", headers=headers)
    sprite = profile.json()["available_sprites"][0]

    created = http_client.post(
        "/api/object-editor/create",
        headers=headers,
        json={"description": "a login test coin", "current_sprite": sprite["sprite_ref"]},
    )
    assert created.status_code == 201
    object_id = created.json()["object_id"]
    client.drain("update_view")
    client.drain("inventory_update")

    client.emit("message", {"text": f":pick @obj:{object_id}"})
    client.wait_for(
        "inventory_update",
        predicate=lambda p: any(i["obj_id"] == object_id for i in (p.get("items") or [])),
        timeout=6.0,
    )
    client.disconnect()

    # Log back in on a fresh socket; inventory_update should arrive quickly
    new_client = socket_client_factory()
    login_socket_user(new_client, username, password)
    inv = new_client.wait_for(
        "inventory_update",
        predicate=lambda p: any(i["obj_id"] == object_id for i in (p.get("items") or [])),
        timeout=8.0,
    )
    assert inv is not None
    new_client.disconnect()


def test_inventory_update_includes_custom_inventory_actions(auth_socket_user):
    user = auth_socket_user(prefix="it_inv_actions")
    client = user["client"]

    client.emit("message", {"text": ":go @way:to_gateway"})
    client.wait_for("update_view", predicate=lambda p: p.get("view") == "header" and p.get("room_id") == "playroom", timeout=8.0)

    room_object = client.wait_for(
        "update_view",
        predicate=lambda p: (
            p.get("view") == "room-object"
            and p.get("change") == "upsert"
            and p.get("entity", {}).get("entity_type") == "object"
        ),
        timeout=8.0,
    )
    object_id = room_object["entity"]["entity_id"]

    client.emit("message", {"text": f":pick @obj:{object_id}"})
    inv_event = client.wait_for(
        "inventory_update",
        predicate=lambda p: any(i["obj_id"] == object_id for i in (p.get("items") or [])),
        timeout=8.0,
    )
    item = next(i for i in inv_event["items"] if i["obj_id"] == object_id)
    actions = item.get("inventory_actions") or []
    assert actions
    assert actions[0]["commands"] == ":use $0, :use $0"

    expanded_commands = [
        command.strip().replace("$0", f"@obj:{object_id}")
        for command in actions[0]["commands"].split(",")
        if command.strip()
    ]
    assert expanded_commands == [f":use @obj:{object_id}", f":use @obj:{object_id}"]

    for command in expanded_commands:
        client.emit("message", {"text": command})

    first = client.wait_for("message", predicate=lambda p: p.get("text") == f"You use @obj:{object_id}.", timeout=8.0)
    second = client.wait_for("message", predicate=lambda p: p.get("text") == f"You use @obj:{object_id}.", timeout=8.0)
    assert first is not None
    assert second is not None

    client.emit("message", {"text": f":drop @obj:{object_id}"})
    client.wait_for(
        "update_view",
        predicate=lambda p: (
            p.get("view") == "room-object"
            and p.get("change") == "upsert"
            and p.get("entity", {}).get("entity_id") == object_id
        ),
        timeout=8.0,
    )
