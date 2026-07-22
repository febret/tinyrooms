# Tinyrooms Command Reference

This document is the canonical reference for commands implemented in `tinyrooms/commands.py`.

## Command channels

- **Superuser commands** start with `:` and run in-world (for example `:look`).
- **Admin console commands** start with `/` and are forwarded to server console execution for users with `admin` power (except `/r` and `/k`, which are blocked from client use).

## Target token formats

Many commands take a `<target>` token:

- `@obj:<obj_id>`: object (in room or your inventory, depending on command)
- `@prop:<prop_instance_id>`: prop in current room
- `@peep:<peep_id>` or `@<username>`: peep/user in current room
- `@way:<way_id>`: room exit (for `:go`)

## Any-user commands (no special power required)

| Command | Effect |
| --- | --- |
| `:?` | Show your powers and available commands. |
| `:list users` | List connected users, their room, and powers. |
| `:list users <search>` | Same as above, filtered by username substring. |
| `:look` | Show current room description in the activity panel. |
| `:look <target>` | Inspect a target in the activity panel. |
| `:go` | Prompt for a destination (`Go where?`). |
| `:go <target>` | Traverse an exit (`@way:<id>` or way id). |
| `:pick` | Error for missing target. |
| `:pick <target>` | Pick up a room object into inventory (`@obj:<id>`). |
| `:drop` | Error for missing target. |
| `:drop <target>` | Drop inventory object at your peep position. |
| `:drop <target> <x> <y>` | Drop inventory object at explicit integer coordinates. |
| `:equip` | Show inventory/equip guidance panel. |
| `:self` | Show your username, room, and character description. |
| `:claim room` | Claim the current room if it is unowned/claimable. |
| `:use` | Prompt for a target (`Use what?`). |
| `:use <target>` | Emit default feedback: `You use <target>.` |

## Admin power (`admin`)

| Command | Effect |
| --- | --- |
| `:power list <username>` | Show persisted powers for a user and online/offline status. |
| `:power set <username> <power> <mode>` | Grant or remove a managed power on a user profile. |

Notes:
- Managed powers: `admin`, `realtor`, `builder`, `moderator`, `game-master`
- Enable modes: `grant`, `add`, `on`, `true`, `1`
- Disable modes: `remove`, `revoke`, `off`, `false`, `0`

## Realtor power (`realtor`)

| Command | Effect |
| --- | --- |
| `:room owner set <username>` | Set current room owner id to `<username>`. |
| `:room owner clear` | Clear current room owner. |
| `:room owner show` | Show current room owner. |
| `:room list` | List rooms with owner and clickable `:goto` links. |
| `:room list <filter>` | Filter room list by room id or label. |

## Builder power (`builder`)

| Command | Effect |
| --- | --- |
| `:room rename <name>` | Set current room label override. |
| `:room describe <text>` | Set current room description override. |
| `:room reset` | Clear overrides and restore props from room YAML defaults. |

## Moderator power (`moderator`)

| Command | Effect |
| --- | --- |
| `:kick <username>` | Move user to default room. |
| `:bring <username>` | Move user into your current room. |
| `:move <username> <room_id>` | Move user to a specific room id. |

## Game-master power (`game-master`)

| Command | Effect |
| --- | --- |
| `:goto <room_id>` | Teleport yourself to room id. |
| `:spawn <thing_id>` | Spawn a new object of a thing in current room near your peep. |
| `:despawn <obj_id>` | Remove object from current room. |
| `:reset-world` | Reset all rooms to YAML defaults. |
| `:obj list` | List objects in current room (with `:despawn` links). |
| `:obj list <filter>` | Filter object list by id or label. |
| `:peep list` | List peeps in current room. |
| `:peep list <filter>` | Filter peep list by id or label. |
| `:prop list` | List props in current room. |
| `:prop list <filter>` | Filter prop list by instance id or prop id. |
| `:thing list` | List world thing definitions (with `:spawn` links). |
| `:thing list <filter>` | Filter thing definitions by thing id or label. |
