# Tinyrooms World Specification

A **world** in tinyrooms is the top-level container for all rooms, ways (exits), props, and things that users interact with. A world is identified by a world-state ID (e.g. `home`) and is loaded from a YAML definition directory, with dynamic runtime state (object positions, prop layouts, room overrides) persisted separately in a SQLite world-state database.

## World Definitions and State

### World Root Directory

A world lives under `data/worlds/<world_id>/`. The root directory contains:

- `world.yaml` — top-level world metadata (name, description, and other world-level settings).
- `rooms/` — one or more YAML files containing room and way definitions.
- `things/` — one or more YAML files containing thing (object template) definitions.
- `props/` — world-scoped prop sets (each set is a `.yaml` definition + matching image file).

Server-level shared prop sets also live under `data/props/` and are available to all worlds.

### Room Definitions

Rooms and ways are defined in YAML files under the `rooms/` directory. Any number of `.yaml` files may be used; all are merged at load time. Each top-level key is a room or way ID.

**Room entry**:

```yaml
room_id:
  type: room
  label: "The Playroom"
  description: "A cozy room with colourful toys."
  image: playroom.png          # background image filename (relative to the world root)
  owner_id: alice              # optional; locks prop-editing to this user
  stage:
    type: basic                # "basic" or "standard" (default: basic)
    width: 400                 # canvas width in pixels
    height: 300                # canvas height (basic rooms only)
    bg_height: 200             # background section height (standard rooms only)
    floor_height: 100          # nominal floor section height (standard rooms only)
    background_mode: stretch   # "tile" or "stretch" (default: tile)
    floor_image: grass.png     # floor tile image (standard rooms only)
    theme: home                # optional theme tag
  ways: [way_id_1, way_id_2]  # single string or list; references way entries below
  props:                       # optional static prop list (overridden by world-state DB once room is saved)
    - prop: "#chipset1/table"
      x: 80
      y: 120
      orientation: front
      layer: 0
```

**Way entry** (an exit connecting two rooms):

```yaml
way_id:
  type: way
  label: "through the garden gate 🌿"
  to: target_room_id
```

Ways are referenced by name from the `ways` field of rooms. A way is directional — to create a two-way passage, define two separate way entries (one in each direction).

### Thing Definitions

Things are object templates defined under `things/`. Any object placed in a room is an **instance** of a thing. Thing definitions carry display assets (`icon`, `img`, `sprite`), label, and description. See the things YAML files for the schema.

### Prop Definitions

Props are semi-static room decorations defined as prop sets (see `prop.md`). Each prop set is a YAML + image pair. Props can be placed in rooms via the world editor or room editor and are stored in the world-state database once a room is saved.

### World-State Database

Runtime state that diverges from the YAML definitions is persisted in a SQLite database (`data/worldstate/<ws_id>.db`):

- **Rooms table**: stores `label_override`, `description_override`, and the full serialised prop list (identity + placement) for each room that has been saved at least once.
- **Objects table**: stores the current location, position (`x`, `y`, `orientation`, `layer`, `z_order`), and optional label/description overrides for every object instance.

When the world is loaded, YAML definitions are read first and then world-state data is overlaid on top. Rooms that have never been saved retain their YAML-defined initial props and things.

---

## World Editor UI

The world editor is a web-based world / room editing utility available in the tinyrooms client and server. It is enabled if the server is launched with argument `--feature world-editor`. It is accessible at `<server url>/world-editor`.

### Overall Layout

The editor is divided into four main areas:

```
+------------------+------------------------------------+------------------+
|                  |  Top Toolbar                       |                  |
|  Room List       +---------+----------+---------------+  Properties      |
|  Panel           |         |          |               |  Panel           |
|  (left sidebar)  |  Room   |  World   |  (future)     |  (right sidebar) |
|                  |  Canvas |  Map     |               |                  |
|                  |         |          |               |                  |
|                  |         |          |               |                  |
+------------------+---------+----------+---------------+------------------+
|  Prop Library Panel  (collapsible bottom drawer)                         |
+--------------------------------------------------------------------------+
```

