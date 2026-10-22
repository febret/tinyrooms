"""Static TinyTown catalogs: districts, avatars, and personality traits."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class District:
    id: str
    label: str
    tagline: str
    description: str
    accent: str


DISTRICTS = (
    District(
        id="downtown",
        label="Downtown",
        tagline="Bricks, neon, and bakery air",
        description="Compact city homes stacked around the old clock tower, noodle counters, and glowing shop windows.",
        accent="#ff8f5a",
    ),
    District(
        id="sea",
        label="The Sea",
        tagline="Salt, gulls, and long horizons",
        description="Pastel cottages and keeper's rooms along a working harbor, where the tide sets the pace.",
        accent="#57b8b5",
    ),
    District(
        id="hills",
        label="The Hills",
        tagline="Orchards, stars, and winding lanes",
        description="Timber cabins and stone manors tucked into green slopes, with clear skies after sunset.",
        accent="#8fa85b",
    ),
    District(
        id="suburbs",
        label="The Suburbs",
        tagline="Gardens, porches, and familiar streets",
        description="Leafy lanes of bungalows and family homes where every kitchen window faces the sun.",
        accent="#d98d6b",
    ),
)


@dataclass(frozen=True, slots=True)
class AvatarChoice:
    id: str
    label: str
    file: str


AVATARS = (
    AvatarChoice("moss", "Moss", "avatar-01.png"),
    AvatarChoice("peach", "Peach", "avatar-02.png"),
    AvatarChoice("bluebell", "Bluebell", "avatar-03.png"),
    AvatarChoice("saffron", "Saffron", "avatar-04.png"),
    AvatarChoice("plum", "Plum", "avatar-05.png"),
    AvatarChoice("mint", "Mint", "avatar-06.png"),
    AvatarChoice("ember", "Ember", "avatar-07.png"),
    AvatarChoice("cloud", "Cloud", "avatar-08.png"),
)


@dataclass(frozen=True, slots=True)
class Trait:
    id: str
    label: str
    description: str
    weights: tuple[tuple[str, float], ...] = ()
    energy_drain: float = 1.0
    cleanliness_drain: float = 1.0
    social: float = 1.0
    positivity: float = 1.0
    cleanliness_want: float = 1.0
    rest_want: float = 1.0


TRAITS = (
    Trait(
        "artsy",
        "Artsy",
        "Notices colour, composition, and a blank wall that needs fixing.",
        (("paint", 3.2), ("gallery", 2.2), ("read", 0.8)),
        energy_drain=1.05,
        cleanliness_drain=1.15,
    ),
    Trait(
        "bookish",
        "Bookish",
        "Always halfway through three books and delighted to tell you about all of them.",
        (("read", 3.0), ("stargaze", 1.2), ("paint", 0.5)),
        energy_drain=0.85,
        positivity=1.1,
    ),
    Trait(
        "clean",
        "Neat Freak",
        "Can spot a crumb from across the room and will absolutely mention it.",
        (("bathe", 2.8), ("tinker", 1.2), ("paint", 0.6)),
        cleanliness_drain=1.6,
        cleanliness_want=2.2,
        rest_want=0.8,
    ),
    Trait(
        "cozy",
        "Cozy",
        "A blanket, a warm drink, and absolutely nowhere to be. Peak living.",
        (("rest", 3.0), ("read", 1.6), ("socialize", 0.5)),
        energy_drain=0.7,
        social=0.7,
        rest_want=1.7,
    ),
    Trait(
        "energetic",
        "Energetic",
        "Runs up the stairs. Runs down the stairs. Runs for no reason at all.",
        (("swim", 2.6), ("garden", 1.8), ("tinker", 0.7)),
        energy_drain=0.8,
        positivity=1.15,
    ),
    Trait(
        "foodie",
        "Foodie",
        "Believes a good meal can repair almost anything, and has strong opinions about toast.",
        (("eat", 3.2), ("socialize", 1.3), ("paint", 0.4)),
        cleanliness_drain=1.1,
        social=1.1,
    ),
    Trait(
        "friendly",
        "Friendly",
        "Will compliment your curtains, your plants, and your choice of hallway art.",
        (("socialize", 3.0), ("garden", 1.0), ("paint", 0.7)),
        social=1.8,
        positivity=1.3,
    ),
    Trait(
        "grumpy",
        "Grumpy",
        "Not rude, exactly. Just deeply unconvinced by most things.",
        (("read", 1.4), ("rest", 1.5), ("tinker", 1.2)),
        social=0.35,
        positivity=0.5,
    ),
    Trait(
        "outdoorsy",
        "Outdoorsy",
        "Happiest with dirt under their nails and the back door propped open.",
        (("garden", 3.0), ("swim", 2.0), ("stargaze", 1.2)),
        cleanliness_drain=1.5,
        positivity=1.15,
    ),
    Trait(
        "social",
        "Social Butterfly",
        "The house feels bigger when everyone is in the same room.",
        (("socialize", 3.2), ("eat", 1.1), ("swim", 0.9)),
        social=2.0,
        energy_drain=1.1,
    ),
    Trait(
        "tinkerer",
        "Tinkerer",
        "There is a loose hinge somewhere and it is a personal invitation.",
        (("tinker", 3.0), ("read", 1.0), ("paint", 0.8)),
        cleanliness_drain=1.25,
        positivity=1.05,
    ),
    Trait(
        "stargazer",
        "Stargazer",
        "Knows the names of six constellations and makes up the rest.",
        (("stargaze", 2.8), ("read", 1.4), ("rest", 0.7)),
        positivity=1.2,
    ),
)

DISTRICTS_BY_ID = {district.id: district for district in DISTRICTS}
AVATARS_BY_ID = {avatar.id: avatar for avatar in AVATARS}
TRAITS_BY_ID = {trait.id: trait for trait in TRAITS}

ACTION_LABELS = {
    "idle": "pottering about",
    "rest": "taking a nap",
    "sleep": "sleeping",
    "bathe": "freshening up",
    "eat": "making a snack",
    "paint": "making art",
    "read": "reading",
    "garden": "tending the garden",
    "swim": "swimming",
    "tinker": "tinkering",
    "socialize": "visiting",
    "stargaze": "stargazing",
}

ACTION_ROLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sleep", ("bedroom", "loft", "nursery")),
    ("rest", ("bedroom", "loft", "living")),
    ("bathe", ("bath",)),
    ("eat", ("kitchen",)),
    ("paint", ("studio", "gallery", "living")),
    ("read", ("library", "living", "bedroom")),
    ("garden", ("garden",)),
    ("swim", ("pool", "bath")),
    ("tinker", ("workshop", "studio")),
    ("socialize", ("living", "kitchen", "garden")),
    ("stargaze", ("roof", "garden", "living")),
)

ROLE_ORDER = (
    "entry",
    "living",
    "kitchen",
    "bedroom",
    "bath",
    "studio",
    "library",
    "garden",
    "pool",
    "gallery",
    "roof",
    "workshop",
    "nursery",
    "loft",
)

MAX_HOUSES = 4
MAX_NPCS_PER_HOUSE = 4
MAX_NAME_LENGTH = 24
