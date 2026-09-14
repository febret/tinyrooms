Implement the tinyrooms game server and client, based on the game design 
provided in `design.md`.

You should keep iterating until ALL elements described in the design document are
implemented, with final graphics and sound (no prototypes or placeholders) and
full client/server logic.

If any aspect of the design is unclear, or if there are design / implementation
alternatives to consider make reasoable choices for this project based on its
design objectives. Keep things simple.

When screenshots are available, follow them as closely as possible.
For UI features missing screenshots, infer the style, layout and structure from
the rest of the design screens.

When example definition yaml files are provided in the design document, try to
follow their schema but feel free to change it if the implementation requires it.


## Requirements
Add sounds to all actions. For instance picking up / selecting cards should have
sounds reminiscent of interacting with actual physical cards.

Once the tinyrooms server and app is complete, extend the tutorial world to add
5-10 new rooms, 10-20 props, 1-2 NPCs (including Molly the cat) to introduce the
user gradually to all game mechanics. Make the world look like the inside of a house, with
three primary quests:
- clean Molly's litter box
- get outside of the house getting keys from the basement
- light up the dark basement (props invisible / disabled) using a consumable light source (light torch) which makes the basement bright for 30 minutes.
- get rid of house centipedes in the basement using a vacuum cleaner

Also create a reasonable set of skill cards (~5) in the base card set. Add a few
collectible animation emotes (gif based) in the tutorial world (note that the emotes
should be defined in the base card set so they can be reused across worlds).

Create all 3D assets and images you need for the tutorial world. Use a simple but
colorful style for assets, going for a hand-drawn retro look. Make assets as high quality 
as possible assuming this game must run on mobile devices as well.

Also create admin interfaces for editing the loaded world, looking at the card database,
and editing the room props (for room owners)

Make the UI engaging and fun to use. Make both cards, peeps and the board feel
like true physical objects. Add animations throughout the UI and gameplay.

## Implementation Notes
- Use the assets and resources available in `./data`. Create any missing assets
you need such as extra UI graphics and sounds. 
- Use FastAPI / uvicorn for the server. Creatse self-signed temorary certificates
to serve content over https
- Use vanilla javascript / html / css for the client. Use three.js to render the 3D
room view.
- Ensure the game UI is fully responsive and functional both on standard browsers 
and touch-based mobile browsers (including portrait view on phones). Scale down
the UI gracefully, adjusting the layout and visibility of elements as needed.
- Your output must be polished. Graphics should be high quality while following the
design screenshots. Interactions should be delightful and engaging, use sounds and
flourish animations throughoug it to make the user interactions pleasant and dynamic.
- Keep the code structure simple to follow, break down components along intuitive 
lines while keeping all source file sizes to less than 1200 lines of code. Provide 
docstrincs for any functions exposed across source file boundaries. Add 1-2 comment lines
for any non-trivial block of code.

## Technical Constraints from the Design
The [design document](./design.md) defines gameplay and user-visible behavior.
The following constraints preserve the implementation notes separated from that
document. Directory paths in this section are relative to the repository root.

### Accounts
- The account-creation passphrase is configured at server startup using
  `TRSERVER_NEW_ACCOUNT_PASSPHRASE`.
- User account information is stored in `users`, or the path specified by
  `TRSERVER_USERS_PATH`.

### Client and Presentation
- The client is a single-page web app. The Board is rendered using Three.js.
- The `show_activity_log` client configuration option controls Action Log visibility.
- Card names and short descriptions come from card definitions. Longer descriptions
  and equipment information are generated at runtime from the card's stats,
  status, and other properties.
- Room-wide visual effects from actions and Effects emotes share an implementation
  and a queue, ordered by receipt on the server.

### Content Definitions
- Card definition YAML files and related assets are located in the
  `data/cardsets` subdirectories and the loaded world's `cards` directory.
- A propset is a directory containing related prop definitions, their 3D models,
  and any other required assets. World-specific props are defined in the loaded
  world's `props` directory.
- Peeps are defined in YAML files in the loaded world's `peeps` directory.
- NPC behavior scripts are Python files in the same directory as the peep
  definition YAML files. Interactive props can also have behavior scripts.
