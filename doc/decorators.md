# Tinyrooms Sprite Decorators

Decorators are combinations of sprites and visual modifiers that can be applied to objects, peeps, and props.

Decorators are temporary effects. They are loaded from YAML and applied at runtime, but they are not persisted to the worldstate database.

## Definition locations

Decorator definitions are loaded from:

1. `data/decos/*.yaml` (server-wide defaults)
2. `<world>/decos/*.yaml` (world-local overrides)

If both define the same decorator reference, the world-local definition wins.

## Referencing format

A decorator can be referenced as:

- `[filename:]<decoratorId>`

Where:

- `filename` is optional and defaults to `main` (for `main.yaml`)
- `decoratorId` is the top-level decorator key inside that file

Examples:

- `on_fire` (same as `main:on_fire`)
- `status:frozen`

## Definition schema

Each YAML top-level key is a unique decorator ID within that file.

```yaml
on_fire:
  sprite: $effects/fire/burn
  glow:
    intensity: 0.8
    color: "#ff4400"
  animation: pulse
```

Fields:

- `sprite` (optional string): sprite/image reference layered on the entity.
- `glow` (optional object): visual glow payload passed to the client.
  - `intensity`: recommended float range `0..1`
  - `color`: CSS color string
- `animation` (optional string): overlay animation name. Supported values are:
  - `wobble`
  - `spin`
  - `pulse`

## Runtime behavior

- Entities can have multiple decorators.
- The same decorator can only be applied once per entity.
- Decorators are included in room payloads:
  - `room-object` entities include `decorators`
  - room stage props include `decorators`
- If a decorator has `sprite`, payloads include resolved sprite metadata in `sprite_display` when resolution succeeds.

## Socket API

- `apply_decorator`  
  Payload: `{ "entity_type": "object|peep|prop", "entity_id": "...", "deco_id": "[filename:]id" }`  
  Applies the decorator if it exists and is not already on that entity, then broadcasts updated room state.

- `remove_decorator`  
  Payload: `{ "entity_type": "object|peep|prop", "entity_id": "...", "deco_id": "[filename:]id" }`  
  Removes the decorator from the entity and broadcasts updated room state.