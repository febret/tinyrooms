import random
from pathlib import Path

import yaml

from .room import Room, Way
from .object import Object
from .prop import Prop
from .utils import load_defs
from . import db, icons as icon_module


def generated_things_dir() -> Path:
    return Path(__file__).parent.parent / "data" / "things"


def load_generated_thing_defs() -> dict:
    gdir = generated_things_dir()
    if not gdir.exists():
        return {}
    return load_defs(gdir)


def save_generated_thing_def(thing_id: str, thing_info: dict) -> None:
    target_dir = generated_things_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "generated.yaml"
    current_defs = {}
    if target_file.exists():
        with open(target_file, 'r', encoding='utf-8') as handle:
            loaded = yaml.safe_load(handle)
        if isinstance(loaded, dict):
            current_defs = loaded
    current_defs[thing_id] = dict(thing_info or {})
    with open(target_file, 'w', encoding='utf-8') as handle:
        yaml.safe_dump(current_defs, handle, sort_keys=False, allow_unicode=True)


class World:
    def __init__(
        self,
        info,
        root_path: Path,
        room_defs: dict,
        thing_defs: dict,
        prop_defs: dict,
        rooms: dict,
        ways: dict,
        objs: dict,
        peeps: dict,
        ws_id: str = 'home',
    ):
        self.info = info
        self.root_path = root_path
        self.room_defs = room_defs
        self.thing_defs = thing_defs
        self.prop_defs = prop_defs
        self.ws_id = ws_id
        self.rooms = rooms
        self.default_room = Room("", {})
        self.ways = ways
        self.objs = objs
        self.peeps = peeps
        self.default_room = self.rooms.get("DEFAULT_ROOM", self.default_room)
        
    def save_state(self, ws_id:str = 'home'):
        with db.get_worldstate_connection(ws_id) as wsdb:
            db.write_room_data(wsdb, self.rooms)
            db.write_object_data(wsdb, self.objs)


