import pytest


pytestmark = [pytest.mark.integration, pytest.mark.char_editor]


def test_char_editor_profile_requires_token_and_lists_available_sprites(auth_socket_user, http_client):
    user = auth_socket_user(prefix="it_char_profile")
    headers = user["headers"]

    profile = http_client.get("/api/char-editor/profile", headers=headers)
    assert profile.status_code == 200
    payload = profile.json()
    assert payload["ok"] is True
    assert "char" in payload
    assert "available_sprites" in payload
    assert payload["char"]["description"] == ""
    assert payload["char"]["main_image_url"] is None
    assert payload["char"]["current_sprite_preview"] is None

    available = payload["available_sprites"]
    assert available
    scopes = {item["scope"] for item in available}
    assert {"server", "world"} <= scopes
    assert all(item["sprite_ref"].startswith("$") for item in available)
    assert all(item["image_url"].startswith("/sprites/") for item in available)


def test_char_editor_profile_update_persists_character_details_and_broadcasts(auth_socket_user, http_client):
    user = auth_socket_user(prefix="it_char_update")
    headers = user["headers"]
    client = user["client"]

    profile = http_client.get("/api/char-editor/profile", headers=headers)
    payload = profile.json()
    selected_sprite = next(item for item in payload["available_sprites"] if item["scope"] == "world")
    client.drain("update_view")

    updated = http_client.put(
        "/api/char-editor/profile",
        headers=headers,
        json={
            "description": "A quiet ranger in a weathered moss cloak.",
            "current_sprite": selected_sprite["sprite_ref"],
        },
    )
    assert updated.status_code == 200, updated.text
    char = updated.json()["char"]
    assert char["description"] == "A quiet ranger in a weathered moss cloak."
    assert char["current_sprite"] == selected_sprite["sprite_ref"]
    assert char["current_sprite_preview"]["sprite_ref"] == selected_sprite["sprite_ref"]

    saved = http_client.get("/api/char-editor/profile", headers=headers)
    assert saved.status_code == 200
    saved_char = saved.json()["char"]
    assert saved_char["description"] == char["description"]
    assert saved_char["current_sprite"] == char["current_sprite"]

    update_event = client.wait_for(
        "update_view",
        predicate=lambda p: (
            p.get("view") == "room-object"
            and p.get("entity", {}).get("owner_username") == user["username"]
            and p.get("entity", {}).get("description") == char["description"]
        ),
        timeout=6.0,
    )
    entity = update_event["entity"]
    assert entity["display"]["sprite"].startswith("/sprites/world/")
    assert entity["display"]["sprite_meta"]["sprite_id"] == selected_sprite["sprite_id"]

    invalid = http_client.put(
        "/api/char-editor/profile",
        headers=headers,
        json={"current_sprite": "$/missing_set/nope"},
    )
    assert invalid.status_code == 400


def test_char_editor_main_image_generation_persists_asset_and_broadcasts(auth_socket_user, http_client):
    user = auth_socket_user(prefix="it_char_main_image")
    headers = user["headers"]
    client = user["client"]

    profile = http_client.get("/api/char-editor/profile", headers=headers)
    payload = profile.json()
    selected_sprite = next(item for item in payload["available_sprites"] if item["scope"] == "server")

    saved = http_client.put(
        "/api/char-editor/profile",
        headers=headers,
        json={
            "description": "An armored knight with a calm expression.",
            "current_sprite": selected_sprite["sprite_ref"],
        },
    )
    assert saved.status_code == 200
    client.drain("update_view")

    generated = http_client.post(
        "/api/char-editor/main-image",
        headers=headers,
        json={
            "description": "An armored knight with a calm expression.",
            "current_sprite": selected_sprite["sprite_ref"],
        },
    )
    assert generated.status_code == 200, generated.text
    char = generated.json()["char"]
    assert char["main_image"]
    assert char["main_image_url"].startswith(f"/user-assets/{user['username']}/images/")
    assert http_client.get(char["main_image_url"]).status_code == 200

    update_event = client.wait_for(
        "update_view",
        predicate=lambda p: (
            p.get("view") == "room-object"
            and p.get("entity", {}).get("owner_username") == user["username"]
            and p.get("entity", {}).get("display", {}).get("img") == char["main_image_url"]
        ),
        timeout=6.0,
    )
    entity = update_event["entity"]
    assert entity["display"]["img"] == char["main_image_url"]
    assert entity["display"]["icon"] == char["main_image_url"]
    assert entity["display"]["sprite"].startswith("/sprites/server/")
