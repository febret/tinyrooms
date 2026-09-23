# Milestone 4 - Complete Tutorial World and Release Polish

## Outcome

Ship a polished tutorial house that teaches every core system through play. It
uses the supplied Hub, Playroom, house rooms, cards, props, peeps, models, and
art as its baseline; adds or improves assets only where required; includes
Molly and Pip; and implements the approved progression, chores, card economy,
activities, editing reward, sounds, animation, mobile support, and final
acceptance coverage.

This milestone does not invent a different storyline. The content decisions in
[planning-hints.md](./planning-hints.md) and the supplied
[tutorial world](../worlds/tutorial) are authoritative.

## Prerequisites

- Milestones 1-3 are complete, reviewed, and passing.
- All tutorial content must be expressible through world/card/task/activity
  definitions and trusted world behavior scripts. If a missing reusable engine
  capability is discovered, implement it in the appropriate engine module with
  tests; do not hard-code tutorial IDs into generic services.
- Existing assets are source material. No placeholder graphics, silent actions,
  broken models, or temporary text remain at release.

## Canonical tutorial content

Use [world.yaml](../worlds/tutorial/world.yaml),
[rooms.yaml](../worlds/tutorial/rooms/rooms.yaml),
[props.yaml](../worlds/tutorial/props/props.yaml),
[peeps.yaml](../worlds/tutorial/peeps/peeps.yaml),
[cards.yaml](../worlds/tutorial/cards/cards.yaml), and
[recipes.yaml](../worlds/tutorial/recipes.yaml) as the starting definitions.

The final world has these ten rooms and connections:

1. **Hub** - entry after initial sticker confirmation; portal to Playroom and
   vending prop for Base/Tutorial packs.
2. **Playroom** - Molly, Lazor Rush, dollhouse dispenser, portal back to Hub,
   entry into the dollhouse/house.
3. **Sunflower Foyer** - Pip, locked front door, routes to kitchen, sitting
   room, bedroom, and garden after unlock.
4. **Buttercup Kitchen** - healing room cards and crafting workbench; routes to
   foyer, utility, and sitting room.
5. **Mint Bathroom** - shower and Molly's litter tray; routes to utility and
   bedroom.
6. **Marmalade Sitting Room** - social/emote teaching and collectible animation
   emotes.
7. **Patchwork Bedroom** - collectible plushie and eventual owned-room editing.
8. **Helpful Utility** - guaranteed personal task tools, the reusable vacuum,
   and stairs to the Basement.
9. **Blue-Hour Basement** - darkness, the spare key, and centipedes.
10. **Pocket Garden** - the final outside destination with collectible cards.

Do not collapse these rooms merely to meet the original 5-10-room estimate; the
supplied ten-room layout is the approved concrete content.

## Tutorial progression

Define these personal, one-time task IDs and rewards. Completion writes a
generated memory in addition to the listed reward:

| Task ID | Completion | Reward |
| --- | --- | --- |
| `first-portal-trip` | First Hub-to-Playroom portal journey | 1 Kudos |
| `lazor-apprentice` | Molly captures the laser after at least 20 seconds | 1 Kudos |
| `clean-molly-litter` | Craft and use Poop in a Bag to finish the litter flow | 1 Kudos |
| `light-the-basement` | Successfully use a Hand Light in the Basement | 1 Kudos |
| `clear-the-centipedes` | Use the Vacuum Cleaner on the visible centipedes | 1 Kudos |
| `reach-the-garden` | Acquire the key and reach the Garden | 2 Kudos |
| `make-the-bedroom-yours` | Save the first valid owner decoration change | no currency; completion memory |

An idempotent `house-helper` meta objective completes after the four house
objectives (litter, light, centipedes, garden) and grants Patchwork Bedroom
ownership with no additional currency. Tool collection, crafting intermediate
steps, dialogs, card pickup, and pack opening are tutorial steps but do not
grant hidden currency.

### Phase 1 - Entry, navigation, level, and skill

1. Account creation and initial Sticker Designer finish.
2. User enters Hub with normal starting state: level 0, 10 Bops, 0 Kudos, four
   base Expression emotes, full 50 Health/80 Energy/100 Cleanliness, no
   equipment, no skill slots.
3. Journal starts a personal introductory task directing the user through the
   portal to Playroom.
4. First Hub-to-Playroom travel awards exactly 1 Kudos and records a memory.
   This reward must not depend on or wait for the shared dollhouse dispenser.
