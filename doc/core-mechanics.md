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


## UI
User status information is displayed in the status bar at the top of the UI. The status bar shows:
- User name and level title. Clicking opens an activity panel to customize character sprite (based on sprite unlocks), traits, and character name. Changing these properties costs Bops.
- A bar showing current received Kudos vs total needed for the next level. Clicking opens an activity panel with level descriptions, required Kudos, unlocks, etc.
- An indicator of how many Kudos are left to give today (goal: reach zero). This indicator glows more as more Kudos are given. Clicking opens an activity panel showing who the user gave the most Kudos to and who gave them the most Kudos.
- An indicator of how much Juice the user has left. Clicking opens an activity panel showing current recharge rate and options to buy juice packs of different sizes with Bops.