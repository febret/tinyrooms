# Vibes Spec
Vibe is a score (-100 to 100) that determines how good/bad the reputation of a peep is with respect to another peep (with 0 meaning the target peep is unknown by the source peep)

Vibes apply to both user controlled peeps and NPCs. Vibes are calculated at runtime based on several factors:
- a baseline score that depends on specific past actions between two peeps. This baseline is saved in the peep data on the worldstate db.
- any other modifiers calculated at runtime based on other peep properties.

Baseline vibes are saved in a `vibes` column on the `peeps` table (worldstate DB), which stores a `{target_peep_id: score}` JSON dictionary with the baseline vibe scores for a set of target peeps. **This applies to both NPC and user-controlled peeps.** User peep vibes are persisted exclusively in the worldstate `peeps` table (not in `profile.yaml`).

Baseline vibe scores are recalculated by the server every minute. Baselines decay by a set amount (default 0.1 point/minute). Baseline vibes decay only for active peeps, ie peeps that are present in the world (either npc or connected users)

Reciprocal vibes are added as part of a peep description when selecting it.

In addition to single peeps, it is also possible to calculate the "Room Vibe" for a target npc. The room vibe is the average of all other peep vibes with respect to the target npc.

Vibes can affect npc peep behavior: an npc can react differently to a user interaction based on the vibe, or can perform different actions in a room / leave based on the room vibe. The `get_target_vibe` and `get_room_vibe` functions can be used to get the vibe for a source peep wrt a target peep or wrt the current room.

Emote definitions have an optional `vibe` property that contains a vibe modifier that will be applied to the target of the emote. For instance a `.smile` emote with `vibe = 0.5` increases the vibe of the target of the emote towards the source of the emote by 0.5.

Note that the actual vibe value between two peeps can exceed the (-100, 100) range, but for gameplay and display purposes it is clamped to this range.

## Vibe descriptors
The following descriptors are used in text descriptions of the vibe towards a target peep:

| Score | Descriptor |
|-------|-----------|
| 0 | (unknown — vibe record removed from source peep) |
| 1–25 | Friend 🙂 |
| 26–50 | Buddy 😃 |
| 51–75 | BFF 🥰 |
| 76–100 | Supreme BFF 😍 |
| -1 to -25 | Annoyance 🙄 |
| -26 to -50 | Enemy 😤 |
| -51 to -75 | Nemesis 😡 |
| -76 to -100 | Archnemesis 👿 |

