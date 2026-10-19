"""Principal Pesto: the hall greeter and quest giver for Scammon Academia."""

from __future__ import annotations

import random

GREETINGS = (
    "Welcome to Scammon Academia!",
    "Need a hand, teacher?",
    "Ask me about quests any time.",
    "The gray husky is always watching, kindly.",
    "Classrooms are down the hall to the right.",
)


def on_enter(context, event):
    """Greet new arrivals to the hall now and then."""

    if random.random() < 0.5:
        context.npc_say(random.choice(GREETINGS))
