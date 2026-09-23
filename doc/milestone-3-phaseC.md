# Milestone 3 — Phase C: Interactive Props, Crafting, Auras, and Environment

> **Execution contract.** This document is self-contained. Do not ask for extra
> context. Read *Orientation*, implement *Work* exactly, then run *Verification*
> and fix every failure. Phases A and B must be complete.

## 1. What this phase delivers

Reusable built-in prop behaviors: unlimited weighted **dispensers** with a shared
persistent cooldown, **crafting stations** with validate-before-consume stack
selection, **room auras** applied only while present, persistent **environment
state** gating visibility/lighting/exits/actions with one revisioned broadcast,
and a centralized **room ownership** service.

Out of scope: powers/auth commands (D), room-owner editing UI (E), world editor
(F), activity result hooks and Lazor Rush (G).

## 2. Orientation (read these before coding)

- `AGENTS.md`, `doc/design.md` sections *Dispenser Behavior*, *Environment and
  Effects*, *Room Ownership*, *Card Actions* (crafting), *Activities*.
- `doc/milestone-3.md` work package 3.
- `server/content/worlds.py` — prop definitions/instances, rooms, validation.
- `server/services/cards.py` — `grant_card_to_inventory`, stack serialization,
  inventory mutations.
- `server/services/stats.py` — buffs, counters, `reconcile_in_transaction`.
- `server/game/buffs.py`, `server/game/modifiers.py`, `server/game/state.py`.
- `server/state/world_state.py` — `room_states`, `room_cards` access.
- `server/behaviors/*` (Phase A) — dispatcher, `Intent` application, builtins.
- `server/commands/outcomes.py`, `server/commands/core.py`, `server/commands/registry.py`.
- `server/app.py` — `create_runtime`, `RuntimeState`, bridge endpoint.
- `server/services/activities.py` — activity config/lifecycle.
- `worlds/tutorial/recipes.yaml`, `worlds/tutorial/rooms/rooms.yaml`
  (dispenser/crafting/shower/supplies/locked-door instances),
  `worlds/tutorial/props/props.yaml`.
- `activities/shared.js`, `activities/shop/` — activity bridge and a full example.
- `activities/crafting/index.html` — currently a redirect stub to replace.

### Hard rules
- Every source file **under 1200 lines**; split modules if needed.
- Python: `from __future__ import annotations`, type hints on public functions,
  docstrings on public cross-module functions, **no inline comments** except one
  or two lines for tricky logic.
- Imports grouped stdlib / third-party / `server.*`.
- No `localStorage`/`sessionStorage`; no direct client-side value creation.
- All timers persist as UTC instants and count elapsed time across restart and
  while nobody is connected.
- Tests: `python -m unittest discover -s tests -v`.

## 3. Work

### 3.1 Schema

Bump **world** schema 7 → 8 and **profile** schema 5 → 6.

World fresh-schema additions (also `_WORLD_TABLES`, column specs,
`_WORLD_MIGRATIONS[8]`):

```sql
CREATE TABLE IF NOT EXISTS prop_cooldowns (
    namespace TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    ready_at TEXT NOT NULL,
    PRIMARY KEY (namespace, instance_id)
);
```

Room state columns added to `room_states` (fresh schema plus
`ALTER TABLE room_states ADD COLUMN ...` in the migration):

```sql
environment_json TEXT NOT NULL DEFAULT '{}'
layout_revision  INTEGER NOT NULL DEFAULT 0
```

Profile fresh-schema addition (`_PROFILE_TABLES`, column specs,
`_PROFILE_MIGRATIONS[6]`):

```sql
CREATE TABLE IF NOT EXISTS craft_operations (
    account_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    recipe_id TEXT NOT NULL,
    world_id TEXT NOT NULL,
    results_json TEXT NOT NULL CHECK (json_valid(results_json)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (account_id, operation_id),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
```

### 3.2 Recipe content