- Dialog trees are defined declaratively in peep definition YAML files.
  Behavior scripts can start dialogs, and dialog nodes can call behavior scripts
  for custom branching and side effects.

### World State
- Worlds are stored as definition files containing the initial room definitions
  and a worldstate database containing the dynamic live state.
- The worldstate tracks peep locations, prop states, room cards, and room ownership.

### Activities
- Activity implementations are located in `activities`.
- Each activity runs in its own iframe and is served at a separate URL.

### Commands
- All user interactions, including quick actions, card plays, and chat messages,
  are sent to the server as command strings.
- Quick actions and card actions are implemented as commands, with corresponding
  user-facing commands described in the design document.

## Approved Content Decisions
These content decisions were separated from the reusable gameplay design.
Further tutorial-world details will be supplied here; do not invent missing
storylines or interpret all screenshot scenery as required content.

### Tutorial World
- Use the supplied Hub and Playroom, portal, and dollhouse interactions as the
  starting point. The Hub is the entry room after initial sticker confirmation.
- The introductory personal task awards 1 Kudos for the first Hub-to-Playroom
  journey through the portal, then guides Level Up in Self View. It must not
  require waiting for the shared dollhouse dispenser.
- First reaching level 1 awards one Sturdy skill card and guides slotting it.
- Molly is an NPC in the Playroom. Play launches Lazor Rush; Pet gives a flavor
  reaction; Chat provides short tutorial help. Pet and Chat are free and have
  no rewards or stat effects.
- A Hub vending prop offers the Base and Tutorial packs with unlimited stock.
- Cleanliness recovery is provided by a shower in a bathroom in the tutorial
  house, not a Hub cleaning prop. Further shower and house details will be
  provided in this prompt; their layout and interactions are not settled here.
- The screenshot house/litter-box/locked-door/key storyline is not automatically
  required merely because it appears in mockups.
- The personal one-time Lazor Rush task awards 1 Kudos for a completed round
  lasting at least 20 seconds. Award only when Molly catches the laser and ends
  the round; abandoned rounds do not qualify. Repeating does not reward again.
  Tune difficulty so the target is achievable on mouse and touch.

### Pack Catalogs
- Base and Tutorial packs each cost 10 Bops and contain 3 independent draws,
  allowing duplicates and following the design's rarity-weight selection rules.
- The Base Pack contains Smile, Sigh, Growl, Goof, Sturdy, Nimble, Charming, and
  Stylish. All eight cards are Common, giving each a 1-in-8 chance per draw.
- The Tutorial Pack contains Ballet Shoes, Fancy Wallet, Hand Light, Juicy Drink,
  Lucille, Plastic Bag, Poop in a Bag, Poop, Pooper Scooper, Seal Plushie,
  Tasty Toast, and Tomato Sauce. All twelve are Common, giving each a 1-in-12
  chance per draw. This catalog does not itself require the screenshot storyline.

### Named Card Rules
- Sturdy, Nimble, Charming, and Stylish are globally available Script Kiddo-rank
  skills. They grant +1 Constitution, +1 Dexterity, +1 Charisma, and +1 Fanciness,
  respectively, while slotted, following the reusable and duplicate skill rules.
- Juicy Drink is self-only, one-use, stack limit 10, restoring 25 Energy per copy.
  It costs no Energy and works while Tired. Reject use at full Energy without
  consumption; discard restoration above maximum.
- Tasty Toast restores 10 Health; Tomato Sauce restores 25 Health, replacing the
  Concentration effects in the example data. Both are one-use, stack limit 10,
  and cost 2 Energy. They target self or another peep with Health. Reject full
  Health/no-effect/unavailable targets without cost. Sick does not block use;
  Tired does. User healing requires no consent prompt; NPC behavior may reject it.
- Ballet Shoes is reusable, non-stackable passive equipment: +1 Charisma and
  +2 Fanciness while equipped, no separate Use action. These values explicitly
  adopt the mockup.
- Lucille is a named collectible seal plushie item, not a summoned NPC.
  Lucille and Seal Plushie are decorative collectibles without active effects
  or gameplay bonuses.
