# Tinyrooms Peep Specification
Peeps are the tinyroom implementation of NPCs. They are displayed as character sprites and can interact with other users, peeps and the environment through behaviors and behavior scripts.

Peeps are used to implement all types of non-player characters, from simple creatures to merchants, quest givers, dialog characters and fully AI-controlled bots.

## Peep Definition

A Peep **class** (template) has the following properties:

| Field         | Required | Description |
|---------------|----------|-------------|
| `label`       | yes      | Display name of the peep |
| `description` | yes      | Text description of the peep |
| `img`         | yes      | Image path or sprite reference for the peep's display asset |
| `sprite`      | no       | Sprite sheet reference (overrides `img` for sprite-based animation) |
| `behavior`    | no       | File stem of the `.py` behavior script in the same directory |

A Peep **instance** (active in the world) has the following properties:

| Field         | Required | Description |
|---------------|----------|-------------|
| `peep_id`     | yes      | Unique identifier for this instance |
| `class`       | yes      | Class id referencing a peep class definition |
| `x`           | yes      | Initial horizontal position in the room |
| `y`           | yes      | Initial vertical position in the room |
| `label`       | no       | Override the class label for this specific instance |
| `description` | no       | Override the class description for this specific instance |

Peep classes live in yaml files in the `data/peeps` server directory and world `peeps` directory. Note the difference between a peep CLASS (ie a template for a peep including the behavior it will use), and a peep INSTANCE (ie an active instance in the world of a peep from a specific class, see tinyrooms/peep.py)

Peep classes are defined exclusively in yaml files. Peep instances can be added to rooms in world yaml files using a `peeps` array, but they are also serialized in the world state DB in their own `peeps` table (similar to the `objects` table)

### Example peep class YAML (`data/peeps/npcs.yaml`):

```yaml
shopkeeper:
  label: "Sam the Shopkeeper"
  description: "A friendly merchant who sells adventuring supplies."
  img: images/shopkeeper.png
  behavior: shopkeeper_behavior
```

### Example room YAML with NPC peeps:

```yaml
market_square:
  type: room
  label: "Market Square"
  description: "A busy marketplace."
  image: images/market.png
  peeps:
    - peep_id: sam_shopkeeper
      class: shopkeeper
      x: 120
      y: 80
    - peep_id: guard_captain
      class: guard
      x: 300
      y: 150
      label: "Captain Elena"
      description: "The leader of the town guard."
```

## Peep Behavior
Peep behaviors are implemented as python scripts placed in the same directory as the peep class yaml files. Each file contains a single behavior definition. Behaviors are referenced in a peep definition simply by the file name (without extension).

A behavior script cannot import any other python module, and it contains one or more handler functions that are triggered on different conditions and interactions with the peep.

### Behavior handler functions:
- `on_tick(secs_from_last)`: called on all peeps that have it implemented at a regular interval (default 1 second, configurable via `--tick-secs` on the server). Used to run regular behavior updates, random movement/chat, bot logic etc.
- `on_message(src, text)`: called when a user or other peep sends a chat message / emote addressed to this peep (directed say or emote that references the peep). `src` is the source entity (user or other peep).


### Behavior handler utility functions:

Behavior handlers can use these utility functions and objects (available in the evaluation context of the handler call):

- `say([target], txt)` — send a chat message to the room, optionally directed at a target
- `emote([target], action, [text])` — emit an emote action, optionally directed at a target
- `get_users()` — returns list of User objects in the peep's current room
- `get_peeps()` — returns list of Peep objects in the peep's current room
- `get_objects()` — returns list of Object instances in the peep's current room
- `get_props()` — returns list of Prop instances in the peep's current room
- `get_ways()` — returns list of Way objects (exits) in the peep's current room
- `move(x, y)` — move the peep's sprite to the given position in the room
- `go_to(way)` — move the peep through the specified way to another room (accepts way id string or Way object)
- `look(entity)` — returns `{"label": ..., "description": ...}` dict for the specified entity
- `set_sprite(sprite_string)` — change the display sprite for this peep and broadcast the update
- `show(animation_id[, frame])` — show the specific animation for the sprite; if `frame` is specified, display that frame with animation disabled
- `peep` — the Peep instance itself (for reading `peep.x`, `peep.y`, `peep.peep_id`, etc.)

Standard Python builtins available: `abs`, `all`, `any`, `bool`, `dict`, `enumerate`, `float`, `getattr`, `hasattr`, `int`, `isinstance`, `iter`, `len`, `list`, `max`, `min`, `next`, `print`, `range`, `round`, `set`, `sorted`, `str`, `sum`, `tuple`, `zip`. The `random` and `math` modules are also available.

### Per-instance global variables:

Behavior script global variables are unique for each behavior instance. For example a global variable `state` in a script can be used to represent the state of each peep using this behavior, with each peep having its own copy of the global. Per-instance state is **not** persisted across server restarts.

### Example behavior script:

```python
# shopkeeper_behavior.py

greeting_count = 0

def on_tick(secs):
    global greeting_count
    # Could implement random movement, idle animations, etc.
    pass

def on_message(src, text):
    global greeting_count
    src_label = getattr(src, 'username', getattr(src, 'peep_id', str(src)))
    text_lower = str(text).lower()
    if 'hello' in text_lower or 'hi' in text_lower:
        greeting_count += 1
        say(f"Welcome, {src_label}! I've greeted {greeting_count} adventurers today.")
    elif 'buy' in text_lower or 'shop' in text_lower:
        say("Take a look at my wares! Unfortunately the shop is still under construction.")
    else:
        say(f"Hmm, I don't understand '{text}'. Try saying hello!")
```

## Server Configuration

The NPC tick rate is configurable via the `--tick-secs` argument on `trserver.py`:

```
python trserver.py --feature world-server --tick-secs 2.0
```

The tick loop runs automatically whenever `world-server` feature is active.