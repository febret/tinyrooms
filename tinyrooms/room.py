from flask_socketio import emit, join_room, leave_room

from .user import User

class Room:
    def __init__(self, room_id):
        self.room_id = room_id
        self.users = set()
    
    def add_user(self, user: User):
        """Add a user to the room"""
        self.users.add(user)
        user.room = self # type: ignore
        join_room(self.room_id, sid=user.sid)
    
    def remove_user(self, user: User):
        """Remove a user from the room"""
        if user in self.users:
            self.users.remove(user)
            user.room = None
            leave_room(self.room_id, sid=user.sid)
    
    def send_text(self, message, sender_id=None):
        """Send a text message to all users in the room"""
        data = { 'text': message }
        emit('message', data, room=self.room_id) # type: ignore
    
    def get_user_count(self):
        """Get the number of users in the room"""
        return len(self.users)
    
# Default room that all users join upon login
default_room = Room("default")