- **Top Toolbar** — global actions, active-tool selector, and save/undo controls.
- **Room List Panel** — lists all rooms and ways; click to open a room in the canvas.
- **Room Canvas** — the main editing area; shows the selected room with background, props, and exit badges.
- **World Map Tab** — a node-graph view of all rooms and their connections; click nodes to navigate to a room.
- **Properties Panel** — context-sensitive right sidebar; shows room properties when nothing is selected, prop properties when a prop is selected, and way properties when a way is selected.
- **Prop Library Panel** — collapsible drawer at the bottom; shows all available props organised by prop set for drag-and-drop placement.

### Top Toolbar

The toolbar spans the full width and contains (left to right):

| Control | Description |
|---|---|
| **World Editor** title/logo | Links back to the main tinyrooms client. |
| `Room` / `World Map` tab selector | Switches the central pane between the Room Canvas and the World Map. |
| ─── | Separator |
| **Tool selector** (icon buttons) | `Select` (arrow), `Place Prop` (stamp), `Draw Exit` (→). Only relevant when the Room Canvas is active. |
| ─── | Separator |
| **Undo** / **Redo** buttons | Step through the local edit history for the current room. |
| ─── | Separator |
| **Save Room** button | Persists the current room's prop layout and metadata overrides to the world-state database and immediately refreshes all connected clients in that room. |
| **Save All** button | Saves every room that has unsaved changes. Rooms with pending changes are shown with a dot indicator in the Room List. |
| **Reset Room** button | Discards unsaved changes for the current room and reloads from the world-state database (or YAML defaults if the room has never been saved). |

### Room List Panel

The left sidebar lists every room and way defined in the world.

