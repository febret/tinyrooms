from pathlib import Path
import yaml

from .room import Room, Way

class World:
    def __init__(self, info, root_path: Path):
        self.info = info
        self.root_path = root_path
        self.default_room = Room("", {})
        self.rooms = {}
        self.ways = {}
        self.objs = {}
        self.peeps = {}
        self.create_rooms()

    def create_rooms(self):
        room_defs = load_room_defs(self.root_path / "rooms")
        for rid, rdata in room_defs.items():
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


def load_room_defs(yaml_path=None):
    """Load room definitions from YAML file or directory."""
    if yaml_path is None:
        yaml_path = Path(__file__).parent.parent / "data" / "worlds" / "home" / "rooms"    
    yaml_path = Path(yaml_path)
    room_defs = {}
    
    if yaml_path.is_dir():
        for yaml_file in yaml_path.glob("*.yaml"):
            with open(yaml_file, 'r', encoding='utf-8') as f:
                loaded_rooms = yaml.safe_load(f)
                if loaded_rooms:
                    for rkey, rvalue in loaded_rooms.items():
                        place = rvalue.get('place', '')
                        rid = f"{place}.{rkey}" if place else rkey
                        if rid in room_defs:
                            print(f"Error: Room '{rid}' from '{yaml_file.name}' clashes with existing room. Skipping.")
                        else:
                            room_defs[rid] = rvalue
    elif yaml_path.is_file():
        with open(yaml_path, 'r', encoding='utf-8') as f:
            loaded_rooms = yaml.safe_load(f)
            if loaded_rooms:
                room_defs.update(loaded_rooms)
    else:
        raise FileNotFoundError(f"Path not found: {yaml_path}")

    print(f"Loaded {len(room_defs)} rooms from {yaml_path}")
    return room_defs


_active_world = None
def active_world() -> World:
    global _active_world
    if _active_world is None:
        _active_world = load_world()
    return _active_world