# tinyrooms

A simple Python MUD-like environment with a browser-based client.

## Overview

`tinyrooms` is a small multiplayer text-world project built with Python, Flask, and Socket.IO. It combines a lightweight real-time server with a web client, persistent local user storage, and a YAML-driven world/action system.

Players can:
- register and log in from the browser
- move between rooms in a small world
- send chat and action messages in real time
- interact through grouped action buttons
- keep some user state persisted locally between sessions

## Features

- **Realtime multiplayer server** using Flask-SocketIO
- **Browser client** served from the app itself
- **Local registration and login**
- **Persistent user data** stored in DuckDB
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

## Requirements

This project appears to rely on:
- Python 3
- Flask
- Flask-SocketIO
- DuckDB
- PyYAML
- Werkzeug

If you do not already have a dependency file, install the required packages manually.

## Getting started

### 1. Clone the repository

```bash
git clone https://github.com/febret/tinyrooms.git
cd tinyrooms
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install flask flask-socketio duckdb pyyaml werkzeug
```

### 4. Start the server

Run the server directly:

```bash
python trserver.py
```

Or use the helper script, which restarts the server when it exits with code `42`:

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

### Actions

Actions are defined in YAML under `data/actions/`. For example, the base `say` action is defined in `data/actions/actions.yaml`, while additional emotes and themed actions live in other YAML files.

## Development notes

- `Ctrl-C` stops the server and saves connected user state.
- The server includes a reboot path that exits with code `42`, which works with `start.sh` to auto-restart.
- The app serves static client files from `app/`.
- World assets can be served through `/world/<path>`.
- Connected usernames can be listed with the `/connected` route.

## Current repository contents

The repository currently includes:
- a browser client in `app/`
- a Python backend in `tinyrooms/`
- a default `home` world under `data/worlds/`
- action packs in `data/actions/`

## Suggested next improvements

You may want to add:
- a `requirements.txt` or `pyproject.toml`
- screenshots or GIFs of the client
- example world authoring documentation
- deployment instructions
- automated tests

## License

No license file is currently present in the repository. If you plan to share or reuse this project publicly, consider adding one.
