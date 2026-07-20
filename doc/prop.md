# Prop definition
Props are semi-static objects that can be added to a tinyrooms room and can only be modified by the room owner.
A prop is made of one or more images, and is optionally animated.

## Referencing Props
A prop can be referenced using a string in the format `#<filename>/<propId>[/<frameNum>][.x<x>][.y<y>][.r<deg>]` where
- `filename` is the stem of the prop set YAML file (without extension)
- `propId` is the id of the prop inside the file
- `frameNum` is the optional 0-based frame index to display (defaults to frame 0)
- `.x<n>`, `.y<n>` apply pixel offsets to the rendered position
- `.r<deg>` applies a rotation in degrees

Examples:
- `#floor_rug/floor_rug` – first frame of the floor_rug prop in the floor_rug set
- `#animated_tiles/coin/2.x10.y5` – third frame, offset 10px right and 5px down
- `#wall_clock/wall_clock.r90` – wall clock rotated 90 degrees

## Prop Loading and Definition
Props are loaded from two sources, with world-scope taking precedence on filename conflicts:
- `data/props/` — server-level shared props
- `<world_root>/props/` — world-specific props

Each prop set consists of:
- A YAML definition file (e.g., `floor_rug.yaml`)
- An image file in the **same directory** as the YAML (referenced by the `image` field)

### YAML Schema

```yaml
label: Optional label for this prop set
description: Optional description for this prop set
image: name_of_image_file.png  # image file in same directory as this YAML
background_color: "#optional-css-color"  # omit or leave empty for transparent
props:
  prop_id:
    width: 64    # width in pixels of a single frame (all frames same size)
    height: 64   # height in pixels of a single frame
    frames:
      - [0, 0]   # pixel top-left coordinate of each frame in the image
      - [64, 0]
    anim_speed: 0.25  # optional: seconds between frames for auto-animation
```

## Server Routes
- `GET /props/<scope>/<filename>` — serves the prop image file; scope is `world` or `server`
- `GET /api/props/library` — returns the full prop library for the authenticated client

## Prop Editor
The prop editor is a web-based prop creation utility available at `/prop-editor` when the server is started with `--feature prop-editor`.

### REST API (all feature-gated)

| Method | Route | Action |
|--------|-------|--------|
| GET    | `/prop-editor` | Serve prop editor HTML |
| POST   | `/api/prop-editor/reindex` | Reindex prop repository |
| GET    | `/api/prop-editor/sets` | List all prop sets (server + world) |
| GET    | `/api/prop-editor/sets/<scope>/<filename>` | Get one set (metadata + definition) |
| POST   | `/api/prop-editor/sets/<scope>/<filename>/create-definition` | Create blank YAML for an image that lacks a definition |
| PUT    | `/api/prop-editor/sets/<scope>/<filename>` | Update full set definition (validate + atomic write) |
| POST   | `/api/prop-editor/sets/<scope>/<filename>/props` | Add a new prop entry |
| DELETE | `/api/prop-editor/sets/<scope>/<filename>/props/<prop_id>` | Delete a prop entry |

### UI Layout

```
+---------------------------------------------+--------------+
| Propset |                                   | Props        |
| List    |  +-----------------------+        |              |
|         |  | Propset image (canvas)|        |              |
|         |  |                       |        +--------------+
|         |  |  (overlay shows       |        | Prop Details |
|         |  |   selected frame)     |        | width/height |
|         |  +-----------------------+        | anim_speed   |
|         |                                   |              |
+---------+-----------------------------------+--------------+
| Frame Sequence Editor                                       |
|  [thumb] [thumb] [thumb] ...                                |
+-------------------------------------------------------------+
```

- **Propset List**: lists all prop sets (server `[S]` and world `[W]`). Shows a "Create def" button for images that lack a YAML. Selecting a set loads its image and definition.
- **Image Canvas**: displays the prop image with a pink overlay on the selected frame rect. Click the image (in add-frame mode) to add a frame at that pixel position.
- **Props Panel**: lists all props; supports add / delete. Selecting a prop loads its details and frames.
- **Prop Details**: edit `width`, `height`, and `anim_speed` for the selected prop.
- **Frame Sequence Editor**: shows frame thumbnails clipped from the image. Supports remove, reorder (Move Left/Right), and canvas-click insertion.
- **Save**: validates all fields and PUTs the full definition to the API atomically.

## Client Rendering
Props with a `prop_meta` field in their display data are rendered as a CSS-clipped `<div>` (background-image + background-position + fixed width/height), enabling pixel-accurate frame selection. If `prop_meta.animation` is present, a `setInterval` loop cycles through the frame list at the specified `speed` in seconds.

Legacy props that only carry `display.sprite` or `display.img` continue to render via a plain `<img>` element.

