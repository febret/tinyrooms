"""Authored prop behavior names recognized as built-ins.

Most built-ins map to a synthetic script id ``builtin:<name>`` whose module
exports no handlers; concrete container, dispenser, crafting, and environment
implementations live in the command and service layers. Built-ins with real
handlers live in ``server.behaviors.builtin_<name>`` modules so every world
can share them.
"""

from __future__ import annotations


BUILTIN_BEHAVIORS: dict[str, str] = {
    "container": "builtin:container",
    "crafting": "builtin:crafting",
    "dispenser": "builtin:dispenser",
    "locked-door": "builtin:locked-door",
    "recipe-book": "builtin:recipe-book",
    "shop": "builtin:shop",
    "supplies": "builtin:supplies",
}
