from pathlib import Path

import pytest
import yaml

from tinyrooms import prop_sets


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_prop_pair(root: Path, name: str, definition: dict | None):
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    if definition is not None:
        (root / f"{name}.yaml").write_text(yaml.safe_dump(definition, sort_keys=False), encoding="utf-8")


_MINIMAL_DEF = {
    "image": "myprop.png",
    "props": {
        "lamp": {"width": 32, "height": 64, "frames": [[0, 0], [32, 0]]},
    },
}

_ANIM_DEF = {
    "image": "clock.png",
    "label": "Clock",
    "description": "A ticking clock",
    "props": {
        "clock": {"width": 48, "height": 48, "frames": [[0, 0], [48, 0], [96, 0]], "anim_speed": 0.5},
    },
}


# ---------------------------------------------------------------------------
# load_prop_set — schema validation
# ---------------------------------------------------------------------------

def test_load_minimal_prop_set(tmp_path: Path):
    root = tmp_path / "props"
    _write_prop_pair(root, "myprop", _MINIMAL_DEF)
    ps = prop_sets.load_prop_set("world", "myprop", root / "myprop.png", root / "myprop.yaml")
    assert ps.scope == "world"
    assert ps.filename == "myprop"
    assert "lamp" in ps.props
    lamp = ps.props["lamp"]
    assert lamp.width == 32
    assert lamp.height == 64
    assert lamp.frames == [(0, 0), (32, 0)]
    assert lamp.anim_speed is None


def test_load_prop_set_with_animation(tmp_path: Path):
    root = tmp_path / "props"
    _write_prop_pair(root, "clock", _ANIM_DEF)
    ps = prop_sets.load_prop_set("server", "clock", root / "clock.png", root / "clock.yaml")
    assert ps.label == "Clock"
    clock = ps.props["clock"]
    assert clock.anim_speed == 0.5
    assert len(clock.frames) == 3


def test_load_prop_set_missing_image(tmp_path: Path):
    root = tmp_path / "props"
    root.mkdir(parents=True)
    yaml_path = root / "nope.yaml"
    yaml_path.write_text(yaml.safe_dump(_MINIMAL_DEF), encoding="utf-8")
    with pytest.raises(prop_sets.PropValidationError) as exc_info:
        prop_sets.load_prop_set("world", "nope", root / "nope.png", yaml_path)
    assert any("missing image" in e for e in exc_info.value.errors)


def test_load_prop_set_invalid_width(tmp_path: Path):
    root = tmp_path / "props"
    bad_def = {
        "image": "bad.png",
        "props": {"x": {"width": -1, "height": 32, "frames": [[0, 0]]}},
    }
    _write_prop_pair(root, "bad", bad_def)
    with pytest.raises(prop_sets.PropValidationError) as exc_info:
        prop_sets.load_prop_set("world", "bad", root / "bad.png", root / "bad.yaml")
    assert any("width" in e for e in exc_info.value.errors)


def test_load_prop_set_invalid_height(tmp_path: Path):
    root = tmp_path / "props"
    bad_def = {
        "image": "bad.png",
        "props": {"x": {"width": 32, "height": 0, "frames": [[0, 0]]}},
    }
    _write_prop_pair(root, "bad", bad_def)
    with pytest.raises(prop_sets.PropValidationError) as exc_info:
        prop_sets.load_prop_set("world", "bad", root / "bad.png", root / "bad.yaml")
    assert any("height" in e for e in exc_info.value.errors)


def test_load_prop_set_empty_props(tmp_path: Path):
    root = tmp_path / "props"
    bad_def = {"image": "bad.png", "props": {}}
    _write_prop_pair(root, "bad", bad_def)
    with pytest.raises(prop_sets.PropValidationError) as exc_info:
        prop_sets.load_prop_set("world", "bad", root / "bad.png", root / "bad.yaml")
    assert any("props" in e for e in exc_info.value.errors)