def load_world(yaml_path=None, ws_id='home', use_saved_state: bool = True) -> World:
    """Load world definitions from YAML file or directory."""
    if yaml_path is None:
        yaml_path = Path(__file__).parent.parent / "data" / "worlds" / "home" / "world.yaml"    
    yaml_path = Path(yaml_path)
    if not yaml_path.is_file():
        raise FileNotFoundError(f"World definition file not found: {yaml_path}")
    
    with open(yaml_path, 'r', encoding='utf-8') as f:
        root_path = yaml_path.parent
        world_info = yaml.safe_load(f)
    print(f"Loaded world definition from {yaml_path}")
    
    # Initialize the worldstate DB
    wsdb = db.get_worldstate_connection(ws_id)
    db.init_workstate_schema(wsdb)
    
    # Load rooms and thing definitions
    room_defs = load_defs(
        root_path / "rooms",
        id_key_func=lambda key, value: f"{value['place']}.{key}" if 'place' in value else key
    )
    thing_defs = load_defs(root_path / "things")
    generated_thing_defs = load_generated_thing_defs()
    for generated_id, generated_info in generated_thing_defs.items():
        if generated_id in thing_defs:
            print(f"Warning: generated thing id '{generated_id}' overrides world thing definition.")
        thing_defs[generated_id] = generated_info
    props_dir = root_path / "props"
    prop_defs = load_defs(props_dir) if props_dir.exists() else {}
    
    rooms = {}
    ways = {}
    for rid, rdata in room_defs.items():
        rtype = rdata.get('type', 'room')
        if rtype == 'room':
            rooms[rid] = Room(rid, rdata, rdata.get('owner_id'))
        elif rtype == 'way':
            ways[rid] = Way(rid, rdata)
        else:
            print(f"Error: Unknown room type '{rtype}' for room '{rid}'. Skipping.")
    for rid, room in rooms.items():
        rw = room.info.get('ways', [])
        if isinstance(rw, str):
            rw = [rw]
        for w in rw:
            wd = ways.get(w, None)
            if wd:
                room.ways[w] = wd

        room_props = room.info.get('props', [])
        for idx, prop_ref in enumerate(room_props):
            if isinstance(prop_ref, str):
                prop_spec = {'prop': prop_ref}
            else:
                prop_spec = dict(prop_ref)
            prop_id = prop_spec.get('prop') or prop_spec.get('id')
            if not prop_id:
                continue
            prop_info = prop_defs.get(prop_id, {})
            merged = {**prop_info, **prop_spec}
            prop_instance_id = prop_spec.get('prop_instance_id') or f"{rid}-{prop_id}-{idx}"
            room.props[prop_instance_id] = Prop(prop_instance_id, prop_id, merged, rid)
                
    # Load room data from worldstate DB
    if use_saved_state:
        room_data = db.read_room_data(wsdb)
        for rid, rdata in room_data.items():
            if rid in rooms:
                room = rooms[rid]
                if rdata.get('label_override'):
                    room.label_override = rdata['label_override']
                if rdata.get('description_override'):
                    room.description_override = rdata['description_override']
                saved_props = rdata.get('props', [])
                if saved_props:
                    room.props = {}
                    for idx, prop_state in enumerate(saved_props):
                        if not isinstance(prop_state, dict):
                            continue
                        prop_id = prop_state.get('prop_id')
                        if not prop_id:
                            continue
                        prop_instance_id = prop_state.get('prop_instance_id') or f"{rid}-{prop_id}-{idx}"
                        base_info = prop_defs.get(prop_id, {})
                        saved_info = prop_state.get('info')
                        merged = {**base_info, **(saved_info if isinstance(saved_info, dict) else {})}
                        saved_display = prop_state.get('display')
                        if isinstance(saved_display, dict):
                            for key in ("img", "sprite", "icon"):
                                value = saved_display.get(key)
                                if value:
                                    merged[key] = value
                        saved_metadata = prop_state.get('metadata')
                        if isinstance(saved_metadata, dict):
                            merged['metadata'] = saved_metadata
                        saved_position = prop_state.get('position')
                        if isinstance(saved_position, dict):
                            for key in ("x", "y", "orientation", "layer", "z_order"):
                                if key in saved_position:
                                    merged[key] = saved_position[key]
                        prop = Prop(prop_instance_id, prop_id, merged, rid)
                        room.props[prop.prop_instance_id] = prop
                room.initialized = True
            else:
                print(f"Warning: Room '{rid}' found in worldstate DB but not in room definitions.")
            
    # For any non-initialized room, created objects from room info init_things
    objs = {}
    for rid, room in rooms.items():
        if not room.initialized:
            init_things = room.info.get('init_things', [])
            if isinstance(init_things, str):
                init_things = [t.strip() for t in init_things.split(',')]
            for thing_id in init_things:
                thing_id = thing_id.strip()
                if thing_id in thing_defs:
                    thing_def = thing_defs[thing_id]
                    random_hex = ''.join(random.choices('0123456789abcdef', k=5))
                    obj_id = f"{thing_id}-{random_hex}"
                    obj = Object(obj_id, thing_id, thing_def, room.id(), room.owner_id)
                    obj.x = 24 + (len(room.objs) % 4) * 56
                    obj.y = 24 + (len(room.objs) // 4) * 56
                    obj.z_order = room.next_z()
                    room.objs[obj_id] = obj
                    objs[obj_id] = obj
                else:
                    print(f"Warning: Thing '{thing_id}' referenced in room '{rid}' not found in thing_defs.")
    
    print(f"Loaded {len(rooms)} rooms and {len(ways)} ways.")

    # Build a reverse-lookup so we can find rooms by their @room:<id> identity string
    room_by_full_id = {r.id(): r for r in rooms.values()}
    # Also allow bare room_id as a fallback for forward-compatibility
    room_by_full_id.update(rooms)
            
    # Load object data from worldstate DB
    if use_saved_state:
        object_data = db.read_object_data(wsdb)
        for oid, odata in object_data.items():
            thing_id = odata['thing_id']
            location_id = odata['location_id']
            base_thing_def = thing_defs.get(thing_id)
            if base_thing_def is not None:
                obj = Object(oid, thing_id, dict(base_thing_def), location_id, odata.get('owner_id'))
                if odata.get('label_override'):
                    obj.label_override = odata['label_override']
                if odata.get('description_override'):
                    obj.description_override = odata['description_override']
                obj.x = int(odata.get('x') or obj.x)
                obj.y = int(odata.get('y') or obj.y)
                obj.orientation = odata.get('orientation') or obj.orientation
                obj.layer = int(odata.get('layer') or obj.layer)
                obj.z_order = int(odata.get('z_order') or obj.z_order)
                objs[oid] = obj
                # Place object in the corresponding room
                target_room = room_by_full_id.get(location_id)
                if target_room:
                    target_room.objs[oid] = obj
                    target_room._z_counter = max(target_room._z_counter, obj.z_order)
                # TODO: support placing inside container objects and in peep / user inventories.
                else:
                    print(f"Warning: Location '{location_id}' for object '{oid}' not found in rooms.")
            else:
                print(f"Warning: Thing '{thing_id}' for object '{oid}' not found in thing definitions.")
    
    print(f"Loaded {len(objs)} objects.")
    
    db.write_object_data(wsdb, objs)
    db.write_room_data(wsdb, rooms)

    # TODO: load peep data from worldstate DB    
    global _active_world
    _active_world = World(world_info, root_path, room_defs, thing_defs, prop_defs, rooms, ways, objs, {}, ws_id=ws_id)
    
    # Preprocess display assets for loaded entities and props
    icon_module.preprocess_world_assets(_active_world)
    
    return _active_world


_active_world = None


def reset_rooms(ws_id: str | None = None) -> World:
    previous_world = active_world()
    target_ws_id = ws_id or previous_world.ws_id
    world_yaml_path = previous_world.root_path / "world.yaml"
    refreshed_world = load_world(yaml_path=world_yaml_path, ws_id=target_ws_id, use_saved_state=False)

    from . import user

    for connected in list(user.connected_users.values()):
        previous_room = connected.room
        previous_room_id = previous_room.room_id if previous_room is not None else ""
        if previous_room is not None:
            previous_room.remove_user(connected)
        previous_world.peeps.pop(connected.peep.peep_id, None)
        connected.world = refreshed_world
        connected.peep.inventory = {}
        refreshed_world.peeps[connected.peep.peep_id] = connected.peep

        target_room = refreshed_world.rooms.get(previous_room_id, refreshed_world.default_room)
        target_room.add_user(connected)

        user_inventory_id = f"@{connected.username}"
        for obj in refreshed_world.objs.values():
            if obj.location_id == user_inventory_id:
                connected.peep.inventory[obj.obj_id] = obj
        db.save_user_state(connected)

    return refreshed_world


def active_world() -> World:
    global _active_world
    if _active_world is None:
        _active_world = load_world()
    return _active_world