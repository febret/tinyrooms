from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
import duckdb

# Configuration
DB_PATH = Path(__file__).parent.parent / "data/users.duckdb"

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
            description_override TEXT
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

        CREATE TABLE IF NOT EXISTS room_props (
            id TEXT PRIMARY KEY,
            room_id TEXT,
            prop_id TEXT,
            img TEXT,
            sprite TEXT,
            icon TEXT,
            x INTEGER,
            y INTEGER,
            orientation TEXT,
            layer INTEGER,
            z_order INTEGER,
            metadata_json TEXT
        );
    """)
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
    res = dbcomm.execute("SELECT id, owner_id, label_override, description_override FROM rooms").fetchall()
    room_data = {}
    for row in res:
        room_id, owner_id, label_override, description_override = row
        room_data[room_id] = {
            'id': room_id,
            'owner_id': owner_id,
            'label_override': label_override,
            'description_override': description_override
        }
    return room_data


def write_room_data(dbconn: duckdb.DuckDBPyConnection, rooms: dict):
    """Write room data to the worldstate database."""
    print(f"Committing room data for {len(rooms)} rooms to worldstate DB...")
    for room_id, room in rooms.items():
        dbconn.execute(
            "INSERT OR REPLACE INTO rooms (id, owner_id, label_override, description_override) VALUES (?, ?, ?, ?)",
            (room_id, room.owner_id, room.label_override, room.description_override)
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


def read_room_prop_data(dbconn: duckdb.DuckDBPyConnection):
    res = dbconn.execute(
        "SELECT id, room_id, prop_id, img, sprite, icon, x, y, orientation, layer, z_order, metadata_json FROM room_props"
    ).fetchall()
    out = []
    for row in res:
        out.append({
            'id': row[0],
            'room_id': row[1],
            'prop_id': row[2],
            'img': row[3],
            'sprite': row[4],
            'icon': row[5],
            'x': row[6],
            'y': row[7],
            'orientation': row[8],
            'layer': row[9],
            'z_order': row[10],
            'metadata_json': row[11],
        })
    return out


def write_room_prop_data(dbconn: duckdb.DuckDBPyConnection, rooms: dict):
    prop_rows = []
    for room in rooms.values():
        for prop in room.props.values():
            display = getattr(prop, '_display_assets', {}) or {}
            prop_rows.append((
                prop.prop_instance_id,
                room.room_id,
                prop.prop_id,
                display.get('img') or prop.info.get('img'),
                display.get('sprite') or prop.info.get('sprite'),
                display.get('icon') or prop.info.get('icon'),
                int(prop.x),
                int(prop.y),
                prop.orientation,
                int(prop.layer),
                int(prop.z_order),
                '',
            ))
    dbconn.execute("DELETE FROM room_props")
    for row in prop_rows:
        dbconn.execute(
            "INSERT INTO room_props (id, room_id, prop_id, img, sprite, icon, x, y, orientation, layer, z_order, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
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
        'skin': ('TEXT', "'base'")
    }
    
    for col_name, (col_type, col_default) in expected_columns.items():
        if col_name not in existing_column_names:
            print(f"Adding missing column '{col_name}' to users table")
            con.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type} DEFAULT {col_default}")


def get_user(username):
    con = get_user_connection()
    res = con.execute("SELECT username, password_hash, skin FROM users WHERE username = ?", [username]).fetchall()
    return res[0] if res else None


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
    con = get_user_connection()
    con.execute("UPDATE users SET skin = ? WHERE username = ?", [user_obj.skin, user_obj.username])


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
