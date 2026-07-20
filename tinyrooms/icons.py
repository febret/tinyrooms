"""Asset path resolution helpers for icon/img/sprite room rendering."""

from pathlib import Path

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


def build_display_assets(info: dict, world_root_path) -> dict:
    assets = resolve_display_assets(info)
    return {
        'icon': _resolve_image_path(assets['icon'], world_root_path),
        'img': _resolve_image_path(assets['img'], world_root_path),
        'sprite': _resolve_image_path(assets['sprite'], world_root_path),
    }


def preprocess_world_assets(world):
    count = 0
    for obj in world.objs.values():
        obj._display_assets = build_display_assets(obj.info, world.root_path)
        count += 1

    for room in world.rooms.values():
        for prop in room.props.values():
            prop._display_assets = build_display_assets(prop.info, world.root_path)
            count += 1

    for peep in world.peeps.values():
        peep._display_assets = build_display_assets(peep.info, world.root_path)
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
