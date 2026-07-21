import uuid

import pytest


pytestmark = pytest.mark.integration


def test_socket_connect_emits_connected_and_emotes(socket_client_factory):
    client = socket_client_factory()
    connected = client.wait_for("connected")
    emotes_def = client.wait_for("emotes_def")

    assert connected["message"] == "connected to server"
    assert "emotes" in emotes_def
    assert "say" in emotes_def["emotes"]
    assert "smile" in emotes_def["emotes"]


def test_login_success_invalid_password_and_duplicate_login(
    register_user,
    socket_client_factory,
    login_socket_user,
):
    username = f"it_login_{uuid.uuid4().hex[:8]}"
    password = "valid_password"
    register_user(username, password)

    first = socket_client_factory()
    login_success = login_socket_user(first, username, password)
    assert login_success["username"] == username
    assert login_success["rest_token"]

    invalid = socket_client_factory()
    invalid.emit("login", {"username": username, "password": "wrong_password"})
    failed = invalid.wait_for("login_failed")
    assert "invalid credentials" in failed["error"]

    duplicate = socket_client_factory()
    duplicate.emit("login", {"username": username, "password": password})
    duplicate_failed = duplicate.wait_for("login_failed")
    assert "already logged in" in duplicate_failed["error"]


def test_message_before_login_returns_not_authenticated(socket_client_factory):
    client = socket_client_factory()
    client.emit("message", {"text": "hello"})
    err = client.wait_for("error")
    assert "not authenticated" in err["error"]
