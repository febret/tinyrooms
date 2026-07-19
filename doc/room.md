# Tinyrooms Room Specifications
A room in tinyrooms is like an extended chat room that contains objects, peeps (user- or NPC-controlled), and a set of props (special objects that appear on the room background and can only be modified by the room owner).

In the client, a room is displayed as a stage: a canvas that displays room + props as the background and places objects/characters (which can move dynamically) in the foreground.

## Room Implementation Notes
On the tinyrooms server, room logic is defined in `tinyrooms/room.py`.
Among other things, a room is defined by a label, description, and a set of props with position/orientation. A room also has an owner, which is the user allowed to modify room props.

## Room Client UI
A room background and props are displayed in the client in the roomPanel section of the UI (see app.md). Objects and peeps present in the room are displayed in the foreground. 

### Object Manipulation
In the app, users are allowed to move the sprite for their own peep, plus any objects in the room. Things can be moved via drag/drop. Moves are synchronized across all clients (see Room Update Messages).

## Prop Definition
Props are defined similarly to things (see `data/worlds/home/things.yaml`): they have image/description/label metadata. They are defined and handled separately because they can only be edited by a room owner and may carry room-specific gameplay metadata.

## Prop and Object Display
Both props and objects have three distinct displays (specified as properties pointing to image or svg files in their yaml definition)
- 'icon' (a fixed 32x32 icon, used to display this entity in menus and inventories)
- 'img' (a custom size - max 128-x128 image used to display this entity in longer description views)
- 'sprite' (a 32x32 min, 64x64 max illustration used to show this object or prop in the room view)

### Room Stage and Foreground Objects
The room background and props are displayed directly on the room canvas, while the object / character sprites are displayed with a subtle background shadow (applied on the client via css) to separate them from the fixed room stage.

### Room Stage Types
**TODO**


## Room Update Messages
The room panel in the client is updated when receiving `update_view` messages (see app/client.js socket.on("update_view", ...)). The view parameter of the message determines which part of the room panel is updated:
- 'header' updates the room description / status header
- 'room-stage' updates the room stage view, i.e. the room background / props / prop position and orientations
- 'room-object' updates a single room object, adding it, removing it or updating its display status (position, sprite, sprite effects). When an existing object moves, the move should be applied smoothly.
- 'room-exits' updates the view with the room exit buttons.

## Implemented Server Contract (current)
Room sync is emitted in `tinyrooms/room.py` by `send_full_room_sync(user)` in this order:
1. `header`
2. `room-stage`
3. one `room-object` message for each object
4. one `room-object` message for each peep
5. `room-exits`

### `update_view: header`
Fields:
- `room_id`
- `label`
- `short_description`
- `status_indicators` (currently empty list placeholder)
- `owner_id`
- `is_room_owner`
- `can_edit_props`

### `update_view: room-stage`
Fields:
- `room_id`
- `stage`: `{ width, height, bounds, theme }`
- `background`: room background image path
- `props`: full prop list
- `can_edit_props`

Each prop entry includes:
- identifiers: `prop_instance_id`, `prop_id`
- text: `label`, `description`
- `display`: normalized `{ icon, img, sprite }`
- `position`: `{ x, y, orientation, layer, z_order }`
- `metadata` (currently passthrough from YAML)

### `update_view: room-object`
Fields:
- `room_id`
- `change`: `upsert` or `remove`
- `entity`

Entity payload fields:
- identifiers: `entity_type` (`object` or `peep`), `entity_id`, `owner_username` (peeps)
- text: `label`, `description`
- `display`: normalized `{ icon, img, sprite }`
- `position`: `{ x, y, orientation, layer, z_order }`
- `is_self`

### `update_view: room-exits`
Fields:
- `room_id`
- `exits`: array of `{ id, label, target_room_id }`

## Interaction and Authority Events
Room interactions use explicit socket events in `tinyrooms/connection.py`:

- `room_move_entity`:
  - input: `{ entity_type, entity_id, x, y, orientation? }`
  - peep move rule: self can move self; room owner can move any peep in that room.
  - object move rule: any user in room can move objects.
  - on success: server emits `room-object` updates to all room users.

- `room_edit_prop`:
  - input: `{ prop_instance_id, x?, y?, orientation? }`
  - permission: room owner only.
  - on success: server re-emits full `room-stage` to all room users.

- `room_save_props`:
  - input: `{ props: [{ prop_instance_id?, prop_id, x, y, orientation }] }`
  - permission: room owner only.
  - behavior: replaces the room prop set with the submitted list (supports add/remove/rotate/move in one save operation).
  - on success: persists props to world state DB and re-emits full `room-stage` to all room users.

## Asset and Size Policy (implemented)
Entity/prop display assets are normalized by `tinyrooms/icons.py`:
- `icon` normalized to 32x32 (`_icon32`)
- `sprite` normalized into 32..64 range (`_sprite64`)
- `img` normalized to max 128 (`_img128`)

Fallback resolution:
- `img` is required canonical source.
- `icon` falls back to `sprite`, then `img`.
- `sprite` falls back to `img`, then `icon`.

## Persistence Model (implemented)
World state persistence is additive and migration-safe in `tinyrooms/db.py`:
- objects table includes transform fields: `x`, `y`, `orientation`, `layer`, `z_order`
- room props persisted in `room_props` table with display refs and transform fields
- props are defined from YAML (`data/worlds/home/props/props.yaml`) and runtime positions are restored from DB when available

User spawn persistence is handled in `data/users.duckdb`:
- users table stores `last_world_id`, `last_room_id`, `last_x`, `last_y`
- login restores room + position before initial room sync
- invalid saved room ids fall back to `DEFAULT_ROOM`, and the fallback room is persisted back to DB
- user state is persisted on login, room transitions (`.go`), disconnect, and graceful shutdown

## Client Stage Runtime Notes
The room stage in `app/client.js` is DOM-layer based (not `<canvas>` drawing API):
- stage background and props are rendered in a fixed layer
- foreground entities are rendered in a separate layer with CSS transition for movement
- drag/drop sends intent only on drop (not continuously during drag)
- drag image uses a translucent clone
- room exits are button-only UI in `roomExits`
