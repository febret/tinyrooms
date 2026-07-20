# Tinyrooms Client Application
The tinyrooms client app lives in the `app` directory. It is served via Flask by the
tinyrooms server.

## UI Logical structure
All UI structure lives in `client.html` and is divided into pages to handle login/game phases of the app.

The client DOM (simplified) is:
- loginPage
- mainPage (contains the main game UI)
    - statusPanel (shows the user status, connection status and buttons to control the overall game)
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
                - inventoryList (shows items currently in the user's inventory; each row has an icon, label, and Drop button)
                - activityPanel (shows context-dependent activity content when active)

## Client Runtime and Event Flow
The current `app/client.js` runtime is event-driven around Socket.IO and uses these key handlers:

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
The palette is a dynamic button grid in `actionsPanel > actionPalette`.

### Default main set
1. Look -> emits `.basic.look` (optionally with selected target ref).
2. Use -> emits `.basic.use` (optionally with selected target ref).
3. Pick Up -> appears only when an object is the selected target; emits `room_pick_object` to the server.
4. Go: [label] -> appears only when a prop with an `exit_way_id` is the selected target; calls `navigateExit(wayId)` to leave via that exit.
5. Emote -> switches to emote subset.
6. Equip -> requests `request_activity_panel` mode `equip`.
7. Self -> requests `request_activity_panel` mode `self`.
8. Extras -> switches to extras subset.

### Emote subset
- Populated from `actions_def` ids with `emotes.` prefix (up to 5 entries).
- Includes a `Back` button to return to main set.

### Extras subset
- `Create Thing` opens a popup that lets the user pick a sprite and optionally generate an image, then creates a new room object.
  - Sprites are listed from the server/world sprite definitions (`GET /api/object-editor/profile`).
  - An image can be generated on demand (`POST /api/object-editor/image`).
  - The user must provide a description and either select a sprite or generate an image.
  - Submitting (`POST /api/object-editor/create`) spawns a new room object in the user's current room and broadcasts it to all users.
  - Created objects' thing definitions are persisted in `data/things/generated.yaml`.
- `Edit Room` enters room-edit mode. Anyone can enter edit mode for unclaimed rooms; only the owner can edit claimed rooms. Foreground objects/characters are hidden locally, room props are outlined with inline rotate/delete/exit-assign controls, and a prop library is shown for adding new props.

See [room.md](room.md) for room ownership and claiming, exit props, and character movement and selection.

See [inventory.md](inventory.md) for the full inventory system specification.

## Activity Panel
`activityPanel` is currently fed by dedicated `activity_panel` socket messages.

Implemented modes:
- `look` via action routing
- `equip` via `request_activity_panel`
- `self` via `request_activity_panel`

Unspecified activity payload details are intentionally left as TODO placeholders in the server message content.