5. Task guides the user to Self and Level Up. Level Up spends the required
   Kudos and reaches level 1.
6. First reaching level 1 grants exactly one Sturdy card through the reward
   ledger and guides the user to place it in the first Script Kiddo slot.
7. Reconnects, repeated portal travel, repeated level checks, and duplicate
   events never duplicate Kudos or Sturdy.

### Phase 2 - Molly, activity, and cards

- Molly lives in Playroom.
- **Pet** is free flavor only, with no reward/stat change.
- **Chat** opens concise tutorial dialog covering play, skills, and supplies.
- **Play** launches room-bound Lazor Rush.
- A round starts explicitly and costs 1 Energy. Tune acceleration/collision so
  20 seconds is achievable on mouse and touch but still becomes challenging.
- The one-time personal task awards 1 Kudos only for a captured, completed
  round lasting at least 20 seconds. Closing, disconnecting, leaving, or any
  uncaptured/abandoned round does not qualify. Repeats update records but not
  rewards.
- The dollhouse Search is an unlimited weighted dispenser with one shared
  10-minute cooldown, granting Fancy Wallet or Ballet Shoes directly to the
  activating inventory. Enter always remains available and is independent of
  Search cooldown.

### Phase 3 - House card and social tutorial

- Pip's foyer dialog points to current Journal steps without forcing a single
  branch order.
- Kitchen room cards teach Room View, pickup quantities, Inventory, equipment,
  target-confirm healing, and optional drop/pin behavior.
- Sitting Room teaches selecting/pinning peeps, friend requests, Expressions,
  and picking up animation emotes.
- Hub vending opens the pack shop with unlimited stock.
- Base Pack: Smile, Sigh, Growl, Goof, Sturdy, Nimble, Charming, Stylish.
- Tutorial Pack: Ballet Shoes, Fancy Wallet, Hand Light, Juicy Drink, Lucille,
  Plastic Bag, Poop in a Bag, Poop, Pooper Scooper, Seal Plushie, Tasty Toast,
  Tomato Sauce.
- Both packs cost 10 Bops, draw three independent Common cards uniformly from
  their exact catalog, and allow duplicates.
- Tutorial-critical tools are provided by the personal supply shelf and never
  require a random pack outcome.

### Phase 4 - House chores and outside objective

Implement separate personal tasks, which may be completed in a flexible order:

1. **Clean Molly's litter box**
   - Personal supply shelf grants the authored starter kit once per user:
     Pooper Scooper, two Plastic Bags, two Hand Lights, and Juicy Drink.
   - Interacting with the dirty tray while owning/using the appropriate tool
     yields Poop according to the authored step.
   - At the kitchen workbench, user selects one Poop stack and one Plastic Bag
     stack and crafts one Poop in a Bag. Inputs are consumed only on success.
   - Returning/using the result completes the cleanup, plays a shared cleanup
     animation, awards once, and records memories. The tray remains a repeatable
     set piece: each user who has not completed the personal task can perform
     the full action even after another user has done so.

2. **Light the dark basement**
   - Basement starts dark; its hidden/disabled props cannot be selected or used.
   - User equips and Uses one Hand Light in the basement. Successful use
     consumes one card, reveals/enables the room for everyone, and sets or
     refreshes one shared expiry 30 real-time minutes in the future across
     disconnect/restart. A user who has not completed the personal task may use
     a Hand Light while the room is already lit; it refreshes the shared expiry
     and grants that user's credit.
   - Full visual/audio feedback makes activation and expiry clear. A second
     Hand Light is available from the guaranteed supplies so users are not
     permanently blocked.

3. **Remove basement centipedes**
   - Vacuum stand grants/loans a reusable Vacuum Cleaner without a random gate.
   - Centipedes are actionable only while visible and the user has the valid
     tool.
   - Successful vacuuming plays a shared flee/cleanup animation, completes
     personal credit exactly once, and does not consume the reusable vacuum.
     The centipede set piece returns after the animation for users who still
     need the personal task; completed users can repeat it for flavor but earn
     no reward.

4. **Get outside**
   - Spare key can be obtained from the lit basement.
   - The locked foyer door visibly rejects use without the key and changes
     nothing.
   - A valid unlock uses the authored key semantics, persists the shared door
     state, and permits garden travel. If another user already unlocked it, a
     user carrying their own key may still choose `Use key` to satisfy their
     personal unlock step without changing shared state.
   - First Garden arrival after personally acquiring the key completes the task
     and records a memory; arriving through an already-open door without the key
     does not complete it.

