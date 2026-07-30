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

---

## Object / Peep Actions

Object / Peep Actions allow room objects and NPC peeps to expose named, custom actions that are displayed in the tinyrooms action panel when the entity is selected. Examples include a `pet` action on an NPC cat, or a `write` action on a signpost. Custom action behavior is not hardcoded on the server — it is implemented through the behavior script system, keeping the server generic and content-agnostic.

### Action Definition

Custom actions are declared in the entity's definition YAML using an `actions` list. Both thing (object) definitions and peep class definitions support this field.

#### Format

Each entry in the `actions` list is an object with the following fields:

| Field   | Required | Description |
|---------|----------|-------------|
| `id`    | yes      | Unique action identifier within this entity (used in the command and behavior handler). Snake_case recommended. |
| `label` | yes      | Human-readable label shown in the action panel button. |
| `icon`  | no       | Emoji or icon string displayed on the action panel button. Falls back to a generic action icon if omitted. |

#### Example — Peep class (`data/peeps/npcs.yaml`)

```yaml
cat_npc:
  label: "Whiskers"
  description: "A friendly tabby cat."
  img: images/cat.png
  behavior: cat_behavior
  actions:
    - id: pet
      label: "Pet"
      icon: "🐾"
    - id: feed
      label: "Feed"
      icon: "🐟"
```

#### Example — Thing definition (object)

```yaml
signpost:
  label: "Signpost"
  description: "A wooden signpost you can write on."
  img: images/signpost.png
  behavior: signpost_behavior
  actions:
    - id: write
      label: "Write"
      icon: "✏️"
    - id: read
      label: "Read"
      icon: "📖"
```

### UI Behavior

- When a room object or NPC peep is selected as the active target, the client reads the `actions` list from the entity's serialized payload.
- Each custom action is rendered as a button in the action panel, alongside the built-in actions (`Look`, `Use`, `Pick Up`, etc.).
- Selecting a custom action button emits a `:action` command for that entity (see [Command Protocol](#command-protocol) below).
- Built-in actions remain available unless a future spec defines override or suppression rules.
- Custom actions are **not** shown in the inventory panel — they only appear when selecting a room-stage entity (object or peep). Inventory-specific customization continues to use `inventory_action` (see above).

### Command Protocol

Custom actions are dispatched via the `:action` command:

```
:action <action_id> <target>
```

Target formats follow the existing conventions:

| Target type   | Format                    |
|---------------|---------------------------|
| Room object   | `@obj:<obj_id>`           |
| NPC peep      | `@peep:<peep_id>`         |

Examples:
```
:action pet @peep:whiskers_cat
:action write @obj:abc123
```

The client emits these as standard message payloads:
```js
socket.emit("message", { text: ":action pet @peep:whiskers_cat" })
```

The `:action` command is handled by `commands.py` and routed to the entity's behavior system. If the target entity has no behavior, or the behavior does not implement `on_action`, the server sends a generic feedback message to the acting user (e.g., `"Nothing happens."`).

### Behavior Handler

Both peep behaviors and object behaviors (see [Object Behavior System](#object-behavior-system) below) handle custom actions via the `on_action` handler function:

```python
def on_action(src, action_id):
    ...
```

| Parameter   | Description |
|-------------|-------------|
| `src`       | The `User` object that triggered the action. |
| `action_id` | The `id` string of the triggered action, as declared in the `actions` list. |

A single `on_action` handler receives all custom actions for that entity. The behavior script is responsible for branching on `action_id`:

```python
# cat_behavior.py

def on_action(src, action_id):
    src_label = getattr(src, 'username', str(src))
    if action_id == 'pet':
        emote('purrs contentedly')
        say(src_label, "Purrr... thank you!")
    elif action_id == 'feed':
        say(src_label, "Nom nom nom!")
        show('eat')
    # Unknown action_ids are silently ignored
```

```python
# signpost_behavior.py

def on_action(src, action_id):
    if action_id == 'read':
        # The server sends the sign text back to the acting user only
        say(f"The sign reads: {sign_text}")
    elif action_id == 'write':
        # Prompt the user for text — a follow-up dialog interaction
        say(getattr(src, 'username', ''), "What would you like to write?")
```

All behavior utility functions available to `on_tick` and `on_message` are also available to `on_action` (see [peep.md](peep.md) for the full list).

### Object Behavior System

Objects (things) do not currently have a behavior system. This section specifies its addition, modeled directly on the existing peep behavior system.

#### Enabling behavior on a thing

A thing definition may include a `behavior` field referencing a Python behavior script by file stem:

```yaml
signpost:
  label: "Signpost"
  description: "A wooden signpost."
  img: images/signpost.png
  behavior: signpost_behavior
  actions:
    - id: write
      label: "Write"
      icon: "✏️"
```

Behavior scripts are loaded from the same directory as the thing definition YAML, using the same compile-and-exec mechanism as peep behaviors (`peep_behavior.load_behavior`). A new `object_behavior.py` module (parallel to `peep_behavior.py`) manages object behavior namespaces.

#### Object behavior handler functions

The following handler is defined for object behaviors in this spec. Additional handlers may be added in future specs.

| Handler | Signature | Description |
|---------|-----------|-------------|
| `on_action` | `on_action(src, action_id)` | Called when a user triggers a named custom action on this object. |

#### Object behavior utility functions

Object behavior scripts have access to a context-bound set of utility functions similar to peep behaviors. The available functions are:

| Function | Description |
|----------|-------------|
| `say([target], txt)` | Send a chat message to the room, optionally directed at a target. |
| `emote([target], action, [text])` | Emit an emote action in the room. |
| `get_users()` | Returns list of `User` objects in the object's current room. |
| `get_peeps()` | Returns list of `Peep` objects in the object's current room. |
| `get_objects()` | Returns list of `Object` instances in the object's current room. |
| `obj` | The `Object` instance itself (for reading `obj.obj_id`, `obj.x`, `obj.y`, etc.). |

Standard Python builtins (`abs`, `all`, `any`, `bool`, `dict`, `enumerate`, `float`, `getattr`, `hasattr`, `int`, `isinstance`, `iter`, `len`, `list`, `max`, `min`, `next`, `print`, `range`, `round`, `set`, `sorted`, `str`, `sum`, `tuple`, `zip`) and the `random` and `math` modules are available, identical to peep behavior scripts.

Per-instance global variables work the same as in peep behaviors: each object instance has its own isolated copy of the behavior namespace, and state is not persisted across server restarts.

### Entity Payload Changes

To support client-side rendering of custom actions, the `_serialize_foreground_entity` method in `room.py` must include the entity's action definitions in the serialized payload. The client reads this list when an entity is selected to populate the action panel.

The following field is added to the `update_view` / `room-object` payload:

```json
{
  "entity_type": "object",
  "entity_id": "abc123",
  "label": "Signpost",
  "actions": [
    { "id": "write", "label": "Write", "icon": "✏️" },
    { "id": "read",  "label": "Read",  "icon": "📖" }
  ]
}
```

- `actions` is always present on entity payloads. It is an empty list `[]` when the entity has no custom actions.
- For objects, actions are sourced from the thing definition. For NPC peeps, actions are sourced from the peep class definition. User peeps always have an empty `actions` list.
- The `icon` field is optional in the YAML; if absent, the serialized entry omits `icon` and the client falls back to a default.