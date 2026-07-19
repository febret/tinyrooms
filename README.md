# tinyrooms

`tinyrooms` is a small multiplayer text-world project built with Python, Flask, and Socket.IO. It combines a lightweight real-time server with a web client, persistent local user storage, and a YAML-driven world/action system.

## Features

- **Realtime multiplayer server** using Flask-SocketIO
- **Browser client** served from the app itself
- **Local registration and login**
- **Persistent user data** stored in DuckDB
- **Persistent user spawn state** (world/room/x/y) restored on reconnect/login
- **YAML-defined worlds** for rooms, ways, and things
- **YAML-defined actions** for chat, emotes, and interactions
- **Live-reload style workflow** via the restart loop in `start.sh`
- **Theme/skin support** in the web client
- **Simple admin/dev console hooks** exposed in the server process

## Project structure

```text
.
├── app/                  # Browser client assets (HTML, JS, CSS)
├── data/
│   ├── actions/          # Action and emote definitions in YAML
│   └── worlds/           # World data; default world is data/worlds/home
├── tinyrooms/            # Core Python package
├── trserver.py           # Server entry point
├── start.sh              # Restart loop for development
└── README.md
```

Notable modules:
- `tinyrooms/server.py` — Flask app, Socket.IO setup, HTTP routes
- `tinyrooms/world.py` — loads world definitions and constructs rooms/things
- `tinyrooms/actions.py` — loads and executes YAML-defined actions
- `tinyrooms/db.py` — DuckDB-backed user persistence

## Getting started

### 1. Clone the repository

```bash
git clone https://github.com/febret/tinyrooms.git
cd tinyrooms
```

### 2. Create and activate a virtual environment

```bash
source ./.venv/Scripts/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Start the server

```bash
bash start.sh
```

### 5. Open the client

Visit:

```text
http://localhost:5000
```

The server binds to `0.0.0.0:5000`, so it can also accept connections from other devices on your local network depending on your firewall and network setup.

## How it works

### Authentication

The client provides a login form plus local registration. The server exposes a `POST /register` route and stores users in a local DuckDB database under `data/users.duckdb`.
On login, the server restores each user's last persisted world/room/position and falls back to the default room when saved room data is invalid.

### Realtime messaging

The browser connects with Socket.IO. Messages, room updates, action definitions, and status/view updates are pushed to connected clients in real time.

### World data

The default world is loaded from:

```text
data/worlds/home/world.yaml
```

Related room and thing definitions are loaded from the world directory, including:
- `data/worlds/home/rooms/rooms.yaml`
- `data/worlds/home/things/things.yaml`

## Development notes

- `Ctrl-C` stops the server and saves connected user state.
- The server includes a reboot path that exits with code `42`, which works with `start.sh` to auto-restart.
- The app serves static client files from `app/`.
- World assets can be served through `/world/<path>`.
- Connected usernames can be listed with the `/connected` route.
- Server bind host/port are configurable: `python trserver.py --host 127.0.0.1 --port 5000`.

## Testing

The repository includes integration tests under `tests/integration` that run against a live server process.

```powershell
python -m pytest
```

For character-editor-only contract coverage:

```powershell
python -m pytest -m char_editor
```

See `doc/testing.md` for details about isolation and runtime behavior.

## Current repository contents

The repository currently includes:
- a browser client in `app/`
- a Python backend in `tinyrooms/`
- a default `home` world under `data/worlds/`
- action packs in `data/actions/`
