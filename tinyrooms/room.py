from pathlib import Path
import yaml
from flask_socketio import emit, join_room, leave_room

from .user import User
from . import text

class Room:
    def __init__(self, room_id, info):
        self.room_id = room_id
        self.info = info
        self.users = set()
    
    def add_user(self, user: User):
        """Add a user to the room"""
        self.users.add(user)
        user.room = self # type: ignore
        join_room(self.room_id, sid=user.sid)        
        self.send_view(user)
    
    def remove_user(self, user: User):
        """Remove a user from the room"""
        if user in self.users:
            self.users.remove(user)
            user.room = None
            leave_room(self.room_id, sid=user.sid)
    
    def send_text(self, message):
        """Send a text message to all users in the room"""
        data = { 'text': message }
        emit('message', data, room=self.room_id, namespace='/') # type: ignore

    def send_view(self, user: User):
        """Send the room view to a specific user"""
        label = self.info.get('label', '')
        image = self.info.get('image', '')
        description = text.make_room_description_text(self, user)
        emit('update_view', {
            'view': 'main',
            'format': 'text',
            'label': label,
            'description': description,
            'image': image,
        }, to=user.sid, namespace='/')


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


def create_rooms(yaml_path=None):
    global room_defs
    global rooms 
    global default_room
    room_defs = load_room_defs(yaml_path)
    rooms = {}
    for rid, rdata in room_defs.items():
        rooms[rid] = Room(rid, rdata)

    default_room = rooms.get("DEFAULT_ROOM", None)

# Default room that all users join upon login
room_defs = None
default_room = None
rooms = None
