# Character Editor

This document describes the current character editor implementation in tinyrooms.

## Overview

After login, users can open the character editor from the **Modify Character** button in the status panel.  
The editor appears as a top-level popup (`#characterEditorPage`) over `#mainPage`.

The editor supports:
- freeform character description editing
- direct sprite selection from indexed server/world sprite definitions
- optional generated main-image portrait
- persistent saved character profile
- live room updates when the profile changes

The old queued sprite-generation pipeline and appearance-descriptor system have been fully removed from both the UI and backend.

## Sprite Source

Selectable sprites come from the indexed sprite-definition files used elsewhere in tinyrooms:

- `data/sprites/*.yaml` (+ matching image files) for **server** sprites
- `data/worlds/<world>/sprites/*.yaml` (+ matching image files) for **world** sprites

Every sprite entry defined under a sprite set's `sprites:` mapping is exposed as a selectable character sprite.

Persisted sprite values use the normal tinyrooms sprite-reference format:

- `$/<filename>/<sprite_id>` for server sprites
- `$<filename>/<sprite_id>` for world sprites

Legacy user-generated sprite asset paths can still be loaded if they already exist in saved character data, but the editor no longer creates new ones.

## Storage Layout

Per-user character data is stored in filesystem paths:

- `data/users/<username>/char.yaml`
- `data/users/<username>/images/*.png`
- `data/users/<username>/sprites/*.png` (legacy only; no longer written by the editor)
- `data/users/<username>/tmp/`

`char.yaml` is the source of truth for the saved character profile.

Typical shape:

```yaml
version: 1
description: A quiet ranger in a weathered moss cloak.
current_sprite: $world_people/world_ranger
main_image: images/main_20260720_021500_ab12cd.png
updated_at: "2026-07-20T02:15:00Z"
```

## Main-Image Generation

The editor can generate a portrait-style **main image** using:

- `tools/make-image`

Current behavior:
- generation is request/response based; there is no queued candidate pipeline
- the prompt is composed from the saved description: `"portrait of a game character. {description}"`
- output is generated at **256x256**
- output must be PNG
- the generated image is persisted under `data/users/<username>/images/`
- when a new main image is generated, the previous generated main image is removed if it was stored in that same `images/` folder

The main image is used for the character's `img` and `icon` display assets.  
The selected sprite reference is used for the character's `sprite` display asset.

## REST API

All character-editor endpoints require an authenticated connected user.

Auth path currently supports:
- `X-TR-Auth` token from Socket.IO `login_success`
- fallback to Flask session username

Endpoints:

- `GET /api/char-editor/profile`
  - returns saved character profile and all selectable sprite options
- `PUT /api/char-editor/profile`
  - saves description and selected sprite reference
- `POST /api/char-editor/main-image`
  - generates and persists a new main image, then returns the updated character profile
- `GET /user-assets/<username>/<path:filename>`
  - serves persisted user assets (including generated main images and any legacy sprite files)

## Profile Payload Shape

`GET /api/char-editor/profile` returns:

- `available_sprites`
- `char`

`available_sprites[]` includes:
- `sprite_ref`
- `scope`
- `filename`
- `sprite_id`
- `label`
- `set_label`
- `set_description`
- `image_url`
- `frame`
- `background_color`

`char` includes:
- `description`
- `current_sprite`
- `current_sprite_preview`
- `main_image`
- `main_image_url`
- `updated_at`

## Client Flow

Implemented in:
- `app/client.html`
- `app/client.css`
- `app/charEditor.js`

Behavior:
1. Open editor → load profile from `GET /api/char-editor/profile`.
2. User edits description.
3. User selects any indexed server/world sprite.
4. User may request a new main image (generated from the description).
5. User saves the profile with `PUT /api/char-editor/profile`.
6. Saved changes apply immediately in-room and persist across sessions.

## Rendering Integration

Character rendering combines:
- `sprite`: selected sprite reference resolved through the sprite repository
- `img`: generated main image (or default fallback)
- `icon`: generated main image (or default fallback)

This lets a character use a sprite-sheet-based room avatar while also keeping a separate portrait-style main image.

## Login / Runtime Integration

- On login, user gets a per-login REST token (`rest_token` in `login_success` payload).
- On login, saved character description is applied to the user's peep info.
- On login, saved character display assets are rebuilt from the current world sprite repository plus any saved user assets.
- On character profile save or main-image generation, the server updates the online peep display assets and broadcasts a room-object update so all clients see changes immediately.
- Users without saved character data still use default user assets.

## Integration Test Coverage

Character-editor API contracts are exercised in `tests/integration/test_char_editor_api.py` against a real running tinyrooms server.