5. **Cleanliness and recovery**
   - The Bathroom shower restores Cleanliness; there is no Hub cleaning prop.
   - Demonstrate Stinky only through a controlled tutorial condition if it can
     be done without tedious waiting or destructive surprise. Always provide a
     clear recovery path.

Encode the table above in tutorial task YAML. Rewards must use the generic
idempotent ledger.

### Phase 5 - Ownership and creation

- Completing the designated house-task set grants the user ownership or
  authorized editing of the Patchwork Bedroom through the normal ownership
  service.
- Journal guides the user to Edit Room.
- User adds an approved decorative prop, moves/rotates/scales it, changes an
  approved visual setting, saves, and sees the update from another client.
- This tutorial step never grants builder authority and cannot edit gameplay.

## Card and collectible audit

Before content sign-off, verify:

- Sturdy, Nimble, Charming, Stylish exactly grant +1 to their named stat and are
  global Common Script Kiddo skills.
- Spirited is a fifth useful skill card (+10 maximum Energy) available as
  authored world content; it need not be in the Base Pack unless the planning
  hints are changed.
- Juicy Drink is self-only, one-use, stack limit 10, restores 25 Energy, costs
  zero, works while Tired, and rejects at full Energy without consumption.
- Tasty Toast/Tomato Sauce restore 10/25 Health, cost 2 Energy, target self or
  another Health peep, and reject no-effect/unavailable targets without cost.
- Ballet Shoes is reusable, non-stackable passive equipment with +1 Charisma
  and +2 Fanciness and no Use action.
- Lucille and Seal Plushie are decorative items and never summon NPCs.
- Wave, Happy Dance, and Heart are collectible GIF animations; Starlight is a
  collectible room-wide Effects emote using the shared effect queue.
- House Key and Vacuum Cleaner are explicit quest items outside the pack
  catalogs unless later design direction says otherwise.
- Every card has front art, back association, type, scope, rarity where
  collectible, concise description, and generated accurate details.

## Gameplay coverage map

The tutorial must expose each reusable player-facing system at least once:

| System | Tutorial exposure |
| --- | --- |
| Account, sticker, active session | Initial creation and mandatory Sticker Designer |
| Chat, bubbles, peep selection | Molly/Pip dialogs and multiplayer rooms |
| Room navigation and Energy | Hub portal and house exits |
| Core cards and modal views | Guided Journal steps open Room, Inventory, Self, Skills, Emotes, and Journal |
| Room cards and equipment | Kitchen healing cards and Bedroom/Sitting Room collectibles |
| Card targeting and rejection | Healing a full/valid peep and tool-on-prop chores |
| Stats, counters, status, buffs | Sturdy, Ballet Shoes, Energy, healing, shower, Hand Light timer |
| Kudos, levels, Bops | Portal reward, manual Level Up, daily claim, pack purchase |
| Skills | Sturdy grant and first Script Kiddo slot |
| Packs and stacking | Hub shop and duplicate-capable three-card reveals |
| Props and dispensers | Dollhouse, supply shelf, and house interaction props |
| Peeps, friends, dialogs | Molly, Pip, friend request step |
| Activities | Sticker Designer, Lazor Rush, shop, and crafting |
| Tasks and memories | Seven tasks, meta objective, generated/manual memory prompt |
| Emotes and room effects | Starting Expressions, GIF pickups, Starlight |
| Crafting | Bagged-poop recipe with selected stacks |
| Room ownership/editing | Patchwork Bedroom reward and first saved layout |

World-authoring, privileged administration, and cross-world handoff are verified
through Milestone 3/editor acceptance scenarios rather than taught to ordinary
tutorial users.

## Art, sound, and performance

- Audit all supplied GLBs and textures for consistent hand-drawn retro style,
  scale, pivot, lighting response, and mobile polygon/texture budgets.
- Complete/rebuild assets reproducibly in `tools/`; retain editable source art
  and deterministic output settings.
- Provide final board art for every room, final sticker/NPC art, card fronts,
  card backs, status icons, activity art, and UI chrome.
- Add sounds to every action category: card pick/select/flip/drop, buttons,
  view/page changes, chat, footsteps/portal travel, prop interaction, crafting,
  dispenser, pack purchase/reveal, level up, rewards, rejection, shower,
  flashlight, vacuum, door unlock, emotes, and Lazor Rush.
- Use a centralized audio manager with user gesture unlock, volume/mute,
  non-overlapping limits, and no autoplay errors.