Create `server/content/recipes.py` — `load_recipes(world_path, card_ids)` reading
`worlds/<world>/recipes.yaml`. Dataclasses:
- `Ingredient(card_id, quantity=1)`.
- `RecipeDefinition(id, label, description, ingredients, output, energy_cost=0)`.
Validate: unique IDs, positive quantities, every card exists, output non-empty.
Add `recipes: dict[str, RecipeDefinition]` to `WorldDefinition`; validate each
prop instance's `recipes` list against it in `load_world_definition`; remove the
`recipes:` field's unvalidated status.

### 3.3 Dispenser

Add to `server/behaviors/builtin.py` (or a new
`server/services/dispensers.py`) a `DispenserService`:
- `dispense(account, room_id, prop_instance_id) -> DispenseResult`.
- Validate the prop's `behavior == "dispenser"` and its `content` card list.
- Enforce one shared cooldown per prop: read `prop_cooldowns[(world_id, instance_id)]`;
  `ready_at` absent means ready. On rejection return `remaining_seconds`; no cost.
- Weighted selection: prop YAML may define `weights: {card_id: number}`; when
  absent every listed card is equally weighted. Use deterministic RNG injection
  (`random.Random`) so tests can seed it.
- Grant directly to the activating account's inventory via
  `grant_card_to_inventory` using normal stacking rules.
- Set `ready_at = now + cooldown` (default 600s) in the same transaction.
- A newly placed prop with no row is ready.
Commands: `.dispense @prop:<instance_id>` (and a `.dispense <instance_id>`
short form for authored quick actions). Authored dispenser action `.dispense
dollhouse0` becomes valid.

### 3.4 Crafting

Create `server/services/crafting.py` — `CraftingService(hub, profiles,
inventory, stats, catalog, content, recipes, world_id)`:
- `preview(account, room_id, prop_instance_id, recipe_id) -> CraftPreview`:
  recipe, output, quantities, energy cost, and each ingredient with the
  account's eligible source stacks (`stack_id`, `quantity`, `equipped`) from
  inventory. Equipped stacks are shown but only used when explicitly selected;
  slotted skill stacks are excluded.
- `craft(account, room_id, prop_instance_id, recipe_id, selections, operation_id)`:
  - Idempotency: `craft_operations[(account_id, operation_id)]`; a duplicate
    returns the stored results without consuming or granting.
  - Validate the prop is a crafting station exposing the recipe.
  - Validate every selection references an eligible stack with enough quantity;
    reject the whole craft on any mismatch.
  - Consume all ingredients, grant the output to inventory, charge
    `energy_cost` via `StatsService`, update affected equipped-stack bonuses,
    and record the operation **in one transaction**. Nothing is consumed when the
    craft is invalid.
- Guard concurrent crafts with the existing `DatabaseHub.transaction()`
  (`BEGIN IMMEDIATE`) and re-read stacks inside the transaction.
Commands:
- `.craft @prop:<instance_id>` — open the crafting activity bound to the prop
  (activity `config` carries the prop and recipe list).
- `.craft_preview <recipe_id>` — preview for the activity's bound prop.
- `.craft_make <recipe_id> <operation_id> <stack_id>:<quantity> ...` — execute.
Extend the activity bridge command path as needed; keep the service API the
contract and commands thin wrappers.

### 3.5 Crafting activity

Replace `activities/crafting/index.html`'s redirect with a real activity:
`index.html`, `crafting.js`, `crafting.css` using `activities/shared.js`.
Show recipe list, selected recipe details, ingredient stacks with quantity
inputs, output preview, and a confirm button. Send selection commands through the
bridge; show success/rejection from `tinyrooms.host.result`. Keep each file under
1200 lines and match `activities/shop/` conventions.

### 3.6 Room auras

