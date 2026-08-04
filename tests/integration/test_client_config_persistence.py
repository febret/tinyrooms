from __future__ import annotations

from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.integration


def test_login_emits_default_client_config(auth_socket_user):
    user = auth_socket_user(prefix="it_client_cfg_default")
    client = user["client"]

    config = client.wait_for("client_config", timeout=8.0)
    assert config["show_own_chat_decorators"] is True
    assert config["show_text_bubbles"] is True
    assert config["color_theme"] == "default"


def test_set_client_config_persists_to_profile_and_next_login(
    register_user,
    socket_client_factory,
    login_socket_user,
    server_runtime,
    unique_username,
):
    username = unique_username("it_client_cfg_save")
    password = "password123"
    register_user(username, password)

    first = socket_client_factory()
    login_socket_user(first, username, password)
    first.wait_for("client_config", timeout=8.0)

    first.emit(
        "set_client_config",
        {
            "show_own_chat_decorators": False,
            "show_text_bubbles": False,
            "color_theme": "ocean",
        },
    )
    updated = first.wait_for(
        "client_config",
        predicate=lambda payload: payload.get("color_theme") == "ocean",
        timeout=8.0,
    )
    assert updated["show_own_chat_decorators"] is False
    assert updated["show_text_bubbles"] is False

    profile_path = Path(server_runtime.workspace) / "data" / "users" / username / "profile.yaml"
    profile_payload = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    profile_config = profile_payload.get("client_config") or {}
    assert profile_config.get("show_own_chat_decorators") is False
    assert profile_config.get("show_text_bubbles") is False
    assert profile_config.get("color_theme") == "ocean"

    first.disconnect()

    second = socket_client_factory()
    login_socket_user(second, username, password)
    restored = second.wait_for("client_config", timeout=8.0)
    assert restored["show_own_chat_decorators"] is False
    assert restored["show_text_bubbles"] is False
    assert restored["color_theme"] == "ocean"
