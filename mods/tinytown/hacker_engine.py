"""Pure rules for the Hacker Collective: difficulty, tuning, rewards, banter."""

from __future__ import annotations

import random
from collections.abc import Iterable
from typing import Any

from mods.tinytown.hacker_library import BanterLine
from mods.tinytown.job_engine import (
    MAX_ELAPSED_MS,
    MIN_ELAPSED_RATIO,
    exhaustion,
    game_params,
    lead_modifier,
)

DEADLINE_SECONDS = 30 * 60
FATIGUE_PER_NODE = 3.0
VIBE_PER_FLOOR = 12
VIBE_GATE = -50
NODE_BOPS_MIN = 2
NODE_BOPS_MAX = 8
CENTRAL_BOPS_MIN = 15
CENTRAL_BOPS_MAX = 40
CENTRAL_KUDOS = 3
CENTRAL_PROPS = 2
MAX_SCREENS = 3
BANTER_LIMIT = 3

GAME_IDS = ("drop-catch", "sweep-stop", "ring-match", "rhythm-lane", "pop-whack", "hold-meter")
FIT_LABELS = ("In their element", "Solid", "Out of their depth")
CENTRAL_GAME = "hold-meter"


def screens_for(layer: int, *, central: bool = False) -> int:
    """Return how many maths screens a node asks for."""

    if central:
        return MAX_SCREENS
    if layer <= 1:
        return 1
    if layer <= 3:
        return 2
    return MAX_SCREENS


def base_difficulty(grade: int, layer: int, *, central: bool = False) -> float:
    base = 2.4 + (max(1, min(5, grade)) - 1) * 0.35
    return base + layer * 0.45 + (1.1 if central else 0.0)


def node_difficulty(
    grade: int,
    layer: int,
    *,
    central: bool,
    player: dict[str, Any],
    lead: dict[str, Any],
    approach: str,
) -> float:
    """Return the hidden 1-10 difficulty for one lead on one node."""

    raw = base_difficulty(grade, layer, central=central) + lead_modifier(player, lead, approach)
    return max(1.0, min(10.0, raw))


def node_modifier(
    grade: int,
    layer: int,
    *,
    central: bool,
    player: dict[str, Any],
    lead: dict[str, Any],
    approach: str,
) -> float:
    return round(
        node_difficulty(
            grade,
            layer,
            central=central,
            player=player,
            lead=lead,
            approach=approach,
        )
        - base_difficulty(grade, layer, central=central),
        2,
    )


def fit_for(
    grade: int,
    layer: int,
    *,
    central: bool,
    player: dict[str, Any],
    lead: dict[str, Any],
    approach: str,
) -> dict[str, Any]:
    """Return the qualitative fit chip shown next to the lead."""

    modifier = node_modifier(
        grade,
        layer,
        central=central,
        player=player,
        lead=lead,
        approach=approach,
    )
    difficulty = node_difficulty(
        grade,
        layer,
        central=central,
        player=player,
        lead=lead,
        approach=approach,
    )
    if modifier <= -1.5:
        label = FIT_LABELS[0]
    elif modifier <= 0.5:
        label = FIT_LABELS[1]
    else:
        label = FIT_LABELS[2]
    return {"label": label, "pips": max(1, min(5, int(difficulty / 2) + 1))}


def pick_game(seed: str, node_id: str, *, central: bool = False) -> str:
    """Choose a reflex minigame deterministically for a node."""

    if central:
        return CENTRAL_GAME
    rng = random.Random(f"tinytown-hacker-game:{seed}:{node_id}")
    return rng.choice(GAME_IDS)


def challenge_for(
    *,
    seed: str,
    node_id: str,
    grade: int,
    layer: int,
    central: bool,
    player: dict[str, Any],
    lead: dict[str, Any],
    approach: str,
    attempt: int,
) -> dict[str, Any]:
    """Return the challenge id, game, tuning params, and hidden difficulty."""

    difficulty = node_difficulty(
        grade,
        layer,
        central=central,
        player=player,
        lead=lead,
        approach=approach,
    )
    fatigue = exhaustion(float(lead.get("energy", 70.0)))
    game = pick_game(seed, node_id, central=central)
    tuning_seed = random.Random(f"tinytown-hacker-params:{seed}:{node_id}:{attempt}").randrange(1, 2**31 - 1)
    params = game_params(game, difficulty, tuning_seed, fatigue)
    params["payout"] = True
    return {
        "game": game,
        "params": params,
        "difficulty": round(difficulty, 2),
        "seed": tuning_seed,
    }