Extend room YAML with an optional `aura:` list of modifier entries
(`{stat: delta}` and/or a named buff with `duration`/`daily`). Load into
`RoomDefinition.aura: tuple[AuraDefinition, ...]`.
Extend `StatsService` with source-scoped, non-stacking application:
- `apply_source(account_id, source, modifiers)` — replaces any existing
  contribution from the same `source`; idempotent.
- `remove_source(account_id, source)`.
`AuraService.enter(account_id, room_id)` applies `aura:<room_id>`; `AuraService.leave`
removes it. Call from `RoomService.navigate`, WS connect/disconnect, and the room
ticker so repeated ticks never stack. Leaving removes the aura immediately;
separately timed buffs and counter changes are left untouched.

### 3.7 Environment state

Create `server/services/environment.py` — `EnvironmentService(hub, world,
world_state)`:
- Well-known keys in `room_states.environment_json`:
  `lighting` (`"normal"`/`"dark"`), `hidden_props`, `disabled_exits`,
  `disabled_actions`, each with an optional `expires_at` per entry.
- `get(room_id) -> dict`, `set(room_id, patch) -> EnvironmentUpdate` incrementing
  `room_states.layout_revision`, returning an event
  `{"type":"room.environment","room_id":…,"revision":…,"environment":…}`.
- `is_prop_visible`, `is_exit_enabled`, `is_action_enabled` helpers.
- Expiry: the ticker clears expired entries and broadcasts one update.
- `RoomService.build_snapshot` and `_serialize_prop`/`_serialize_exit` filter
  hidden props, disabled exits, and disabled actions; the snapshot includes
  `"environment": {...}`.
- Behavior `context.set_environment(key, value)` intent goes through this service.

### 3.8 Ownership

Create `server/services/ownership.py` — `OwnershipService(hub, profiles,
world_state, world)`:
- `owner_of(room_id) -> str | None` from `room_states.owner_account_id`.
- `grant(room_id, account_id)`, `revoke(room_id)`, `modify(room_id, account_id)`.
- `can_edit(account, room_id) -> bool`: owner, or a `builder` power (the power
  service arrives in Phase D; accept an injected `has_power` callable now and
  default it to `False`).
- Mirror world-scoped claims in `user_profiles.ownership_json`.
Register in `RuntimeState`; realtor/game-master commands that call it are added in
Phase D.

## 4. Tests

Create `tests/test_milestone3_props.py` and `tests/test_milestone3_crafting.py`
(subclass `tests/common.py:ServiceTestCase`). Cover:
- Shared dispenser cooldown across two users and across a hub reopen; remaining
  time on rejection; new prop is ready; deterministic weighted draw with a seeded
  RNG; direct-to-inventory grant with correct stacking.
- Craft source-stack selection (including an explicitly selected equipped stack),
  equipped count/bonus update on consume, invalid recipe rollback (nothing
  consumed), duplicate `operation_id` replay, and concurrent-craft protection.
- Aura enter/leave idempotency (repeat ticks do not stack) and independent timed
  buffs/counters.
- Environment visibility/lighting/exit/action gating, revisioned broadcast, and
  expiry clearing.
Bump migration tests to the new versions. Add a browser flow for the crafting
activity (`tests/browser/flows.spec.js`).

## 5. Verification

```bash
python -m unittest discover -s tests -v
npm run test:browser
```

Definition of done:
- [ ] A dispenser attempt during cooldown rejects with remaining time and no cost.
- [ ] Cooldown survives restart and counts elapsed stopped/serverless time.
- [ ] Invalid crafts consume nothing; duplicate operations never double-grant.
- [ ] Auras never stack and clear on departure.
- [ ] Environment changes broadcast one revisioned update and gate the room.
- [ ] Every file under 1200 lines; existing tests pass.

## 6. Guardrails

- Do **not** hard-code tutorial IDs into generic services; use YAML fields.
- Do **not** consume ingredients before full validation succeeds.
- Do **not** let a second source-buff stack the same aura.
- Do **not** remove timed buffs/counters when an aura leaves.
