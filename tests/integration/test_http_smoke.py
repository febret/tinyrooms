import uuid

import pytest


pytestmark = pytest.mark.integration


def test_http_smoke_and_register_contract(http_client):
    root = http_client.get("/")
    assert root.status_code == 200
    assert "<html" in root.text.lower()

    missing = http_client.post("/register", json={"username": "missing_only"})
    assert missing.status_code == 400

    username = f"it_http_{uuid.uuid4().hex[:8]}"
    password = "test_password"
    created = http_client.post("/register", json={"username": username, "password": password})
    assert created.status_code == 201
    assert created.json()["ok"] is True

    duplicate = http_client.post("/register", json={"username": username, "password": password})
    assert duplicate.status_code == 409


def test_connected_reflects_online_after_socket_login(
    http_client,
    register_user,
    socket_client_factory,
    login_socket_user,
    unique_username,
):
    username = unique_username("it_connected")
    password = "test_password"
    register_user(username, password)

    client = socket_client_factory()
    login_socket_user(client, username, password)
    connected = http_client.get("/connected")
    assert connected.status_code == 200
    assert username in connected.json()["connected"]


def test_char_editor_endpoints_require_auth(http_client):
    requests_no_auth = [
        ("GET", "/api/char-editor/profile"),
        ("POST", "/api/char-editor/requests"),
        ("GET", "/api/char-editor/requests/req_missing"),
        ("DELETE", "/api/char-editor/requests/req_missing"),
        ("GET", "/api/char-editor/queue"),
        ("POST", "/api/char-editor/sprites/sprite_missing/select"),
        ("DELETE", "/api/char-editor/sprites/sprite_missing"),
        ("GET", "/api/object-editor/profile"),
        ("POST", "/api/object-editor/requests"),
        ("GET", "/api/object-editor/requests/obj_req_missing"),
        ("DELETE", "/api/object-editor/requests/obj_req_missing"),
        ("GET", "/api/object-editor/queue"),
        ("DELETE", "/api/object-editor/icons/icon_missing.png"),
        ("POST", "/api/object-editor/icons/icon_missing.png/create"),
        ("GET", "/api/props/library"),
    ]
    for method, path in requests_no_auth:
        response = http_client.request(method, path, json={"descriptors": {}})
        assert response.status_code == 401, f"{method} {path}: {response.text}"
