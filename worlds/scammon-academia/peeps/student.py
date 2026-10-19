"""Generated student NPC behavior for Scammon Academia lessons.

Students are materialized at runtime by the classrooms mod and share this one
script. Every student keeps its own durable state row (subjects, trait, Energy,
attention, and heard topics), so a room-level card play or tick reaches each of
them independently and they react in character.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import random

from mods.classrooms.lessons import (
    MAX_ATTENTION,
    SUBJECT_LABELS,
    TIRED_ENERGY,
    VERY_TIRED_ENERGY,
    affinity,
    topic_energy_cost,
)

# Five students each roll once per tick, so ~1/5 per tick is one comment per
# five seconds across the class.
COMMENT_CHANCE = 0.04
CAFETERIA_MOVE_INTERVAL = (10.0, 15.0)
CAFETERIA_COMMENT_CHANCE = 0.012

CAFETERIA_LINES = (
    "These fries are so good.",
    "Is it recess yet?",
    "I saved you a seat!",
    "Somebody took the last chocolate milk.",
    "The mashed potatoes are looking back at me.",
    "Trade you my carrots for your cookie?",
    "I hope it is pizza day again tomorrow.",
)

LIKED_LINES = (
    "{subject}? Yes! My favorite.",
    "Ooh, I love {subject}.",
    "Finally, {subject}! I was waiting for this.",
    "This is my best subject, {subject}.",
    "I could do {subject} all day.",
)

DISLIKED_LINES = (
    "{subject} again? Ugh.",
    "I never get {subject}.",
    "My brain hurts when we do {subject}.",
    "Please, not {subject}...",
    "{subject} is the worst.",
)

NEUTRAL_LINES = (
    "Okay, {subject}, I'm listening.",
    "Huh, {subject}. Sure.",
    "I guess {subject} is fine.",
    "Writing this down for {subject}.",
    "So that's {subject}.",
)

TIRED_LINES = (
    "I'm so sleepy...",
    "My eyes are closing.",
    "Can we take a break?",
    "*yawns loudly*",
    "I need a nap, not a lesson.",
)

VERY_TIRED_LINES = (
    "I can't keep my head up...",
    "Everything is going blurry.",
    "Five more minutes of sleep, please.",
)

DISTRACTED_LINES = (
    "Wait, what did they just say?",
    "I keep looking out the window.",
    "Is it recess yet?",
    "I forgot the last three words.",
)

PEER_LINES = (
    "{peer} likes {subject} too, right?",
    "{peer} is nodding, they agree with me.",
    "Me and {peer} both like {subject}!",
    "Hey {peer}, did you get that?",
    "{peer}, are you even awake?",
    "Shh, {peer}, I'm trying to learn.",
)

CLASS_LINES = (
    "Everyone looks pretty into this.",
    "The whole class is quiet for once.",
    "Some of us are really fading.",
    "I think we're all tired now.",
    "Best class mood in a while.",
)


def _topic_subject(card) -> str | None:
    if card is None:
        return None
    for tag in card.tags:
        if tag.startswith("subject:"):
            return tag.split(":", 1)[1]
    return None


def _active(context, event) -> bool:
    return bool(event.room_id) and context.state.get("lesson_room") == event.room_id


def _pick(lines, **fields):
    line = random.choice(lines)
    return line.format(**fields) if fields else line


def _say(context, text: str, style: str = "expression") -> None:
    context.npc_say(text, style=style)


def on_card_play(context, event):
    """React to a topic taught to the class."""

    subject = _topic_subject(context.card)
    if subject is None or not _active(context, event):
        return

    state = context.state
    favorites = tuple(item for item in state.get("favorites", []) if isinstance(item, str))
    tricky = state.get("tricky") if isinstance(state.get("tricky"), str) else None
    trait = state.get("trait") if isinstance(state.get("trait"), str) else None

    energy = float(state.get("energy", 10))
    attention = float(state.get("attention", 5))
    max_energy = float(state.get("max_energy", 10))

    energy = max(0.0, energy - topic_energy_cost(trait, random))
    kind = affinity(subject, favorites, tricky)
    if kind == "favorite":
        attention = min(MAX_ATTENTION, attention + 2)
    elif kind == "tricky":
        attention = max(0, attention - 2)
    else:
        attention = min(MAX_ATTENTION, attention + 1)

    if energy <= VERY_TIRED_ENERGY:
        attention = max(0, attention - 2)
    elif energy <= TIRED_ENERGY:
        attention = max(0, attention - 1)

    state["energy"] = energy
    state["attention"] = attention
    topics = [item for item in state.get("topics", []) if isinstance(item, str)]
    if subject not in topics:
        topics.append(subject)
    state["topics"] = topics

    display = SUBJECT_LABELS.get(subject, subject)
    if energy <= VERY_TIRED_ENERGY:
        _say(context, _pick(VERY_TIRED_LINES), "thinking")
        return
    if kind == "favorite":
        _say(context, _pick(LIKED_LINES, subject=display))
    elif kind == "tricky":
        _say(context, _pick(DISLIKED_LINES, subject=display), "spiky")
    else:
        _say(context, _pick(NEUTRAL_LINES, subject=display))


def _cafeteria_deadline(context, event):
    """Return the next sprite-move deadline for this cafeteria visit."""

    state = context.state
    if state.get("sprite_move_room") != event.room_id:
        state["sprite_move_room"] = event.room_id
        seconds = random.uniform(*CAFETERIA_MOVE_INTERVAL)
        state["next_sprite_move_at"] = (context.now + timedelta(seconds=seconds)).isoformat()
        return None
    raw = state.get("next_sprite_move_at")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _cafeteria_tick(context, event):
    """Wander the cafeteria and occasionally chat over lunch."""

    deadline = _cafeteria_deadline(context, event)
    if deadline is not None and context.now >= deadline:
        context.move_sprite_random()
        seconds = random.uniform(*CAFETERIA_MOVE_INTERVAL)
        context.state["next_sprite_move_at"] = (context.now + timedelta(seconds=seconds)).isoformat()
    if random.random() < CAFETERIA_COMMENT_CHANCE:
        _say(context, _pick(CAFETERIA_LINES))


def on_tick(context, event):
    """Comment on the class at an average of about one line per five seconds."""

    if context.sprites_enabled:
        _cafeteria_tick(context, event)
        return
    if not _active(context, event):
        return

    state = context.state
    energy = float(state.get("energy", 10))
    attention = float(state.get("attention", 5))

    # A tired student's attention keeps slipping even between topics.
    if energy <= VERY_TIRED_ENERGY or (energy <= TIRED_ENERGY and random.random() < 0.5):
        attention = max(0, attention - 1)
        state["attention"] = attention

    if random.random() >= COMMENT_CHANCE:
        return
    favorites = tuple(item for item in state.get("favorites", []) if isinstance(item, str))
    subjects = [item for item in state.get("topics", []) if isinstance(item, str)]
    label = str(state.get("label", ""))

    if energy <= VERY_TIRED_ENERGY:
        _say(context, _pick(VERY_TIRED_LINES), "thinking")
        return
    if energy <= TIRED_ENERGY:
        _say(context, _pick(TIRED_LINES), "thinking")
        return
    if attention <= 2:
        _say(context, _pick(DISTRACTED_LINES), "thinking")
        return

    peers = [peer.get("label") for peer in (context.room.get("peeps") or []) if peer.get("label") and peer.get("label") != label]
    subject_id = favorites[0] if favorites else (subjects[-1] if subjects else None)
    subject = SUBJECT_LABELS.get(subject_id, subject_id) if subject_id else "class"
    roll = random.random()
    if peers and roll < 0.35:
        _say(context, _pick(PEER_LINES, peer=random.choice(peers), subject=subject))
    elif roll < 0.6:
        _say(context, _pick(CLASS_LINES))
    else:
        _say(context, _pick(NEUTRAL_LINES, subject=subject))
