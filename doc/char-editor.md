# Character Sprite Editor

This document describes the current character editor implementation in tinyrooms.

## Overview

After login, users can open the character editor from the **Modify Character** button in the status panel.  
The editor appears as a top-level popup (`#characterEditorPage`) over `#mainPage`.

The system supports:
- descriptor-based sprite generation
- queued image generation
- up to 4 candidate sprites in the UI
- per-sprite discard
- persistent selected sprite
- live room update when a new sprite is saved

## Descriptor Configuration

Descriptor classes and options are server-driven from:

- `data/ui/char-editor.yaml`

Current descriptor classes:
- `hair_color` (`type: color`)
- `skin_color` (`type: color`)
- `body_adjective` (`type: text`)
- `clothing` (`type: text`)
- `clothing_material_or_color` (`type: text`)

Server-side style presets (hidden from user UI) are also defined in this YAML.

## Storage Layout

Per-user character data is stored in filesystem paths:

- `data/users/<username>/char.yaml`
- `data/users/<username>/sprites/*.png`
- `data/users/<username>/tmp/` (reserved temp folder)

`char.yaml` is treated as source of truth for appearance + selected sprite and is regenerated when character properties change.

Typical shape:

```yaml
version: 1
appearance:
  hair_color: black
  skin_color: olive
  body_adjective: athletic
  clothing: cloak
  clothing_material_or_color: dark linen
current_sprite: sprites/sprite_20260717_180000_a1b2c3.png
updated_at: "2026-07-17T18:00:00Z"
```

## Generation Tooling

Sprite generation is performed by:

- `tools/make-image`

Features:
- prompt composition from descriptor values
- sticker/simple-line style intent
- generate at high resolution and fit to **64x128**
- background-removal post-process step
- optional border/glow post-effects
- PNG output only
- SVG generation uses a text-to-SVG model and enforces pure vector markup (no embedded raster images)
- explicit non-zero exit on failure

## Queue and Worker Architecture

Queue logic is implemented in `tinyrooms/char_editor.py` via `CharacterEditorService`.

- Uses a dedicated **OS child process** (`multiprocessing.Process`) for sprite generation jobs.
- Main server keeps request state + queue metadata in memory.
- States: `queued`, `running`, `done`, `failed`, `cancelled`.
- Enforces **one active request per user** (`queued` or `running`).
- Requests are processed one at a time.

Cancellation semantics:
- queued request: removed and marked cancelled
- running request: marked cancelled; worker allowed to complete in background, result ignored

Temporary output root:
- default: system temp directory + `tinyrooms-char-editor`
- override via server arg: `python trserver.py --char-temp-dir <path>`

## REST API

All character-editor endpoints require an authenticated connected user.

Auth path currently supports:
- `X-TR-Auth` token from Socket.IO `login_success`
- fallback to Flask session username

Endpoints:

- `GET /api/char-editor/profile`
  - descriptor classes, current char state, sprite list, queue summary
- `POST /api/char-editor/requests`
  - submit one generation request with descriptors
- `GET /api/char-editor/requests/<request_id>`
  - request status + queue position
- `DELETE /api/char-editor/requests/<request_id>`
  - cancel request
- `GET /api/char-editor/queue`
  - queue summary for current user
- `DELETE /api/char-editor/sprites/<sprite_id>`
  - delete generated candidate (and clear current sprite if it was selected)
- `POST /api/char-editor/sprites/<sprite_id>/select`
  - persist selected sprite and appearance
- `GET /user-assets/<username>/<path:filename>`
  - serve user sprite files to clients

## Client Flow

Implemented in:
- `app/client.html`
- `app/client.css`
- `app/client.js`

State flow:
- `closed`
- `editing`
- `rolling`
- `slots_ready`

Behavior:
1. Open editor -> load profile from `/api/char-editor/profile`.
2. User picks descriptor options.
3. Press Roll -> client chains single-image requests until 4 slots are filled (or stopped).
4. UI polls status endpoint and shows queue info (`items ahead`).
5. User can discard any filled slot.
6. User selects one candidate and saves.
7. Selected sprite applies immediately in room and persists across sessions.

## Rendering Integration

Room rendering now supports:
- absolute asset URLs (including `/user-assets/...`)
- existing `/world/...` relative asset fallback

This allows world assets and user sprite assets to coexist.

## Login / Runtime Integration

- On login, user gets a per-login REST token (`rest_token` in `login_success` payload).
- On user creation/login, saved `char.yaml` sprite (if present) is applied to peep display assets.
- On sprite select/discard (when affecting current sprite), server broadcasts room-object updates so all clients see changes immediately.
- Users without character data still use default sprite assets.

## Placeholder / Unspecified Items

The following remain intentionally minimal/placeholder pending further spec detail:
- advanced style controls beyond hidden border/glow presets
- persistence of generation request state across full server restarts
- richer queue UX metrics beyond current queue/running/items-ahead fields

## Integration Test Coverage

Character-editor API contracts are exercised in `tests/integration/test_char_editor_api.py` against a real running tinyrooms server.

To keep these tests fast and deterministic, the integration harness runs the server in an isolated copied workspace and swaps `tools/make-image` with a lightweight test stub in that copied workspace only.
