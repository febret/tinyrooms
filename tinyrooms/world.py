from pathlib import Path
import yaml

from .room import Room, Way

class World:
    def __init__(self, info, root_path: Path):
        self.info = info
        self.root_path = root_path
        self.room_defs = {}
        self.thing_defs = {}
        self.rooms = {}
        self.default_room = Room("", {})
        self.ways = {}
        self.objs = {}
        self.peeps = {}
        self.create_rooms()

    def create_rooms(self):
        self.room_defs = load_defs(
            self.root_path / "rooms",
            id_key_func=lambda key, value: f"{value.get('place', '')}.{key}" if value.get('place', '') else key
        )
        for rid, rdata in self.room_defs.items():
            rtype = rdata.get('type', 'room')
            if rtype == 'room':
                self.rooms[rid] = Room(rid, rdata)
            elif rtype == 'way':
                self.ways[rid] = Way(rid, rdata)
            else:
                print(f"Error: Unknown room type '{rtype}' for room '{rid}'. Skipping.")
        for rid, room in self.rooms.items():
            ways = room.info.get('ways', [])
            if isinstance(ways, str):
                ways = [ways]
            for w in ways:
                wd = self.ways.get(w, None)
                if wd:
                    room.ways[w] = wd
        self.default_room = self.rooms.get("DEFAULT_ROOM", self.default_room)
        print(f"Created {len(self.rooms)} rooms and {len(self.ways)} ways.")


def load_world(yaml_path=None) -> World:
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
    global _active_world
    _active_world = World(world_info, root_path)
    return _active_world


def load_defs(yaml_path, id_key_func=None):
    """
    Load definitions from YAML file or directory.
    Args:
        yaml_path: Path to YAML file or directory containing YAML files
        id_key_func: Optional function to generate ID from key and value dict.
                     If None, uses the key as-is.
    """
    yaml_path = Path(yaml_path)
    defs = {}
    if yaml_path.is_dir():
        for yaml_file in yaml_path.glob("*.yaml"):
            with open(yaml_file, 'r', encoding='utf-8') as f:
                loaded_defs = yaml.safe_load(f)
                if loaded_defs:
                    for key, value in loaded_defs.items():
                        if id_key_func:
                            def_id = id_key_func(key, value)
                        else:
                            def_id = key
                        
                        if def_id in defs:
                            print(f"Error: Definition '{def_id}' from '{yaml_file.name}' clashes with existing definition. Skipping.")
                        else:
                            defs[def_id] = value
    elif yaml_path.is_file():
        with open(yaml_path, 'r', encoding='utf-8') as f:
            loaded_defs = yaml.safe_load(f)
            if loaded_defs:
                if id_key_func:
                    for key, value in loaded_defs.items():
                        def_id = id_key_func(key, value)
                        defs[def_id] = value
                else:
                    defs.update(loaded_defs)
    else:
        raise FileNotFoundError(f"Path not found: {yaml_path}")
    print(f"Loaded {len(defs)} definitions from {yaml_path}")
    return defs


_active_world = None
def active_world() -> World:
    global _active_world
    if _active_world is None:
        _active_world = load_world()
    return _active_world