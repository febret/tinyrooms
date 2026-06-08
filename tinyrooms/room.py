from pathlib import Path
import yaml
from flask_socketio import emit, join_room, leave_room

from .user import User
from . import text, icons as icon_module


class Room:
    def __init__(self, room_id, info, owner_id: str = ''):
        self.room_id = room_id
        self.info = info
        self.users = {}
        self.ways = {}
        self.objs = {}
        self.peeps = {}
        self.owner_id = owner_id
        self.label_override = None
        self.description_override = None
        self.initialized = False
        
    def id(self):
        return f"@room:{self.room_id}"
    
    def label(self):
        if self.label_override:
            return self.label_override
        return self.info.get('label', f"Room {self.room_id}")

    def add_user(self, user: User):
        """Add a user to the room"""
        self.users[user.username] = user
        user.room = self # type: ignore
        join_room(self.room_id, sid=user.sid)        
        self.send_view(user)
        # Refresh all other users in the room so they see the new user's icon
        for other in list(self.users.values()):
            if other.username != user.username:
                self.send_view(other)
    
    def remove_user(self, user: User):
        """Remove a user from the room"""
        if user.username in self.users:
            del self.users[user.username]
            user.room = None
            leave_room(self.room_id, sid=user.sid)
            # Refresh remaining users so the departed user's icon disappears
            for other in list(self.users.values()):
                self.send_view(other)
    
    def send_text(self, message):
        """Send a text message to all users in the room"""
        data = { 'text': message }
        emit('message', data, room=self.room_id, namespace='/') # type: ignore

    def send_view(self, user: User):
        """Send the room view to a specific user"""
        label = self.info.get('label', '')
        image = self.info.get('image', '')
        description = text.make_room_description_text(self, user)
        room_icons = icon_module.make_room_icons_data(self)
        emit('update_view', {
            'view': 'main',
            'format': 'text',
            'label': label,
            'description': description,
            'image': image,
            'icons': room_icons,
        }, to=user.sid, namespace='/')


class Way:
    def __init__(self, way_id, info):
        self.way_id = way_id
        self.info = info
        self.label = info.get('label', '')
