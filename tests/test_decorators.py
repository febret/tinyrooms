from pathlib import Path

import yaml

from tinyrooms import decorators as decorator_module
from tinyrooms.object import Object
from tinyrooms.prop import Prop
from tinyrooms.room import Room


def _write_sprite_set(root: Path, stem: str):
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{stem}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / f"{stem}.yaml").write_text(
        yaml.safe_dump(
            {
                "frame_width": 16,
                "frame_height": 16,
                "sprites": {
                    "flame": {
                        "default_frame": "0x0",
                        "anims": {
                            "burn": {"speed": 0.2, "type": "loop", "frames": ["0x0", "1x0"]},
                        },
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_load_decorator_definitions_supports_override_and_missing_dirs(tmp_path: Path):
    server_dir = tmp_path / "data" / "decos"
    world_dir = tmp_path / "world" / "decos"
    missing_dir = tmp_path / "missing"
    server_dir.mkdir(parents=True, exist_ok=True)
    world_dir.mkdir(parents=True, exist_ok=True)

    (server_dir / "main.yaml").write_text(
        yaml.safe_dump({"on_fire": {"animation": "wobble", "glow": {"intensity": 0.4, "color": "#f60"}}}),
        encoding="utf-8",
    )
    (world_dir / "main.yaml").write_text(
        yaml.safe_dump({"on_fire": {"animation": "spin", "glow": {"intensity": 0.8, "color": "#f40"}}}),
        encoding="utf-8",
    )
    (world_dir / "status.yaml").write_text(
        yaml.safe_dump({"frozen": {"animation": "pulse"}}),
        encoding="utf-8",
    )

    loaded = decorator_module.load_decorator_definitions([server_dir, missing_dir, world_dir])
    assert loaded["main:on_fire"]["animation"] == "spin"
    assert loaded["main:on_fire"]["glow"]["intensity"] == 0.8
    assert loaded["status:frozen"]["animation"] == "pulse"


def test_room_serialization_includes_resolved_decorators_for_entities_and_props(tmp_path: Path, monkeypatch):
    world_root = tmp_path / "world"
    _write_sprite_set(world_root / "sprites", "effects")
    (world_root / "images").mkdir(parents=True, exist_ok=True)
    (world_root / "images" / "thing.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    class FakeWorld:
        def __init__(self):
            self.root_path = world_root
            self.deco_defs = {
                "main:on_fire": {
                    "sprite": "$effects/flame/burn",
                    "glow": {"intensity": 0.8, "color": "#ff4400"},
                    "animation": "pulse",
                },
                "main:sparkle": {"animation": "wobble"},
            }

    fake_world = FakeWorld()
    monkeypatch.setattr("tinyrooms.world.active_world", lambda: fake_world)

    room = Room("test_room", {"label": "Test Room"})
    obj = Object("obj-1", "thing-1", {"label": "thing", "img": "images/thing.png", "decorators": ["on_fire"]}, room.id())
    prop = Prop("prop-1", "floor_rug", {"decorators": ["sparkle"]}, room.id())

    serialized_obj = room._serialize_foreground_entity(obj, entity_type="object")
    obj_decorators = serialized_obj["decorators"]
    assert len(obj_decorators) == 1
    assert obj_decorators[0]["id"] == "main:on_fire"
    assert obj_decorators[0]["sprite_display"]["sprite_meta"]["filename"] == "effects"

    serialized_prop = room._serialize_prop(prop)
    prop_decorators = serialized_prop["decorators"]
    assert len(prop_decorators) == 1
    assert prop_decorators[0]["id"] == "main:sparkle"
