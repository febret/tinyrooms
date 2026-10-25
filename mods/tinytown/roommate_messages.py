"""Roommate phone texts: hourly hellos and canned replies.

Hourly texts are rolled once per wall-clock hour for each adopted roommate and
written straight to the owner's phone inbox, even while the owner is offline.
Canned replies answer one player text immediately from the roommate's current
state; they never adjust vibes and never roll the hourly chance again.
"""

from __future__ import annotations

from dataclasses import dataclass

from mods.tinytown.catalog import ACTION_LABELS, TRAITS_BY_ID
from mods.tinytown.interests import interest_label
from mods.tinytown.jobs import bff_band, job_label, positive_band, valid_job
from mods.tinytown.roommate_dialog import condition_label


MESSAGE_CHANCE_PER_HOUR = 0.10

TINYTOWN_WORLD_ID = "tinytown"


def hour_bucket(moment_iso: str) -> int:
    """Return the wall-clock hour bucket for an ISO timestamp."""

    from datetime import datetime

    try:
        moment = datetime.fromisoformat(str(moment_iso))
    except (TypeError, ValueError):
        return 0
    return int(moment.timestamp() // 3600)


def vibe_band(score: int) -> str:
    """Describe a vibe score without numbers for message snapshots."""

    value = int(score)
    if bff_band(value):
        return "bff"
    if positive_band(value):
        return "warm"
    if value == 0:
        return "neutral"
    if value <= -26:
        return "cold"
    return "cool"


@dataclass(frozen=True, slots=True)
class TextSnapshot:
    """The roommate state that picks message copy."""

    job_state: str
    job_label: str
    npc_score: int
    owner_score: int
    npc_band: str
    owner_band: str
    energy_label: str
    health_label: str
    cleanliness_label: str
    worn: bool
    action: str
    action_label: str
    likes_label: str
    dislikes_label: str
    traits: tuple[str, ...]


def job_state_for(record: object) -> str:
    """Derive the dialog job state from stored fields, without side effects."""

    if not valid_job(str(getattr(record, "job_id", "") or "")):
        return "resting"
    if getattr(record, "job_claim_json", ""):
        return "ready"
    return "waiting"


def snapshot_for(npc_house: object, record: object) -> TextSnapshot:
    """Build the copy-selection snapshot for one roommate, best effort."""

    stats = getattr(record, "stats", {}) or {}
    try:
        energy = float(stats.get("energy", 80.0))
        health = float(stats.get("health", 80.0))
        cleanliness = float(stats.get("cleanliness", 80.0))
    except (TypeError, ValueError):
        energy = health = cleanliness = 80.0
    npc_score = 0
    owner_score = 0
    vibes = getattr(npc_house, "vibes", None)
    if vibes is not None:
        try:
            npc_score = int(vibes.get(record.npc_id, record.owner_account_id))
        except Exception:  # noqa: BLE001 - copy selection must never break the sim
            npc_score = 0
        try:
            owner_score = int(vibes.get(record.owner_account_id, record.npc_id))
        except Exception:  # noqa: BLE001 - copy selection must never break the sim
            owner_score = 0
    action = str(getattr(record, "action", "idle") or "idle")
    traits = tuple(str(trait) for trait in (getattr(record, "traits", ()) or ()))
    return TextSnapshot(
        job_state=job_state_for(record),
        job_label=job_label(str(getattr(record, "job_id", "") or "")),
        npc_score=npc_score,
        owner_score=owner_score,
        npc_band=vibe_band(npc_score),
        owner_band=vibe_band(owner_score),
        energy_label=condition_label(energy),
        health_label=condition_label(health),
        cleanliness_label=condition_label(cleanliness),
        worn=min(energy, health, cleanliness) < 40.0,
        action=action,
        action_label=str(ACTION_LABELS.get(action, action)),
        likes_label=interest_label(str(getattr(record, "likes", "") or "")),
        dislikes_label=interest_label(str(getattr(record, "dislikes", "") or "")),
        traits=traits,
    )


JOB_READY_TEXTS = (
    "Finished my shift! I have got something with your name on it, come talk to me.",
    "Work went great today. I set something aside for you, come claim it.",
    "All done! I made something good. Swing by when you have a minute?",
    "My {job} shift paid off. I saved you the best bit, come see.",
    "Guess who finished work early? I have a little surprise waiting.",
)

BFF_TEXTS = (
    "Just thinking about you. This house feels like home because of you.",
    "You are my favorite person in TinyTown. That is all. That is the text.",
    "Had the best day. Wish you had been here to see it!",
    "I told the housemates all about you. They are very jealous.",
)

WARM_TEXTS = (
    "Hey! Hope your day is going well out there.",
    "Just checking in. The house misses you when you are away.",
    "Saw something funny today and thought of you.",
)

COLD_TEXTS = (
    "We need to talk when you are back. That is all.",
    "Do not expect me to be cheerful. The house is a mess.",
    "I am keeping to myself today. Do not take it personally. Or do.",
)

COOL_TEXTS = (
    "Hey. Things are fine here. Just keeping you posted.",
    "Not much to report. House is standing. I am standing.",
    "Hope town is treating you okay. Later.",
)

WORN_TEXTS = (
    "I am {condition} today. Going to take it slow, okay?",
    "Feeling {condition}. Do not worry, I am looking after myself.",
    "Long day. I am {condition} and heading for a rest soon.",
)

INTEREST_TEXTS = (
    "Spent ages on {interest} today. I am getting pretty good!",
    "You know what I love? {interest}. We should do it together sometime.",
    "Found a new trick for {interest}. I will show you when you visit!",
)

ACTION_TEXTS: dict[str, tuple[str, ...]] = {
    "eat": (
        "Made myself something tasty. Wish you were here to try it!",
        "Cooking up a storm. The kitchen smells amazing right now.",
    ),
    "sleep": (
        "Off to bed early tonight. Dream of tiny houses!",
        "So sleepy. Telling you goodnight before I conk out.",
    ),
    "rest": (
        "Taking a breather on the sofa. Comfy and thinking of you.",
        "Resting my feet. The house is quiet and nice.",
    ),
    "bathe": (
        "Bath time! I will be all fresh when you visit.",
        "Having a lovely soak. Do not rush home on my account!",
    ),
    "garden": (
        "The garden is looking lovely. I planted something new!",
        "Out among the flowers. It is peaceful here today.",
    ),
    "read": (
        "Curled up with a good book. You would love this one.",
        "Reading something great. Saving you the good bits!",
    ),
    "paint": (
        "Paint everywhere! Made something colorful today.",
        "Working on a painting. It is coming out really nice.",
    ),
    "swim": (
        "Just had a swim. Feeling refreshed and splashy!",
        "The water was perfect today. You should join me sometime!",
    ),
    "tinker": (
        "Took something apart and mostly put it back together. Progress!",
        "Fiddling with gadgets. Nothing exploded today!",
    ),
    "socialize": (
        "Hanging out with the housemates. Wish you were here!",
        "Good company tonight. We raised a glass to you!",
    ),
    "stargaze": (
        "The stars are out. Picked out the brightest one for you.",
        "Stargazing tonight. The sky is doing something special.",
    ),
    "idle": (
        "Pottering about the house. All quiet on the home front!",
        "Nothing much happening here. Just wanted to say hi.",
    ),
}

TRAIT_OPENERS = (
    ("friendly", "Hey friend! "),
    ("grumpy", "Hmph. "),
    ("energetic", "Big news energy over here! "),
    ("cozy", "From my favorite cozy corner: "),
    ("foodie", "Between snacks: "),
    ("bookish", "Bookmarking this moment to tell you: "),
    ("artsy", "Picture this: "),
    ("outdoorsy", "Fresh air update: "),
    ("social", "Everyone says hi, by the way! "),
    ("tinkerer", "Workshop report: "),
    ("stargazer", "Looking skyward and thinking: "),
    ("clean", "Everything is spotless, so: "),
)

GENERIC_TEXTS = (
    "Hi from home! Everything is fine here.",
    "Just wanted to say hello. The house is good.",
    "Thinking of you. Hope town is fun!",
    "No news, just a hello from your roommate!",
)

UNREACHABLE_LINES = (
    "Sorry, I cannot get through right now. I will write when I am back in range!",
    "No signal on my end! Your text is saved and I will reply soon.",
    "I am out of range at the moment. Talk soon, promise!",
)


def _trait_opener(traits: tuple[str, ...]) -> str:
    for trait_id, opener in TRAIT_OPENERS:
        if trait_id in traits:
            return opener
    return ""


def choose_hourly_text(rng, record: object, snapshot: TextSnapshot) -> str:
    """Pick one unsolicited hourly text, highest matching bucket first."""

    if snapshot.job_state == "ready":
        return rng.choice(JOB_READY_TEXTS).format(job=snapshot.job_label.lower())
    if snapshot.npc_band == "bff":
        return rng.choice(BFF_TEXTS)
    if snapshot.npc_band == "warm":
        return rng.choice(WARM_TEXTS)
    if snapshot.npc_band == "cold":
        return rng.choice(COLD_TEXTS)
    if snapshot.npc_band == "cool":
        return rng.choice(COOL_TEXTS)
    if snapshot.worn:
        weakest = snapshot.energy_label
        if snapshot.health_label in {"running on fumes", "ready to drop"}:
            weakest = snapshot.health_label
        elif snapshot.cleanliness_label in {"running on fumes", "ready to drop"}:
            weakest = snapshot.cleanliness_label
        return _trait_opener(snapshot.traits) + rng.choice(WORN_TEXTS).format(condition=weakest)
    pool = ACTION_TEXTS.get(snapshot.action, ACTION_TEXTS["idle"])
    if snapshot.likes_label and rng.random() < 0.35:
        return _trait_opener(snapshot.traits) + rng.choice(INTEREST_TEXTS).format(
            interest=snapshot.likes_label.lower()
        )
    return _trait_opener(snapshot.traits) + rng.choice(pool)


REPLY_READY = (
    "Yes! It is ready, come talk to me and I will hand it over.",
    "All yours! Come find me and I will give you the rundown.",
    "Finished! Come by and claim it before I get distracted.",
)

REPLY_WAITING_WARM = (
    "Still working on it! I will text you the moment it is done.",
    "Not quite yet, but I am on it! I will let you know as soon as it lands.",
)

REPLY_WAITING_CURT = (
    "Still working. You will know when it is done.",
    "Not yet. Do not rush me.",
)

REPLY_RESTING_WARM = (
    "I am between jobs right now, but I am all ears!",
    "No shift today, so I have plenty of time to chat.",
    "Work can wait. What is on your mind?",
)

REPLY_RESTING_CURT = (
    "No shift today. What do you want?",
    "I am between jobs. Make it quick.",
    "Not working. Talk.",
)

REPLY_BUSY = (
    "Bit tied up with {doing} right now, but I saw your text!",
    "In the middle of {doing}. I will catch up properly soon!",
    "Can I text you back in a bit? {doing_cap} takes focus.",
)


def choose_reply_text(rng, record: object, snapshot: TextSnapshot, player_text: str) -> str:
    """Pick one immediate reply that sounds like an answer, not a hello."""

    del player_text
    if snapshot.action in {"sleep", "bathe"}:
        doing = snapshot.action_label.lower()
        return rng.choice(REPLY_BUSY).format(
            doing=doing, doing_cap=doing[:1].upper() + doing[1:]
        )
    if snapshot.job_state == "ready":
        return rng.choice(REPLY_READY)
    warm = snapshot.npc_band in {"bff", "warm", "neutral"}
    if snapshot.job_state == "waiting":
        return rng.choice(REPLY_WAITING_WARM if warm else REPLY_WAITING_CURT)
    return rng.choice(REPLY_RESTING_WARM if warm else REPLY_RESTING_CURT)


def _ensure_hour_table(npc_house: object) -> None:
    hub = npc_house.hub
    with hub.transaction() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS world.tinytown_npc_message_hours (
                npc_id TEXT PRIMARY KEY,
                last_hour INTEGER NOT NULL
            )
            """
        )


def _last_hour(npc_house: object, npc_id: str) -> int | None:
    with npc_house.hub.locked() as connection:
        row = connection.execute(
            "SELECT last_hour FROM world.tinytown_npc_message_hours WHERE npc_id = ?",
            (npc_id,),
        ).fetchone()
    return int(row["last_hour"]) if row is not None else None


def _record_hour(npc_house: object, npc_id: str, bucket: int) -> None:
    with npc_house.hub.transaction() as connection:
        connection.execute(
            "INSERT INTO world.tinytown_npc_message_hours (npc_id, last_hour)"
            " VALUES (?, ?) ON CONFLICT (npc_id) DO UPDATE SET last_hour = excluded.last_hour",
            (npc_id, bucket),
        )


async def _notify_owner(
    npc_house: object,
    owner_account_id: str,
    thread_key: str,
    sender_name: str,
    preview: str,
    unread: int,
    body: str = "",
) -> None:
    connections = getattr(npc_house.runtime, "connections", None)
    if connections is None:
        return
    try:
        target = await connections.get(owner_account_id)
    except Exception:  # noqa: BLE001 - texts must survive push failures
        return
    if target is None:
        return
    from server.protocol import room_event_envelope

    event = {
        "type": "phone.message",
        "thread_key": thread_key,
        "sender_name": sender_name,
        "preview": preview[:48],
        "body": body,
        "unread": unread,
    }
    try:
        await target.send(room_event_envelope(event))
    except RuntimeError:
        return


async def maybe_send_hourly_texts(npc_house: object, records: list, moment: object) -> None:
    """Roll one hourly text per roommate and deliver it to the owner's phone."""

    phone = getattr(npc_house.runtime, "phone_messages", None)
    if phone is None:
        return
    moment_iso = moment.isoformat() if hasattr(moment, "isoformat") else str(moment)
    bucket = hour_bucket(moment_iso)
    try:
        _ensure_hour_table(npc_house)
    except Exception:  # noqa: BLE001 - texts must never break the sim
        return
    rng = getattr(npc_house, "_random", None)
    if rng is None:
        import random as random_module

        rng = random_module.Random()
    for record in records:
        try:
            if _last_hour(npc_house, record.npc_id) == bucket:
                continue
            _record_hour(npc_house, record.npc_id, bucket)
            if rng.random() >= MESSAGE_CHANCE_PER_HOUR:
                continue
            snapshot = snapshot_for(npc_house, record)
            text = choose_hourly_text(rng, record, snapshot)
            from server.services.phone_messages import npc_thread_key

            thread_key = npc_thread_key(TINYTOWN_WORLD_ID, record.npc_id)
            phone.deliver_inbound(
                record.owner_account_id,
                thread_key,
                record.name,
                text,
                TINYTOWN_WORLD_ID,
                {
                    "action": snapshot.action,
                    "job_id": str(getattr(record, "job_id", "") or ""),
                    "job_state": snapshot.job_state,
                    "vibe_band": snapshot.npc_band,
                },
            )
            await _notify_owner(
                npc_house,
                record.owner_account_id,
                thread_key,
                record.name,
                text,
                phone.unread_count(record.owner_account_id),
                text,
            )
        except Exception:  # noqa: BLE001 - one bad text must not stop the rest
            continue
