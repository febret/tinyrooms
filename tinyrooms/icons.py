"""Icon parsing, preprocessing, and room icon data for tinyrooms.

Icon definition format: comma-separated key:value pairs.
Currently supported keys:
  img  - path to image file (relative to world root), e.g. 'img:images/seal.png'

Additional effect keys (reserved for future use):
  blur, color_filter, text, status_bar, overlay, etc.
"""

from pathlib import Path

# Default icon assigned to every user peep (already 64×64, no preprocessing needed)
DEFAULT_USER_ICON_DEF = {'img': 'images/default_user.png'}


def parse_icon_def(icon_str: str) -> dict:
    """Parse an icon definition string into a dict.

    Example: 'img:images/seal.png,blur:2' -> {'img': 'images/seal.png', 'blur': '2'}
    """
    if not icon_str:
        return {}
    result = {}
    for part in str(icon_str).split(','):
        part = part.strip()
        if ':' in part:
            key, _, value = part.partition(':')
            result[key.strip()] = value.strip()
    return result


def icon_def_to_str(icon_def: dict) -> str:
    """Serialize an icon def dict back to the definition string format."""
    return ','.join(f'{k}:{v}' for k, v in icon_def.items())


def preprocess_icon(icon_def: dict, world_root_path) -> dict:
    """Ensure the icon image is 64x64, creating an adjusted copy when needed.

    Compares modification times so that regeneration only happens when the
    original image is newer than the previously adjusted copy.

    Returns an updated copy of icon_def with the img path pointing to the
    64x64-ready file.
    """
    img_path = icon_def.get('img')
    if not img_path:
        return icon_def

    world_root_path = Path(world_root_path)
    full_path = world_root_path / img_path
    if not full_path.exists():
        print(f"icons: Image not found: {full_path}")
        return icon_def

    adjusted_path = full_path.parent / f"{full_path.stem}_icon64{full_path.suffix}"

    try:
        from PIL import Image as _Image

        # Check whether the existing adjusted file is still up to date
        if adjusted_path.exists():
            src_mtime = full_path.stat().st_mtime
            adj_mtime = adjusted_path.stat().st_mtime
            if adj_mtime >= src_mtime:
                with _Image.open(adjusted_path) as probe:
                    is_anim = hasattr(probe, 'n_frames') and probe.n_frames > 1
                    if is_anim or probe.size == (64, 64):
                        rel = adjusted_path.relative_to(world_root_path)
                        return {**icon_def, 'img': str(rel).replace('\\', '/')}

        # If the original is already 64x64 and not animated, no adjustment needed
        with _Image.open(full_path) as probe:
            is_anim = hasattr(probe, 'n_frames') and probe.n_frames > 1
            if not is_anim and probe.size == (64, 64):
                return icon_def

    except Exception as e:
        print(f"icons: Error probing {full_path}: {e}")
        return icon_def

    _make_icon64(full_path, adjusted_path)
    rel = adjusted_path.relative_to(world_root_path)
    return {**icon_def, 'img': str(rel).replace('\\', '/')}


def _make_icon64(src_path: Path, dst_path: Path):
    """Resize/crop an image to 64x64 and save it to dst_path.

    For animated GIFs every frame is processed individually.
    The strategy is: scale so the shortest dimension equals 64, then
    center-crop the result to 64x64.
    """
    from PIL import Image

    def _resize_frame(frame):
        frame = frame.convert('RGBA')
        w, h = frame.size
        scale = 64 / min(w, h)
        new_w = max(64, int(round(w * scale)))
        new_h = max(64, int(round(h * scale)))
        frame = frame.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - 64) // 2
        top = (new_h - 64) // 2
        return frame.crop((left, top, left + 64, top + 64))

    try:
        with Image.open(src_path) as img:
            is_anim = hasattr(img, 'n_frames') and img.n_frames > 1

            if is_anim:
                frames, durations = [], []
                for i in range(img.n_frames):
                    img.seek(i)
                    frames.append(_resize_frame(img.copy()))
                    durations.append(img.info.get('duration', 100))
                frames[0].save(
                    dst_path,
                    save_all=True,
                    append_images=frames[1:],
                    loop=0,
                    duration=durations,
                    disposal=2,
                )
            else:
                _resize_frame(img.copy()).save(dst_path)

        print(f"icons: Created {dst_path.name}")
    except Exception as e:
        print(f"icons: Failed to create icon64 for {src_path}: {e}")


def preprocess_world_icons(world):
    """Preprocess all icons in *world*, storing the adjusted icon_def on each entity.

    Iterates over objects and peeps, parses their 'icon' field, ensures the
    image is 64x64 (creating an adjusted copy when necessary), and stores the
    resolved icon_def as ``_icon_def`` on the entity.
    """
    count = 0
    for obj in world.objs.values():
        icon_str = obj.info.get('icon')
        if icon_str:
            icon_def = parse_icon_def(icon_str)
            obj._icon_def = preprocess_icon(icon_def, world.root_path)
            count += 1

    for peep in world.peeps.values():
        icon_str = peep.info.get('icon')
        if icon_str:
            icon_def = parse_icon_def(icon_str)
            peep._icon_def = preprocess_icon(icon_def, world.root_path)
            count += 1

    print(f"icons: Preprocessed {count} icon(s).")


def make_room_icons_data(room) -> list:
    """Return a list of icon data dicts for all icon-bearing entities in *room*.

    Each entry has:
      ref_id      - reference ID string (without leading @) used in action commands
      label       - display label for the entity
      description - entity description text
      icon        - dict of icon key:value pairs (img path, future effects, …)
      is_user     - True when the entity is a connected user (for client-side styling)
    """
    icons = []

    for obj_id, obj in room.objs.items():
        icon_def = getattr(obj, '_icon_def', None)
        if icon_def:
            icons.append({
                'ref_id': f'obj:{obj_id}',
                'label': obj.label(),
                'description': obj.info.get('description', ''),
                'icon': icon_def,
                'is_user': False,
            })

    for uname, user_obj in room.users.items():
        icon_def = getattr(user_obj.peep, '_icon_def', None)
        if icon_def:
            icons.append({
                'ref_id': uname,
                'label': uname,
                'description': '',
                'icon': icon_def,
                'is_user': True,
            })

    return icons