- Add purposeful animation: card spring/tilt, peep marker reaction, prop
  selection, view transitions, floating counters, toasts, effects, pack reveal,
  task completion, and level up. Honor reduced motion.
- Optimize/cached assets for mobile. Define measurable budgets and verify on a
  mid-range phone profile: initial compressed transfer, texture memory, stable
  frame rate, and no unbounded DOM/Three.js/audio allocations.

## Accessibility and responsive acceptance

- All gameplay remains operable without hover.
- Keyboard users can reach actions, close views, manage cards, dialogs, and
  editors; focus is visible and restored logically.
- Every meaningful image/model has a text label/description; status and rarity
  do not rely on color alone.
- Phone portrait keeps own peep, Board, favorite cards, Look/Quick Actions, and
  Chat usable. Overlays scroll internally and activity maximize fits between
  sidebar/bottom controls as designed.
- Test touch drag thresholds, pinch/rotate, card targeting, Lazor Rush, and room
  editing on actual touch emulation and at least one real mobile browser.

## End-to-end acceptance scenarios

Automate isolated black-box scenarios against real HTTPS servers:

1. Fresh account -> sticker -> Hub -> portal -> 1 Kudos -> Level Up -> Sturdy
   grant -> slot skill.
2. Molly dialog/Pet and a qualifying/non-qualifying/abandoned Lazor Rush round.
3. Supply grant -> litter interaction -> exact-stack crafting -> cleanup.
4. Hand Light -> 30-minute basement state -> key -> locked-door unlock ->
   Garden.
5. Vacuum acquisition -> dark rejection -> lit success -> centipede completion.
6. Room cards, heal full/no-effect, heal another user, emotes/effect ordering,
   daily Bops, pack purchase/reveal, duplicates, and restart persistence.
7. Friend request with one user offline and monthly Journal aggregation.
8. Bedroom ownership -> constrained edit -> second-client live update.
9. Two-user concurrency at dispenser, shared props, room cards, and task credit.
10. Restart during active timed light/buff and verify elapsed-time
    recovery/expiry (the dispenser cooldown instead resets on restart).
11. Desktop and phone playthrough with screenshots at every major view.
12. Trusted cross-world round trip preserving shared state and restoring native
    tutorial cards on return.

Use disposable profile/world-state paths for every black-box run. Never point
acceptance automation at a developer's live world.

## Release audit

- Cross-reference every non-future requirement in
  [design.md](./design.md) to an automated test or named manual check.
- Cross-reference every decision in
  [planning-hints.md](./planning-hints.md) to final definitions and tests.
- Validate all YAML, script references, assets, exits, dialogs, task triggers,
  rewards, packs, recipes, and editor whitelists in one content-lint command.
- Run unit, integration, browser, two-client concurrency, migration, restart,
  and black-box suites.
- Confirm no file exceeds 1,200 lines and every public cross-module function is
  documented.
- Confirm production static routes cannot expose `.local`, users, databases,
  drafts, source YAML outside intended read APIs, or behavior source.
- Confirm clean startup creates only intended runtime state and no tracked file
  changes.
- Update the root README with exact setup, configuration, run, editor,
  asset-build, backup, and test instructions.

## Definition of done

- A new user can learn and complete the entire tutorial without external
  instructions, luck-gated tools, admin commands, or waiting on the dollhouse.
- All ten supplied rooms, at least twenty supplied props, Molly and Pip, four
  chore/outside objectives, crafting, packs, cards, emotes, progression,
  Journal, friends, room editing, and Lazor Rush are polished and persistent.
- Every action has appropriate sound and feedback; graphics are final and
  coherent.
- Desktop and touch/mobile flows meet the design and pass acceptance tests.
- No duplicate rewards, purchases, crafts, pickups, or task credit occur under
  retries, reconnects, concurrent clients, or restart.
- Release audit finds no uncovered initial-release requirement.

## Final manual review gate

Give the user a clean review account and a second observer account. The user
plays the tutorial organically and reviews:

1. Story clarity, pacing, task order flexibility, and reward balance.
2. Every room's composition, lighting, prop scale, and visual identity.
3. Molly/Pip personality, dialogs, Lazor Rush difficulty, and activity windows.
4. Card economy, pack reveal, crafting clarity, and recovery from mistakes.
5. Sound mix, animation timing, reduced-motion behavior, and mobile ergonomics.
6. Bedroom editing and shared multiplayer feedback.

Log and apply the final tuning pass, rerun affected automated scenarios, then
run the complete release audit before declaring the game complete.
