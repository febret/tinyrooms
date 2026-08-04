from . import user_data, char_editor, peep, sprites
from .icons import DEFAULT_USER_ASSETS
from . import db as _db, vibes as _vibes
from . import gameplay as _gameplay
from . import user_data as _user_data


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
        self.status_stale = True
        self.skin = "base"
        self.client_config = user_data.normalize_client_config(
            persisted_state.get("client_config") if isinstance(persisted_state, dict) else None
        )
        # Load powers from persisted state
        if isinstance(persisted_state, dict):
            raw_powers = persisted_state.get("powers", [])
            if isinstance(raw_powers, list):
                self.powers = {str(p) for p in raw_powers}
        # Gameplay state
        self._juice: float = _gameplay.BASE_MAX_JUICE
        self.juice_last_tick: str = _user_data._now_iso()
        self.bops: int = 0
        self.traits: list[str] = []
        self._load_gameplay_state(persisted_state)
        # Ephemeral crafting context — not persisted
        self.active_crafting_station_obj_id: str | None = None
        self.active_crafting_station_thing_id: str | None = None
        self.join_world(world, persisted_state=persisted_state)

    def _load_gameplay_state(self, persisted_state: dict | None) -> None:
        """Load juice, bops, traits from persisted profile state."""
        if not isinstance(persisted_state, dict):
            return
        raw_juice = persisted_state.get("juice")
        try:
            self._juice = float(raw_juice) if raw_juice is not None else _gameplay.BASE_MAX_JUICE
        except (TypeError, ValueError):
            self._juice = _gameplay.BASE_MAX_JUICE
        juice_tick = persisted_state.get("juice_last_tick")
        if isinstance(juice_tick, str):
            self.juice_last_tick = juice_tick
        raw_bops = persisted_state.get("bops")
        try:
            self.bops = int(raw_bops) if raw_bops is not None else 0
        except (TypeError, ValueError):
            self.bops = 0
        raw_traits = persisted_state.get("traits")
        if isinstance(raw_traits, list):
            self.traits = [str(t) for t in raw_traits]

    @property
    def level_info(self) -> dict:
        """Current level info computed from total kudos received."""
        kudos = _user_data.read_kudos(self.username)
        return _gameplay.compute_level(kudos.get("total_received", 0))

    @property
    def level(self) -> int:
        """Current user level (0–10)."""
        return self.level_info["level"]

    @property
    def max_juice(self) -> float:
        """Maximum juice for this user's level."""
        return _gameplay.max_juice(self.level)

    @property
    def juice(self) -> float:
        return self._juice

    @juice.setter
    def juice(self, value: float) -> None:
        self._juice = max(0.0, min(float(value), self.max_juice))

    @property
    def can_act(self) -> bool:
        """True when the user has enough juice to take any action."""
        return self._juice > 0.0

    def recover_juice(self) -> None:
        """Recover juice based on elapsed time since last tick.

        Updates ``juice_last_tick`` to now.
        """
        rate = _gameplay.juice_rate_for_user(self)
        recovered = _gameplay.compute_juice_recovery(self.juice_last_tick, rate)
        self.juice = self._juice + recovered
        self.juice_last_tick = _user_data._now_iso()
        self.status_stale = True

    def consume_juice(self, amount: float | None = None) -> bool:
        """Deduct *amount* of juice (default: one message cost).

        Returns True if the user had enough juice; False otherwise.
        """
        cost = amount if amount is not None else _gameplay.juice_cost_per_message()
        if self._juice <= 0.0:
            return False
        self._juice = max(0.0, self._juice - cost)
        self.status_stale = True
        return True
    
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
    
    def clear_crafting_context(self) -> None:
        """Clear the active crafting station context."""
        self.active_crafting_station_obj_id = None
        self.active_crafting_station_thing_id = None

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
        # Load vibes from worldstate DB
        try:
            ws_id = getattr(world, "ws_id", "home")
            with _db.get_worldstate_connection(ws_id) as wsdb:
                loaded_vibes = _db.read_peep_vibes(wsdb, self.username)
            self.peep.vibes = _vibes.normalize_vibe_map(loaded_vibes)
        except Exception as exc:
            print(f"User.join_world: could not load vibes for '{self.username}': {exc}")
        
    def save(self):
        user_data.save_user_state(self)
    
    def update_status(self):
        """Send the user's current gameplay status to the client."""
        from flask_socketio import emit
        kudos = _user_data.read_kudos(self.username)
        level_info = _gameplay.compute_level(kudos.get("total_received", 0))
        emit('update_status', {
            'username': self.username,
            'level': level_info["level"],
            'level_title': level_info["title"],
            'level_icon': level_info["icon"],
            'kudos_received': kudos.get("total_received", 0),
            'kudos_next_level': level_info["next_threshold"],
            'kudos_required': level_info["kudos_required"],
            'daily_given_remaining': kudos.get("daily_given_remaining", 0),
            'juice': round(self._juice, 2),
            'max_juice': round(self.max_juice, 2),
            'bops': self.bops,
            'traits': list(self.traits),
        }, to=self.sid, namespace='/')
        self.status_stale = False


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
