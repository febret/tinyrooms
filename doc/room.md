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

### Character Movement and Selection
Users move their own character by clicking or tapping on an empty spot in the room canvas. The character smoothly transitions to the target position via CSS animation (180ms linear). During movement:

- **Multi-frame sprite**: the sprite's animation plays continuously (unchanged from idle — no separate walk/idle state machine).
- **Static sprite** (single frame or plain image): a short CSS wobble plays during the transition for visual feedback.

A crosshair cursor on the canvas indicates the stage is clickable for movement.

Dragging is no longer used to move your own character. The room owner may still drag *other* users' peeps.

Objects are still moved by dragging. Dropping an object onto your own character picks it up (see inventory.md).

#### Entity Selection and Targeting
- Clicking a room entity/prop sets it as selected target.
- `lookBox` shows one-line quick information (`label: description`) for the selected target.
- Action emits append a target ref based on selected target type:
  - object -> `@obj:<id>`
  - peep -> `@<username>`
  - prop -> `@prop:<id>`
- Selecting an object target adds a `Pick Up` button to the main action palette.

### Exit Props
Room exits are represented directly on the room canvas as props rather than as overlay buttons. Any prop can be assigned an exit in room-edit mode.

- In normal play: clicking an exit prop sets it as the selected target and adds a **Go: [label]** button to the action palette. Clicking that button calls `navigateExit(wayId)`.
- An exit badge (`→ label`) is rendered below the prop sprite so the exit is always visible.
- `handleRoomExitsUpdate()` stores exit metadata in `roomState.exits` for reference by prop rendering and palette logic.
- `navigateExit(wayId)` emits `room_navigate { way_id }` to the server (same as the old exit buttons did).
- The `#roomExits` DOM element is hidden; its variable is kept in `client.js` for backwards-compatibility but is never populated.

## Prop Definition
Props are defined similarly to things (see `data/worlds/home/things.yaml`): they have image/description/label metadata. They are defined and handled separately because they can only be edited by a room owner and may carry room-specific gameplay metadata. See prop.md.

## Prop and Object Display
Both props and objects have three display slots (specified as properties pointing to image or svg files in their yaml definition):
- `icon` (used in menus and inventories)
- `img` (used in longer description views)
- `sprite` (used for room-stage rendering)

The server now resolves and serves the configured source paths directly; it does not generate resized derivative image files for these slots.

### Room Stage and Foreground Objects
The room background and props are displayed directly on the room canvas, while the object / character sprites are displayed with a subtle background shadow (applied on the client via css) to separate them from the fixed room stage.

### Room Stage Types
A room can have a stage type. The stage type determined how backgrounds / props / sprites are placed on the client room canvas, and it allows the display of different room types. 

Stage type - specific properties are saved in the room yaml definition file together with the rest of a room definition. It is not possible to override stage types or stage properties in the world stage db (rooms table)

The supported room stage types are specified in the following subsections.

#### Basic Room Stage
A Basic room just has a background image, width and height (default to 400x300). The background image is tiled by default but the room definition can choose to stretch it instead. 

Sprites can be placed anywhere on the room stage.

#### Standard Room Stage
A standard room stage has a background and a floor section.

The beckground section has a background image, width and height (default to 400x200). The background image is tiled by default but the room definition can choose to stretch it instead. 

The floor section has a floor image, which is tiled AND stretched to occupy the entire floor space, as explained below.

The floor space height is variable based on the client and 'camera' position, and defaults to 100 pixels. Sprites can be placed on a restriced space over the floor section, to appear like they are displayed in 2.5D, with the y coordinate affecting the sprite 'depth'. The sprite depth also determines the display order of sprites. Sprites can only be dragged / moved so that their center point is within the displayed floor space.

The camera on the client can 'move' by expanding or reducing the floor space. for instance, the nominal 100 pixel high floor space can be squeezed in 10 pixels to give the impression of camera movement up. All sprites should move accordingly when the camera moves. The client UI has three camera setting options (camera 10, camera 100, camera 200) in the extra actions menu that allow testing camera movement.


## Room Update Messages
The room panel in the client is updated when receiving `update_view` messages (see app/client.js socket.on("update_view", ...)). The view parameter of the message determines which part of the room panel is updated:
- 'header' updates the room description / status header
- 'room-stage' updates the room stage view, i.e. the room background / props / prop position and orientations
- 'room-object' updates a single room object, adding it, removing it or updating its display status (position, sprite, sprite effects). When an existing object moves, the move should be applied smoothly.
- 'room-exits' updates the exit list used by the action palette Directions tab.

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
- `stage`: `{ type, width, height, bg_height, floor_height, background_mode, floor_image, bounds, theme }`
  - `type`: `'basic'` or `'standard'` (default: `'basic'`)
  - `width`: canvas width in pixels (default: 400)
  - `height`: total canvas height for basic rooms (default: 300)
  - `bg_height`: background section height for standard rooms (default: 200)
  - `floor_height`: nominal floor section height for standard rooms (default: 100)
  - `background_mode`: `'tile'` or `'stretch'` (default: `'tile'`)
  - `floor_image`: floor image path (empty string if not set)
- `background`: room background image path
- `props`: full prop placement list
- `can_edit_props`

Each prop entry includes:
- identifiers: `prop_instance_id`, `prop_id`
- `position`: `{ x, y, orientation, layer, z_order }`

### `GET /api/props/library`
Returns prop definitions and images separately from room-stage.

