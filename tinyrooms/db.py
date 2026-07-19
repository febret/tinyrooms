from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
import duckdb
import json

# Configuration
DB_PATH = Path(__file__).parent.parent / "data/users.duckdb"
DEFAULT_WORLD_ID = "home"
DEFAULT_SPAWN_X = 32
DEFAULT_SPAWN_Y = 32

# Persistent database connection
_user_db_connection = None


def get_user_connection():
    """Get or create a persistent database connection."""
    global _user_db_connection
    if _user_db_connection is None:
        _user_db_connection = duckdb.connect(str(DB_PATH))
    return _user_db_connection


def get_worldstate_connection(ws_id: str):
    """Get a database connection context for a specific world."""
    world_db_path = Path(__file__).parent.parent / "data" / f"worldstate_{ws_id}.duckdb"
    return duckdb.connect(str(world_db_path))


def init_workstate_schema(dbconn: duckdb.DuckDBPyConnection):
    """Initialize the worldstate schema if it doesn't exist."""
    dbconn.execute("""
        CREATE TABLE IF NOT EXISTS rooms (
            id TEXT PRIMARY KEY,
            owner_id TEXT,
            label_override TEXT,
            description_override TEXT,
            props TEXT DEFAULT '[]'
        );
        
        CREATE TABLE IF NOT EXISTS peeps (
            id TEXT PRIMARY KEY,
            location_id TEXT,
            type TEXT
        );
        
        CREATE TABLE IF NOT EXISTS objects (
            id TEXT PRIMARY KEY,
            thing_id TEXT,
            location_id TEXT,
            owner_id TEXT,
            label_override TEXT,
            description_override TEXT
        );

    """)
    _ensure_column(dbconn, "rooms", "props", "TEXT DEFAULT '[]'")
    _ensure_column(dbconn, "objects", "x", "INTEGER DEFAULT 16")
    _ensure_column(dbconn, "objects", "y", "INTEGER DEFAULT 16")
    _ensure_column(dbconn, "objects", "orientation", "TEXT DEFAULT 'front'")
    _ensure_column(dbconn, "objects", "layer", "INTEGER DEFAULT 0")
    _ensure_column(dbconn, "objects", "z_order", "INTEGER DEFAULT 0")
    _ensure_column(dbconn, "peeps", "x", "INTEGER DEFAULT 32")
    _ensure_column(dbconn, "peeps", "y", "INTEGER DEFAULT 32")
    _ensure_column(dbconn, "peeps", "orientation", "TEXT DEFAULT 'front'")
    _ensure_column(dbconn, "peeps", "layer", "INTEGER DEFAULT 1")
    _ensure_column(dbconn, "peeps", "z_order", "INTEGER DEFAULT 1")

def _ensure_column(dbconn: duckdb.DuckDBPyConnection, table_name: str, column_name: str, column_def: str):
    columns = dbconn.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing = {col[1] for col in columns}
    if column_name not in existing:
        dbconn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")

def read_room_data(dbcomm: duckdb.DuckDBPyConnection):
    """Retrieve room data from the worldstate database."""
    res = dbcomm.execute("SELECT id, owner_id, label_override, description_override, props FROM rooms").fetchall()
    room_data = {}
    for row in res:
        room_id, owner_id, label_override, description_override, props_raw = row
        props = []
        if props_raw:
            try:
                parsed_props = json.loads(props_raw)
                if isinstance(parsed_props, list):
                    props = parsed_props
            except json.JSONDecodeError:
                print(f"Warning: invalid props JSON for room '{room_id}', ignoring saved props.")
        room_data[room_id] = {
            'id': room_id,
            'owner_id': owner_id,
            'label_override': label_override,
            'description_override': description_override,
            'props': props,
        }
    return room_data


def write_room_data(dbconn: duckdb.DuckDBPyConnection, rooms: dict):
    """Write room data to the worldstate database."""
    print(f"Committing room data for {len(rooms)} rooms to worldstate DB...")
    for room_id, room in rooms.items():
        prop_rows = []
        for prop in room.props.values():
            prop_rows.append({
                'prop_instance_id': prop.prop_instance_id,
                'prop_id': prop.prop_id,
                'info': dict(getattr(prop, 'info', {}) or {}),
                'position': {
                    'x': int(getattr(prop, 'x', 0)),
                    'y': int(getattr(prop, 'y', 0)),
                    'orientation': getattr(prop, 'orientation', 'front'),
                    'layer': int(getattr(prop, 'layer', 0)),
                    'z_order': int(getattr(prop, 'z_order', 0)),
                },
                'metadata': dict(getattr(prop, 'metadata', {}) or {}),
                'display': dict(getattr(prop, '_display_assets', {}) or {}),
            })
        dbconn.execute(
            "INSERT OR REPLACE INTO rooms (id, owner_id, label_override, description_override, props) VALUES (?, ?, ?, ?, ?)",
            (room_id, room.owner_id, room.label_override, room.description_override, json.dumps(prop_rows))
        )