def test_load_prop_set_bad_frame(tmp_path: Path):
    root = tmp_path / "props"
    bad_def = {
        "image": "bad.png",
        "props": {"x": {"width": 32, "height": 32, "frames": [[0]]}},  # one-element list
    }
    _write_prop_pair(root, "bad", bad_def)
    with pytest.raises(prop_sets.PropValidationError) as exc_info:
        prop_sets.load_prop_set("world", "bad", root / "bad.png", root / "bad.yaml")
    assert any("frames" in e for e in exc_info.value.errors)


def test_load_prop_set_bad_anim_speed(tmp_path: Path):
    root = tmp_path / "props"
    bad_def = {
        "image": "bad.png",
        "props": {"x": {"width": 32, "height": 32, "frames": [[0, 0]], "anim_speed": -1}},
    }
    _write_prop_pair(root, "bad", bad_def)
    with pytest.raises(prop_sets.PropValidationError) as exc_info:
        prop_sets.load_prop_set("world", "bad", root / "bad.png", root / "bad.yaml")
    assert any("anim_speed" in e for e in exc_info.value.errors)


# ---------------------------------------------------------------------------
# parse_prop_reference
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ref,expected", [
    ("#lamp/lamp_shade", {"filename": "lamp", "prop_id": "lamp_shade", "frame_num": None,
                          "offset_x": 0.0, "offset_y": 0.0, "rotation_deg": 0.0}),
    ("#lamp/lamp_shade/2", {"filename": "lamp", "prop_id": "lamp_shade", "frame_num": 2,
                             "offset_x": 0.0, "offset_y": 0.0, "rotation_deg": 0.0}),
    ("#set/prop.x10.y-5.r45", {"filename": "set", "prop_id": "prop", "frame_num": None,
                                "offset_x": 10.0, "offset_y": -5.0, "rotation_deg": 45.0}),
    ("#set/prop/1.x3.r90", {"filename": "set", "prop_id": "prop", "frame_num": 1,
                             "offset_x": 3.0, "offset_y": 0.0, "rotation_deg": 90.0}),
])
def test_parse_prop_reference_valid(ref, expected):
    result = prop_sets.parse_prop_reference(ref)
    assert result is not None
    assert result.filename == expected["filename"]
    assert result.prop_id == expected["prop_id"]
    assert result.frame_num == expected["frame_num"]
    assert result.offset_x == expected["offset_x"]
    assert result.offset_y == expected["offset_y"]
    assert result.rotation_deg == expected["rotation_deg"]


@pytest.mark.parametrize("bad_ref", [
    "$lamp/shade",     # wrong sigil
    "lamp/shade",      # no sigil
    "#",               # no content
    "#/lamp",          # empty filename
    "#lamp",           # no prop_id
])
def test_parse_prop_reference_invalid(bad_ref):
    assert prop_sets.parse_prop_reference(bad_ref) is None


# ---------------------------------------------------------------------------
# PropRepository — world overrides server
# ---------------------------------------------------------------------------

def test_prop_repository_world_precedence(tmp_path: Path):
    server_root = tmp_path / "server_props"
    world_root = tmp_path / "world"
    world_props = world_root / "props"

    server_def = {"image": "myprop.png", "props": {"from_server": {"width": 8, "height": 8, "frames": [[0, 0]]}}}
    world_def = {"image": "myprop.png", "props": {"from_world": {"width": 16, "height": 16, "frames": [[0, 0]]}}}

    _write_prop_pair(server_root, "myprop", server_def)
    _write_prop_pair(world_props, "myprop", world_def)

    repo = prop_sets.PropRepository(world_root_path=world_root, server_root_path=server_root)
    repo.reindex()

    # World takes precedence on same filename
    record = repo.lookup("myprop")
    assert record is not None
    assert record.scope == "world"
    assert "from_world" in record.prop_set.props

    # Can still access server version directly
    server_record = repo.get("server", "myprop")
    assert server_record is not None
    assert "from_server" in server_record.prop_set.props


