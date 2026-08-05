from pathlib import Path

import pytest
import yaml

from tinyrooms import icons, sprites


def _write_sprite_pair(image_root: Path, defs_root: Path, name: str, definition: dict | None, image_name: str | None = None):
    image_root.mkdir(parents=True, exist_ok=True)
    defs_root.mkdir(parents=True, exist_ok=True)
    asset_name = image_name or name
    (image_root / f"{asset_name}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    if definition is not None:
        (defs_root / f"{name}.yaml").write_text(yaml.safe_dump(definition, sort_keys=False), encoding="utf-8")


def test_sprite_repository_world_precedence_and_reference_resolution(tmp_path: Path):
    server_root = tmp_path / "server_sprites"
    world_root = tmp_path / "world"
    world_sprites = world_root / "sprites"
    image_root = tmp_path / "assets" / "sprites"
    _write_sprite_pair(
        image_root,
        server_root,
        "hero",
        {
            "image": "hero_server.png",
            "frame_width": 16,
            "frame_height": 16,
            "scale": 2,
            "background_color": "#101010",
            "sprites": {"server_idle": {"default_frame": "0x0", "offset_x": 8, "offset_y": 16, "anims": {}}},
        },
        image_name="hero_server",
    )
    _write_sprite_pair(
        image_root,
        world_sprites,
        "hero",
        {
            "image": "hero_world.png",
            "frame_width": 16,
            "frame_height": 16,
            "sprites": {
                "world_idle": {
                    "default_frame": "1x2",
                    "offset_x": 8,
                    "offset_y": 16,
                    "anims": {
                        "walk": {"speed": 0.2, "type": "loop", "frames": ["1x2", "2x2", "3x2"]},
                    },
                }
            },
        },
        image_name="hero_world",
    )
    repo = sprites.SpriteRepository(world_root_path=world_root, server_root_path=server_root, image_root_path=image_root)
    repo.reindex()

    resolved_default = sprites.resolve_sprite_reference(sprites.parse_sprite_reference("$hero"), repo)  # type: ignore[arg-type]
    assert resolved_default["scope"] == "world"
    assert resolved_default["sprite_id"] == "world_idle"
    assert resolved_default["frame"]["token"] == "1x2"
    assert resolved_default["offset_x"] == 8.0
    assert resolved_default["offset_y"] == 16.0

    resolved_server = sprites.resolve_sprite_reference(sprites.parse_sprite_reference("$/hero/server_idle"), repo)  # type: ignore[arg-type]
    assert resolved_server["scope"] == "server"
    assert resolved_server["sprite_id"] == "server_idle"
    assert resolved_server["scale"] == 2
    assert resolved_server["background_color"] == "#101010"
    assert resolved_server["offset_x"] == 8.0
    assert resolved_server["offset_y"] == 16.0

    resolved_anim = sprites.resolve_sprite_reference(sprites.parse_sprite_reference("$hero/world_idle/walk/1"), repo)  # type: ignore[arg-type]
    assert resolved_anim["animation"]["type"] == "loop"
    assert resolved_anim["frame"]["token"] == "2x2"


def test_sprite_schema_validation(tmp_path: Path):
    """Bad frame_width and bad offset_x are both flagged as validation errors."""
    sprite_defs = tmp_path / "sprites"
    sprite_assets = tmp_path / "assets" / "sprites"
    _write_sprite_pair(
        sprite_assets,
        sprite_defs,
        "broken",
        {
            "image": "broken.png",
            "frame_width": 0,
            "frame_height": 16,
            "sprites": {"oops": {"default_frame": "nope", "anims": {}}},
        },
    )
    with pytest.raises(sprites.SpriteValidationError) as err:
        sprites.load_sprite_set("world", "broken", sprite_assets / "broken.png", sprite_defs / "broken.yaml")
    assert "frame_width" in "; ".join(err.value.errors)

    _write_sprite_pair(
        sprite_assets,
        sprite_defs,
        "offset_err",
        {
            "image": "offset_err.png",
            "frame_width": 16,
            "frame_height": 16,
            "sprites": {"idle": {"default_frame": "0x0", "offset_x": "bad", "anims": {}}},
        },
    )
    with pytest.raises(sprites.SpriteValidationError) as err2:
        sprites.load_sprite_set("world", "offset_err", sprite_assets / "offset_err.png", sprite_defs / "offset_err.yaml")
    assert "offset_x" in "; ".join(err2.value.errors)


def test_sprite_background_color_can_be_cleared_and_invalid_type_rejected(tmp_path: Path):
    sprite_defs = tmp_path / "sprites"
    sprite_assets = tmp_path / "assets" / "sprites"
    _write_sprite_pair(
        sprite_assets,
        sprite_defs,
        "hero",
        {
            "image": "hero.png",
            "frame_width": 16,
            "frame_height": 16,
            "background_color": "  ",
            "sprites": {"idle": {"default_frame": "0x0", "anims": {}}},
        },
    )
    loaded = sprites.load_sprite_set("world", "hero", sprite_assets / "hero.png", sprite_defs / "hero.yaml")
    assert loaded.background_color is None
    assert "background_color" not in sprites.to_definition_dict(loaded)

    (sprite_defs / "hero.yaml").write_text(
        yaml.safe_dump(
            {
                "image": "hero.png",
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
        sprites.load_sprite_set("world", "hero", sprite_assets / "hero.png", sprite_defs / "hero.yaml")
    assert "background_color" in "; ".join(err.value.errors)


def test_sprite_scale_defaults_and_validation(tmp_path: Path):
    sprite_defs = tmp_path / "sprites"
    sprite_assets = tmp_path / "assets" / "sprites"
    _write_sprite_pair(
        sprite_assets,
        sprite_defs,
        "hero",
        {
            "image": "hero.png",
            "frame_width": 16,
            "frame_height": 16,
            "sprites": {"idle": {"default_frame": "0x0", "anims": {}}},
        },
    )
    loaded = sprites.load_sprite_set("world", "hero", sprite_assets / "hero.png", sprite_defs / "hero.yaml")
    assert loaded.scale == 1.0
    assert sprites.to_definition_dict(loaded)["scale"] == 1.0

    (sprite_defs / "hero.yaml").write_text(
        yaml.safe_dump(
            {
                "image": "hero.png",
                "frame_width": 16,
                "frame_height": 16,
                "scale": 0,
                "sprites": {"idle": {"default_frame": "0x0", "anims": {}}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(sprites.SpriteValidationError) as err:
        sprites.load_sprite_set("world", "hero", sprite_assets / "hero.png", sprite_defs / "hero.yaml")
    assert "scale" in "; ".join(err.value.errors)


def test_sprite_tags_are_normalized_and_validated(tmp_path: Path):
    sprite_defs = tmp_path / "sprites"
    sprite_assets = tmp_path / "assets" / "sprites"
    _write_sprite_pair(
        sprite_assets,
        sprite_defs,
        "hero",
        {
            "image": "hero.png",
            "frame_width": 16,
            "frame_height": 16,
            "sprites": {
                "idle": {
                    "default_frame": "0x0",
                    "tags": [" Avatar ", "avatar", "peep"],
                    "anims": {},
                }
            },
        },
    )
    loaded = sprites.load_sprite_set("world", "hero", sprite_assets / "hero.png", sprite_defs / "hero.yaml")
    assert loaded.sprites["idle"].tags == ["avatar", "peep"]
    assert sprites.to_definition_dict(loaded)["sprites"]["idle"]["tags"] == ["avatar", "peep"]

    (sprite_defs / "hero.yaml").write_text(
        yaml.safe_dump(
            {
                "image": "hero.png",
                "frame_width": 16,
                "frame_height": 16,
                "sprites": {
                    "idle": {
                        "default_frame": "0x0",
                        "tags": "avatar",
                        "anims": {},
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(sprites.SpriteValidationError) as err:
        sprites.load_sprite_set("world", "hero", sprite_assets / "hero.png", sprite_defs / "hero.yaml")
    assert "tags" in "; ".join(err.value.errors)


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


def test_build_display_assets_invalid_sprite_reference_falls_back_to_placeholder(tmp_path: Path, capsys):
    world_root = tmp_path / "world"
    world_root.mkdir(parents=True, exist_ok=True)
    display = icons.build_display_assets(
        {"img": "images/thing.png", "sprite": "$missing_set/sprite_1"},
        world_root,
    )
    assert display["sprite"] == "/app/placeholder-sprite.svg"
    assert display["sprite_meta"]["sprite_id"] == "placeholder_invalid"
    assert display["icon"] == "/app/placeholder-sprite.svg"
    assert display["icon_meta"]["sprite_id"] == "placeholder_invalid"
    output = capsys.readouterr().out
    assert "assets: warning:" in output
    assert "Using placeholder sprite." in output


def test_parse_sprite_reference_rejects_invalid_shapes():
    with pytest.raises(sprites.SpriteValidationError):
        sprites.parse_sprite_reference("$")
    with pytest.raises(sprites.SpriteValidationError):
        sprites.parse_sprite_reference("$a/b/c/d/e")


def test_resolve_sprite_reference_front_animation_preference(tmp_path: Path):
    """Prefers 'front' animation for default frame; falls back to first animation when absent."""
    world_root = tmp_path / "world"
    sprite_defs = world_root / "sprites"
    sprite_assets = tmp_path / "assets" / "sprites"
    _write_sprite_pair(
        sprite_assets,
        sprite_defs,
        "hero",
        {
            "image": "hero.png",
            "frame_width": 16,
            "frame_height": 16,
            "sprites": {
                "idle": {
                    "default_frame": "0x0",
                    "anims": {
                        "walk": {"speed": 0.2, "type": "loop", "frames": ["4x0", "5x0"]},
                        "front": {"speed": 0.2, "type": "loop", "frames": ["2x1"]},
                    },
                },
                "walk_only": {
                    "default_frame": "0x0",
                    "anims": {
                        "walk": {"speed": 0.2, "type": "loop", "frames": ["3x2", "4x2"]},
                    },
                },
            },
        },
    )
    repo = sprites.SpriteRepository(world_root_path=world_root, server_root_path=tmp_path / "server_sprites", image_root_path=sprite_assets)
    repo.reindex()

    resolved = sprites.resolve_sprite_reference(sprites.parse_sprite_reference("$hero/idle"), repo)  # type: ignore[arg-type]
    assert resolved["frame"]["token"] == "2x1", "should prefer 'front' animation"

    resolved2 = sprites.resolve_sprite_reference(sprites.parse_sprite_reference("$hero/walk_only"), repo)  # type: ignore[arg-type]
    assert resolved2["frame"]["token"] == "3x2", "should fall back to first animation when 'front' absent"
