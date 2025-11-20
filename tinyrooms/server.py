import os
from flask_socketio import SocketIO
from flask import Flask, send_from_directory, request, jsonify
from pathlib import Path

from tinyrooms import db, user


STATIC_FOLDER = Path(__file__).parent.parent / "app"
CLIENT_FILENAME = "client.html"


# Create app and SocketIO
app = Flask(__name__, static_folder=str(STATIC_FOLDER), static_url_path="/app")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")


# Route to serve the client HTML at the default route and /client
@app.route("/")
def client():
    return send_from_directory(str(STATIC_FOLDER), CLIENT_FILENAME)


# Simple registration endpoint (for local testing)
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


# Basic API to list connected users (for debug)
@app.route("/connected")
def list_connected():
    # Extract usernames from User instances
    usernames = [u.username for u in user.connected_users.values()]
    return jsonify({"connected": usernames})
