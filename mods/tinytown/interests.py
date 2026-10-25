"""Roommate interests: one liked and one disliked pastime per household peep."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Interest:
    """A pastime a roommate can love or avoid."""

    id: str
    label: str
    blurb: str


INTERESTS = (
    Interest("soccer", "soccer", "Weekend matches, questionable refereeing, strong halftime-snack opinions."),
    Interest("cooking", "cooking", "Believes dinner fixes most things and seasons accordingly."),
    Interest("videogames", "videogames", "Stays up too late chasing one more checkpoint."),
    Interest("gardening", "gardening", "Talks to seedlings and means it as encouragement."),
    Interest("books", "books", "Always halfway through three novels at once."),
    Interest("painting", "painting", "Sees every blank wall as an unfinished sentence."),
    Interest("music", "music", "Hums while doing the dishes. Harmonizes while hoovering."),
    Interest("dancing", "dancing", "Turns kitchen waiting time into a dance floor."),
    Interest("hiking", "hiking", "Collects viewpoints the way other people collect mugs."),
    Interest("swimming", "swimming", "Counts laps, then loses count on purpose."),
    Interest("cycling", "cycling", "Knows every shortcut and most of the potholes."),
    Interest("photography", "photography", "Chases golden hour around the house."),
    Interest("knitting", "knitting", "Produces scarves at an alarming, cozy rate."),
    Interest("chess", "chess", "Thinks four moves ahead and gloats in advance."),
    Interest("poetry", "poetry", "Leaves verses on the fridge and denies everything."),
    Interest("theatre", "theatre", "Narrates household chores in a stage whisper."),
    Interest("films", "films", "Quotes movies at moments of peak inappropriateness."),
    Interest("comics", "comics", "Keeps longboxes in strict, well-defended order."),
    Interest("stargazing", "stargazing", "Knows six constellations and invents the rest."),
    Interest("yoga", "yoga", "Salutes the sun from the living-room rug."),
    Interest("baking", "baking", "Measures flour with confidence and everything else by feel."),
    Interest("birdwatching", "birdwatching", "Owns binoculars and strong dawn-chorus opinions."),
    Interest("woodwork", "woodwork", "Smells faintly of sawdust and satisfaction."),
    Interest("coding", "coding", "Explains side projects at the slightest encouragement."),
    Interest("skateboarding", "skateboarding", "Treats the front path as a personal runway."),
    Interest("singing", "singing", "Practises scales where the acoustics flatter them."),
    Interest("pottery", "pottery", "Leaves little clay fingerprints on everything beloved."),
    Interest("running", "running", "Waves at the house on every lap past the window."),
    Interest("boardgames", "board games", "Reads rulebooks for fun and enforces them for sport."),
    Interest("fishing", "fishing", "Tells fish stories that improve with each retelling."),
)

INTERESTS_BY_ID = {interest.id: interest for interest in INTERESTS}


def random_interests(rng) -> tuple[str, str]:
    """Return a distinct (liked, disliked) interest pair using *rng*."""

    first = rng.choice(INTERESTS).id
    second = rng.choice(INTERESTS).id
    while second == first:
        second = rng.choice(INTERESTS).id
    return first, second


def interest_label(interest_id: str) -> str:
    """Return the display label for an interest id."""

    interest = INTERESTS_BY_ID.get(str(interest_id))
    return interest.label if interest is not None else "quiet hobbies"


def interest_blurb(interest_id: str) -> str:
    """Return the one-line flavor text for an interest id."""

    interest = INTERESTS_BY_ID.get(str(interest_id))
    return interest.blurb if interest is not None else "Keeps to small, mysterious pleasures."
