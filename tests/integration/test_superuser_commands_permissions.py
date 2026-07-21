from __future__ import annotations

from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.integration


def _go_to_playroom(client):
    client.emit("navigate", {"way_id": "to_gateway"})
    client.wait_for(
        "update_view",
        predicate=lambda payload: payload.get("view") == "header" and payload.get("room_id") == "playroom",
        timeout=8.0,
    )


def _grant_powers(server_runtime, username: str, powers: list[str]) -> None:
    profile_path = Path(server_runtime.workspace) / "data" / "users" / username / "profile.yaml"
    assert profile_path.exists(), f"profile does not exist for user {username}"
    payload = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    payload["powers"] = list(powers)
    profile_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_realtor_room_owner_set_updates_header(
    register_user,
    socket_client_factory,
    login_socket_user,
    unique_username,
    server_runtime,
):
    target_username = unique_username("it_owner_target")
    register_user(target_username, "target_pass")

    realtor_username = unique_username("it_realtor")
    realtor_password = "realtor_pass"
    register_user(realtor_username, realtor_password)
    _grant_powers(server_runtime, realtor_username, ["realtor"])

    realtor_client = socket_client_factory()
    login_socket_user(realtor_client, realtor_username, realtor_password)
    _go_to_playroom(realtor_client)

    realtor_client.emit("message", {"text": f":room owner set {target_username}"})
    panel = realtor_client.wait_for(
        "activity_panel",
        predicate=lambda p: p.get("title") == "Room Owner",
        timeout=8.0,
    )
    assert target_username in panel.get("content", "")

    header = realtor_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "header" and p.get("room_id") == "playroom",
        timeout=8.0,
    )
    assert header.get("owner_id") == target_username


def test_moderator_move_transfers_user_to_target_room(
    register_user,
    socket_client_factory,
    login_socket_user,
    unique_username,
    server_runtime,
):
    victim_username = unique_username("it_move_victim")
    victim_password = "victim_pass"
    register_user(victim_username, victim_password)
    victim_client = socket_client_factory()
    login_socket_user(victim_client, victim_username, victim_password)

    moderator_username = unique_username("it_moderator")
    moderator_password = "moderator_pass"
    register_user(moderator_username, moderator_password)
    _grant_powers(server_runtime, moderator_username, ["moderator"])
    moderator_client = socket_client_factory()
    login_socket_user(moderator_client, moderator_username, moderator_password)
    _go_to_playroom(moderator_client)

    moderator_client.emit("message", {"text": f":move {victim_username} playroom"})
    panel = moderator_client.wait_for(
        "activity_panel",
        predicate=lambda p: p.get("title") == "Move",
        timeout=8.0,
    )
    assert victim_username in panel.get("content", "")

    victim_header = victim_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "header" and p.get("room_id") == "playroom",
        timeout=8.0,
    )
    assert victim_header.get("room_id") == "playroom"


def test_game_master_goto_teleports_between_rooms(
    register_user,
    socket_client_factory,
    login_socket_user,
    unique_username,
    server_runtime,
):
    gm_username = unique_username("it_gm_goto")
    gm_password = "gm_pass"
    register_user(gm_username, gm_password)
    _grant_powers(server_runtime, gm_username, ["game-master"])

    gm_client = socket_client_factory()
    login_socket_user(gm_client, gm_username, gm_password)
    _go_to_playroom(gm_client)

    gm_client.emit("message", {"text": ":goto DEFAULT_ROOM"})
    default_header = gm_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "header" and p.get("room_id") == "DEFAULT_ROOM",
        timeout=8.0,
    )
    assert default_header.get("room_id") == "DEFAULT_ROOM"

    gm_client.emit("message", {"text": ":goto playroom"})
    playroom_header = gm_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "header" and p.get("room_id") == "playroom",
        timeout=8.0,
    )
    assert playroom_header.get("room_id") == "playroom"


def test_reset_world_restores_yaml_room_label(
    register_user,
    socket_client_factory,
    login_socket_user,
    unique_username,
    server_runtime,
):
    gm_username = unique_username("it_gm_reset")
    gm_password = "gm_reset_pass"
    register_user(gm_username, gm_password)
    _grant_powers(server_runtime, gm_username, ["builder", "game-master"])

    gm_client = socket_client_factory()
    login_socket_user(gm_client, gm_username, gm_password)
    _go_to_playroom(gm_client)

    gm_client.emit("message", {"text": ":room rename Temp Integration Label"})
    renamed_header = gm_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "header" and p.get("room_id") == "playroom" and p.get("label") == "Temp Integration Label",
        timeout=8.0,
    )
    assert renamed_header.get("label") == "Temp Integration Label"

    gm_client.emit("message", {"text": ":reset-world"})
    reset_panel = gm_client.wait_for(
        "activity_panel",
        predicate=lambda p: p.get("title") == "Reset World",
        timeout=8.0,
    )
    assert "reset" in reset_panel.get("content", "").lower()

    restored_header = gm_client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "header" and p.get("room_id") == "playroom" and p.get("label") == "the Playroom",
        timeout=8.0,
    )
    assert restored_header.get("label") == "the Playroom"
