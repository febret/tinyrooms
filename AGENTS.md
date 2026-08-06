# Tinyrooms AGENTS

## What is tinyrooms?

Tinyrooms is a small multiplayer text-world built with Python, Flask, and Socket.IO. A core goal of the project is to be a teaching tool: the code is intentionally kept straightforward, and the feature set is designed to help learners understand how multiplayer worlds, gameplay systems, and content pipelines fit together. Users connect through a browser client, register/log in locally, and are placed into a persistent, YAML-driven virtual world made up of interconnected rooms. Inside those rooms they can chat, emote, move their character, pick up and carry objects, interact with NPCs, and craft items.

### Core concepts

- **World** — the top-level container for all rooms, ways, props, and things. Worlds are defined in YAML files under `data/worlds/<world_id>/` and their runtime state (object positions, prop layouts, room overrides) is persisted in a SQLite/DuckDB database. See `doc/world.md`.

- **Room** — a visual scene displayed as a canvas with a background image and props in the background, and interactive objects/peeps in the foreground. Rooms connect to each other through *ways* (exits). See `doc/room.md`.

- **Props** — semi-static room decorations placed by the room owner. Defined as prop sets (YAML + spritesheet). Any prop can be assigned an exit to act as a passage to another room. See `doc/prop.md`.

- **Peeps** — in-world character sprites. Every logged-in user controls a peep. NPCs are also modeled as peeps and driven by Python behavior scripts that can respond to ticks, chat messages, and custom actions. See `doc/peep.md`.

- **Things / Objects** — item templates (defined in YAML) whose instances can be placed in rooms, picked up into a user's inventory, dropped, and crafted into new objects. See `doc/inventory.md` and `doc/core-mechanics.md`.

- **Actions & Commands** — users interact with the world through the action palette (Look, Use, Pick Up, Drop, Go, custom object/peep actions) and through colon-prefixed commands (`:look`, `:go`, `:craft`, etc.). Power-gated superuser commands give admins, realtors, builders, moderators, and game-masters extended control. See `doc/actions.md`, `doc/commands.md`, and `doc/permissions.md`.

- **Gameplay systems** — traits (long-term peep modifiers), juice (energy spent on actions), kudos (peer-given reputation that drives levelling), bops (in-world currency), vibes (per-peep reputation scores), and object crafting. See `doc/core-mechanics.md` and `doc/vibes.md`.

- **Editors** — the world editor (`/world-editor`), room editor (in-client), prop editor (`/prop-editor`), and character editor provide in-browser tools for content authoring and customization. These editors are intended to be approachable for younger creators so kids can build and personalize their own worlds. Most editors are feature-gated and enabled with `--feature <name>` on the server.

## Project structure

Tinyrooms is split into a few main areas:

- `app/` — browser client code and UI assets.
- `tinyrooms/` — the Python backend package, including server logic, gameplay systems, persistence, and socket/message handlers.
- `data/` — YAML content, runtime user/world state, and shared assets.
- `doc/` — canonical feature specifications. Treat these as the source of truth for behavior.
- `tests/` — pytest coverage, including integration and client tests.
- `trserver.py` — server entry point.
- `start.sh` — local restart loop for development.

## Spec map

When working in a feature area, follow the matching document under `doc/`:

- `app.md` — client layout and runtime flow.
- `room.md` — room staging, props, movement, exits, and sync payloads.
- `world.md` — world loading, room/way definitions, and world editor structure.
- `prop.md` — prop set definitions, editor API, and rendering behavior.
- `peep.md` — peep definitions, NPC behaviors, and behavior script rules.
- `commands.md` — command syntax and power rules.
- `actions.md` — action palette behavior and custom action dispatch.
- `inventory.md` — inventory lifecycle, pick/drop, and crafting inventory flow.
- `core-mechanics.md` — gameplay systems such as traits, juice, kudos, and crafting.
- `decorators.md` — decorator definitions and runtime behavior.
- `emotes.md`, `sprite.md`, `vibes.md`, `permissions.md`, `testing.md` — feature-specific rules and test expectations.

## Coding rules

- Do not use local imports in Python files. Use global imports only.
- Add docstrings or doc comments to all nontrivial public functions.
- Strive for design simplicity and remember this is a teaching tool. If you create complex sections of code, use comments to explain what the code does. Avoid trivial helper functions.
