"""Roommate jobs: hourly useful output claimed through conversation."""

from __future__ import annotations


JOB_INTERVAL_SECONDS = 3600.0

JOB_IDS = ("cook", "engineer", "cleaner", "musician", "artist", "comedian")

JOB_LABELS = {
    "cook": "House Cook",
    "engineer": "Tinkerer-Engineer",
    "cleaner": "Finder-Cleaner",
    "musician": "Chiptune Musician",
    "artist": "Easel Artist",
    "comedian": "House Comedian",
}

JOB_DESCRIPTIONS = {
    "cook": "Turns kitchen experiments into extra portions for whoever asks nicely.",
    "engineer": "Fiddles with gadgets until they earn their keep in Bops.",
    "cleaner": "Finds useful lost things while tidying places nobody else tidies.",
    "musician": "Stars chiptune tracks and brings home gig money when a set lands.",
    "artist": "Paints on the house easel; finished pieces go up for sale in the market.",
    "comedian": "Keeps the hallway laughing so small frictions never quite land.",
}

JOB_REQUIREMENT_TAGS = {
    "cook": ("kitchen",),
    "engineer": ("computer", "office", "desk"),
    "cleaner": ("utility",),
    "musician": ("seating", "sofa"),
    "artist": ("whiteboard", "easel", "studio", "art"),
    "comedian": ("seating", "sofa", "living"),
}

JOB_REQUIREMENT_COUNTS = {
    "cook": 5,
    "engineer": 3,
    "cleaner": 1,
    "musician": 2,
    "artist": 1,
    "comedian": 2,
}

JOB_REQUIREMENT_BLURBS = {
    "cook": "a proper kitchen to work in, stocked with plenty of cookware",
    "engineer": "a decent workshop corner with computers and office bits",
    "cleaner": "some utility nooks worth rummaging through",
    "musician": "a cozy corner with seats for an audience",
    "artist": "an easel or whiteboard corner with room to make a mess",
    "comedian": "a lived-in lounge where everyone can gather round",
}

CLEANER_CARD_POOL = (
    "market-apple",
    "market-bread",
    "market-tea",
    "market-soap",
    "market-bandage",
    "market-battery",
)

MUSICIAN_SET_NAMES = (
    "a sunrise set",
    "a rainy-day set",
    "a kitchen-disco set",
    "a stargazing set",
    "a hallway-anthem set",
)


def valid_job(job_id: str) -> bool:
    """Return whether *job_id* names a known roommate job."""

    return str(job_id) in JOB_LABELS


def job_label(job_id: str) -> str:
    """Return the display label for a job id."""

    return JOB_LABELS.get(str(job_id), "House Helper")


def job_description(job_id: str) -> str:
    """Return the one-line description for a job id."""

    return JOB_DESCRIPTIONS.get(str(job_id), "Helps out around the house where needed.")


def requirement_blurb(job_id: str) -> str:
    """Describe what a job needs from the house, without numbers."""

    return JOB_REQUIREMENT_BLURBS.get(str(job_id), "a little space to work")


def requirement_met(job_id: str, tag_counts: dict[str, int]) -> bool:
    """Return whether placed-prop tag counts satisfy a job's workshop needs."""

    wanted = JOB_REQUIREMENT_TAGS.get(str(job_id), ())
    needed = JOB_REQUIREMENT_COUNTS.get(str(job_id), 1)
    have = sum(int(tag_counts.get(str(tag), 0)) for tag in wanted)
    return have >= needed


def positive_band(score: int) -> bool:
    """Return whether a vibe score reads as warm enough to share work."""

    return int(score) > 0


def bff_band(score: int) -> bool:
    """Return whether a vibe score reads as best-friends territory."""

    return int(score) >= 51


