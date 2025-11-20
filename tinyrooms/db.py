from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
import duckdb

# Configuration
DB_PATH = Path(__file__).parent.parent / "data/users.duckdb"

# Initialize duckdb and users table
def init_db():
    con = duckdb.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL
        )
    """)
    con.close()


def get_user(username):
    con = duckdb.connect(DB_PATH)
    res = con.execute("SELECT username, password_hash FROM users WHERE username = ?", [username]).fetchall()
    con.close()
    return res[0] if res else None


def create_user(username, password_plain):
    # returns True if created, False if username exists
    if get_user(username):
        return False
    password_hash = generate_password_hash(password_plain)
    con = duckdb.connect(DB_PATH)
    con.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", [username, password_hash])
    con.close()
    return True
