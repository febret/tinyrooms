# Tinyrooms
Tinyrooms is a multiplayer web-based game, where users can join and move across 'miniature' rooms, solve puzzles together and play mini-games.

## Quick Start
Tinyrooms is implemented as a python FastAPI Server and a web-based client app (using vanilla JS/HTML/CSS and three.js).

Install dependencies with pip:
```bash
source ./.venv/Scripts/activate
pip install -r requirements.txt
```

Start the server using the `start-server.sh` script:
```bash
# Set custom path to world. Defaults to ./data/worlds/tutorial
# export TRSERVER_WORLD_PATH=/custom/world/path
# Set custom path to worldstate DB. Defaults to ./data/worlds/worldstate_tutorial.sqlite
# export TRSERVER_WORLDSTATE_PATH=/custom/worldstate_path.sqlite
# Set custom path to users directory. Defaults to ./data/users
# export TRSERVER_USERS_PATH=/custom/users/path
# Set tinyrooms server enabled features. Defaults to world-server
# export TRSERVER_FEATURES=world-server,world-editor
# Set the tinyrooms server port. Defaults to 5000
# export TRSERVER_PORT=8000
./start.sh
```

## Basic server control
Use `Ctrl-C` or `\q` to quit the server.
Use `\r` to restart the server process.
Use `\l` to reload all data/definitions without restarting the server process.Main View, Favorite Core Cards, and Equipped Cards
