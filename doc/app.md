# Tinyrooms Client Application
The tinyrooms client app lives in the `app` directory. It is served via Flask by the
tinyrooms server.

## UI Logical structure
All UI structure lives in `client.html` and is divided into pages to handle login/game phases of the app.

The client DOM (simplified) is:
- loginPage
- mainPage (contains the main game UI)
    - statusPanel (shows the user status, connection status, and Exit button)
    - logPanel (shows the message log)
    - roomPanel (contains the room view, description and actions)
        - roomHeader (contains room description, status indicators, and room interaction controls)
        - roomCanvas (the canvas where the room items, users, background and props are displayed; see room.md for more information of how a room is defined/displayed)
        - ~~roomExits~~ (replaced by exit props on the canvas; the `#roomExits` div remains in the DOM but is hidden and unused)
    - controlsPanel
        - lookBox (a one line box showing the description of the last selected object/action/etc.)
        - interactionPanel (two-column panel: actionsPanel + inventoryPanel)
            - actionsPanel (contains the action palette and message input)
                - actionPalette (see section below)
            - inventoryPanel
                - inventoryHeader (label "Inventory")
                - inventoryList (shows icon-only inventory items)
                - activityPanel (shows context-dependent activity content when active)

## Client Runtime and Event Flow
The client runtime is split between `app/client.js` (socket and room sync flow) and `app/actionPanel.js` (action palette and inventory interaction logic). It is event-driven around Socket.IO and uses these key handlers:

- `actions_def`: receives server action definitions and rebuilds the action palette state.
- `update_status`: updates `statusPanel > statusDisplay`.
- `update_view`: routes room updates by `view`:
  - `header` -> `handleHeaderUpdate`
  - `room-stage` -> `handleRoomStageUpdate`
  - `room-object` -> `handleRoomObjectUpdate`
  - `room-exits` -> `handleRoomExitsUpdate`
- Prop library loading and room-prop editing/rendering helpers are implemented in `app/prop.js` (`makePropNode`, library fetch/cache, and room editor prop actions).
- `activity_panel`: displays server-provided activity content in `activityPanel`.
- `inventory_update`: updates `inventoryList` with the current inventory contents.
- `message`, `error`: append text to `logPanel > messages`.

## The Action Palette
The palette is a dynamic tabbed control in `actionsPanel > actionPalette`. Tabs are compact emoji buttons in a vertical strip on the left.
Command syntax details referenced below are centralized in [commands.md](commands.md).

### Tabs
- 🤚 **Actions**
  1. Look -> emits `:look` (optionally with selected target ref).
  2. Use -> emits `:use` (optionally with selected target ref).
  3. Drop -> emits `:drop @obj:<id>` (with optional x/y when dropped on canvas).
  4. Equip -> emits `:equip`.
  5. Self -> emits `:self`.
  6. Pick Up -> appears only when an object is the selected target; emits `:pick @obj:<id>`.
  7. Go: [label] -> appears only when a prop with an `exit_way_id` is the selected target; emits `:go @way:<id>`.
  8. Inventory custom actions -> appear for selected inventory items from `inventory_action` metadata and emit one or more commands via `message`.
- 🧭 **Directions**
  - Populated from current room exits (`update_view: room-exits`), so buttons change with the room.
- 📦 **Objects**
  - Populated from current room objects (`roomState.entities` filtered by `entity_type: object`).
  - Uses thumbnail-style icon buttons; clicking selects the object as the active target for Actions (Look/Use/Pick Up/etc.).
- 🧑 **Peeps**
  - Populated from current room peeps (`roomState.entities` filtered by `entity_type: peep`).
  - Uses thumbnail-style icon buttons; clicking selects the peep as the active target for Actions.
- 😀 **Emotes**
  - Populated from known emotes (excluding `say`).
- 🧰 **Tools**
  - Includes all former Extras actions and app-level tools.
  - `Create Thing` opens a popup that lets the user pick a sprite and optionally generate an image, then creates a new room object.
  - Sprites are listed from the server/world sprite definitions (`GET /api/object-editor/profile`).
  - An image can be generated on demand (`POST /api/object-editor/image`).
  - The user must provide a description and either select a sprite or generate an image.
  - Submitting (`POST /api/object-editor/create`) spawns a new room object in the user's current room and broadcasts it to all users.
  - Created objects' thing definitions are persisted in `data/things/generated.yaml`.
  - `Edit Room` enters room-edit mode. Anyone can enter edit mode for unclaimed rooms; only the owner can edit claimed rooms. Foreground objects/characters are hidden locally, room props are outlined with inline rotate/delete/exit-assign controls, and a prop library is shown for adding new props.
  - `Modify Character` opens Character Editor.
  - `World Editor` opens the world editor app when available.

See [room.md](room.md) for room ownership and claiming, exit props, and character movement and selection.

See [inventory.md](inventory.md) for the full inventory system specification.

## Activity Panel
`activityPanel` is currently fed by dedicated `activity_panel` socket messages.

Implemented modes:
- `look` via `:look` command routing
- `equip` via `:equip`
- `self` via `:self`
