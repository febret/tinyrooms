from tinyrooms import db

class User:
    """Represents a connected user."""
    def __init__(self, username, sid):
        self.username = username
        self.sid = sid
        self.label = f"[[@{username}[[#d33 {username}]]]]"
        self.room = None
        self.status = "Happy"
        self.actions_stale = True
        self.client_stale = False
        self.styles_stale = False
        self.skin_stale = True
        self.skin = "base"
    
    def __repr__(self):
        return f"User(username={self.username!r}, sid={self.sid!r})"
    
    def load(self):
        user_data = db.get_user(self.username)
        if user_data:
            _, _, self.skin = user_data
        
    def save(self):
        db.save_user_state(self)
    
    def update_status(self):
        """Send the user's status to the client"""
        from flask_socketio import emit
        emit('update_status', {
            'status': {'label': f'Status: {self.status}'}
        }, to=self.sid, namespace='/')


def find_online(username):
    """Check if a user with the given username is currently online."""
    for u in connected_users.values():
        if u.username == username:
            return u
    return None


def reload_clients():
    for u in connected_users.values():
        u.client_stale = True


def reload_styles():
    for u in connected_users.values():
        u.styles_stale = True


def reload_skins(force_value=None):
    for u in connected_users.values():
        if force_value is not None:
            u.skin = force_value
            db.save_user_state(u)
        u.skin_stale = True

# Maps sid -> User instance
connected_users = {}
