from pathlib import Path
import yaml
from flask_socketio import emit, join_room, leave_room

from .user import User
from . import text


class Room:
    def __init__(self, room_id, info):
        self.room_id = room_id
        self.info = info
        self.users = {}
        self.ways = {}
        self.objs = {}
        self.peeps = {}
        self.label = info.get('label', '')
    
    def add_user(self, user: User):
        """Add a user to the room"""
        self.users[user.username] = user
        user.room = self # type: ignore
        join_room(self.room_id, sid=user.sid)        
        self.send_view(user)
    
    def remove_user(self, user: User):
        """Remove a user from the room"""
        if user.username in self.users:
            del self.users[user.username]
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


class Way:
    def __init__(self, way_id, info):
        self.way_id = way_id
        self.info = info
        self.label = info.get('label', '')
