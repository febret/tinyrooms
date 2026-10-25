"""Ambient housemate banter for rooms the user is standing in."""

from __future__ import annotations


BANTER_COOLDOWN_SECONDS = 300.0
BANTER_CHANCE = 0.35


def choose_banter(rng, records: list, outgoing: dict[str, dict[str, int]]) -> str | None:
    """Pick one ambient line about housemate reciprocal vibes, if any fits."""

    from mods.tinytown.interests import interest_label
    from mods.tinytown.relationships import describe_pair_reason

    if len(records) < 2:
        return None
    first = rng.choice(records)
    others = [record for record in records if record.npc_id != first.npc_id]
    if not others:
        return None
    second = rng.choice(others)
    score = int((outgoing.get(first.npc_id) or {}).get(second.npc_id, 0))
    likes = getattr(first, "likes", "")
    dislikes = getattr(first, "dislikes", "")
    reason = describe_pair_reason(
        likes, dislikes, getattr(second, "likes", ""), getattr(second, "dislikes", "")
    )
    if score >= 26:
        templates = (
            f"{first.name} is telling {second.name} all about {interest_label(likes)} again. {second.name} is delighted, obviously.",
            f"{first.name} and {second.name} are thick as thieves lately — blame {reason}.",
        )
    elif score > 0:
        templates = (
            f"{first.name} saved {second.name} the good seat. It is {reason}, probably.",
            f"{first.name} and {second.name} are swapping stories — {reason} keeps coming up.",
        )
    elif score <= -26:
        templates = (
            f"{first.name} sighs whenever {interest_label(getattr(second, 'likes', ''))} comes up. {second.name} pretends not to notice.",
            f"There is a certain chill between {first.name} and {second.name} — something about {reason}.",
        )
    elif score < 0:
        templates = (
            f"{first.name} and {second.name} are being very polite about {reason}.",
            f"{first.name} gives {second.name} a look. It passes. Mostly.",
        )
    else:
        templates = (
            f"{first.name} wonders aloud what {second.name} is up to. Roommates, eh?",
            f"{first.name} and {second.name} orbit each other peacefully — {reason}, one day.",
        )
    return rng.choice(templates)
