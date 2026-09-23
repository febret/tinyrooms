"""Authored prop behavior names recognized as built-in no-ops for Phase A.

Concrete dispenser, crafting, aura, and environment implementations arrive in
Phase C; until then each authored ``behavior:`` value maps to a synthetic
script id ``builtin:<name>`` whose module exports no handlers.
"""

from __future__ import annotations


BUILTIN_BEHAVIORS: dict[str, str] = {
    "centipedes": "builtin:centipedes",
    "crafting": "builtin:crafting",
    "dispenser": "builtin:dispenser",
    "key": "builtin:key",
    "litter": "builtin:litter",
    "locked-door": "builtin:locked-door",
    "shower": "builtin:shower",
    "shop": "builtin:shop",
    "supplies": "builtin:supplies",
    "vacuum": "builtin:vacuum",
}
