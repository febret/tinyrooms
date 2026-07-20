# Inventory System

The tinyrooms inventory system lets users pick up objects from the current room and carry them as they move between rooms. Only objects (things placed in the world) can be picked up; peeps (other users' characters) cannot.

## Data Model

### Object location
Every object in the world has a `location_id` field:
- When in a room: `location_id = "@room:<room_id>"`
- When carried by a user: `location_id = "@<username>"`

The `@<username>` convention distinguishes inventory objects from room objects in the worldstate database. The object record is otherwise unchanged — its position coordinates are preserved but ignored while in inventory.

### Peep inventory
Each `Peep` (the in-world representation of a connected user) holds an `inventory` dict:

```
peep.inventory: dict[obj_id → Object]
```

This is populated on login by scanning `world.objs` for any object whose `location_id` matches the user's `@<username>` string.

### Persistence
Inventory state persists across sessions. When `world.save_state()` is called (after pick or drop), the object's updated `location_id` is written to the worldstate database (`objects` table). On next login the object is restored to the user's inventory automatically.

## Server Events

### `room_pick_object` (client → server)
```json
{ "entity_id": "<obj_id>" }
```
- Validates the user is authenticated and in a room.
- Validates the object exists in the current room (`room.objs`).
- Moves the object: `room.objs` → `peep.inventory`; sets `obj.location_id = "@<username>"`.
- Broadcasts a `room-object` remove update to all users in the room.
- Saves world state.
- Emits `inventory_update` to the picking user.
- Broadcasts a chat message to the room: "You pick up X." / "Username picks up X."

### `room_drop_object` (client → server)
```json
{ "obj_id": "<obj_id>", "x": 120, "y": 200 }
```
- `x` and `y` are optional; defaults to the user's current peep position.
- Validates the object is in the user's inventory.
- Moves the object: `peep.inventory` → `room.objs`; sets `obj.location_id = room.id()`.
- Sets the object's `x`, `y`, and a new `z_order` so it appears on top.
- Broadcasts a `room-object` upsert update to all users in the room.
- Saves world state.
- Emits `inventory_update` to the dropping user.
- Broadcasts a chat message: "You drop X." / "Username drops X."

### `inventory_update` (server → client)
Emitted privately to the owning user after every pick, drop, or on login.
```json
{
  "items": [
    {
      "obj_id": "abc123",
      "label": "Old Lantern",
      "description": "A battered tin lantern.",
      "display": { "icon": "/assets/...", "img": "..." }
    }
  ]
}
```
`display` mirrors the object's display assets (icon/img/sprite URLs) for rendering the inventory row icon.

## Client UI

### Inventory panel
The inventory panel lives in `#inventoryPanel > #inventoryList` in the right-hand controls area. It is always visible.

Each row contains:
- An icon (the object's display asset image, if available).
- The object's label and description.
- A **Drop** button that emits `room_drop_object { obj_id }`.

When the inventory is empty the list shows "Empty".

### Picking up from the action palette
When an object entity is the selected target, a **Pick Up** button appears in the main action palette. Clicking it calls `pickUpSelectedObject()`, which emits `room_pick_object { entity_id }` and clears the selection.

### Drag-to-pickup
Dragging an object entity and dropping it on top of the user's own peep (character) on the room canvas also picks it up. This works for both mouse drag and touch drag. The drop target check inspects the element under the pointer at drag end; if that element belongs to the user's own peep entity node, `room_pick_object` is emitted instead of `room_move_entity`.

## Constraints
- Only room objects can be picked up; peeps cannot.
- An object must be in the current room (`room.objs`) to be picked up — objects in another room or in someone else's inventory cannot be targeted.
- Carrying capacity is currently unlimited.
- Objects in inventory are invisible on the room canvas (they receive a `room-object` remove broadcast on pickup) and reappear at the drop position on drop.
