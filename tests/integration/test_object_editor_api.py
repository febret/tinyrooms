from pathlib import Path

import duckdb
import pytest
import yaml


pytestmark = [pytest.mark.integration]


def _poll_object_request(http_client, headers, request_id, timeout_seconds: float = 16.0):
    import time

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = http_client.get(f"/api/object-editor/requests/{request_id}", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()["request"]
        if payload["status"] in {"done", "failed", "cancelled"}:
            return payload
        time.sleep(0.2)
    raise AssertionError("timed out waiting for object editor request")


def test_object_editor_profile_and_request_lifecycle(auth_socket_user, http_client):
    user = auth_socket_user(prefix="it_obj_profile")
    headers = user["headers"]

    profile = http_client.get("/api/object-editor/profile", headers=headers)
    assert profile.status_code == 200
    profile_payload = profile.json()
    assert profile_payload["ok"] is True
    assert "icons" in profile_payload
    assert "queue" in profile_payload
    assert {"queued", "running", "active_request_id", "active_status", "items_ahead"} <= set(profile_payload["queue"].keys())

    created = http_client.post(
        "/api/object-editor/requests",
        headers=headers,
        json={"description": "a tiny glowing lantern"},
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["request"]["request_id"]

    duplicate = http_client.post(
        "/api/object-editor/requests",
        headers=headers,
        json={"description": "another lantern"},
    )
    assert duplicate.status_code == 409

    done = _poll_object_request(http_client, headers, request_id)
    assert done["status"] == "done"
    assert done["icon_id"]
    assert done["icon_url"]


def test_object_editor_create_thing_broadcasts_and_persists(auth_socket_user, http_client, server_runtime):
    user = auth_socket_user(prefix="it_obj_create")
    headers = user["headers"]
    client = user["client"]

    created_icon = http_client.post(
        "/api/object-editor/requests",
        headers=headers,
        json={"description": "a brass key with ruby inlay"},
    )
    assert created_icon.status_code == 201
    request_id = created_icon.json()["request"]["request_id"]
    done = _poll_object_request(http_client, headers, request_id)
    assert done["status"] == "done"
    icon_id = done["icon_id"]

    created_object = http_client.post(
        f"/api/object-editor/icons/{icon_id}/create",
        headers=headers,
        json={"description": "a brass key with ruby inlay"},
    )
    assert created_object.status_code == 201, created_object.text
    payload = created_object.json()
    object_id = payload["object_id"]
    assert object_id

    room_update = client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-object"
        and p.get("entity", {}).get("entity_type") == "object"
        and p.get("entity", {}).get("entity_id") == object_id,
        timeout=8.0,
    )
    entity = room_update["entity"]
    assert "/object-assets/" in entity["display"]["sprite"]
    assert entity["description"] == "a brass key with ruby inlay"

    deleted_icon = http_client.delete(f"/api/object-editor/icons/{icon_id}", headers=headers)
    assert deleted_icon.status_code == 200
    sprite_response = http_client.get(entity["display"]["sprite"])
    assert sprite_response.status_code == 200

    world_db_path = Path(server_runtime.workspace) / "data" / "worldstate_home.duckdb"
    with duckdb.connect(str(world_db_path), read_only=True) as conn:
        row = conn.execute(
            "SELECT thing_id FROM objects WHERE id = ?",
            [object_id],
        ).fetchone()
    assert row is not None
    thing_id = row[0]
    assert isinstance(thing_id, str) and thing_id.startswith("generated_thing_")

    generated_defs_path = Path(server_runtime.workspace) / "data" / "things" / "generated.yaml"
    assert generated_defs_path.exists()
    with generated_defs_path.open("r", encoding="utf-8") as handle:
        generated_defs = yaml.safe_load(handle) or {}
    assert thing_id in generated_defs
    assert generated_defs[thing_id]["description"] == "a brass key with ruby inlay"
    assert generated_defs[thing_id]["sprite"].startswith("/object-assets/")