def read_object_data(dbcomm: duckdb.DuckDBPyConnection):
    """Retrieve object data from the worldstate database."""
    res = dbcomm.execute(
        "SELECT id, thing_id, location_id, owner_id, label_override, description_override, x, y, orientation, layer, z_order FROM objects"
    ).fetchall()
    object_data = {}
    for row in res:
        obj_id, thing_id, location_id, owner_id, label_override, description_override, x, y, orientation, layer, z_order = row
        object_data[obj_id] = {
            'id': obj_id,
            'thing_id': thing_id,
            'location_id': location_id,
            'owner_id': owner_id,
            'label_override': label_override,
            'description_override': description_override,
            'x': x,
            'y': y,
            'orientation': orientation,
            'layer': layer,
            'z_order': z_order,
        }
    return object_data


def write_object_data(dbconn: duckdb.DuckDBPyConnection, objects: dict):
    """Write object data to the worldstate database."""
    print(f"Committing object data for {len(objects)} objects to worldstate DB...")
    for obj_id, obj in objects.items():
        dbconn.execute(
            "INSERT OR REPLACE INTO objects (id, thing_id, location_id, owner_id, label_override, description_override, x, y, orientation, layer, z_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                obj_id,
                obj.thing_id,
                obj.location_id,
                obj.owner_id,
                obj.label_override,
                obj.description_override,
                int(getattr(obj, 'x', 0)),
                int(getattr(obj, 'y', 0)),
                getattr(obj, 'orientation', 'front'),
                int(getattr(obj, 'layer', 0)),
                int(getattr(obj, 'z_order', 0)),
            )
        )


# Initialize duckdb and users table
def init_db(ws_id = 'home'):
    con = get_user_connection()
    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            skin TEXT DEFAULT 'base'
        )
    """)
    
    # Add missing columns if they don't exist (for schema migration)
    existing_columns = con.execute("PRAGMA table_info(users)").fetchall()
    existing_column_names = {col[1] for col in existing_columns}
    
    # Define expected columns with their types and defaults
    expected_columns = {
        'skin': ('TEXT', "'base'"),
        'last_world_id': ('TEXT', f"'{DEFAULT_WORLD_ID}'"),
        'last_room_id': ('TEXT', "''"),
        'last_x': ('INTEGER', str(DEFAULT_SPAWN_X)),
        'last_y': ('INTEGER', str(DEFAULT_SPAWN_Y)),
    }
    
    for col_name, (col_type, col_default) in expected_columns.items():
        if col_name not in existing_column_names:
            print(f"Adding missing column '{col_name}' to users table")
            con.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type} DEFAULT {col_default}")


def get_user(username):
    con = get_user_connection()
    res = con.execute(
        "SELECT username, password_hash, skin, last_world_id, last_room_id, last_x, last_y FROM users WHERE username = ?",
        [username],
    ).fetchall()
    return res[0] if res else None


def _coerce_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def user_row_to_state(user_row):
    if user_row is None:
        return None
    username, password_hash, skin, last_world_id, last_room_id, last_x, last_y = user_row
    return {
        "username": username,
        "password_hash": password_hash,
        "skin": skin or "base",
        "last_world_id": last_world_id or DEFAULT_WORLD_ID,
        "last_room_id": last_room_id or "",
        "last_x": _coerce_int(last_x, DEFAULT_SPAWN_X),
        "last_y": _coerce_int(last_y, DEFAULT_SPAWN_Y),
    }


def create_user(username, password_plain):
    # returns True if created, False if username exists
    if get_user(username):
        return False
    password_hash = generate_password_hash(password_plain)
    con = get_user_connection()
    con.execute("INSERT INTO users (username, password_hash, skin) VALUES (?, ?, ?)", [username, password_hash, 'base'])
    return True


def save_user_state(user_obj):
    """Save user's state to database."""
    room = getattr(user_obj, "room", None)
    peep = getattr(user_obj, "peep", None)
    world = getattr(user_obj, "world", None)
    world_id = getattr(world, "ws_id", DEFAULT_WORLD_ID)
    room_id = room.room_id if room is not None else ""
    x = _coerce_int(getattr(peep, "x", DEFAULT_SPAWN_X), DEFAULT_SPAWN_X)
    y = _coerce_int(getattr(peep, "y", DEFAULT_SPAWN_Y), DEFAULT_SPAWN_Y)
    con = get_user_connection()
    con.execute(
        "UPDATE users SET skin = ?, last_world_id = ?, last_room_id = ?, last_x = ?, last_y = ? WHERE username = ?",
        [user_obj.skin, world_id, room_id, x, y, user_obj.username],
    )


def set_user_value(username, field, value):
    """Set a specific field for a user in the database."""
    con = get_user_connection()
    con.execute(f"UPDATE users SET {field} = ? WHERE username = ?", [value, username])


def save_userdb_state():
    """Save state of all connected users to database."""
    from tinyrooms.user import connected_users
    if not connected_users:
        return
    con = get_user_connection()
    for user_obj in connected_users.values():
        save_user_state(user_obj)
    print(f"Saved state for {len(connected_users)} connected users")
