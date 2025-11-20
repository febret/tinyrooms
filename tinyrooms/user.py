
class User:
    """Represents a connected user."""
    def __init__(self, username, sid):
        self.username = username
        self.sid = sid
        self.label = f"[[@{username}[[#d33 {username}]]]]"
        self.room = None
        self.actions_stale = True
        self.client_stale = False
        self.styles_stale = False
    
    def __repr__(self):
        return f"User(username={self.username!r}, sid={self.sid!r})"


def reload_clients():
    for u in connected_users.values():
        u.client_stale = True


def reload_styles():
    for u in connected_users.values():
        u.styles_stale = True

# Maps sid -> User instance
connected_users = {}
