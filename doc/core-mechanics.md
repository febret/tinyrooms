# Tinyrooms Main Gameplay Mechanics
This document describes the primary gameplay mechanics in tinyrooms.
Gameplay is intentionally customizable: character (peep) attributes, stats, and status effects are not fixed and can be assembled from a library or custom definitions.

The main building blocks for tinyrooms gameplay are:
- Peep Attributes: Main peep properties that can increase with level. Examples: Intelligence, Constitution.
- Peep Stats: Current character status values with a maximum. Examples: Health, Mana, Stamina.
- Peep Buffs: Temporary positive or negative effects applied to attributes or stats.
- User Traits: Long-term modifiers users apply to their peeps.
- User Level: Gained with Kudos; unlocks peep sprites, emotes, extra trait slots, and other bonuses.
- Kudos: Earned for positive behavior and given by other users. Users receive daily Kudos they can donate.
- Juice: Energy users spend on any server action (for example, any socket message).
- Bops: Currency users gain daily, based on level.

The sections below provide more details on some of these. 

## User Traits
Traits are long-term modifiers users can apply to their peeps.
Traits can be changed in the character editor and selected from a library of available traits.
Traits are defined in YAML files in `data/traits`.
Traits apply one or more buffs to the user peep, but those buffs do not time out. For example, a `Strong` trait can apply a `Strength +20` buff.

Traits can also modify other gameplay features, like daily kudos, bop gain rates, etc.

Traits can have an optional opposite trait. Matching or opposite traits can apply positive or negative vibe modifiers.


## Juice
Juice (short, JUS, icon 🧃) is a form of energy users spend on any action they perform on the server (i.e. any socket message). 
When a user is out of juice, they cannot interact with the world.
Juice recovers over time based on a user-specific rate.
Max Juice depends on level.
Juice can be used to soft-ban users and limit gameplay time.

Juice applies to users only, not NPC peeps.
Users without juice, or inactive for long periods, are shown blurry/semitransparent.

Users can buy juice packs (🥫) with Bops.

## User Level
Levels are gained with Kudos and unlock peep sprites, emotes, extra trait slots and other bonuses.
This is the level list, with Kudos required to unlock:
- L0 - Guest:
- L1 - 🔰Novice: 10
- L2 - 🌱Student: 20
- L3 - ⚡Senior Student: 30
- L4 - 💧Candidate: 40
- L5 - 🟦 Acolyte: 50
- L6 - 🦭 White Scholar: 60
- L7 - 🐢 Green Scholar: 70
- L8 - 🐙 Red Scholar: 80
- L9 - ⬛ Master: 90
- L10 - 🔳 Grandmaster: 100

## Object Crafting
Object crafting lets users transform inventory objects into new objects using recipe metadata on thing definitions.

Crafting is data-driven and world-specific:
- Recipes are defined in thing YAML under world/server `things/` directories.
- Crafting checks current user level and inventory state.
- Crafted outputs are normal object instances and use the same inventory persistence flow as pick/drop.

### Thing definition fields
The following optional thing properties are added for crafting:

| Field | Type | Description |
| --- | --- | --- |
| `craftable_mode` | string | Either `ALWAYS` or a comma-separated list of thing IDs that can craft this thing. |
| `craftable_level` | integer | Minimum user level required to craft this thing. |
| `craftable_inputs` | string | Comma-separated list of required input thing IDs. Each entry can be `thing_id` or `thing_id:count` (count defaults to `1`). |
| `craftable_stack_size` | integer | Optional output count per craft. Only valid for stackable thing definitions. |

Parsing rules:
- Comma-separated values trim whitespace and ignore empty segments.
- Input counts must be positive integers.
- Duplicate input IDs are merged by summing counts.
- Thing IDs must resolve in the active world thing definition set.

### `craftable_mode`
- `ALWAYS`: the recipe is available directly to the user (no crafting station required).
- `<thing_id_a>,<thing_id_b>,...`: recipe is available only when the user is interacting with one of those object types.
  - Interaction source uses existing target/use flow (`:use @obj:<id>`) and opens crafting content in the Activity Panel.
  - Matching is done against the target object's `thing_id`.

### Crafting UI and command flow
Crafting uses existing UI surfaces rather than a new screen:
- **Activity Panel** is the primary crafting UI.
- A new `:craft` command family drives recipe listing and execution.

Recommended command forms:
- `:craft` -> open craftable recipe list for the current user context.
- `:craft <thing_id>` -> attempt one craft of `<thing_id>`.
- `:craft <thing_id> <count>` -> attempt repeated craft operations when allowed.

Activity Panel content should include:
- recipe label and output amount
- required level vs current user level
- input requirements with owned/required counts
- clickable craft links using the existing command-link format (`[[Craft|:craft ...]]`)

### Craft execution rules
On `:craft` attempt, server validates in this order:
1. recipe exists and has valid crafting metadata
2. user meets `craftable_level`
3. recipe is available in current mode/context (`ALWAYS` or active crafting object)
4. user inventory has required input quantities

If validation passes:
1. consume required input objects from inventory
2. create output object(s) using crafted thing definition
3. place outputs in user inventory (`location_id = "@<username>"`)
4. emit inventory update and success feedback in Activity Panel/chat
5. persist world state

### Output quantity behavior
- Default output is `1`.
- If `craftable_stack_size` is set, output amount is that value.
- `craftable_stack_size` is only valid on stackable things. Using it on non-stackable thing definitions is a recipe-definition error and the recipe must not be craftable until fixed.

### YAML example
```yaml
wood_plank:
  type: object
  label: Wood Plank
  description: A smooth crafting plank.
  icon: "img:images/wood_plank.png"
  craftable_mode: "workbench,carpenter_table"
  craftable_level: 2
  craftable_inputs: "wood_log:2,sandpaper"
  craftable_stack_size: 4
```

### Backward compatibility
- Thing definitions without `craftable_mode` are not craftable.
- Existing non-crafting object behavior is unchanged.
- Existing inventory and room object protocols remain unchanged except for normal inventory updates caused by craft actions.


## UI
User status information is displayed in the status bar at the top of the UI. The status bar shows:
- User name and level title. Clicking opens an activity panel to customize character sprite (based on sprite unlocks), traits, and character name. Changing these properties costs Bops.
- A bar showing current received Kudos vs total needed for the next level. Clicking opens an activity panel with level descriptions, required Kudos, unlocks, etc.
- An indicator of how many Kudos are left to give today (goal: reach zero). This indicator glows more as more Kudos are given. Clicking opens an activity panel showing who the user gave the most Kudos to and who gave them the most Kudos.
- An indicator of how much Juice the user has left. Clicking opens an activity panel showing current recharge rate and options to buy juice packs of different sizes with Bops.