from pathlib import Path
from types import SimpleNamespace

from tinyrooms import world_editor_api


def test_serialize_room_prefers_world_assets_directory(tmp_path: Path, monkeypatch):
    world_root = tmp_path / "world"
    assets_dir = world_root / "assets" / "images"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "backdrop.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    monkeypatch.setattr(world_editor_api, "active_world", lambda: SimpleNamespace(root_path=world_root))

    room = SimpleNamespace(
        room_id="room1",
        info={"image": "backdrop.png", "stage": {}},
        description_override=None,
        owner_id=None,
        props={},
        label=lambda: "Room 1",
        _serialize_prop=lambda prop: prop,
    )

    serialized = world_editor_api._serialize_room(room)

    assert serialized["background"] == "assets/images/backdrop.png"
