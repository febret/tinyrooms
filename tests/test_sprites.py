from pathlib import Path

import pytest
import yaml

from tinyrooms import icons, sprites


def _write_sprite_pair(root: Path, name: str, definition: dict | None):
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    if definition is not None:
        (root / f"{name}.yaml").write_text(yaml.safe_dump(definition, sort_keys=False), encoding="utf-8")


def test_sprite_repository_world_precedence_and_reference_resolution(tmp_path: Path):
    server_root = tmp_path / "server_sprites"
    world_root = tmp_path / "world"
    world_sprites = world_root / "sprites"
    _write_sprite_pair(
        server_root,
        "hero",
        {
            "frame_width": 16,
            "frame_height": 16,
            "background_color": "#101010",
            "sprites": {"server_idle": {"default_frame": "0x0", "anims": {}}},
        },
    )
    _write_sprite_pair(
        world_sprites,
        "hero",
        {
            "frame_width": 16,
            "frame_height": 16,
            "sprites": {
                "world_idle": {
                    "default_frame": "1x2",
                    "anims": {
                        "walk": {"speed": 0.2, "type": "loop", "frames": ["1x2", "2x2", "3x2"]},
                    },
                }
            },
        },
    )
    repo = sprites.SpriteRepository(world_root_path=world_root, server_root_path=server_root)
    repo.reindex()

    resolved_default = sprites.resolve_sprite_reference(sprites.parse_sprite_reference("$hero") , repo)  # type: ignore[arg-type]
    assert resolved_default["scope"] == "world"
    assert resolved_default["sprite_id"] == "world_idle"
    assert resolved_default["frame"]["token"] == "1x2"

    resolved_server = sprites.resolve_sprite_reference(sprites.parse_sprite_reference("$/hero/server_idle") , repo)  # type: ignore[arg-type]
    assert resolved_server["scope"] == "server"
    assert resolved_server["sprite_id"] == "server_idle"
    assert resolved_server["background_color"] == "#101010"

    resolved_anim = sprites.resolve_sprite_reference(sprites.parse_sprite_reference("$hero/world_idle/walk/1") , repo)  # type: ignore[arg-type]
    assert resolved_anim["animation"]["type"] == "loop"
    assert resolved_anim["frame"]["token"] == "2x2"


def test_sprite_schema_validation_reports_errors(tmp_path: Path):
    sprite_dir = tmp_path / "sprites"
    _write_sprite_pair(
        sprite_dir,
        "broken",
        {
            "frame_width": 0,
            "frame_height": 16,
            "sprites": {"oops": {"default_frame": "nope", "anims": {}}},
        },
    )
    with pytest.raises(sprites.SpriteValidationError) as err:
        sprites.load_sprite_set("world", "broken", sprite_dir / "broken.png", sprite_dir / "broken.yaml")
    assert "frame_width" in "; ".join(err.value.errors)


def test_sprite_background_color_can_be_cleared_and_invalid_type_rejected(tmp_path: Path):
    sprite_dir = tmp_path / "sprites"
    _write_sprite_pair(
        sprite_dir,
        "hero",
        {
            "frame_width": 16,
            "frame_height": 16,
            "background_color": "  ",
            "sprites": {"idle": {"default_frame": "0x0", "anims": {}}},
        },
    )
    loaded = sprites.load_sprite_set("world", "hero", sprite_dir / "hero.png", sprite_dir / "hero.yaml")
    assert loaded.background_color is None
    assert "background_color" not in sprites.to_definition_dict(loaded)

    (sprite_dir / "hero.yaml").write_text(
        yaml.safe_dump(
            {
                "frame_width": 16,
                "frame_height": 16,
                "background_color": 123,
                "sprites": {"idle": {"default_frame": "0x0", "anims": {}}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(sprites.SpriteValidationError) as err:
        sprites.load_sprite_set("world", "hero", sprite_dir / "hero.png", sprite_dir / "hero.yaml")
    assert "background_color" in "; ".join(err.value.errors)


def test_build_display_assets_keeps_plain_image_behavior(tmp_path: Path):
    world_root = tmp_path / "world"
    world_root.mkdir(parents=True, exist_ok=True)
    display = icons.build_display_assets(
        {"img": "images/thing.png", "sprite": "images/thing.png", "icon": "img:images/thing.png"},
        world_root,
    )
    assert display["img"] == "images/thing.png"
    assert display["sprite"] == "images/thing.png"
    assert "sprite_meta" not in display


def test_parse_sprite_reference_rejects_invalid_shapes():
    with pytest.raises(sprites.SpriteValidationError):
        sprites.parse_sprite_reference("$")
    with pytest.raises(sprites.SpriteValidationError):
        sprites.parse_sprite_reference("$a/b/c/d/e")