def assign_job(rng, traits: tuple[str, ...]) -> str:
    """Pick a job for a new roommate, weighted toward their traits."""

    weights: dict[str, float] = {job_id: 1.0 for job_id in JOB_IDS}
    trait_set = {str(trait) for trait in traits}
    if "foodie" in trait_set:
        weights["cook"] += 3.0
    if "tinkerer" in trait_set:
        weights["engineer"] += 3.0
    if "clean" in trait_set:
        weights["cleaner"] += 3.0
    if "artsy" in trait_set:
        weights["artist"] += 3.0
    if "social" in trait_set or "friendly" in trait_set:
        weights["comedian"] += 2.0
    if "bookish" in trait_set or "stargazer" in trait_set:
        weights["musician"] += 2.0
    if "energetic" in trait_set or "outdoorsy" in trait_set:
        weights["cleaner"] += 1.0
    total = sum(weights.values())
    roll = rng.random() * total
    for job_id in JOB_IDS:
        roll -= weights[job_id]
        if roll <= 0:
            return job_id
    return "cleaner"


def cook_outputs(recipe_outputs: list[str], rng, *, generous: bool) -> list[str]:
    """Choose one (or two, when vibes are best-friends deep) recipe results."""

    pool = [str(card_id) for card_id in recipe_outputs if str(card_id)]
    if not pool:
        return []
    first = rng.choice(pool)
    if not generous:
        return [first]
    second = rng.choice(pool)
    return [first, second]


def engineer_payout(rng, score: int) -> int:
    """Return an engineer's hourly Bops share, warmer vibes pay better."""

    base = 4 + int(rng.random() * 5)
    if bff_band(score):
        return base + 8
    if int(score) >= 26:
        return base + 4
    if positive_band(score):
        return base
    return 0


def cleaner_find(card_pool: list[str], rng) -> str:
    """Choose what the cleaner shakes out of the sofa cushions."""

    pool = [str(card_id) for card_id in card_pool if str(card_id)] or list(CLEANER_CARD_POOL)
    return rng.choice(pool)


def musician_gig(rng, score: int) -> tuple[str, str, int]:
    """Return a (set name, verdict, payout) triple for a musician's hour."""

    set_name = rng.choice(MUSICIAN_SET_NAMES)
    skill = rng.random() + (0.35 if bff_band(score) else 0.15 if positive_band(score) else 0.0)
    if skill >= 1.0:
        return set_name, "an absolute house anthem", 14
    if skill >= 0.6:
        return set_name, "a warm little triumph", 9
    return set_name, "a cozy near-miss", 5


def artist_price(score: int) -> int:
    """Return the market price tier for a finished painting."""

    if bff_band(score):
        return 60
    if int(score) >= 26:
        return 40
    return 25


def artist_title(rng, name: str) -> str:
    """Return a gallery-ready title for a roommate painting."""

    subjects = (
        "the kitchen at golden hour",
        "everyone's shoes by the door",
        "the hallway, but braver",
        "a portrait of the kettle",
        "the roof at midnight",
        "the sofa's good side",
    )
    return f"{name}'s {rng.choice(subjects)}"


def generate_painting_surface(rng, seed_text: str) -> dict[str, object]:
    """Build a whiteboard-format surface so the piece lives in the art system."""

    seed = sum(ord(char) for char in str(seed_text)) + int(rng.random() * 997)
    strokes: list[dict[str, object]] = []
    palette = ("#e4572e", "#29335c", "#f3a712", "#669bbc", "#e8e9eb")
    for index in range(5):
        color = palette[(seed + index * 2) % len(palette)]
        base_x = 90 + ((seed * (index + 3)) % 700)
        base_y = 80 + ((seed * (index + 5)) % 380)
        points: list[list[int]] = []
        for step in range(6):
            points.append([base_x + step * 24, base_y + ((seed + step * 37 + index * 11) % 60) - 30])
        strokes.append({"color": color, "width": 6 + (index % 3) * 3, "points": points})
    return {
        "strokes": strokes,
        "texts": [
            {
                "text": str(seed_text)[:80],
                "x": 90,
                "y": 560,
                "size": 28,
                "color": "#29335c",
            }
        ],
    }
