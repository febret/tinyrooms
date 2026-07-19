"""Asset normalization helpers for icon/img/sprite room rendering."""

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


def preprocess_world_assets(world):
    count = 0
    for obj in world.objs.values():
        assets = resolve_display_assets(obj.info)
        obj._display_assets = {
            'icon': _normalize_image(assets['icon'], world.root_path, mode='icon'),
            'img': _normalize_image(assets['img'], world.root_path, mode='img'),
            'sprite': _normalize_image(assets['sprite'], world.root_path, mode='sprite'),
        }
        count += 1

    for room in world.rooms.values():
        for prop in room.props.values():
            assets = resolve_display_assets(prop.info)
            prop._display_assets = {
                'icon': _normalize_image(assets['icon'], world.root_path, mode='icon'),
                'img': _normalize_image(assets['img'], world.root_path, mode='img'),
                'sprite': _normalize_image(assets['sprite'], world.root_path, mode='sprite'),
            }
            count += 1

    for peep in world.peeps.values():
        assets = resolve_display_assets(peep.info)
        peep._display_assets = {
            'icon': _normalize_image(assets['icon'], world.root_path, mode='icon'),
            'img': _normalize_image(assets['img'], world.root_path, mode='img'),
            'sprite': _normalize_image(assets['sprite'], world.root_path, mode='sprite'),
        }
        count += 1
    print(f"assets: preprocessed {count} entity/prop asset sets.")


def _normalize_image(image_path: str, world_root_path, mode: str) -> str:
    world_root_path = Path(world_root_path)
    src_path = world_root_path / image_path
    if not src_path.exists():
        print(f"assets: image not found: {src_path}")
        return image_path
    if src_path.suffix.lower() == ".svg":
        return str(src_path.relative_to(world_root_path)).replace('\\', '/')

    suffix = {'icon': '_icon32', 'sprite': '_sprite64', 'img': '_img128'}[mode]
    dst_path = src_path.parent / f"{src_path.stem}{suffix}{src_path.suffix}"

    if dst_path.exists() and dst_path.stat().st_mtime >= src_path.stat().st_mtime:
        return str(dst_path.relative_to(world_root_path)).replace('\\', '/')

    try:
        from PIL import Image
        with Image.open(src_path) as img:
            normalized = _resize_for_mode(img, mode)
            normalized.save(dst_path)
    except Exception as err:
        print(f"assets: failed normalizing {src_path}: {err}")
        return image_path
    return str(dst_path.relative_to(world_root_path)).replace('\\', '/')


def _resize_for_mode(img, mode: str):
    from PIL import Image

    if mode == 'icon':
        return img.convert('RGBA').resize((32, 32), Image.LANCZOS)

    if mode == 'img':
        max_size = 128
        canvas = img.convert('RGBA')
        canvas.thumbnail((max_size, max_size), Image.LANCZOS)
        return canvas

    max_side = 64
    min_side = 32
    sprite = img.convert('RGBA')
    w, h = sprite.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        sprite = sprite.resize((max(min_side, int(w * scale)), max(min_side, int(h * scale))), Image.LANCZOS)
    w, h = sprite.size
    if min(w, h) < min_side:
        scale = min_side / min(w, h)
        sprite = sprite.resize((min(max_side, int(w * scale)), min(max_side, int(h * scale))), Image.LANCZOS)
    return sprite
