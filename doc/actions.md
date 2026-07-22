# User Actions
User actions are interaction commands normal users can perform during normal gameplay. Actions can optionally have one or more target entity (like an object, peep or prop).

Contextual actions are displayed on the tinyrooms client in the action panel. Some actions are invoked implicitly as part of user interaction (for instance, drag/dropping an object from the object panel or room stage to the inventory performs `:pick @obj:<id>` on that object).

On the server, actions are implemented as message handlers on the client websocket connection (see tinyrooms/connection.py).

Some actions have different meanings depending on the target, but they share the same logic and are implemented using a single message handler. On the UI, their appearance (like the icon) may change based on the selected target to reflect the specific meaning of the action.

## Actions Reference
These are the currently implemented actions

For exact command forms (including command powers and target token conventions), see [commands.md](commands.md).

### Look
Icon: 👁️
Description: Look at a target
Implementation Notes: Usually opens an activity panel in the client providing a detailed description of the target. Actual description format depends 
on the target type

### Use/Interact
Icon: 🤚
Description: Use or interact with a target
Implementation Notes: Interactions depend on the target. They may trigger opening a container, starting a dialog with an NPC, toggling a switch etc.


### Pick Up / Drop
Icon: 🫳
Description: Pick up or drop an object to the inventory
Implementation Notes: Implemented by `:pick @obj:<id>` and `:drop @obj:<id> [x y]`.

## Performing actions in the UI
The user action experience is centered in the action palette, room stage interaction, and inventory interaction surfaces.



### Gesture behavior
- Single tap/click on a room object, peep, or prop selects it as the active target.
- Tap/click on an already selected target, performs the `:use` action on it.
- A long tap/right click on a target, performs the ':look' command on it, whose implementation opens an action panel with a long, target description (potentially different style based on the target type).
- Look and Use are explicit actions in the Actions tab and emit `:look` / `:use` for the selected target.
- Stage background tap/click performs movement for the local player (`room_move_entity` flow), not Look/Use.
- Drag/drop is supported for both mouse and touch input (touch-drag threshold: 8px).

### Command/target encoding used by action buttons
- Object or inventory target: `@obj:<obj_id>`
- Peep target: `@<username>`
- Prop target: `@prop:<prop_instance_id>`
- Example emitted payload:
  - `socket.emit("message", { text: ":use @obj:abc123" })`

## Object Actions
This section defines object action behavior in the target experience.

### Inventory-provided custom actions (`inventory_action`)
Thing definitions may provide inventory-specific actions via an `inventory_action` property.

#### `inventory_action` format
- String containing one or more commands, comma-separated.
- `$0` resolves to the selected inventory object reference (`@obj:<selected_obj_id>`).
- Commands are executed left-to-right.

Examples:
- `inventory_action = ":attack $0"`
- `inventory_action = ":consume $0, .actions.eat $0"`

#### UI behavior for inventory actions
- When an inventory object is selected, its `inventory_action` entries are shown in the Actions tab as contextual object actions.
- Built-in actions (`Look`, `Use`, `Drop`, etc.) remain available unless a future spec explicitly defines an override/replacement rule.

## Server action behavior
- `:look` resolves an optional target and returns an `activity_panel` payload (`mode: "look"`).
- `:use` currently provides source-user feedback (`message`) and is the canonical default use implementation.