- Rooms are shown with their label and a small thumbnail of their background image.
- Ways are shown indented under the room that references them, with an arrow icon and the target room label.
- A search/filter field at the top filters the list by ID or label.
- Clicking a room opens it in the Room Canvas and loads its properties into the Properties Panel.
- Clicking a way opens its properties in the Properties Panel without changing the canvas view.
- A **＋ New Room** button at the bottom opens a dialog to create a new room (see [Creating a New Room](#creating-a-new-room)).
- A **＋ New Way** button opens a dialog to create a new way (see [Creating a New Way--Exit](#creating-a-new-way--exit)).
- Right-clicking a room or way shows a context menu with **Rename**, **Duplicate**, and **Delete** options.

### Room Canvas

The canvas displays the selected room as it appears to users, with the background image and all placed props rendered at their correct positions. The canvas is the primary editing surface.

#### Canvas Controls

- **Pan**: middle-mouse-drag or Space + drag to pan the canvas view. A reset-view button (⊡) in the canvas corner restores the default fit-to-window view.
- **Zoom**: mouse wheel or pinch-to-zoom. A zoom level indicator is shown; click it to reset to 100 %.
- **Grid overlay**: a toggle button (⊞) in the canvas corner shows/hides a pixel grid aligned to 8 px increments.
- **Stage outline**: the room canvas boundary is always shown with a thin border so the usable area is clear.

For **Standard** stage rooms, the canvas shows both the background section and the floor section, with a visible dividing line. The floor section is shaded differently to indicate the zone where peeps can walk. A camera-level slider on the canvas edge lets the designer preview how the room looks at different floor-height zoom values (e.g. camera 10, 100, 200) without affecting the saved definition.

#### Select Tool

This is the default tool. In Select mode:

- Click an empty spot on the canvas to deselect any selection.
- Click a prop to select it. The selected prop is highlighted with a resize/move handle overlay.
- Drag a selected prop to reposition it. The position snaps to the grid when the grid is visible; hold **Alt** to suppress snapping for pixel-precise placement.
- Arrow keys nudge the selected prop by 1 px; Shift + arrow nudges by 8 px.
- **Delete** or **Backspace** removes the selected prop from the room (with undo support).
- Right-clicking a prop opens a context menu with: **Flip Horizontal**, **Rotate 90°**, **Send Backward**, **Bring Forward**, **Send to Back**, **Bring to Front**, **Assign Exit…**, **Remove Prop**.

#### Place Prop Tool

Activated from the toolbar or by pressing **P**. While active:

- The cursor changes to a crosshair with the selected prop thumbnail attached.
- The prop to place is chosen in the Prop Library Panel (see below). The last selected prop from the library persists until a different one is chosen.
- Click anywhere on the canvas to place an instance of the selected prop at that position.
- The placed prop is immediately selected (switches back to Select tool semantics) so it can be fine-tuned without manually switching tools.
- Press **Escape** to cancel placement and return to the Select tool.

#### Draw Exit Tool

Activated from the toolbar or by pressing **E**. Allows assigning an exit way to a prop without opening the Properties Panel:

- Click a prop on the canvas to open an inline exit picker (a small floating dropdown listing all ways in the room plus a "— none —" option).
- Selecting a way from the picker assigns it as that prop's exit and shows the exit badge immediately.
- Click away from the picker or press **Escape** to dismiss without changing the assignment.

### Properties Panel

The right sidebar is context-sensitive and changes based on the current selection.

#### Room Properties (no prop selected)

Shown when a room is open in the canvas but no prop is selected. Fields:

| Field | Control | Notes |
|---|---|---|
| Room ID | Read-only text | The unique identifier used in YAML. Not editable after creation. |
| Label | Text input | Display name shown to users. |
| Description | Textarea | Short narrative description shown in the room header. |
| Owner | Text input | Optional username. Leave empty for an unclaimed room. |
| Background Image | Dropdown + preview | Lists all image files available in the world root and subdirectories. Selecting one updates the canvas preview immediately. A **Upload…** button allows adding a new image file. |

#### Stage Settings (sub-section of Room Properties)

A collapsible sub-section below the room fields:

| Field | Control | Notes |
|---|---|---|
| Stage Type | Dropdown (`basic` / `standard`) | Changing the type shows/hides type-specific fields and redraws the canvas. |
| Width | Number input (px) | Canvas width. |
| Height | Number input (px) | Total canvas height (basic rooms only). |
| Background Height | Number input (px) | Background section height (standard rooms only). |
| Floor Height | Number input (px) | Nominal floor section height (standard rooms only). |
| Background Mode | Radio buttons (`tile` / `stretch`) | How the background image is displayed. |
| Floor Image | Dropdown + preview | Floor tile image (standard rooms only). Same source list as Background Image. |
| Theme | Text input | Optional theme tag (e.g. `home`). |

#### Prop Properties (prop selected)

Shown when a prop is selected in the canvas:

| Field | Control | Notes |
|---|---|---|
| Prop | Read-only label + thumbnail | Shows the prop ID and a small preview frame from the prop set. |
| X | Number input (px) | Horizontal position of the prop's top-left corner on the canvas. Editing this field moves the prop on the canvas. |
| Y | Number input (px) | Vertical position. |
| Orientation | Dropdown (`front` / `back` / `left` / `right`) | Visual facing direction. The canvas updates immediately. |
| Layer | Number input | Rendering layer (higher = in front of lower-layer props). |
| Z-order | Number input | Fine-grained draw order within the same layer. **Bring Forward** / **Send Backward** buttons increment/decrement this field. |
| Exit | Dropdown | `— none —` or any way ID available in this room. Selecting a way assigns the prop as an exit trigger and shows the exit badge on the canvas. |

A **Remove Prop** button at the bottom of this section deletes the selected prop from the room.

#### Way Properties (way selected from Room List)

Shown when a way entry is selected:

| Field | Control | Notes |
|---|---|---|
| Way ID | Read-only text | Unique identifier for the way. |
| Label | Text input | Exit label shown to users (e.g. `"to the garden 🌿"`). |
| Target Room | Dropdown | Lists all rooms in the world. Selecting a room updates the `to` field. An arrow button (→) navigates to the target room in the canvas. |
| Referenced By | Read-only list | Shows which rooms include this way in their `ways` list. |

A **Delete Way** button removes the way. If the way is still referenced by rooms, a warning lists the affected rooms and asks for confirmation.

### Prop Library Panel

A collapsible drawer at the bottom of the editor, toggled with a **Props ▲/▼** button or by pressing **L**.

- Prop sets are shown as tabs across the top of the panel; each tab is labelled with the set's `label` (or filename if no label). Server-scope sets are marked `[S]`, world-scope sets are marked `[W]`.
- Inside each tab, individual props are shown as a grid of thumbnails (the first frame of each prop, rendered at 64 × 64 with the set's `background_color` or a checkerboard for transparent props).
- Hovering a thumbnail shows a tooltip with the prop's `prop_id`, dimensions, and whether it is animated.
- Clicking a thumbnail selects it for placement: the toolbar automatically switches to the **Place Prop** tool and the cursor shows the selected prop thumbnail attached to it.
- A search input at the top-left of the panel filters props by ID across all sets.

### World Map

The **World Map** tab in the central pane shows all rooms as rectangular nodes and all ways as directed edges between them. This gives an overview of the world's connection graph and is useful for planning navigation.

- Each room node shows the room label and a small background thumbnail.
- Way edges are labelled with the way's label text. One-way connections are shown with a single arrowhead; if a reverse way also exists, the edge is shown as bidirectional.
- Nodes can be dragged to rearrange the layout (layout is stored in the browser session only and does not affect YAML files).
- Clicking a room node opens that room in the Room Canvas (switches to the Room tab).
- Clicking a way edge selects the way and shows its properties in the Properties Panel.
- A **＋ New Room** button in the map toolbar opens the new-room dialog and positions the new node near the cursor.
- A **＋ Connect** button activates a "draw connection" mode: click a source room, then a target room to create a new way between them (opens the new-way dialog pre-filled with the source and target).

### Creating a New Room

Triggered by the **＋ New Room** button in the Room List or World Map. A modal dialog collects:

1. **Room ID** — a unique snake_case identifier. The dialog validates uniqueness and character restrictions as the user types.
2. **Label** — display name.
3. **Stage Type** — `basic` or `standard`, with a brief description of each.
4. **Copy From** (optional) — a dropdown to clone all settings from an existing room as a starting point.

Clicking **Create** adds the room to the in-memory definition, opens it in the canvas, and marks the world as having unsaved changes. The room is not written to any YAML file automatically — it is saved to the world-state database when **Save Room** is clicked.

### Creating a New Way / Exit

Triggered by the **＋ New Way** button or by right-clicking a room in the World Map. A modal dialog collects:

1. **Way ID** — a unique snake_case identifier (auto-suggested as `to_<target_room_id>`).
2. **Label** — the exit label shown to users, including any emoji.
3. **From Room** — the room that will have this way in its `ways` list (pre-filled with the current room).
4. **To Room** — the target room from a dropdown of all rooms.
5. **Also create reverse way** — a checkbox (default on) that creates a matching way back from the target room to the source room, with a suggested reverse label.

Clicking **Create** adds the way entry, updates the `ways` list of the source room (and optionally the target room), and redraws the World Map and canvas exit badges.

### Editing Workflow Summary

#### Placing Props in a Room

1. Open a room from the Room List.
2. Expand the Prop Library Panel and select a prop set tab.
3. Click the desired prop thumbnail — the toolbar switches to Place Prop mode.
4. Click on the canvas at the desired position to drop the prop.
5. With the prop still selected, fine-tune position (drag or X/Y fields), orientation, and layer in the Properties Panel.
6. To assign an exit: select the prop and choose a way from the **Exit** dropdown in the Properties Panel, or use the Draw Exit tool for rapid bulk assignment.
7. Click **Save Room** when satisfied.

#### Setting Up a Room's Stage

1. Open the room, ensure nothing is selected.
2. In the Properties Panel, set the **Label**, **Description**, and **Owner** as needed.
3. Under Stage Settings, choose the **Stage Type**. The canvas redraws to show the correct layout.
4. For `standard` rooms, set **Background Height** and **Floor Height**, and pick a **Floor Image**.
5. Choose a **Background Image** and **Background Mode**.
6. Click **Save Room**.

#### Creating a New Room with Exits

1. Click **＋ New Room**, fill in the ID and label, click **Create**.
2. Configure the stage and background in the Properties Panel.
3. Click **＋ New Way** to add an exit to an existing room. Check **Also create reverse way** if the passage should be two-way.
4. In the Room Canvas, place a prop to act as the visible exit marker. Select the prop and assign the new way to it via the **Exit** dropdown.
5. Click **Save Room** (or **Save All** to save both rooms at once).

### Keyboard Shortcuts

| Key | Action |
|---|---|
| `S` | Select tool |
| `P` | Place Prop tool |
| `E` | Draw Exit tool |
| `L` | Toggle Prop Library Panel |
| `G` | Toggle grid overlay |
| `Del` / `Backspace` | Remove selected prop |
| `Ctrl+Z` | Undo |
| `Ctrl+Shift+Z` / `Ctrl+Y` | Redo |
| `Ctrl+S` | Save current room |
| Arrow keys | Nudge selected prop 1 px |
| `Shift` + arrow | Nudge selected prop 8 px |
| `Escape` | Cancel current tool / deselect |
| `F` | Fit canvas to window |

