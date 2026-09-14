# Milestone 2 - Core Gameplay, Props, Peeps, and Complete Core UI

## Outcome

Turn the Milestone 1 multiplayer slice into the complete reusable core game:
Three.js props, user and NPC peeps, stats/counters/statuses, Energy, levels,
Kudos, Bops, skills, equipment, full card actions, emotes, friends, packs, and
every core UI screen. All systems are server-authoritative, definition-driven,
persistent, and usable with mouse, keyboard, and touch.

At completion, all core screens are functionally complete even where later
milestones will add content. Journal and Edit Room therefore have finished UI
shells and empty/locked states; their mutation logic arrives in Milestone 3.

## Inputs and compatibility

- Milestone 1 is complete and its account, profile, command, WebSocket,
  activity, content-loading, and persistence contracts are stable.
- Read [design.md](./design.md) sections UI through Peep Buffs, plus Props,
  Peeps, Activities, and Friends.
- Apply all numerical and named-card decisions in
  [planning-hints.md](./planning-hints.md).
- Keep Milestone 1 accounts and world state loadable via migrations.

Prototype guidance:

- The entity serialization/delta concepts in
  [room.py](../attic/tinyrooms-prototype/tinyrooms/room.py) and the small data
  objects in [peep.py](../attic/tinyrooms-prototype/tinyrooms/peep.py) and
  [prop.py](../attic/tinyrooms-prototype/tinyrooms/prop.py) are useful.
- The inventory location/state transitions in
  [inventory.md](../attic/tinyrooms-prototype/doc/inventory.md) illustrate
  atomic pickup/drop, but replace object instances with the current card-stack
  model.
- Do not reuse prototype level/Kudos/juice constants from
  [gameplay.py](../attic/tinyrooms-prototype/tinyrooms/gameplay.py); they
  contradict the current design and `data/core/*.yaml`.

## Required domain model

Create explicit services/models for:

- `Peep`: user or NPC identity, room, sticker/image, statuses, and effective
  presentation. Peeps have no in-room position.
- `PropDefinition` and `PropInstance`: model URL, transform, decorative flag,
  actions, state, and optional behavior reference.
- `CardDefinition`, `CardStack`, `PackDefinition`, `EquipmentLoadout`, and
  `SkillSlot`.
- `StatDefinition`, `CounterDefinition`, `Modifier`, `BuffInstance`, and
  `StatusDefinition`.
- `Friendship` and `FriendRequest`.
- `ActivitySession`, extending the Milestone 1 host with shop support.

Separate calculations from persistence and command handlers. A single
`EffectivePeepState` calculation should combine base values, equipment, skills,
buffs, and statuses so every UI and action sees identical results.

## Work packages

### 1. Props and Three.js presentation

- Validate propsets as directories containing definitions, GLB models, and
  related assets. Load shared propsets and world-specific
  `worlds/<id>/props`, with world IDs scoped to avoid collisions.
- Load GLB models through Three.js, cache immutable geometry/material assets,
  clone scenes per instance, and dispose room-specific GPU resources.
- Apply position, rotation, and scale from definitions/live state. Provide a
  visible loading state and a surfaced asset error; do not silently render a
  fake prop.
- Decorative props are not selectable. Interactive props support ray-cast
  selection, touch selection, a highlight, a slowly rotating preview above the
  Look Bar, and Prop Details with orbit controls.
- Keep board rotation separate from prop selection using movement thresholds so
  a drag never becomes an accidental action.
- Support room environment presentation hooks (lighting, fog, darkness, color
  palette) and one FIFO room-effect queue shared by action effects and Effects
  emotes. Gameplay auras are implemented in Milestone 3.

### 2. Peeps List and social presence

- Render user peeps and definition-only NPC peeps as sticker sprites mounted on
  solid board-piece markers in the left sidebar, not on the Board.
- Own peep is first and larger. Pinned peeps precede unpinned peeps. When space
  is insufficient, preserve pinned entries and collapse other peeps into an
  expandable group.
- Selecting a peep updates highlight, preview, Look Bar, and server-provided
  quick actions. Clear selection if the peep leaves.
- Display status icons under peeps and gray a Tired peep.
- Implement Pin/Unpin as a per-user presentation preference.
- Implement friend requests with offline persistence: send, accept, decline,
  cancel, remove, online status, and race-safe mutual friendship creation.

