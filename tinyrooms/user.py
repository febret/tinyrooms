from . import user_data, char_editor, peep, sprites
from .icons import DEFAULT_USER_ASSETS


def _coerce_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class User:
    """Represents a connected user."""
    def __init__(self, username, sid, world, persisted_state=None):
        self.username = username
        self.sid = sid
        self.label = f"[[@{username}[[#d33 {username}]]]]"
        self.room = None
        self.powers: set[str] = set()
        # TODO: load user description etc. from db
        self.peep = peep.Peep(username, "user", {"img": DEFAULT_USER_ASSETS["img"]})
        self.peep._display_assets = dict(DEFAULT_USER_ASSETS)
        self._apply_saved_character_state(world)
        self.actions_stale = True
        self.client_stale = False
        self.styles_stale = False
        self.skin_stale = True
        self.skin = "base"
        # Load powers from persisted state
        if isinstance(persisted_state, dict):
            raw_powers = persisted_state.get("powers", [])
            if isinstance(raw_powers, list):
                self.powers = {str(p) for p in raw_powers}
        self.join_world(world, persisted_state=persisted_state)
    
    def __repr__(self):
        return f"User(username={self.username!r}, sid={self.sid!r})"

    def has_power(self, power: str) -> bool:
        """Return True if this user has the named power."""
        return power in self.powers

    def _apply_saved_character_state(self, world):
        char = user_data.read_char(self.username)
        self.peep.info["description"] = str(char.get("description") or "")
        world_root = getattr(world, "root_path", None)
        if not world_root:
            return
        sprite_repo = sprites.SpriteRepository(world_root)
        sprite_repo.reindex()
        self.peep._display_assets = char_editor.build_character_display_assets(
            self.username,
            char,
            world_root,
            sprite_repo=sprite_repo,
        )
    
    def join_world(self, world, persisted_state=None):
        """Join the given world, restoring room/position when available."""
        self.world = world
        self.room = world.default_room
        persisted_world_id = ""
        persisted_room_id = ""
        persisted_x = self.peep.x
        persisted_y = self.peep.y
        if isinstance(persisted_state, dict):
            persisted_world_id = str(persisted_state.get("last_world_id") or "")
            persisted_room_id = str(persisted_state.get("last_room_id") or "")
            persisted_x = _coerce_int(persisted_state.get("last_x"), self.peep.x)
            persisted_y = _coerce_int(persisted_state.get("last_y"), self.peep.y)

        target_room = world.default_room
        if persisted_world_id == getattr(world, "ws_id", "") and persisted_room_id in world.rooms:
            target_room = world.rooms[persisted_room_id]

        self.peep.x = persisted_x
        self.peep.y = persisted_y
        self.room = target_room
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
        user_data.save_user_state(self)
    
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
            user_data.save_user_state(u)
        u.skin_stale = True

# Maps sid -> User instance
connected_users = {}