The integration harness:
- runs the server in an isolated copied workspace
- provides sample server/world sprite definitions for character selection tests
- swaps `tools/make-image` with a lightweight test stub so main-image generation remains fast and deterministic


Selectable sprites come from the indexed sprite-definition files used elsewhere in tinyrooms:

- `data/sprites/*.yaml` (+ matching image files) for **server** sprites
- `data/worlds/<world>/sprites/*.yaml` (+ matching image files) for **world** sprites

Every sprite entry defined under a sprite set's `sprites:` mapping is exposed as a selectable character sprite.

Persisted sprite values use the normal tinyrooms sprite-reference format:

- `$/<filename>/<sprite_id>` for server sprites
- `$<filename>/<sprite_id>` for world sprites

Legacy user-generated sprite asset paths can still be loaded if they already exist in saved character data, but the editor no longer creates new ones.

## Storage Layout

Per-user character data is stored in filesystem paths:

- `data/users/<username>/char.yaml`
- `data/users/<username>/images/*.png`
- `data/users/<username>/sprites/*.png` (legacy only; no longer written by the editor)
- `data/users/<username>/tmp/`

`char.yaml` is the source of truth for the saved character profile.

Typical shape:

```yaml
version: 1
appearance:
  hair_color: black
  skin_color: olive
  body_adjective: athletic
  clothing: cloak
  clothing_material_or_color: dark linen
description: A quiet ranger in a weathered moss cloak.
current_sprite: $world_people/world_ranger
main_image: images/main_20260720_021500_ab12cd.png
updated_at: "2026-07-20T02:15:00Z"
```

## Main-Image Generation

The editor can still generate a portrait-style **main image** using:

- `tools/make-image`

Current behavior:
- generation is request/response based; there is no queued candidate pipeline
- the prompt is composed from the saved description plus appearance descriptors
- output is generated at **256x256**
- output must be PNG
- the generated image is persisted under `data/users/<username>/images/`
- when a new main image is generated, the previous generated main image is removed if it was stored in that same `images/` folder

The main image is used for the character's `img` and `icon` display assets.  
The selected sprite reference is used for the character's `sprite` display asset.

## REST API

All character-editor endpoints require an authenticated connected user.

Auth path currently supports:
- `X-TR-Auth` token from Socket.IO `login_success`
- fallback to Flask session username

Endpoints:

- `GET /api/char-editor/profile`
  - returns descriptor classes, saved character profile, and all selectable sprite options
- `PUT /api/char-editor/profile`
  - saves appearance, description, and selected sprite reference
- `POST /api/char-editor/main-image`
  - generates and persists a new main image, then returns the updated character profile
- `GET /user-assets/<username>/<path:filename>`
  - serves persisted user assets (including generated main images and any legacy sprite files)

## Profile Payload Shape

`GET /api/char-editor/profile` returns:

- `descriptor_classes`
- `available_sprites`
- `char`

`available_sprites[]` includes:
- `sprite_ref`
- `scope`
- `filename`
- `sprite_id`
- `label`
- `set_label`
- `set_description`
- `image_url`
- `frame`
- `background_color`

`char` includes:
- `appearance`
- `description`
- `current_sprite`
- `current_sprite_preview`
- `main_image`
- `main_image_url`
- `updated_at`

## Client Flow

Implemented in:
- `app/client.html`
- `app/client.css`
- `app/charEditor.js`

Behavior:
1. Open editor -> load profile from `GET /api/char-editor/profile`.
2. User edits descriptor options and description.
3. User selects any indexed server/world sprite.
4. User may request a new main image.
5. User saves the profile with `PUT /api/char-editor/profile`.
6. Saved changes apply immediately in-room and persist across sessions.

## Rendering Integration

Character rendering now combines:
- `sprite`: selected sprite reference resolved through the sprite repository
- `img`: generated main image (or default fallback)
- `icon`: generated main image (or default fallback)

This lets a character use a sprite-sheet-based room avatar while also keeping a separate portrait-style main image.

## Login / Runtime Integration

- On login, user gets a per-login REST token (`rest_token` in `login_success` payload).
- On login, saved character description is applied to the user's peep info.
- On login, saved character display assets are rebuilt from the current world sprite repository plus any saved user assets.
- On character profile save or main-image generation, the server updates the online peep display assets and broadcasts a room-object update so all clients see changes immediately.
- Users without saved character data still use default user assets.

## Integration Test Coverage

Character-editor API contracts are exercised in `tests/integration/test_char_editor_api.py` against a real running tinyrooms server.

The integration harness:
- runs the server in an isolated copied workspace
- provides sample server/world sprite definitions for character selection tests
- swaps `tools/make-image` with a lightweight test stub so main-image generation remains fast and deterministic
