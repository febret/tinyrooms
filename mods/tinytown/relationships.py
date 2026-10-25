"""Reciprocal roommate vibes driven by shared and opposite interests."""

from __future__ import annotations


HOUSE_VIBE_INTERVAL_SECONDS = 600.0


def pair_tick_delta(
    first_likes: str,
    first_dislikes: str,
    second_likes: str,
    second_dislikes: str,
) -> int:
    """Return the 10-minute reciprocal vibe delta for one housemate pair.

    Roommates drift together by default, faster when they share a liked or
    disliked interest, and apart when one loves what the other avoids.
    """

    first_likes = str(first_likes)
    first_dislikes = str(first_dislikes)
    second_likes = str(second_likes)
    second_dislikes = str(second_dislikes)
    opposite = first_likes == second_dislikes or first_dislikes == second_likes
    if opposite:
        return -1
    shared = first_likes == second_likes or first_dislikes == second_dislikes
    if shared:
        return 2
    return 1


def describe_pair_reason(
    first_likes: str,
    first_dislikes: str,
    second_likes: str,
    second_dislikes: str,
) -> str:
    """Return a short descriptive reason for a pair's current drift."""

    from mods.tinytown.interests import interest_label

    first_likes = str(first_likes)
    first_dislikes = str(first_dislikes)
    second_likes = str(second_likes)
    second_dislikes = str(second_dislikes)
    if first_likes == second_likes and first_likes:
        return f"a shared love of {interest_label(first_likes)}"
    if first_dislikes == second_dislikes and first_dislikes:
        return f"a shared suspicion of {interest_label(first_dislikes)}"
    if first_likes == second_dislikes and first_likes:
        return f"a friendly argument about {interest_label(first_likes)}"
    if first_dislikes == second_likes and first_dislikes:
        return f"a friendly argument about {interest_label(first_dislikes)}"
    return "the slow magic of sharing a hallway"


def apply_house_tick(
    vibes,
    records: list,
    *,
    comedian_ids: set[str] | frozenset[str] = frozenset(),
) -> dict[tuple[str, str], int]:
    """Apply one 10-minute reciprocal tick for every housemate pair.

    Returns the applied {(source, target): delta} mapping. A present
    comedian with a warm reading on both halves softens one friction
    pair per tick instead of letting it sting.
    """

    if vibes is None:
        return {}
    deltas: dict[tuple[str, str], int] = {}
    soothed = False
    for index, first in enumerate(records):
        for second in records[index + 1 :]:
            delta = pair_tick_delta(
                getattr(first, "likes", ""),
                getattr(first, "dislikes", ""),
                getattr(second, "likes", ""),
                getattr(second, "dislikes", ""),
            )
            if delta < 0 and not soothed and comedian_ids:
                soothed = True
                delta = 0
            if delta == 0:
                continue
            deltas[(first.npc_id, second.npc_id)] = delta
            deltas[(second.npc_id, first.npc_id)] = delta
    if deltas:
        vibes.adjust_many(list(deltas.items()))
    return deltas
