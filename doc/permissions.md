# Tinyrooms User Permissions
Users can be given special powers in `data/users/<username>/profile.yaml` (the `powers` property).
These powers affect both gameplay and admin capabilities.

## User profile storage (source of truth)
User identity and persistence are stored in `data/users/<username>/profile.yaml`.
There is no separate user DuckDB anymore.

Current profile fields:
- `password_hash`
- `skin`
- `last_world_id`
- `last_room_id`
- `last_x`
- `last_y`
- `powers`
- `updated_at`

## Available Powers
- admin: can send admin commands to the server from the client
- realtor: can grant, remove, and modify ownership of rooms
- builder: can modify any rooms regardless of ownership, can use the world editor and commands to create / remove rooms.
- moderator: can control other users, including mute/kick them.
- game-master: can control all gameplay aspects and rules.

## Admin commands
Admin commands start with the '/' character and are defined in console.py (run_admin_cmd). Users with the 'admin'
power can send server commands from their client.

## Superuser commands
superuser commands are string commands that can be entered by a logged in user inside a tinyroom world, and that control gameplay in ways not allowed to normal users. The specific set of superuser commands available to a user depends on their powers (eg a realtor has access to room ownership control commands)

superuser commands start with a ':'. superuser commands are separate from server admin commands, which start with a slash, are evaluated globally on the server and are reserved to users with the 'admin' power.

## Superuser command output
Superuser commands provide their output in the app **Activity Panel** (a popup panel in front of the room view).
Output can embed clickable command links using `[[<text>|<command>]]`.
Clicking `<text>` sends `<command>` to the server exactly as if it was typed in chat.
This makes text-driven command UIs possible.

## Superuser commands reference
The canonical command list is maintained in [commands.md](commands.md), including:

- any-user commands
- `admin`, `realtor`, `builder`, `moderator`, and `game-master` command sets
- target token formats and optional arguments
- `/` admin-console routing notes