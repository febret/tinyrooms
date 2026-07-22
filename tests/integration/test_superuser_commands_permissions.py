from __future__ import annotations

from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.integration


def _go_to_playroom(client):
    client.emit("message", {"text": ":go @way:to_gateway"})
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


def test_admin_power_set_and_list_updates_target_profile(
    register_user,
    socket_client_factory,
    login_socket_user,
    unique_username,
    server_runtime,
):
    admin_username = unique_username("it_admin_power")
    admin_password = "admin_power_pass"
    register_user(admin_username, admin_password)
    _grant_powers(server_runtime, admin_username, ["admin"])

    target_username = unique_username("it_target_power")
    target_password = "target_power_pass"
    register_user(target_username, target_password)

    admin_client = socket_client_factory()
    login_socket_user(admin_client, admin_username, admin_password)

    admin_client.emit("message", {"text": f":power set {target_username} game-master grant"})
    grant_panel = admin_client.wait_for(
        "activity_panel",
        predicate=lambda p: p.get("title") == "Power Set",
        timeout=8.0,
    )
    assert "granted" in grant_panel.get("content", "").lower()
    assert "game-master" in grant_panel.get("content", "")

    admin_client.emit("message", {"text": f":power list {target_username}"})
    list_panel = admin_client.wait_for(
        "activity_panel",
        predicate=lambda p: p.get("title") == "Power List",
        timeout=8.0,
    )
    assert "game-master" in list_panel.get("content", "")

    target_profile_path = Path(server_runtime.workspace) / "data" / "users" / target_username / "profile.yaml"
    target_profile = yaml.safe_load(target_profile_path.read_text(encoding="utf-8")) or {}
    target_powers = set(target_profile.get("powers", []))
    assert "game-master" in target_powers

    admin_client.emit("message", {"text": f":power set {target_username} game-master remove"})
    remove_panel = admin_client.wait_for(
        "activity_panel",
        predicate=lambda p: p.get("title") == "Power Set",
        timeout=8.0,
    )
    assert "removed" in remove_panel.get("content", "").lower()

    target_profile_after = yaml.safe_load(target_profile_path.read_text(encoding="utf-8")) or {}
    target_powers_after = set(target_profile_after.get("powers", []))
    assert "game-master" not in target_powers_after
