from pathlib import Path

import pytest
import yaml


pytestmark = [pytest.mark.integration]


def _write_png(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n")


def test_sprite_editor_list_and_edit_lifecycle(http_client, server_runtime):
    world_sprite_dir = Path(server_runtime.workspace) / "data" / "worlds" / "home" / "sprites"
    server_sprite_dir = Path(server_runtime.workspace) / "data" / "sprites"
    _write_png(world_sprite_dir / "hero.png")
    _write_png(server_sprite_dir / "hero.png")
    (world_sprite_dir / "hero.yaml").write_text(
        yaml.safe_dump(
            {
                "frame_width": 16,
                "frame_height": 16,
                "sprites": {
                    "idle": {
                        "default_frame": "0x0",
                        "anims": {"walk": {"speed": 0.2, "type": "loop", "frames": ["0x0", "1x0"]}},
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    reindex = http_client.post("/api/sprite-editor/reindex")
    assert reindex.status_code == 200, reindex.text

    listed = http_client.get("/api/sprite-editor/sets")
    assert listed.status_code == 200, listed.text
    sets = listed.json()["sets"]
    world_hero = next((item for item in sets if item["scope"] == "world" and item["filename"] == "hero"), None)
    server_hero = next((item for item in sets if item["scope"] == "server" and item["filename"] == "hero"), None)
    assert world_hero is not None
    assert server_hero is not None
    assert world_hero["has_yaml"] is True
    assert server_hero["has_yaml"] is False

    create_def = http_client.post(
        "/api/sprite-editor/sets/server/hero/create-definition",
        json={
            "frame_width": 32,
            "frame_height": 32,
            "background_color": "#223344",
            "sprite_id": "idle",
            "default_frame": "0x0",
        },
    )
    assert create_def.status_code == 201, create_def.text

    add_sprite = http_client.post(
        "/api/sprite-editor/sets/server/hero/sprites",
        json={"sprite_id": "wave", "default_frame": "1x0"},
    )
    assert add_sprite.status_code == 201, add_sprite.text

    add_anim = http_client.post(
        "/api/sprite-editor/sets/server/hero/sprites/wave/anims",
        json={"anim_id": "wave_loop", "speed": 0.15, "type": "bounce", "frames": ["1x0", "2x0", "3x0"]},
    )
    assert add_anim.status_code == 201, add_anim.text

    update_anim = http_client.put(
        "/api/sprite-editor/sets/server/hero/sprites/wave/anims/wave_loop",
        json={"speed": 0.3, "type": "random", "frames": ["2x0", "4x0"]},
    )
    assert update_anim.status_code == 200, update_anim.text

    get_server_set = http_client.get("/api/sprite-editor/sets/server/hero")
    assert get_server_set.status_code == 200, get_server_set.text
    definition = get_server_set.json()["definition"]
    assert definition["background_color"] == "#223344"
    assert definition["sprites"]["wave"]["anims"]["wave_loop"]["type"] == "random"
    assert definition["sprites"]["wave"]["anims"]["wave_loop"]["frames"] == ["2x0", "4x0"]

    definition["background_color"] = ""
    clear_bg = http_client.put(
        "/api/sprite-editor/sets/server/hero",
        json={"definition": definition},
    )
    assert clear_bg.status_code == 200, clear_bg.text
    refreshed = http_client.get("/api/sprite-editor/sets/server/hero")
    assert refreshed.status_code == 200, refreshed.text
    assert "background_color" not in refreshed.json()["definition"]

    delete_anim = http_client.delete(
        "/api/sprite-editor/sets/server/hero/sprites/wave/anims/wave_loop",
    )
    assert delete_anim.status_code == 200, delete_anim.text

    bad_anim = http_client.post(
        "/api/sprite-editor/sets/server/hero/sprites/wave/anims",
        json={"anim_id": "invalid", "speed": 0.2, "type": "loop", "frames": ["bad-token"]},
    )
    assert bad_anim.status_code == 400
    assert bad_anim.json()["ok"] is False
