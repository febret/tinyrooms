"""Asset path resolution helpers for icon/img/sprite room rendering."""

from pathlib import Path

from . import sprites

DEFAULT_USER_ASSETS = {
    'img': 'images/default_user.svg',
    'sprite': 'images/default_user.svg',
    'icon': 'images/default_user.svg',
}


def parse_asset_def(asset_value) -> dict:
    if isinstance(asset_value, dict):
        return dict(asset_value)
    if not asset_value:
        return {}
    if isinstance(asset_value, str):
        if ':' in asset_value:
            out = {}
            for part in asset_value.split(','):
                part = part.strip()
                if ':' not in part:
                    continue
                key, _, value = part.partition(':')
                out[key.strip()] = value.strip()
            return out
        return {'img': str(asset_value)}
    return {}


def resolve_display_assets(info: dict) -> dict:
    img = info.get('img') or info.get('image')
    icon_def = parse_asset_def(info.get('icon'))
    sprite_def = parse_asset_def(info.get('sprite'))
    img_def = parse_asset_def(info.get('img'))
    if 'img' not in img_def and img:
        img_def['img'] = img
    if 'img' not in img_def:
        raise ValueError("Display assets require at least an 'img' field")
    base_img = img_def['img']
    icon_img = icon_def.get('img') or sprite_def.get('img') or base_img
    sprite_img = sprite_def.get('img') or img_def.get('img') or icon_img
    return {'img': base_img, 'icon': icon_img, 'sprite': sprite_img}


def _resolve_display_asset_value(asset_value: str, world_root_path, sprite_repo: sprites.SpriteRepository | None = None):
    sprite_ref = sprites.parse_sprite_reference(asset_value)
    if sprite_ref is None:
        return _resolve_image_path(asset_value, world_root_path), None
    repo = sprite_repo or sprites.SpriteRepository(Path(world_root_path))
    if sprite_repo is None:
        repo.reindex()
    resolved = sprites.resolve_sprite_reference(sprite_ref, repo)
    return resolved['image_url'], resolved


def build_display_assets(info: dict, world_root_path, sprite_repo: sprites.SpriteRepository | None = None) -> dict:
    assets = resolve_display_assets(info)
    out = {}
    for key in ('icon', 'img', 'sprite'):
        resolved_value, resolved_meta = _resolve_display_asset_value(assets[key], world_root_path, sprite_repo=sprite_repo)
        out[key] = resolved_value
        if resolved_meta is not None:
            out[f'{key}_meta'] = resolved_meta
    return out


def _build_prop_display_assets(prop_id: str, prop_repo) -> dict:
    """Build display assets for a prop using the PropRepository."""
    from . import prop_sets as prop_sets_module
    # prop_id may be a bare id like "floor_rug" or namespaced "#floor_rug/floor_rug"
    record = prop_repo.lookup(prop_id)
    if record is None or record.prop_set is None:
        return {"img": "", "icon": "", "sprite": ""}
    ps = record.prop_set
    prop_entry = ps.props.get(prop_id) or next(iter(ps.props.values()), None)
    if prop_entry is None:
        return {"img": "", "icon": "", "sprite": ""}
    image_url = f"/props/{ps.scope}/{ps.image_path.name}"
    frame_x, frame_y = prop_entry.frames[0] if prop_entry.frames else (0, 0)
    prop_meta = {
        "ref": f"#{ps.filename}/{prop_entry.prop_id}",
        "scope": ps.scope,
        "filename": ps.filename,
        "prop_id": prop_entry.prop_id,
        "image_url": image_url,
        "frame": {"x": frame_x, "y": frame_y, "width": prop_entry.width, "height": prop_entry.height},
        "offset_x": 0,
        "offset_y": 0,
        "rotation_deg": 0,
    }
    if prop_entry.anim_speed is not None:
        prop_meta["animation"] = {
            "speed": prop_entry.anim_speed,
            "frames": [
                {"x": fx, "y": fy, "width": prop_entry.width, "height": prop_entry.height}
                for fx, fy in prop_entry.frames
            ],
        }
    return {"img": image_url, "icon": image_url, "sprite": image_url, "prop_meta": prop_meta}


def preprocess_world_assets(world):
    from . import prop_sets as prop_sets_module
    sprite_repo = sprites.SpriteRepository(world.root_path)
    sprite_repo.reindex()
    prop_repo = prop_sets_module.PropRepository(world.root_path)
    prop_repo.reindex()
    count = 0
    for obj in world.objs.values():
        obj._display_assets = build_display_assets(obj.info, world.root_path, sprite_repo=sprite_repo)
        count += 1

    for room in world.rooms.values():
        for prop in room.props.values():
            prop._display_assets = _build_prop_display_assets(prop.prop_id, prop_repo)
            count += 1

    for peep in world.peeps.values():
        peep._display_assets = build_display_assets(peep.info, world.root_path, sprite_repo=sprite_repo)
        count += 1
    print(f"assets: preprocessed {count} entity/prop asset sets.")


def _resolve_image_path(image_path: str, world_root_path) -> str:
    if image_path.startswith("/") or image_path.startswith("http://") or image_path.startswith("https://"):
        return image_path
    world_root_path = Path(world_root_path)
    src_path = world_root_path / image_path
    if not src_path.exists():
        print(f"assets: image not found: {src_path}")
        return image_path
    return str(src_path.relative_to(world_root_path)).replace('\\', '/')
