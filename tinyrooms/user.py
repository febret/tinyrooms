from . import db, peep
from .icons import DEFAULT_USER_ASSETS

class User:
    """Represents a connected user."""
    def __init__(self, username, sid, world):
        self.username = username
        self.sid = sid
        self.label = f"[[@{username}[[#d33 {username}]]]]"
        self.room = None
        # TODO: load user description etc. from db
        self.peep = peep.Peep(username, "user", {"img": DEFAULT_USER_ASSETS["img"]})
        self.peep._display_assets = dict(DEFAULT_USER_ASSETS)
        self.actions_stale = True
        self.client_stale = False
        self.styles_stale = False
        self.skin_stale = True
        self.skin = "base"
        self.join_world(world)
    
    def __repr__(self):
        return f"User(username={self.username!r}, sid={self.sid!r})"
    
    def load(self):
        user_data = db.get_user(self.username)
        if user_data:
            _, _, self.skin = user_data
    
    def join_world(self, world):
        """Join the given world, placing the user in the default room."""
        self.world = world
        self.room = world.default_room
        self.world.peeps[self.peep.peep_id] = self.peep
        self.peep.inventory = {}
        if self.room:
            self.room.add_user(self)
        # Find any objects whose location id is @user, and add them to the user's peep inventory
        uid = f"@{self.username}"
        for obj in world.objs.values():
            if obj.location_id == uid:
                self.peep.inventory[obj.obj_id] = obj
        print(f"Found {len(self.peep.inventory)} objects in inventory for user {self.username}")
        
    def save(self):
        db.save_user_state(self)
    
    def update_status(self):
        """Send the user's status to the client"""
        from flask_socketio import emit
        emit('update_status', {
            'status': {'label': f'Status: '}
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
