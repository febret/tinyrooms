# Tinyrooms User Permissions
Users can be given special powers (specified in the data/users/<username>/profile.yaml in the 'powers' property)
that affect both gameplay and admin powers for them.

## Available Powers
- admin: can send admin commands to the server from the client
- realtor: can grant remove and modify ownership of rooms
- shapeshifter: can use the character editor at any time rather than on first login only.

## Admin commands
Admin commands start with the '/' character and are defined in console.py (run_admin_cmd). Users with the 'admin'
power can send server commands from their client.

## Superuser commands
superuser commands are string commands that can be entered by a logged in user inside a tinyroom world, and that control gameplay in ways not allowed to normal users. The specific set of superuser commands available to a user depends on their powers (eg a realtor has access to room ownership control commands)

superuser commands start with a ':'. superuser commands are separate from server admin commands, which start with a slash, are evaluated globally on the server and are reserved to users with the 'admin' power.

These are the currently available superuser commands, granted by each power:

realtor (control room ownership):
- `:room owner set <username>` — transfer ownership of the current room to the named user
- `:room owner clear` — remove the owner from the current room (make it claimable again)
- `:room owner show` — display who currently owns the current room

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