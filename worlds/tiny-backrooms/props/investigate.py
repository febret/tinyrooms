"""Investigate behavior: search props for picture pieces, loot, or weapon caches.

World-authored so the core server stays free of Tiny Backrooms rules.
Instance ids carry the outcome (``inv-<level>-<nn>-<kind>``), which keeps the
puzzle deterministic and solvable:

- ``piece0..2`` hand over that level's photo quarter, once per player.
- ``cache`` hands over the level weapon, once per player.
- ``loot`` cycles a level loot table by instance index.
- ``empty`` is flavor only.
- ``fin-`` memorial instances play the escape cutscene.

Level monsters live in dedicated lurking props (see ``lurking.py``), not here.
"""

from __future__ import annotations

LEVELS = ("br", "ud", "op")

WEAPONS = {"br": "lullaby-music-box", "ud": "iron-bat", "op": "elder-sign"}

LOOT = {
    "br": ["fluorescent-tube", "almond-water", "portal-jerky", "mold-bread"],
    "ud": ["demodog-tooth", "almond-water", "static-candy", "portal-jerky"],
    "op": ["ectoplasm-vial", "black-seashell", "almond-water", "static-candy"],
}


def _instance_id(context) -> str:
    target = context.target
    if target is not None and getattr(target, "instance_id", None):
        return str(target.instance_id)
    return ""


def _level_of(instance_id: str) -> str | None:
    for level in LEVELS:
        if instance_id.startswith(f"inv-{level}-"):
            return level
    return None


def _kind_of(instance_id: str) -> str:
    parts = instance_id.split("-")
    return parts[-1] if parts else ""


def on_quick_action(context, event):
    if event.action != "search":
        return
    instance_id = _instance_id(context)
    if instance_id.startswith("fin-") or "sun-memorial" in instance_id:
        if context.has_card("tb-restored-op"):
            context.update_task_progress("tb-escape-3", "reach-surface")
            context.cutscene("escape-dawn", audience="room")
            context.grant(kudos=3, ledger_key="tb-escaped")
            context.feedback("Sunlight. Real, warm, indifferent sunlight. You escaped the Tiny Backrooms.", "success")
        else:
            context.feedback("The sun is warm but the way is not open. Restore all three photographs first.", "error")
        return
    level = _level_of(instance_id)
    if level is None:
        return
    kind = _kind_of(instance_id)
    if kind in ("piece0", "piece1", "piece2"):
        piece = f"tb-piece-{level}-{kind[-1]}"
        if context.has_card(piece):
            context.feedback("You already pocketed that photo quarter. It is safe in your inventory.", "info")
            return
        context.give_card(piece)
        context.update_task_progress(f"tb-escape-{LEVELS.index(level) + 1}", f"piece-{level}-{kind[-1]}")
        context.feedback("A torn photo quarter! Study it at the workbench to learn the door code.", "success")
        return
    if kind == "cache":
        weapon = WEAPONS[level]
        if context.has_card(weapon):
            context.feedback("You already carry that weapon. One is enough. Probably.", "info")
            return
        context.give_card(weapon)
        context.feedback(f"You pry out a {weapon.replace('-', ' ')}. The travelers were right.", "success")
        return
    if kind == "loot":
        try:
            index = int(instance_id.split("-")[2])
        except (ValueError, IndexError):
            index = 0
        table = LOOT[level]
        card = table[index % len(table)]
        if context.has_card(card):
            context.feedback("Only dust and echoes. Somebody else got here first, or you did.", "info")
            return
        context.give_card(card)
        context.feedback(f"You find {card.replace('-', ' ')}. Worth keeping.", "success")
        return
    context.feedback("Only dust, hum, and bad wallpaper. Nothing here but atmosphere.", "info")
