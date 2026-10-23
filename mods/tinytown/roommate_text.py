"""Editorial copy for TinyTown roommate classifieds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from mods.tinytown.catalog import TRAITS_BY_ID


@dataclass(frozen=True, slots=True)
class RoommateAd:
    headline: str
    description: str


ROOMMATE_ADS: dict[tuple[str, str], RoommateAd] = {
    ("artsy", "cozy"): RoommateAd(
        "I need a bright wall and a chair I can ruin with paint.",
        "I paint at the kitchen table and keep the good blanket on the reading chair. "
        "Looking for a room with decent light, a patient neighbour, and space for one unfinished canvas.",
    ),
    ("bookish", "friendly"): RoommateAd(
        "Good morning, then three quiet hours with a book.",
        "I make excellent tea, keep odd hours quietly, and would love a kitchen table that doubles as a library. "
        "I am friendly by default and reclusive by mid-afternoon.",
    ),
    ("clean", "tinkerer"): RoommateAd(
        "I label the spice jars. I also own the right screwdriver.",
        "Nothing in this house needs to stay broken. I fix hinges, straighten shelves, and put things back where "
        "they belong. Looking for a tidy home where small repairs are a pleasure, not a chore.",
    ),
    ("energetic", "outdoorsy"): RoommateAd(
        "Mud on the boots. Coffee on for the house.",
        "I am up before the sun and out the back door with the secateurs. A garden, a drying rack, and neighbours "
        "who wave across the fence would suit me perfectly.",
    ),
    ("foodie", "social"): RoommateAd(
        "I cook for the whole house on Sundays.",
        "Dinner is better with one more chair at the table. I have strong opinions about toast, a generous hand with "
        "olive oil, and no interest in eating alone behind a closed door.",
    ),
    ("bookish", "cozy"): RoommateAd(
        "A blanket, a warm drink, and nowhere to be.",
        "I read three books at once and return them to the shelf in exactly the right order. I am looking for a quiet "
        "corner, a tolerant kettle, and a household that understands the value of an early night.",
    ),
    ("friendly", "social"): RoommateAd(
        "Hallway chats are a valid evening plan.",
        "I remember names, bring back pastries, and like a house where the door is usually open. Looking for people "
        "who will share a table, a walk, and the occasional very long conversation.",
    ),
    ("grumpy", "tinkerer"): RoommateAd(
        "Not unfriendly. Selective. Very good with a hinge.",
        "I keep to myself, fix what is broken, and prefer a house where people mean what they say. The kettle is mine; "
        "you are welcome to use it, provided you put it back.",
    ),
    ("bookish", "stargazer"): RoommateAd(
        "Six constellations, three books, one quiet roof.",
        "I read late, keep the lights low, and can name six constellations without checking. I would trade roof "
        "access for a quiet conversation and a clear night.",
    ),
    ("outdoorsy", "stargazer"): RoommateAd(
        "Dirt under the nails, stars overhead.",
        "I grow tomatoes, sweep up the mud, and stay out for the meteor shower. Looking for a home with a back door "
        "that opens easily and a roof worth climbing.",
    ),
    ("artsy", "stargazer"): RoommateAd(
        "I notice the blank wall. Then I notice the sky.",
        "Colour and composition follow me into every room. By day I am sketching the corner that needs fixing; by "
        "night I am on the roof with a notebook. A good window is non-negotiable.",
    ),
    ("clean", "cozy"): RoommateAd(
        "A warm room and a clean counter, in that order.",
        "I make tea, fold the throw, and quietly return everything to its proper place. Looking for a calm home where "
        "comfort and order are not opposites.",
    ),
    ("energetic", "social"): RoommateAd(
        "Swim before breakfast. Dinner with everyone after.",
        "I run up the stairs, down the stairs, and out for a swim before the kettle boils. House dinners and game "
        "nights are my idea of a well-spent week.",
    ),
    ("bookish", "grumpy"): RoommateAd(
        "I read. I rest. I fix the odd hinge.",
        "I do not need much conversation, but I do need a quiet room and a door that closes properly. If you are kind "
        "and reasonably tidy, we will get along fine.",
    ),
    ("foodie", "friendly"): RoommateAd(
        "First I compliment the curtains. Then I cook.",
        "I am looking for a house that eats together and does not take itself too seriously. I will remember your "
        "birthday, bring home good bread, and never skimp on garlic.",
    ),
}

FALLBACK_HEADLINE = "Looking for a room with good light and reasonable people."
FALLBACK_DESCRIPTION = (
    "A new face at the classified desk, still deciding what to write. "
    "They have a decent record with kettles and a clear preference for a quiet corner."
)


def _trait_key(traits: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(str(trait) for trait in traits))


def _fallback_description(traits: Iterable[str]) -> str:
    parts = []
    for trait in traits:
        definition = TRAITS_BY_ID.get(str(trait))
        if definition is None:
            continue
        description = definition.description.strip()
        if description:
            parts.append(description if description.endswith((".", "!", "?")) else f"{description}.")
    return " ".join(parts) or FALLBACK_DESCRIPTION


def roommate_ad(traits: Iterable[str]) -> RoommateAd:
    """Return the curated advert for a trait pairing, with a graceful fallback."""

    values = tuple(str(trait) for trait in traits)
    curated = ROOMMATE_ADS.get(_trait_key(values))
    if curated is not None:
        return curated
    return RoommateAd(FALLBACK_HEADLINE, _fallback_description(values))