### 3. Stats, counters, modifiers, buffs, and statuses

- Load `data/core/stats.yaml`, `statuses.yaml`, `juice.yaml`, `levels.yaml`, and
  `bops.yaml` with strict validation.
- Base Constitution, Dexterity, Charisma, and Fanciness are each 1.
- Effective stats: add flat modifiers, then sum percentages and apply once,
  floor once, minimum 0.
- Health maximum: `max(50, 50 * effective Constitution)` before direct
  max-Health modifiers; floor once, final minimum 1.
- Energy maximum comes from `max_energy_per_level`; Cleanliness base maximum is
  100. Current values clamp only when above a reduced maximum and may retain
  fractions.
- Health and Cleanliness do not passively change by default. Energy recovers at
  1/minute online and offline using elapsed UTC timestamps.
- Implement timed, daily, condition-based, and explicitly stackable buffs.
  Reapplication/expiration/stack-limit behavior must exactly follow the design.
- Reconcile Sick, Stinky, and Tired after every relevant mutation and on login.
  Tired clears only at 10% of effective maximum Energy.
- Centralize action affordability and transactional charging. Rejection consumes
  nothing. Energy refill works while Tired; other Energy-consuming actions do
  not.

### 4. Levels, Kudos, Bops, and skills

- New users retain Milestone 1's level 0, 0 Kudos, 10 Bops, full starting
  counters, and no skill slots.
- Level Up is explicit. Spend only `kudos_to_next`, retain surplus, stop at
  level 15, and continue tracking Kudos afterward.
- Award one unlocked skill slot per level across three ordered rows of five:
  Script Kiddo, Hacker, Leet.
- Slot only an owned copy in an eligible rank. Multiple owned copies may occupy
  multiple slots; one copy cannot. Remove/replace for free.
- Slotted skills do not consume equipped slots. Apply/remove their modifiers
  immediately and atomically.
- Implement a generic idempotent reward ledger so later tasks/activities can
  award Kudos/cards exactly once.
- Implement Claim Daily Bops once per configured game day, using level at claim
  time and the shared profile timestamp. Missed claims do not accumulate.

### 5. Complete inventory, equipment, and card actions

- Enforce non-stackable default and explicit stack limits. Acquisition fills
  equipped stacks first, then unequipped stacks, then creates new stacks.
- Implement split and merge while preserving stack identity and equipped state;
  split-off stacks start unequipped.
- Enforce `max_equipped` as stacks, not copies. Only item/action stacks equip.
  Each copy in an equipped stack contributes passive bonuses.
- Dropping part of an equipped stack preserves equipment; dropping/using its
  final copy frees the slot. Slotted copies cannot be dropped.
- Ordinary item/action cards require equipment and explicit Use. Emotes never
  equip. Core cards never enter inventory.
- Implement self-only and target-required action execution. Targeting closes the
  source view, previews an animated card-to-target line on first selection, and
  confirms the same target on second selection. A different target changes the
  preview.
- Cancel targeting through the visible Cancel action, Escape, room change, view
  opening, source loss, or target loss. Explain unavailability without cost.
- Implement action feedback channels: Action Log text, floating counter numbers,
  top-center toasts, and queued room effects.
- Implement the approved named-card rules for Juicy Drink, Tasty Toast, Tomato
  Sauce, Ballet Shoes, Lucille, Seal Plushie, Sturdy, Nimble, Charming, and
  Stylish. Long descriptions are generated from live card properties.

### 6. Emotes and speech/effect presentation

- Implement Expression, Animation, and Effects categories with the configured
  Energy costs of 1, 3, and 5 respectively.
- Expressions and animations use peep-side bubbles. Effects enter the same
  room-wide FIFO queue as gameplay visual effects.
- A successful submission is ordered by the server. Clients must not reorder,
  cancel, or overlap effects contrary to queue rules.
- Provide all four starting Expressions and render the supplied GIF-based
  animation assets.

### 7. Card packs and shop activity

- Load pack definitions from shared and world card directories.
- Implement default rarity weights Common 70, Uncommon 20, Rare 8, Epic 1.8,
  Legendary 0.2, renormalized over rarities present in a pack. Draw uniformly
  within the selected rarity. Allow duplicates and independent draws.
- The Base and Tutorial packs cost 10 Bops and contain 3 draws with the exact
  catalogs in [planning-hints.md](./planning-hints.md).
