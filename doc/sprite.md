# Sprites
Sprites are collections of images representing a character / object which include animations or multiple poses. Sprites are defined as an image file containing the sprite set, and a sprite definition yaml with information on sprites and frames for that image.

The sprite image file and yaml file always must match (ie explosions.yaml will apply to aexplosions.png in the same directory)

Characters (Users / Peeps) and Things / Objects use sprites as their display representation.

## Referencing sprites
A sprite can be referenced using a string in the format `$[/]<filename>/<spriteId>
Where the initial `/` indicates the file is from the server sprites directory rather than the world sprites. The spriteId selects the sprite from the `filename` sprite set. If the sprite id is not specified, the reference is to the first sprite in the sprite set. The reference can also include an optional `/<anim>/<frame>` to select a sprite animation and optionally specific frame image.

For instance a character `sprite` property can be set to `$/char_dimuru_01` to select the server `char_dimuru_01.png/yaml` files and use the first sprite from that set.

Implemented resolver behavior:
- `$<filename>/...` resolves with **world-first precedence** (`<world>/sprites` before `data/sprites`).
- `$/<filename>/...` resolves from `data/sprites` only.
- If `<spriteId>` is omitted, the first sprite in YAML order is used.
- `<frame>` may be either a frame token (`NxM`) or an animation frame index (`0`, `1`, ... when an animation is selected).

## Sprite Definition
Sprites are loaded from either data/sprites and the sprites directory of the loaded world. The sprites directory contains pairs of png images and yaml files with the sprite definitions for that image.

Example sprites.yaml
```
label: Optional label for this sprite set
description: Optional description for this sprite set
frame_width: width in pixels of a single sprite frame (all frames are the same size)
frame_height: height of sprite frame
background_color: optional background color for this sprite set (any CSS color string); omit/empty to remove
sprites:
    sprite_1: #Sprite ID
        default_frame: 0x0 # Frame to use as the default display frame for this sprite.
        anims: #Animations for this sprite
            anim_1: 
                speed: 0.5 #Frame speed in seconds. Default is 0.5
                type: loop #Either loop, bounce, random
                frames: [0x0,1x0,2x0,3x0,3x0,0x1]
```

### Frame coordinates
Frames are represented in the definition as the x,y GRID index of the frame image in the sprite set image. So for instance, `0x0` is the frame at the top left corner of the sprite set (with pixel size determined by the frame with and height)

## Sprite Editor
The sprite editor is a web-based sprite creation utility available in the tinyrooms client and server. It is enabled if the server is launched with argument `--feature sprite-editor`. It is accessible at <server url>/sprite-editor.

The sprite editor lets the user create new sprite definitions for images in the server/world sprites directories, or modify existing sprite definitions.

The sprite editor looks like this:
+---------------------------------------------+--------------+
| Spriteset|                                  | Sprites      |
| List     |  +-----------------------+       |              |
|          |  | Spriteset image       |       |              |
|          |  |                       |       |              |
|          |  |                       |       |              |
|          |  |                       |       +--------------+
|          |  |                       |       | Animations   |
|          |  |                       |       |              |
|          |  |                       |       |              |
|          |  |                       |       |              |
|          |  +-----------------------+       |              |
|          |                                  |              |
|          |                                  |              |
+----------+----------------------------------+--------------+
| Animation Editor                                           |
|                                                            |
|                                                            |
|                                                            |
+------------------------------------------------------------+

- The Spriteset List shows all available sprite sets in the server and world. It also allows creating new sprite sets for images that do not yet have a sprite definition file. Selecting a sprite set loads the spriteset image and definitions in the rest of the panels.
- The spriteset image displays the sprite set image and the frame grid on top of it, showing the frame size and alignment with the background image. There are controls to change the frame size, including an autodetect option. 
- The Sprites panel shows all sprites defined in the set, and lets the user create new ones and delete existing ones. Selecting a sprite shows its animations in the bottom panel.
- The Animations panel shows the animations for the selected sprite, including options for creating new animations and deleting existing ones. Selecting an animation shows its properties and frames in the Animation Editor panel.
- The Animation editor panel shows the frames for the currectly selected animation. Clicking on a frame in the animation selects it. Clicking on a frame in the spriteset image inserts that frame in the animation sequence, in the selected position. The animation panel also has controls to set the animation frame duration and type (loop/bounce/random).

## Sprite Editor Implementation
The sprite editor should work through a set of REST APIs exposed by the tinyrooms server.

### Feature flag
- Start server with `--feature sprite-editor` to enable:
  - `/sprite-editor` web UI
  - `/api/sprite-editor/*` APIs

### REST API surface
- `POST /api/sprite-editor/reindex`  
  Rebuild sprite index for server + world directories.
- `GET /api/sprite-editor/sets`  
  List indexed sets with `scope`, `filename`, image/yaml presence, and validation status.
- `GET /api/sprite-editor/sets/<scope>/<filename>`  
  Load one set with parsed definition.
- `POST /api/sprite-editor/sets/<scope>/<filename>/create-definition`  
  Create initial YAML for an image that has no definition yet. Accepts optional `background_color`.
- `PUT /api/sprite-editor/sets/<scope>/<filename>`  
  Replace definition (frame size + background color + sprites/anims) atomically after validation.
- `POST /api/sprite-editor/sets/<scope>/<filename>/sprites`  
  Create sprite entry.
- `DELETE /api/sprite-editor/sets/<scope>/<filename>/sprites/<sprite_id>`  
  Delete sprite entry.
- `POST /api/sprite-editor/sets/<scope>/<filename>/sprites/<sprite_id>/anims`  
  Create animation.
- `PUT /api/sprite-editor/sets/<scope>/<filename>/sprites/<sprite_id>/anims/<anim_id>`  
  Update animation speed/type/frames.
- `DELETE /api/sprite-editor/sets/<scope>/<filename>/sprites/<sprite_id>/anims/<anim_id>`  
  Delete animation.

### Auth + validation
- When `sprite-editor` feature is enabled, sprite-editor UI and APIs are intentionally open and do not require login/authentication.
- Validation errors return structured JSON with `ok: false`, `error`, and `details[]`.

### Rendering payload
When a display asset is a `$...` sprite reference, server payload now includes:
- resolved sprite image URL (`/sprites/<scope>/<image-file>`)
- selected frame rectangle (`x`, `y`, `width`, `height`)
- optional animation metadata (`speed`, `type`, `frames[]`)

Non-sprite image paths (`images/...`, `/...`, `http(s)://...`) are preserved unchanged.
