from pathlib import Path

import pytest
import yaml

from tinyrooms import icons, prop_sets


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


@pytest.mark.parametrize("name,bad_def,write_png,expected_error", [
    ("no_image", _MINIMAL_DEF, False, "missing image"),
    ("bad_width", {"image": "bad.png", "props": {"x": {"width": -1, "height": 32, "frames": [[0, 0]]}}}, True, "width"),
    ("bad_height", {"image": "bad.png", "props": {"x": {"width": 32, "height": 0, "frames": [[0, 0]]}}}, True, "height"),
    ("empty_props", {"image": "bad.png", "props": {}}, True, "props"),
    ("bad_frame", {"image": "bad.png", "props": {"x": {"width": 32, "height": 32, "frames": [[0]]}}}, True, "frames"),
    ("bad_anim_speed", {"image": "bad.png", "props": {"x": {"width": 32, "height": 32, "frames": [[0, 0]], "anim_speed": -1}}}, True, "anim_speed"),
])
def test_load_prop_set_validation_errors(tmp_path: Path, name, bad_def, write_png, expected_error):
    root = tmp_path / "props"
    if write_png:
        _write_prop_pair(root, name, bad_def)
    else:
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{name}.yaml").write_text(yaml.safe_dump(bad_def), encoding="utf-8")
    with pytest.raises(prop_sets.PropValidationError) as exc_info:
        prop_sets.load_prop_set("world", name, root / f"{name}.png", root / f"{name}.yaml")
    assert any(expected_error in e for e in exc_info.value.errors)


def test_prop_tags_are_normalized_and_validated(tmp_path: Path):
    root = tmp_path / "props"
    tagged_def = {
        "image": "tagged.png",
        "props": {
            "crate": {
                "width": 32,
                "height": 32,
                "frames": [[0, 0]],
                "tags": [" Object ", "object", "container"],
            }
        },
    }
    _write_prop_pair(root, "tagged", tagged_def)
    loaded = prop_sets.load_prop_set("world", "tagged", root / "tagged.png", root / "tagged.yaml")
    assert loaded.props["crate"].tags == ["object", "container"]
    assert prop_sets.to_definition_dict(loaded)["props"]["crate"]["tags"] == ["object", "container"]

    bad_def = {
        "image": "tagged.png",
        "props": {
            "crate": {
                "width": 32,
                "height": 32,
                "frames": [[0, 0]],
                "tags": "object",
            }
        },
    }
    _write_prop_pair(root, "tagged_bad", bad_def)
    with pytest.raises(prop_sets.PropValidationError) as exc_info:
        prop_sets.load_prop_set("world", "tagged_bad", root / "tagged_bad.png", root / "tagged_bad.yaml")
    assert any("tags" in e for e in exc_info.value.errors)


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
# PropRepository — world overrides server, server-only, listing
# ---------------------------------------------------------------------------

def test_prop_repository(tmp_path: Path):
    """World overrides server for same filename; server-only props are accessible; list is sorted world-first."""
    server_root = tmp_path / "server_props"
    world_root = tmp_path / "world"
    world_props = world_root / "props"

    server_def = {"image": "myprop.png", "props": {"from_server": {"width": 8, "height": 8, "frames": [[0, 0]]}}}
    world_def = {"image": "myprop.png", "props": {"from_world": {"width": 16, "height": 16, "frames": [[0, 0]]}}}
    server_only_def = {"image": "tile.png", "props": {"tile": {"width": 32, "height": 32, "frames": [[0, 0]]}}}

    _write_prop_pair(server_root, "myprop", server_def)
    _write_prop_pair(world_props, "myprop", world_def)
    _write_prop_pair(server_root, "tile", server_only_def)

    repo = prop_sets.PropRepository(world_root_path=world_root, server_root_path=server_root)
    repo.reindex()

    # World takes precedence on same filename
    record = repo.lookup("myprop")
    assert record is not None and record.scope == "world"
    assert "from_world" in record.prop_set.props

    # Server version directly accessible
    server_record = repo.get("server", "myprop")
    assert server_record is not None and "from_server" in server_record.prop_set.props

    # Server-only prop shows as server scope
    tile = repo.lookup("tile")
    assert tile is not None and tile.scope == "server"

    # list_sets: world entries come before server for same filename
    alpha_entries = [r for r in repo.list_sets() if r.filename == "myprop"]
    assert alpha_entries[0].scope == "world"


# ---------------------------------------------------------------------------
# resolve_prop_reference
# ---------------------------------------------------------------------------

def test_resolve_prop_reference(tmp_path: Path):
    """Basic and animated prop references resolve correctly; missing prop raises."""
    world_root = tmp_path / "world"
    _write_prop_pair(
        world_root / "props",
        "items",
        {
            "image": "items.png",
            "background_color": "#ff00ff",
            "props": {"gem": {"width": 16, "height": 16, "frames": [[0, 0], [16, 0]]}},
        },
    )
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

    ref = prop_sets.parse_prop_reference("#items/gem/1")
    assert ref is not None
    result = prop_sets.resolve_prop_reference(ref, repo)
    assert result["prop_id"] == "gem"
    assert result["frame"]["x"] == 16
    assert result["frame"]["y"] == 0
    assert result["frame"]["width"] == 16
    assert result["image_url"] == "/props/world/items.png"
    assert result["background_color"] == "#ff00ff"

    ref2 = prop_sets.parse_prop_reference("#animated/spin")
    assert ref2 is not None
    result2 = prop_sets.resolve_prop_reference(ref2, repo)
    assert "animation" in result2
    assert result2["animation"]["speed"] == 0.25
    assert len(result2["animation"]["frames"]) == 2

    with pytest.raises(prop_sets.PropValidationError, match="not found"):
        prop_sets.resolve_prop_reference(prop_sets.parse_prop_reference("#missing/prop"), repo)


def test_build_prop_display_assets_resolves_namespaced_reference(tmp_path: Path):
    world_root = tmp_path / "world"
    _write_prop_pair(
        world_root / "props",
        "items",
        {
            "image": "items.png",
            "props": {"gem": {"width": 16, "height": 16, "frames": [[4, 8]]}},
        },
    )
    repo = prop_sets.PropRepository(world_root_path=world_root)
    repo.reindex()

    display = icons._build_prop_display_assets("#items/gem.x3.y-2.r45", repo)

    assert display["prop_meta"]["prop_id"] == "gem"
    assert display["prop_meta"]["frame"]["x"] == 4
    assert display["prop_meta"]["offset_x"] == 3.0
    assert display["prop_meta"]["offset_y"] == -2.0
    assert display["prop_meta"]["rotation_deg"] == 45.0


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