def test_prop_repository_server_only(tmp_path: Path):
    server_root = tmp_path / "server_props"
    world_root = tmp_path / "world"

    _write_prop_pair(server_root, "tile", {
        "image": "tile.png",
        "props": {"tile": {"width": 32, "height": 32, "frames": [[0, 0]]}},
    })

    repo = prop_sets.PropRepository(world_root_path=world_root, server_root_path=server_root)
    repo.reindex()

    record = repo.lookup("tile")
    assert record is not None
    assert record.scope == "server"


def test_prop_repository_list_sets_sorted(tmp_path: Path):
    server_root = tmp_path / "server_props"
    world_root = tmp_path / "world"
    world_props = world_root / "props"

    for name, def_ in [
        ("alpha", {"image": "alpha.png", "props": {"a": {"width": 8, "height": 8, "frames": [[0, 0]]}}}),
        ("beta", {"image": "beta.png", "props": {"b": {"width": 8, "height": 8, "frames": [[0, 0]]}}}),
    ]:
        _write_prop_pair(server_root, name, def_)
        _write_prop_pair(world_props, name, def_)

    repo = prop_sets.PropRepository(world_root_path=world_root, server_root_path=server_root)
    repo.reindex()

    names = [r.filename for r in repo.list_sets()]
    # Should be sorted by filename; world entries come before server for same name
    alpha_entries = [r for r in repo.list_sets() if r.filename == "alpha"]
    assert alpha_entries[0].scope == "world"


# ---------------------------------------------------------------------------
# resolve_prop_reference
# ---------------------------------------------------------------------------

def test_resolve_prop_reference(tmp_path: Path):
    world_root = tmp_path / "world"
    _write_prop_pair(
        world_root / "props",
        "items",
        {
            "image": "items.png",
            "props": {"gem": {"width": 16, "height": 16, "frames": [[0, 0], [16, 0]]}},
        },
    )
    repo = prop_sets.PropRepository(world_root_path=world_root)
    repo.reindex()

    ref = prop_sets.parse_prop_reference("#items/gem/1")
    assert ref is not None
    result = prop_sets.resolve_prop_reference(ref, repo)
    assert result["prop_id"] == "gem"
    assert result["frame"]["x"] == 16
    assert result["frame"]["y"] == 0
    assert result["frame"]["width"] == 16
    assert result["image_url"] == "/props/world/items.png"


def test_resolve_prop_reference_with_animation(tmp_path: Path):
    world_root = tmp_path / "world"
    _write_prop_pair(
        world_root / "props",
        "animated",
        {
            "image": "animated.png",
            "props": {"spin": {"width": 24, "height": 24, "frames": [[0, 0], [24, 0]], "anim_speed": 0.25}},
        },
    )
    repo = prop_sets.PropRepository(world_root_path=world_root)
    repo.reindex()

    ref = prop_sets.parse_prop_reference("#animated/spin")
    assert ref is not None
    result = prop_sets.resolve_prop_reference(ref, repo)
    assert "animation" in result
    assert result["animation"]["speed"] == 0.25
    assert len(result["animation"]["frames"]) == 2


def test_resolve_prop_reference_not_found(tmp_path: Path):
    repo = prop_sets.PropRepository(world_root_path=tmp_path / "world")
    repo.reindex()
    ref = prop_sets.parse_prop_reference("#missing/prop")
    assert ref is not None
    with pytest.raises(prop_sets.PropValidationError, match="not found"):
        prop_sets.resolve_prop_reference(ref, repo)


# ---------------------------------------------------------------------------
# to_definition_dict / validate round-trip
# ---------------------------------------------------------------------------

def test_round_trip_serialization(tmp_path: Path):
    root = tmp_path / "props"
    _write_prop_pair(root, "clock", _ANIM_DEF)
    ps = prop_sets.load_prop_set("world", "clock", root / "clock.png", root / "clock.yaml")
    d = prop_sets.to_definition_dict(ps)
    assert d["image"] == "clock.png"
    assert "clock" in d["props"]
    assert d["props"]["clock"]["anim_speed"] == 0.5
    assert d["props"]["clock"]["frames"] == [[0, 0], [48, 0], [96, 0]]
