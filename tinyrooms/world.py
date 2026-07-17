from pathlib import Path
import yaml
import random

from .room import Room, Way
from .object import Object
from .prop import Prop
from .utils import load_defs
from . import db, icons as icon_module


class World:
    def __init__(self, info, root_path: Path, room_defs: dict, thing_defs: dict, prop_defs: dict, rooms: dict, ways: dict, objs: dict, peeps: dict):
        self.info = info
        self.root_path = root_path
        self.room_defs = room_defs
        self.thing_defs = thing_defs
        self.prop_defs = prop_defs
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
            db.write_room_prop_data(wsdb, self.rooms)


def load_world(yaml_path=None, ws_id='home') -> World:
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
    room_data = db.read_room_data(wsdb)
    for rid, rdata in room_data.items():
        if rid in rooms:
            room = rooms[rid]
            if rdata.get('label_override'):
                room.label_override = rdata['label_override']
            if rdata.get('description_override'):
                room.description_override = rdata['description_override']
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
    object_data = db.read_object_data(wsdb)
    for oid, odata in object_data.items():
        thing_id = odata['thing_id']
        location_id = odata['location_id']
        if thing_id in thing_defs:
            thing_def = thing_defs[thing_id]
            obj = Object(oid, thing_id, thing_def, location_id, odata.get('owner_id'))
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
    
    prop_state_data = db.read_room_prop_data(wsdb)
    for row in prop_state_data:
        room = rooms.get(row['room_id'])
        if room is None:
            continue
        prop = room.props.get(row['id'])
        if prop is None:
            base_info = prop_defs.get(row['prop_id'], {})
            merged = {**base_info}
            if row.get('img'):
                merged['img'] = row.get('img')
            if row.get('sprite'):
                merged['sprite'] = row.get('sprite')
            if row.get('icon'):
                merged['icon'] = row.get('icon')
            prop = Prop(row['id'], row['prop_id'], merged, row['room_id'])
            room.props[prop.prop_instance_id] = prop
        prop.x = int(row.get('x') or prop.x)
        prop.y = int(row.get('y') or prop.y)
        prop.orientation = row.get('orientation') or prop.orientation
        prop.layer = int(row.get('layer') or prop.layer)
        prop.z_order = int(row.get('z_order') or prop.z_order)

    db.write_object_data(wsdb, objs)
    db.write_room_data(wsdb, rooms)
    db.write_room_prop_data(wsdb, rooms)

    # TODO: load peep data from worldstate DB    
    global _active_world
    _active_world = World(world_info, root_path, room_defs, thing_defs, prop_defs, rooms, ways, objs, {})
    
    # Preprocess display assets for loaded entities and props
    icon_module.preprocess_world_assets(_active_world)
    
    return _active_world


_active_world = None
def active_world() -> World:
    global _active_world
    if _active_world is None:
        _active_world = load_world()
    return _active_world