Response fields:
- `ok`
- `world_id`
- `props`: list of prop definitions where each entry includes:
  - `prop_id`
  - `label`, `description`
  - `display`: `{ icon, img, sprite }`
  - `metadata`

### `update_view: room-object`
Fields:
- `room_id`
- `change`: `upsert` or `remove`
- `entity`

Entity payload fields:
- identifiers: `entity_type` (`object` or `peep`), `entity_id`, `owner_username` (peeps)
- text: `label`, `description`
- `display`: `{ icon, img, sprite }`
- `position`: `{ x, y, orientation, layer, z_order }`
- `is_self`

### `update_view: room-exits`
Fields:
- `room_id`
- `exits`: array of `{ id, label, target_room_id }`

## Interaction and Authority Events
Room interactions use explicit socket events in `tinyrooms/connection.py`:

- `room_move_entity`:
  - input: `{ entity_type, entity_id, x, y, orientation?, z_order? }`
  - `z_order` is included by the client for Standard-stage rooms and is derived from the entity's y position within the floor section.
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


Fallback resolution:
- `img` is required canonical source.
- `icon` falls back to `sprite`, then `img`.
- `sprite` falls back to `img`, then `icon`.

## Room Ownership and Claiming
Rooms may have an optional owner (`owner_id`). Ownership is stored per-room in the worldstate database.

- **Unclaimed rooms** (no owner): any logged-in user can edit props and claim the room.
- **Claimed rooms**: only the owner can edit props.
- `can_edit_props` and `can_claim_room` flags are sent in the `header` view update on every room entry or ownership change.
- Claiming a room emits `room_claim {}` to the server. The server sets `room.owner_id = username`, persists the change, and broadcasts an updated header to all users in the room.
- After claiming, `can_claim_room` becomes `False` and only the claimant retains `can_edit_props = True`.
- The room editor panel shows a **Claim Room** button and a short explanation when `roomState.canClaimRoom` is `True`.
- Prop library definitions (including prop images) are loaded through REST (`GET /api/props/library`) and kept separate from `room-stage` room layout payloads.
- **Exit prop assignment**: each prop in room-edit mode has a 🚪 button that cycles through available room exits (none → exit1 → exit2 → … → none). An exit badge (`→ label`) is displayed beneath assigned props both in editor mode and normal play.
- `Save Room` from the editor writes the full room prop layout (including `exit_way_id` per prop) to world state storage and all users in the room receive an updated room stage.
- Camera buttons change the floor-height zoom level for standard-stage rooms.
- The exits reference list in the editor panel shows all exits available for assignment.

## Persistence Model
World state persistence is additive and migration-safe in `tinyrooms/db.py`:
- objects table includes transform fields: `x`, `y`, `orientation`, `layer`, `z_order`
- room `props` column stores prop identity + placement only (`prop_instance_id`, `prop_id`, `position`)
- props are defined from YAML (`data/worlds/home/props/props.yaml` and `data/props/*.yaml`) and runtime positions are restored from DB when available

User spawn persistence is handled in `data/users.duckdb`:
- users table stores `last_world_id`, `last_room_id`, `last_x`, `last_y`
- login restores room + position before initial room sync
- invalid saved room ids fall back to `DEFAULT_ROOM`, and the fallback room is persisted back to DB
- user state is persisted on login, room transitions (`.go`), disconnect, and graceful shutdown

## Client Stage Runtime Notes
The room stage in `app/stage.js` is rendered using **PixiJS v8** (canvas/WebGL):
- `app/client.html` loads PixiJS from CDN (`pixi.js@8.17.0`) before the application scripts, making `PIXI` available globally.
- `initPixiApp()` creates a `PIXI.Application` and appends its canvas inside `#roomCanvas`. It is called once on the first `room-stage` event and is a no-op thereafter.
- The PixiJS scene graph has three z-ordered containers: `pixiBgContainer` (background + floor), `pixiPropsContainer` (props, sortable by `z_order`), and `pixiEntitiesContainer` (peeps/objects, sortable by computed depth).
- Textures are loaded via `PIXI.Assets.load()` and cached in `pixiTextureCache`. Sub-textures for spritesheet frames are created via `makeFrameTexture()`.
- Background and floor are rendered as `PIXI.Sprite` (stretch) or `PIXI.TilingSprite` (tile).
- Props are rendered as `PIXI.Sprite` with optional `PIXI.Ticker`-driven frame animation. Editor-mode prop controls (rotate/delete/exit) are rendered as a DOM overlay (`#pixiEditorOverlay`) positioned over the PixiJS canvas.
- Foreground entities use a move tween driven by the PixiJS ticker for smooth 180ms positional interpolation (equivalent to the previous CSS `transition: left 180ms linear`).
- Drag interactions (entity drag, prop drag in editor mode) use PixiJS pointer events (`pointerdown`, `globalpointermove`, `pointerup`) — no HTML5 drag API or separate touch handling needed.
- Click-to-move fires from a `pointertap` listener on `pixiApp.stage`; entity/prop wrappers call `ev.stopPropagation()` to prevent click-through.
- Selection highlight is drawn as a `PIXI.Graphics` outline child of the entity wrapper, toggled via `pixiSetEntitySelected(key, isSelected)`.
- DOM overlays (`#roomTitleOverlay`, `#logPanel`, `#roomExits`) remain as regular HTML elements layered over the canvas via `position:absolute`.
