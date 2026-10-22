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
    SUBJECT_TAG_PREFIX,
    TIRED_ENERGY,
    VERY_TIRED_ENERGY,
    affinity,
    topic_energy_cost,
)

# Students each roll once per 1-second tick. The room-wide cooldown below keeps
# ambient chatter to at most one comment every five seconds in a class.
COMMENT_CHANCE = 0.04
CLASSROOM_CHAT_INTERVAL = timedelta(seconds=5)
TOPIC_REACTION_LIMIT = 2
CAFETERIA_MOVE_INTERVAL = (10.0, 15.0)
CAFETERIA_COMMENT_CHANCE = 0.04
CAFETERIA_CHAT_INTERVAL = timedelta(seconds=8)
VIBE_COMMENT_THRESHOLD = 10

_last_classroom_chat: dict[str, datetime] = {}
_last_cafeteria_chat: dict[str, datetime] = {}

CAFETERIA_LINES = (
    "These fries are so good.",
    "Is it recess yet?",
    "I saved you a seat!",
    "Somebody took the last chocolate milk.",
    "The mashed potatoes are looking back at me.",
    "Trade you my carrots for your cookie?",
    "I hope it is pizza day again tomorrow.",
)

CAFETERIA_PEER_LINES = (
    "Hey {peer}, want half of my cookie?",
    "{peer}, did you see the lunch lady's new hat?",
    "{peer}, save me a seat by the window!",
    "What did you get, {peer}?",
    "{peer}, want to swap sandwiches?",
    "Did you finish the math homework, {peer}?",
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

TEACHER_LIKED_LINES = (
    "The teacher actually listens to us.",
    "Best teacher ever, honestly.",
    "I hope we get this teacher again.",
    "This class is way more fun with them.",
)

TEACHER_DISLIKED_LINES = (
    "The teacher is being kind of unfair.",
    "I do not think the teacher likes us.",
    "Can we have a different teacher next time?",
    "This teacher gives way too much homework.",
)

PEER_LIKED_LINES = (
    "{peer} is my best friend in this class.",
    "I am glad {peer} is here.",
    "{peer} always has my back.",
    "Sitting next to {peer} makes class better.",
)

PEER_DISLIKED_LINES = (
    "{peer} keeps bothering me.",
    "I wish {peer} would stop talking.",
    "{peer} is not being very nice today.",
    "Why does {peer} keep copying me?",
)


def _topic_subject(card) -> str | None:
    if card is None:
        return None
    for tag in card.tags:
        if tag.startswith(SUBJECT_TAG_PREFIX):
            return tag[len(SUBJECT_TAG_PREFIX):]
    return None


def _active(context, event) -> bool:
    return bool(event.room_id) and context.state.get("lesson_room") == event.room_id


def _pick(lines, **fields):
    line = random.choice(lines)
    return line.format(**fields) if fields else line


def _say(context, text: str, style: str = "expression") -> None:
    context.npc_say(text, style=style)


def _peer_views(context) -> list[dict[str, object]]:
    own_id = getattr(getattr(context, "target", None), "peep_id", None)
    label = str(context.state.get("label", ""))
    return [
        peer
        for peer in (context.room.get("peeps") or [])
        if isinstance(peer.get("id"), str)
        and peer.get("id")
        and peer.get("id") != own_id
        and peer.get("label")
        and (not label or peer.get("label") != label)
    ]


def _strongest_peer_vibe(context) -> tuple[dict[str, object], int] | None:
    best: tuple[dict[str, object], int] | None = None
    for peer in _peer_views(context):
        score = context.vibe_toward(str(peer["id"]))
        if abs(score) < VIBE_COMMENT_THRESHOLD:
            continue
        if best is None or abs(score) > abs(best[1]):
            best = (peer, score)
    return best


def _teacher_vibe_line(context) -> str | None:
    teacher_id = context.state.get("teacher_account_id")
    if not isinstance(teacher_id, str) or not teacher_id:
        return None
    score = context.vibe_toward(teacher_id)
    if abs(score) < VIBE_COMMENT_THRESHOLD:
        return None
    return _pick(TEACHER_LIKED_LINES if score > 0 else TEACHER_DISLIKED_LINES)


def _peer_vibe_line(context) -> str | None:
    strongest = _strongest_peer_vibe(context)
    if strongest is None:
        return None
    peer, score = strongest
    lines = PEER_LIKED_LINES if score > 0 else PEER_DISLIKED_LINES
    return _pick(lines, peer=str(peer["label"]))


def _claim_classroom_chat(context, event) -> bool:
    """Claim the room's ambient-chatter slot when five seconds have passed."""

    room_id = str(event.room_id or "")
    if not room_id:
        return False
    previous = _last_classroom_chat.get(room_id)
    if previous is not None and context.now - previous < CLASSROOM_CHAT_INTERVAL:
        return False
    _last_classroom_chat[room_id] = context.now
    return True


def _claim_cafeteria_chat(context, event) -> bool:
    """Claim the cafeteria's lunch-chatter slot when the room is due to speak."""

    room_id = str(event.room_id or "")
    if not room_id:
        return False
    previous = _last_cafeteria_chat.get(room_id)
    if previous is not None and context.now - previous < CAFETERIA_CHAT_INTERVAL:
        return False
    _last_cafeteria_chat[room_id] = context.now
    return True


def _topic_reactor_ids(context, event) -> set[str]:
    """Return at most two student ids chosen to react to this topic."""

    student_ids = sorted(
        str(peep.get("id", ""))
        for peep in (context.room.get("peeps") or [])
        if str(peep.get("id", "")).startswith("student:")
    )
    targeted = getattr(getattr(event, "target", None), "peep_id", None)
    if isinstance(targeted, str) and targeted in student_ids:
        return {targeted}
    if len(student_ids) <= TOPIC_REACTION_LIMIT:
        return set(student_ids)
    card_id = context.card.id if context.card is not None else ""
    seed = sum((index + 1) * ord(char) for index, char in enumerate(card_id))
    start = seed % len(student_ids)
    return {
        student_ids[(start + offset) % len(student_ids)]
        for offset in range(TOPIC_REACTION_LIMIT)
    }


def _may_react_to_topic(context, event) -> bool:
    peep_id = getattr(context.target, "peep_id", None)
    return isinstance(peep_id, str) and peep_id in _topic_reactor_ids(context, event)


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

    if not _may_react_to_topic(context, event):
        return
    if event.room_id:
        _last_classroom_chat[event.room_id] = context.now

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
    if random.random() >= CAFETERIA_COMMENT_CHANCE or not _claim_cafeteria_chat(context, event):
        return
    vibe_line = _peer_vibe_line(context)
    if vibe_line is not None:
        _say(context, vibe_line)
        return
    peers = _peer_views(context)
    if peers:
        _say(context, _pick(CAFETERIA_PEER_LINES, peer=str(random.choice(peers)["label"])))
        return
    _say(context, _pick(CAFETERIA_LINES))


def on_tick(context, event):
    """Comment on the class at most once every five seconds."""

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
    if not _claim_classroom_chat(context, event):
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

    teacher_line = _teacher_vibe_line(context)
    if teacher_line is not None and random.random() < 0.5:
        _say(context, teacher_line)
        return
    peer_vibe_line = _peer_vibe_line(context)
    if peer_vibe_line is not None and random.random() < 0.6:
        _say(context, peer_vibe_line)
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
