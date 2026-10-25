"""Household fixture needs: beds, toilets, and baths per headcount."""

from __future__ import annotations

from collections import Counter


BED_TAGS = ("bed",)
TOILET_TAGS = ("toilet",)
BATH_TAGS = ("bathroom", "tub", "bath")

FIXTURE_KINDS = ("beds", "toilets", "baths")


def required_beds(roommate_count: int) -> int:
    """Return the beds a happy house needs: one per roommate, plus a guest bed."""

    count = int(roommate_count)
    if count <= 0:
        return 0
    return count + 1


def required_toilets(roommate_count: int) -> int:
    """Return the toilets a happy house needs: roughly one per two roommates."""

    count = int(roommate_count)
    if count <= 0:
        return 0
    return (count + 1) // 2


def required_baths(roommate_count: int) -> int:
    """Return the baths a happy house needs: roughly one per three roommates."""

    count = int(roommate_count)
    if count <= 0:
        return 0
    return (count + 2) // 3


def count_fixtures(all_prop_tags: list[tuple[str, ...] | list[str]]) -> dict[str, int]:
    """Count beds, toilets, and baths from placed-prop tag lists."""

    counts: Counter[str] = Counter()
    for tags in all_prop_tags:
        tag_set = {str(tag) for tag in tags}
        if tag_set & set(BED_TAGS):
            counts["beds"] += 1
        if tag_set & set(TOILET_TAGS):
            counts["toilets"] += 1
        if tag_set & set(BATH_TAGS):
            counts["baths"] += 1
    return {kind: int(counts.get(kind, 0)) for kind in FIXTURE_KINDS}


def needs_status(counts: dict[str, int], roommate_count: int) -> dict[str, dict[str, object]]:
    """Return per-fixture requirement state without exposing raw headcounts."""

    requirements = {
        "beds": required_beds(roommate_count),
        "toilets": required_toilets(roommate_count),
        "baths": required_baths(roommate_count),
    }
    status: dict[str, dict[str, object]] = {}
    for kind in FIXTURE_KINDS:
        have = int(counts.get(kind, 0))
        need = requirements[kind]
        status[kind] = {
            "comfortable": have >= need,
            "short": have < need,
            "empty": have == 0,
        }
    return status


def shortfall_kinds(counts: dict[str, int], roommate_count: int) -> list[str]:
    """Return the fixture kinds the house is short on."""

    status = needs_status(counts, roommate_count)
    return [kind for kind in FIXTURE_KINDS if bool(status[kind]["short"])]


def owner_drift(shortfalls: list[str]) -> int:
    """Return the owner-directed vibe drift for unmet needs (never a block)."""

    if not shortfalls:
        return 0
    return max(-3, -len(shortfalls))


def describe_needs(counts: dict[str, int], roommate_count: int) -> str:
    """Describe the house's fixture comfort in words, never numbers."""

    if int(roommate_count) <= 0:
        return "The house is quiet and the fixtures are gathering dust."
    shortfalls = shortfall_kinds(counts, roommate_count)
    if not shortfalls:
        return "Beds are plentiful, the bathroom queue is a rumour, and the tub is gloriously uncontested."
    notes: list[str] = []
    if "beds" in shortfalls:
        notes.append("someone is eyeing the sofa as a permanent address")
    if "toilets" in shortfalls:
        notes.append("mornings involve a certain hopeful hovering")
    if "baths" in shortfalls:
        notes.append("the tub has a waiting list and a legend")
    return "The house feels a little cramped — " + " and ".join(notes) + "."