- The shop activity shows only pack name, price, and card count before purchase.
  Require confirmation; insufficient funds changes nothing.
- Charge and persist granted results in one transaction before reveal. Use an
  operation ID so retry/reconnect cannot reroll or duplicate a purchase.
- The reveal remains presentation-only after commit.

### 8. Complete core UI screens

Match the supplied `doc/images` visual direction. Implement:

- **Main screen:** polished Board, Peeps List, physical Card View, favorite core
  cards, Look/Quick Actions/Chat bars, settings, toasts, floating numbers,
  bubbles, Action Log.
- **Room View:** card stacks, quantities, pickup/drop, authorized pin/unpin,
  selection, inspection, empty state.
- **Card Details:** front/back corners, rarity, dynamic description and stats,
  parent-view return behavior.
- **Emotes View:** radial category selector and owned cards.
- **Skills View:** 15-slot three-rank grid, locks, eligibility, slot/remove/
  replace, live bonuses.
- **Inventory:** Bops header, claim action, groups, filters, sorting, stack
  controls, equip/unequip/use/drop/inspect.
- **Self View:** level, Kudos, Level Up, stats, counters, statuses, and Swap
  Sticker.
- **Friends panel:** friends, status, requests, accept/decline/cancel/remove.
- **Prop Details:** large rotatable model with metadata.
- **Journal:** complete Tasks/Memories tabs, calendar/list layout, and empty
  states, but no persistence/mutations until Milestone 3.
- **Edit Room:** complete permission-denied/locked entry state; editing tools
  arrive in Milestone 3.

Every main view follows the shared modal/selection/Escape rules. Do not create
one-off overlay behavior.

### 9. Swap Sticker

- Reuse Sticker Designer as a non-modal global activity.
- Read `sticker_swap_cost` from `bops.yaml` (default 10).
- Charge only when confirming a different sticker. Cancel/current selection is
  free. Update the visible peep across all room clients after commit.

## Required tests

### Rules

- Modifier ordering, rounding, minima, maximum changes, and current-value clamps.
- Offline Energy recovery, Tired threshold, full-Energy refill rejection, and
  no-cost failures.
- Every status application/clear rule and timed/daily/stackable buff expiration.
- Level 0-15 transitions, surplus Kudos, max level, slot unlock/rank/ownership.
- Stack fill/split/merge/equip/drop/use invariants and passive bonus updates.
- Pack rarity selection using deterministic RNG injection; exact Base/Tutorial
  catalogs; idempotent purchase.
- Friend request races and single mutual relationship.

### Integration

- Two users observe prop/peep selection and room effects consistently.
- Target preview/confirm/cancel and concurrent target disappearance.
- Healing self/other/NPC acceptance contract and full-health rejection.
- Daily Bops across restart and two cooperating process instances sharing
  profiles.
- Sticker swap charging/idempotency and room broadcast.
- Shop disconnect after commit preserves exact revealed cards.

### Browser and presentation

- Exercise every listed screen at desktop, tablet, and phone portrait widths.
- Test mouse/touch board controls and ray-cast prop selection.
- Verify view replacement, nested Card Details, Escape order, stale selection
  clearing, and activity layering.
- Verify minimum touch targets, keyboard focus containment, reduced-motion
  behavior, readable contrast, sounds, and mute controls.
- Add stable screenshots for each design reference screen.

## Definition of done

- Every core UI screen is reachable and complete or shows an intentional
  Milestone 3 empty/locked state.
- The effective peep state displayed in Self is the same state used to validate
  actions.
- Props use supplied GLB models in Three.js and peeps remain in the sidebar.
- Levels, Kudos, Bops, Energy, statuses, equipment, skills, friends, emotes, and
  packs survive restart and concurrent use without duplication.
- Named cards and pack catalogs match planning hints exactly.
- No rejected action spends Energy, cards, Bops, or other resources.
- Targeted unit, integration, and browser suites pass.

## Manual review gate

Provide a seeded review account with representative cards, statuses, friends,
and level/skill state. Ask the user to review:

1. All core views against the screenshots.
2. Card/prop physical feel, targeting clarity, animations, and sounds.
3. Mobile portrait flow and touch controls.
4. Progression numbers, status feedback, and rejection messages.
5. Shop reveal, emote presentation, and friend-request UX.

Apply review tweaks before Milestone 3 while preserving tested gameplay rules.
