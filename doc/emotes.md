# Emotes Specification
NOTE: emotes replace the current actions implementation in tinyrooms/actions.py

Emotes are predefined visual / text actions that can be triggered by users (or any scripted entity), can optionally target other entities, and unlike other actions do not have any gameplay effect.

Emotes are defined under data/emotes in a set of yaml files. Worlds can define additional emotes, which are typically used for custom peep  behaviors.

Emotes can be referenced in this format: [.filename].<emoteId>[@target]

where:
- filename is the optional name of the file containing the emote ID. when unspecified, assume it is main (ie use defs from emotes/main.yaml).

When a world emote filename overlaps a server emote filename, emotes from both are merged on load, with world emotes taking precedence on name clashes.
- target is an optional reference to another entity such as an object, peep, etc.

Emotes can be invoked in a standard chat message, for instance:
"hello! .smile@foo"
makes the character say "Hello!" and then smile at the entity called foo. Note that a chat message is implicitly prefixed by the .say emote and can be broken into many separate emote sequenced one after the other

The .say emote is used to send plain chat message. it is implemented like any other emote, as they all use the same message sending functions.

Emotes have the following properties:
- a unique emote ID
- an optional label and description
- rules for generating first person, second person (when the target is a user) and third person messages, including ways to reference the target and source and generate random message combinations
- optional animations to play on the source sprite. 

## YAML Schema

Emotes are defined in YAML files under `data/emotes/`. Each entry uses the following schema:

```yaml
emote_id:
  label: "emoji or short string"          # optional; shown in the client action bar
  description: "Short description"         # optional
  msg:                                     # message definitions
    - verb: ["You smile", "$0 smiles"]     # [first-person, third-person]
      target: "at $1"                      # optional, defaults to "$1"
      end: [".", "warmly"]                 # optional, defaults to ["."]
  animations: "!0"                         # comma-separated animation steps (default: "!0")
```

`msg` is a list of message-definition dicts. Emotes support at most one target.

### Placeholder substitution

- `$0` — sender's display label
- `$1`, `$2`, … — display labels of the 1st, 2nd, … target refs
- `$-N` — same as `$N` but with leading articles stripped
- `$*` — "melted" label combining tokens from all refs
- `<<text>>` — expands to a client-side text-reference link `[[@ text ]]`

## Animations

The `animations` field is a comma-separated string of steps:

| Step syntax | Meaning |
|-------------|---------|
| `!N` | Emit the message definition at index N from `msg` (0-based). Default: `!0` |
| `#<seconds>` | Pause for this many seconds (executed in a background thread, never blocks the socket handler) |
| `.<emoteID>` | Run another emote (one level of nesting only; silently ignored at depth ≥ 1) |
| anything else | Treated as a sprite animation ID; emits an `emote_anim` socket event to the room |

The default animation when `animations` is absent is `!0` (emit first message).

## Implementation modules

- **`tinyrooms/emotes.py`** — `load_emotes()`, `emote_defs` dict, `do_emote()`
- **`tinyrooms/text.py`** — `make_emote_text()` generates `(first, second, third)` tuples
- **`tinyrooms/message.py`** — `parse_message()` scans all tokens for inline emote refs
- **`tinyrooms/types.py`** — `ParsedEmote` namedtuple, `ParsedMessage.emotes` field
- **`tinyrooms/actions.py`** — simplified to only handle `.go` navigation
- **`tinyrooms/world.py`** — calls `emotes.load_emotes()` with world emotes path on load

## Socket events

- **`emotes_def`** (server → client) — sent on connect and heartbeat when stale; payload `{"emotes": {emote_id: def, ...}}` (flat keys only, no `filename.id` qualified keys)
- **`emote_anim`** (server → room) — emitted by sprite animation steps; payload `{"entity": "peep", "entity_id": username, "anim_id": "..."}`

## Navigation (non-emote)

The `.go` token as the first word of a message remains a non-emote navigation action handled by `actions.do_action()`. All other dot-prefixed tokens are treated as emote invocations.
