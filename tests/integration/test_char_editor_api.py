import pytest


pytestmark = [pytest.mark.integration, pytest.mark.char_editor]


def _valid_descriptors(profile_payload: dict) -> dict[str, str]:
    descriptor_classes = profile_payload["descriptor_classes"]
    out = {}
    for key, meta in descriptor_classes.items():
        options = meta.get("options", [])
        first = options[0]
        out[key] = first["id"] if isinstance(first, dict) else str(first)
    return out


def test_char_editor_profile_requires_token_and_returns_contract(auth_socket_user, http_client):
    user = auth_socket_user(prefix="it_char_profile")
    headers = user["headers"]

    profile = http_client.get("/api/char-editor/profile", headers=headers)
    assert profile.status_code == 200
    payload = profile.json()
    assert payload["ok"] is True
    assert "descriptor_classes" in payload
    assert "char" in payload
    assert "sprites" in payload
    assert "queue" in payload
    assert {"queued", "running", "active_request_id", "active_status", "items_ahead"} <= set(payload["queue"].keys())


def test_char_editor_request_queue_lifecycle_and_validation(auth_socket_user, http_client, poll_until_terminal):
    primary = auth_socket_user(prefix="it_char_main")
    secondary = auth_socket_user(prefix="it_char_invalid")

    profile = http_client.get("/api/char-editor/profile", headers=primary["headers"])
    descriptors = _valid_descriptors(profile.json())

    created = http_client.post(
        "/api/char-editor/requests",
        headers=primary["headers"],
        json={"descriptors": descriptors},
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["request"]["request_id"]

    duplicate = http_client.post(
        "/api/char-editor/requests",
        headers=primary["headers"],
        json={"descriptors": descriptors},
    )
    assert duplicate.status_code == 409

    invalid_descriptors = dict(descriptors)
    first_key = next(iter(invalid_descriptors.keys()))
    invalid_descriptors[first_key] = "__invalid__"
    invalid = http_client.post(
        "/api/char-editor/requests",
        headers=secondary["headers"],
        json={"descriptors": invalid_descriptors},
    )
    assert invalid.status_code == 400

    terminal = poll_until_terminal(request_id, primary["headers"])
    assert terminal["status"] == "done"
    assert terminal["sprite_id"]

    queue = http_client.get("/api/char-editor/queue", headers=primary["headers"])
    assert queue.status_code == 200
    queue_payload = queue.json()["queue"]
    assert {"queued", "running", "active_request_id", "active_status", "items_ahead"} <= set(queue_payload.keys())


def test_char_editor_cancel_and_sprite_select_delete(auth_socket_user, http_client, poll_until_terminal):
    user = auth_socket_user(prefix="it_char_cancel")
    headers = user["headers"]
    profile = http_client.get("/api/char-editor/profile", headers=headers)
    descriptors = _valid_descriptors(profile.json())

    cancelling = http_client.post("/api/char-editor/requests", headers=headers, json={"descriptors": descriptors})
    assert cancelling.status_code == 201
    cancelling_request_id = cancelling.json()["request"]["request_id"]
    cancelled = http_client.delete(f"/api/char-editor/requests/{cancelling_request_id}", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["request"]["status"] in {"cancelled", "done"}

    cancelled_terminal = poll_until_terminal(cancelling_request_id, headers)
    assert cancelled_terminal["status"] in {"cancelled", "done"}

    created = http_client.post("/api/char-editor/requests", headers=headers, json={"descriptors": descriptors})
    assert created.status_code == 201
    request_id = created.json()["request"]["request_id"]
    done = poll_until_terminal(request_id, headers, timeout_seconds=14.0)
    assert done["status"] == "done"
    sprite_id = done["sprite_id"]
    assert sprite_id

    selected = http_client.post(
        f"/api/char-editor/sprites/{sprite_id}/select",
        headers=headers,
        json={"descriptors": descriptors},
    )
    assert selected.status_code == 200
    char = selected.json()["char"]
    assert char["current_sprite_id"] == sprite_id

    deleted = http_client.delete(f"/api/char-editor/sprites/{sprite_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True
