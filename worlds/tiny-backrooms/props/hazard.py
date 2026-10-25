"""Hazard-marker behavior: poison fog and radioactive static punish the unprotected.

World-authored. Immunity comes from equipped gear: gas masks (or hazmat suits)
against poison, hazmat suits against radiation. Damage lands on user-actor
entry and inspection events; the marker props carry the visible fog/spark fx.
"""

from __future__ import annotations

POISON_DAMAGE = 3
RAD_DAMAGE = 4


def _kinds_of(context) -> set[str]:
    target = context.target
    instance_id = str(getattr(target, "instance_id", "") or "")
    prop_id = str(getattr(target, "prop_id", "") or "")
    kinds: set[str] = set()
    if "poison" in instance_id or "both" in instance_id or prop_id == "poison-vent":
        kinds.add("poison")
    if "-rad" in instance_id or "both" in instance_id or prop_id == "rad-rod":
        kinds.add("rad")
    return kinds


def _protected(context, kinds: set[str]) -> bool:
    if "rad" in kinds:
        return context.has_equipped_card("hazmat-suit")
    return context.has_equipped_card("gas-mask") or context.has_equipped_card("hazmat-suit")


def _sting(context, kinds: set[str]) -> None:
    if "rad" in kinds and "poison" in kinds:
        if _protected(context, {"rad"}):
            context.feedback("Your hazmat suit crinkles. Fog and static both slide right off.", "success")
            return
        context.apply_counter("health", -(POISON_DAMAGE + RAD_DAMAGE))
        context.feedback("Fog in your lungs and static in your teeth. You need a hazmat suit.", "error")
        return
    if "rad" in kinds:
        if _protected(context, kinds):
            context.feedback("Your hazmat suit drinks the static. The snow hisses off you.", "success")
            return
        context.apply_counter("health", -RAD_DAMAGE)
        context.feedback("Yellow static crawls over you. Find a hazmat suit.", "error")
        return
    if _protected(context, kinds):
        context.feedback("Your mask hisses softly. The fog cannot reach you.", "success")
        return
    context.apply_counter("health", -POISON_DAMAGE)
    context.feedback("Green fog burns your throat. Find a gas mask or hazmat suit.", "error")


def on_enter(context, event):
    if event.actor.kind != "user":
        return
    kinds = _kinds_of(context)
    if kinds:
        _sting(context, kinds)


def on_quick_action(context, event):
    if event.action != "inspect":
        return
    kinds = _kinds_of(context)
    if not kinds:
        return
    _sting(context, kinds)
