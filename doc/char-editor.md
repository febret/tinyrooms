# Character Editor

## Overview

After login, users can open the character editor from the **Modify Character** button in the status panel. The editor appears as a top-level popup (`#characterEditorPage`) over `#mainPage`.

Supports: freeform description editing, sprite selection from indexed server/world sprite definitions, optional AI-generated portrait, and persistent saved character profile. Changes broadcast immediately to other room occupants.

## Sprite Source

Selectable sprites come from the indexed sprite-definition files used elsewhere in tinyrooms (`data/sprites/` for server sprites, `data/worlds/<world>/sprites/` for world sprites). Persisted sprite values use the standard sprite-reference format (see sprite.md). Legacy user-generated sprite paths can still be loaded but are no longer created by the editor.

## Storage Layout

Per-user character data lives in `data/users/<username>/`:
- `char.yaml` — source of truth (description, current_sprite, main_image)
- `images/*.png` — generated portrait images
- `sprites/*.png` — legacy only; no longer written

## Main-Image Generation

The editor generates a portrait-style **main image** via `tools/make-image` (see make-image.md):
- Prompt: `"portrait of a game character. {description}"`
- Output: 256×256 PNG persisted to `data/users/<username>/images/`
- Previous generated image is replaced on each new generation
- Used as `img` and `icon` display assets; selected sprite is used for `sprite`

## REST API

All endpoints require an authenticated user (`X-TR-Auth` token or Flask session).

- `GET /api/char-editor/profile` — saved profile + selectable sprite options
- `PUT /api/char-editor/profile` — save description and selected sprite
- `POST /api/char-editor/main-image` — generate and persist a portrait; returns updated profile
- `GET /user-assets/<username>/<path>` — serve persisted user assets

## Client Flow

1. Open editor → `GET /api/char-editor/profile`
2. Edit description; select sprite
3. Optionally generate main image
4. Save with `PUT /api/char-editor/profile`
5. Changes apply immediately in-room and persist across sessions

## Rendering Integration

- `sprite`: selected sprite-reference resolved through the sprite repository
- `img` / `icon`: generated portrait (or default fallback)

## Login / Runtime Integration

- Per-login REST token (`rest_token`) issued in `login_success` payload
- On login: saved description applied to peep; display assets rebuilt from current sprite repository
- On save or image generation: server updates online peep and broadcasts `room-object` update to all clients
- Users without saved character data use default user assets

## Implementation References

- Server: `tinyrooms/char_editor.py`
- Client: `app/charEditor.js`, `app/client.html`, `app/client.css`
- User data: `data/users/<username>/char.yaml`
- Integration tests: `tests/integration/test_char_editor_api.py`
