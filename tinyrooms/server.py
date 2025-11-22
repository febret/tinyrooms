import os
from flask_socketio import SocketIO
from flask import Flask, send_from_directory, request, jsonify
from pathlib import Path

from . import db, user
from .world import active_world


STATIC_FOLDER = Path(__file__).parent.parent / "app"
CLIENT_FILENAME = "client.html"


# Create app and SocketIO
app = Flask(__name__, static_folder=str(STATIC_FOLDER), static_url_path="/app")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")


@app.route("/")
def client():
    return send_from_directory(str(STATIC_FOLDER), CLIENT_FILENAME)

@app.route("/world/<path:filename>")
def world_data(filename):
    """Serve static files from the world's root path"""
    if active_world().root_path is None:
        return jsonify({"error": "World not loaded"}), 404
    return send_from_directory(str(active_world().root_path), filename)

@app.route("/register", methods=["POST"])
def register():
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"ok": False, "error": "username and password required"}), 400
    created = db.create_user(username, password)
    if not created:
        return jsonify({"ok": False, "error": "username already exists"}), 409
    return jsonify({"ok": True, "message": "user created"}), 201


@app.route("/connected")
def list_connected():
    # Extract usernames from User instances
    usernames = [u.username for u in user.connected_users.values()]
    return jsonify({"connected": usernames})