def score_result(params: dict[str, Any], score: int, elapsed_ms: int) -> tuple[bool, int, str]:
    """Return (passed, counted_score, note) for a finished payout challenge.

    Reflex challenges always pass; the counted score only sets the payout.
    """

    expected = int(params.get("expected_ms", 1000))
    maximum = int(params.get("max_score", 0))
    if int(score) < 0 or int(score) > maximum:
        return True, 0, "That result did not look like real play, so it paid the floor rate."
    if elapsed_ms < expected * MIN_ELAPSED_RATIO:
        return True, 0, "Too fast to count. The node still falls, at the floor rate."
    if elapsed_ms > MAX_ELAPSED_MS:
        return True, 0, "That challenge ran far too long. The node still falls, at the floor rate."
    counted = max(0, min(int(score), maximum))
    return True, counted, ""


def payout_bops(score: int, max_score: int, minimum: int, maximum: int) -> int:
    """Map a reflex score onto a Bops payout between the two bounds."""

    peak = max(1, int(max_score))
    ratio = max(0.0, min(1.0, float(score) / peak))
    return round(int(minimum) + (int(maximum) - int(minimum)) * ratio)



def tip_pack(
    grade: int,
    screens: list[dict[str, Any]],
    lines: Iterable[BanterLine],
    seed: str,
) -> list[str]:
    """Return helpful facts and strategy lines that never reveal an answer."""

    forbidden: set[str] = set()
    prompts: set[str] = set()
    for screen in screens:
        payload = screen.get("payload", {})
        for value in screen.get("answers", {}).values():
            forbidden.add(str(value).strip())
        for prompt in payload.get("prompts", []):
            prompts.add(str(prompt.get("text", "")).strip())
            for choice in prompt.get("choices", []):
                forbidden.add(str(choice.get("label", "")).strip())
        for equation in payload.get("equations", []):
            prompts.add(str(equation.get("text", "")).strip())
        for problem in payload.get("problems", []):
            prompts.add(f"{problem.get('top')} × {problem.get('bottom')}")
        for part in payload.get("parts", []):
            prompts.add(str(part.get("text", "")).strip())
    rng = random.Random(f"tinytown-hacker-tips:{seed}")
    facts: list[str] = []
    for _ in range(24):
        if len(facts) >= 3:
            break
        if grade >= 5:
            left, right = rng.randint(2, 9), rng.randint(2, 9)
            product = left * right
            expression = f"{left} × {right}"
            if str(product) in forbidden or expression in prompts:
                continue
            facts.append(f"Useful fact: {expression} = {product}.")
        else:
            left, right = rng.randint(1, 9), rng.randint(1, 9)
            operator = rng.choice(("+", "-"))
            if operator == "-" and left < right:
                left, right = right, left
            result = left + right if operator == "+" else left - right
            expression = f"{left} {operator} {right}"
            if str(result) in forbidden or expression in prompts:
                continue
            facts.append(f"Useful fact: {expression} = {result}.")
    authored = [line.text for line in lines if line.event == "tip"]
    rng.shuffle(authored)
    packed: list[str] = []
    for tip in [*facts, *authored]:
        if tip not in packed:
            packed.append(tip)
    return packed[:6]

def mood_for(energy: float) -> str:
    fatigue = exhaustion(energy)
    if fatigue >= 0.75:
        return "drained"
    if fatigue >= 0.4:
        return "tired"
    return "rested"


def _eligible(line: BanterLine, traits: set[str], mood: str) -> bool:
    if line.traits and not set(line.traits) & traits:
        return False
    return not (line.mood and line.mood != mood)


def banter_pool(lines: Iterable[BanterLine], lead: dict[str, Any] | None, seed: str, limit: int = BANTER_LIMIT) -> dict[str, list[str]]:
    """Group authored reactions by event for the current roommate."""

    traits = {str(trait) for trait in (lead or {}).get("traits", ())}
    mood = mood_for(float((lead or {}).get("energy", 70.0))) if lead else ""
    rng = random.Random(f"tinytown-hacker-banter:{seed}")
    grouped: dict[str, list[str]] = {}
    for line in lines:
        if not _eligible(line, traits, mood):
            continue
        grouped.setdefault(line.event, []).append(line.text)
    for event, texts in grouped.items():
        rng.shuffle(texts)
        grouped[event] = texts[:limit]
    return grouped
