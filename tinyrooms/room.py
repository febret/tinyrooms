from flask_socketio import emit, join_room, leave_room

class Room:
    def __init__(self, room_id):
        self.room_id = room_id
        self.users = set()
    
    def add_user(self, user_id):
        """Add a user to the room"""
        self.users.add(user_id)
        join_room(self.room_id)
    
    def remove_user(self, user_id):
        """Remove a user from the room"""
        if user_id in self.users:
            self.users.remove(user_id)
            leave_room(self.room_id)
    
    def send_text(self, message, sender_id=None):
        """Send a text message to all users in the room"""
        data = {
            'message': message,
            'room_id': self.room_id,
            'sender_id': sender_id
        }
        emit('message', data, room=self.room_id)
    
    def get_user_count(self):
        """Get the number of users in the room"""
        return len(self.users)