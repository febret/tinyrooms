from .room import Room


class User:
    """Represents a connected user."""
    def __init__(self, username, sid):
        self.username = username
        self.sid = sid
        self.label = username  # For now, label is same as username
        self.room = default_room  # Will be set when user joins a room
    
    def __repr__(self):
        return f"User(username={self.username!r}, sid={self.sid!r})"


# Maps sid -> User instance
connected_users = {}

# Default room that all users join upon login
default_room = Room("default")