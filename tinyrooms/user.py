
class User:
    """Represents a connected user."""
    def __init__(self, username, sid):
        self.username = username
        self.sid = sid
        self.label = f"[[@{username}[[#d33 {username}]]]]"
        self.room = None
        self.actions_stale = True
    
    def __repr__(self):
        return f"User(username={self.username!r}, sid={self.sid!r})"


# Maps sid -> User instance
connected_users = {}
