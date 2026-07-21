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
These are the currently available superuser commands, granted by each power:

any user (no special power needed):
- `:?` - outputs user information, powers, and a list of available commands based on user powers.
- `:list users [search]` - prints users, optionally filtered by search text, with connection status

admin (manage user powers):
- `:power list <username>` - display current powers for a user
- `:power set <username> <power> <grant|remove>` - grant or remove a power from a user

realtor (control room ownership):
- `:room owner set <username>` — transfer ownership of the current room to the named user
- `:room owner clear` — remove the owner from the current room (make it claimable again)
- `:room owner show` — display who currently owns the current room
- `:room list [filter]` - display rooms optionally filtered by `<filter>`. Room names are clickable and teleport using `:goto`

builder (modify rooms):
- `:room rename <name>` — set a display name override for the current room
- `:room describe <text>` — set a description override for the current room
- `:room reset` — reset the current room's props and overrides to their YAML-defined defaults

moderator (control other users):
- `:kick <username>` — remove a user from the current room and send them to the default room
- `:bring <username>` — pull a user from wherever they are into your current room
- `:move <username> <room_id>` — move a user to a specific room by room id

game-master (control all gameplay aspects):
- `:goto <room_id>` — teleport yourself to any room by room id
- `:spawn <thing_id>` — spawn a new instance of a world thing in the current room
- `:despawn <obj_id>` — remove an object from the current room
- `:reset-world` — reset all rooms to their YAML-defined default state, relocating connected users
- `:obj list [filter]` - prints objects in the current room
- `:peep list [filter]` - prints peeps in the current room
- `:prop list [filter]` - prints props in the current room
- `:thing list [filter]` - prints all available thing definitions