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
    - activityPanel (visible only when an activity like dialog or container/inventory interaction is engaged; content depends on activity type)
    - roomPanel (contains the room view, description and actions)
        - roomHeader (contains room description, status indicators, and room interaction controls)
        - roomCanvas (the canvas where the room items, users, background and props are displayed; see room.md for more information of how a room is defined/displayed)
        - roomExits (contains the buttons for the exits to the room - these can change for different rooms)
    - actionsPanel (contains the main UI for the user)
        - lookBox (a one line box showing the description of the last selected object/action/etc.)
        - actionPalette (contains the buttons for actions the user can execute. See section on the Action Palette for more information)

## Client Runtime and Event Flow
The current `app/client.js` runtime is event-driven around Socket.IO and uses these key handlers:

- `actions_def`: receives server action definitions and rebuilds the action palette state.
- `update_status`: updates `statusPanel > statusDisplay`.
- `update_view`: routes room updates by `view`:
  - `header` -> `handleHeaderUpdate`
  - `room-stage` -> `handleRoomStageUpdate`
  - `room-object` -> `handleRoomObjectUpdate`
  - `room-exits` -> `handleRoomExitsUpdate`
- `activity_panel`: displays server-provided activity content in `activityPanel`.
- `message`, `error`: append text to `logPanel > messages`.

## The Action Palette
The current palette is a fixed six-slot UI in `actionsPanel > actionPalette`.

### Default main set
1. Look -> emits `.basic.look` (optionally with selected target ref).
2. Use -> emits `.basic.use` (optionally with selected target ref).
3. Emote -> switches to emote subset.
4. Equip -> requests `request_activity_panel` mode `equip`.
5. Self -> requests `request_activity_panel` mode `self`.
6. Extras -> switches to extras subset.

### Emote subset
- Populated from `actions_def` ids with `emotes.` prefix (up to 5 entries).
- Includes a `Back` button to return to main set.

### Extras subset
- Currently placeholder behavior by design.
- Includes a `Back` button to return to main set.

## Selection and lookBox behavior
- Clicking a room entity/prop sets it as selected target.
- `lookBox` shows one-line quick information (`label: description`) for the selected target.
- Action emits append a target ref based on selected target type:
  - object -> `@obj:<id>`
  - peep -> `@<username>`
  - prop -> `@prop:<id>`

## Activity Panel
`activityPanel` is currently fed by dedicated `activity_panel` socket messages.

Implemented modes:
- `look` via action routing
- `equip` via `request_activity_panel`
- `self` via `request_activity_panel`
- `extras` currently local placeholder content

Unspecified activity payload details are intentionally left as TODO placeholders in the server message content.
