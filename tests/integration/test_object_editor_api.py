import pytest


pytestmark = [pytest.mark.integration]


def test_object_editor_profile_lists_sprites_from_both_scopes(auth_socket_user, http_client):
    user = auth_socket_user(prefix="it_obj_profile")
    headers = user["headers"]

    profile = http_client.get("/api/object-editor/profile", headers=headers)
    assert profile.status_code == 200
    payload = profile.json()
    assert payload["ok"] is True
    assert "available_sprites" in payload

    available = payload["available_sprites"]
    assert available
    scopes = {item["scope"] for item in available}
    assert {"server", "world"} <= scopes
    assert all(item["sprite_ref"].startswith("$") for item in available)
    assert all(item["image_url"].startswith("/sprites/") for item in available)


def test_object_editor_create_with_sprite_broadcasts_and_persists(auth_socket_user, http_client, server_runtime):
    import duckdb
    from pathlib import Path

    user = auth_socket_user(prefix="it_obj_create")
    headers = user["headers"]
    client = user["client"]

    profile = http_client.get("/api/object-editor/profile", headers=headers)
    payload = profile.json()
    world_sprite = next(item for item in payload["available_sprites"] if item["scope"] == "world")
    client.drain("update_view")

    created = http_client.post(
        "/api/object-editor/create",
        headers=headers,
        json={
            "description": "a tiny glowing lantern",
            "current_sprite": world_sprite["sprite_ref"],
        },
    )
    assert created.status_code == 201, created.text
    response_payload = created.json()
    object_id = response_payload["object_id"]
    assert object_id

    room_update = client.wait_for(
        "update_view",
        predicate=lambda p: (
            p.get("view") == "room-object"
            and p.get("entity", {}).get("entity_type") == "object"
            and p.get("entity", {}).get("entity_id") == object_id
        ),
        timeout=8.0,
    )
    entity = room_update["entity"]
    assert entity["description"] == "a tiny glowing lantern"
    assert entity["display"]["sprite"].startswith("/sprites/world/")

    world_db_path = Path(server_runtime.workspace) / "data" / "worldstate_home.duckdb"
    with duckdb.connect(str(world_db_path), read_only=True) as conn:
        row = conn.execute(
            "SELECT thing_id FROM objects WHERE id = ?",
            [object_id],
        ).fetchone()
    assert row is not None


def test_object_editor_create_requires_description(auth_socket_user, http_client):
    user = auth_socket_user(prefix="it_obj_nodesc")
    headers = user["headers"]

    profile = http_client.get("/api/object-editor/profile", headers=headers)
    sprite = profile.json()["available_sprites"][0]

    no_desc = http_client.post(
        "/api/object-editor/create",
        headers=headers,
        json={"current_sprite": sprite["sprite_ref"]},
    )
    assert no_desc.status_code == 400

    no_sprite_no_image = http_client.post(
        "/api/object-editor/create",
        headers=headers,
        json={"description": "a lonely thing"},
    )
    assert no_sprite_no_image.status_code == 400

