from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
import duckdb

# Configuration
DB_PATH = Path(__file__).parent.parent / "data/users.duckdb"

# Persistent database connection
_db_connection = None


def get_connection():
    """Get or create a persistent database connection."""
    global _db_connection
    if _db_connection is None:
        _db_connection = duckdb.connect(str(DB_PATH))
    return _db_connection


# Initialize duckdb and users table
def init_db():
    con = get_connection()
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
    con = get_connection()
    res = con.execute("SELECT username, password_hash, skin FROM users WHERE username = ?", [username]).fetchall()
    return res[0] if res else None


def create_user(username, password_plain):
    # returns True if created, False if username exists
    if get_user(username):
        return False
    password_hash = generate_password_hash(password_plain)
    con = get_connection()
    con.execute("INSERT INTO users (username, password_hash, skin) VALUES (?, ?, ?)", [username, password_hash, 'base'])
    return True


def save_user_state(user_obj):
    """Save user's state to database."""
    con = get_connection()
    con.execute("UPDATE users SET skin = ? WHERE username = ?", [user_obj.skin, user_obj.username])

def set_user_value(username, field, value):
    """Set a specific field for a user in the database."""
    con = get_connection()
    con.execute(f"UPDATE users SET {field} = ? WHERE username = ?", [value, username])

def save_state():
    """Save state of all connected users to database."""
    from tinyrooms.user import connected_users
    if not connected_users:
        return
    con = get_connection()
    for user_obj in connected_users.values():
        save_user_state(user_obj)
    print(f"Saved state for {len(connected_users)} connected users")
