"""Difficulty, minigame parameters, and step resolution for TinyTown Job Office runs."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from mods.tinytown.job_library import JobDefinition, JobLibrary, JobStep

# --- Challenge styles and trait matching -----------------------------------
#
# Every step tests one of five "challenge styles" (the keys below). A roommate's
# traits (ids from mods.tinytown.catalog.TRAITS_BY_ID) make them better or worse
# at a style, which lowers or raises the hidden difficulty of that scene.

# Traits that are a STRONG fit for a style. Each match lowers difficulty by
# TRAIT_PRIMARY_BONUS (capped at TRAIT_PRIMARY_CAP). The same table also steers
# which authored narration choice is shown for a lead (choose_approach).
APPROACH_PRIMARY: dict[str, frozenset[str]] = {
    "grit": frozenset({"energetic", "outdoorsy", "grumpy"}),
    "nouse": frozenset({"bookish", "tinkerer", "stargazer"}),
    "charm": frozenset({"friendly", "social", "foodie"}),
    "care": frozenset({"clean", "cozy", "bookish"}),
    "chaos": frozenset({"artsy", "grumpy", "stargazer"}),
}

# Traits that are a WEAK fit for a style. Each match lowers difficulty by
# TRAIT_SUPPORT_BONUS (capped at TRAIT_SUPPORT_CAP).
APPROACH_SUPPORT: dict[str, frozenset[str]] = {
    "grit": frozenset({"tinkerer", "clean"}),
    "nouse": frozenset({"artsy", "clean"}),
    "charm": frozenset({"cozy", "artsy"}),
    "care": frozenset({"foodie", "artsy"}),
    "chaos": frozenset({"social", "energetic"}),
}

# Maps a step's authored `pool` (the kind of complication it draws from, see
# content/jobs/complications.yaml) to the challenge style it tests. This is what
# makes a "machines" scene reward tinkerers and a "people" scene reward the
# friendly. Unknown pools fall back to "nouse".
POOL_CHALLENGE: dict[str, str] = {
    "machines": "nouse",
    "paperwork": "nouse",
    "office": "nouse",
    "people": "charm",
    "stage": "charm",
    "mess": "care",
    "food": "care",
    "animals": "care",
    "outdoors": "grit",
    "danger": "grit",
    "creative": "chaos",
    "night": "chaos",
}

# Difficulty removed per matching trait, and the most a lead can gain from each
# kind (so three matching traits do not stack beyond the cap).
TRAIT_PRIMARY_BONUS = 1.2
TRAIT_PRIMARY_CAP = 2.0
TRAIT_SUPPORT_BONUS = 0.6
TRAIT_SUPPORT_CAP = 1.2
# Added when the lead has no trait that helps at all: an unremarkable lead is a
# little worse than the baseline.
TRAIT_MISMATCH_PENALTY = 0.5

# Choosing which authored narration to show: a primary-trait match scores this
# much, a support-trait match scores this much, and a choice matching the step's
# own challenge style gets a +1 tie-break.
NARRATION_PRIMARY_WEIGHT = 2.0
NARRATION_SUPPORT_WEIGHT = 1.0

# --- Rewards ------------------------------------------------------------------

# steps passed (0-4) -> (Bops paid to the player, vibe change applied to EACH
# invited roommate toward the player). Quitting early pays for the steps already
# passed; the remaining scenes count as misses.
JOB_REWARDS: dict[int, tuple[int, int]] = {
    0: (0, -5),
    1: (10, 0),
    2: (20, 5),
    3: (40, 10),
    4: (100, 20),
}

# --- Difficulty ---------------------------------------------------------------
#
# Difficulty is a hidden 1-10 score. It is computed as:
#   base_difficulty(job, step) + trait mods + energy mods + vibe mod
# then clamped to [MIN_DIFFICULTY, MAX_DIFFICULTY] and mapped onto each
# minigame's speed/size/count tuning by game_params().

# Base difficulty = BASE_DIFFICULTY + job.tier * BASE_PER_TIER + step_index * BASE_PER_STEP.
# Tier 1 jobs are easy, tier 3 hard, and later steps in a job are harder. Kept low
# on purpose so energy and trait modifiers have headroom before hitting the clamp.
BASE_DIFFICULTY = 2.6
BASE_PER_TIER = 0.8
BASE_PER_STEP = 0.4

MIN_DIFFICULTY = 1.0
MAX_DIFFICULTY = 10.0

# Energy (0-100) is the biggest lever on difficulty. At REST_ENERGY the shift is
# zero; above it a lead earns up to MAX_REST_BONUS off the difficulty (at energy
# 100); below it the penalty rises toward MAX_EXHAUSTION_PENALTY (at energy 0),
# growing faster than linearly (EXHAUSTION_CURVE) so a nearly-drained peep is
# clearly the wrong pick while a merely tired one is only a little worse.
REST_ENERGY = 55.0
MAX_REST_BONUS = 1.4
MAX_EXHAUSTION_PENALTY = 6.0
EXHAUSTION_CURVE = 1.4

# When a roommate leads, the PLAYER's own (post-charge) energy still matters, at
# this fraction of a lead's weight. When the player leads, only their own energy
# counts, at full weight.
PLAYER_SUPPORT_WEIGHT = 0.5

# Mutual vibe (average of roommate->player and player->roommate, roughly -100..100)
# is divided by this to get the difficulty shift: warm pairs make scenes easier,
# cold ones harder.
VIBE_DIVISOR = 40.0

# Persistent energy a roommate loses (on their household record) after leading one
# scene, so rotating roommates matters across a shift and beyond it.
FATIGUE_PER_STEP = 6.0

# --- Picker labels ------------------------------------------------------------

# The qualitative fit shown for each possible lead instead of numbers. A lead whose
# total (non-base) modifier is at or below FIT_GREAT_MODIFIER is "In their element",
# at or below FIT_SOLID_MODIFIER is "Solid", otherwise "Out of their depth". The
# 1-5 challenge meter shows difficulty / DIFFICULTY_PER_PIP, rounded up.
FIT_LABELS = ("In their element", "Solid", "Out of their depth")
FIT_GREAT_MODIFIER = -1.5
FIT_SOLID_MODIFIER = 0.5
DIFFICULTY_PER_PIP = 2.0

# --- Result validation (anti-cheat) --------------------------------------------

# The client reports a minigame's score and elapsed time; the server decides pass or
# fail. A run shorter than MIN_ELAPSED_RATIO * expected_ms (a game's typical
# duration, from game_params) is impossible for real play and scores zero instead
# of raising an error, so mashing never leaves the UI stuck. Results longer than
# MAX_ELAPSED_MS are rejected outright.
MIN_ELAPSED_RATIO = 0.15
MAX_ELAPSED_MS = 10 * 60 * 1000


@dataclass(frozen=True, slots=True)
class StepResolution:
    """One resolved challenge, as shown to the player."""

    passed: bool
    text: str
    approach_label: str
    lead_name: str
    lead_id: str
    step_index: int
    steps_passed: int
    completed: bool
    score: int
    required: int
    total: int


def reward_for(steps_passed: int) -> tuple[int, int]:
    """Return (bops, vibe delta) for a completed shift."""

    return JOB_REWARDS[max(0, min(4, int(steps_passed)))]


def ending_key(steps_passed: int) -> str:
    """Map a step count to the authored ending key."""

    return ("disaster", "scraped", "okay", "great", "legendary")[max(0, min(4, int(steps_passed)))]


def _value(participant: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(participant.get(key, default))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _lerp(low: float, high: float, amount: float) -> float:
    return low + (high - low) * amount


def step_challenge(job_step: JobStep) -> str:
    """Return the approach a step's pool tests."""

    return POOL_CHALLENGE.get(job_step.pool, "nouse")


def trait_matches(traits: tuple[str, ...] | list[str], approach: str) -> tuple[int, int]:
    """Return (primary matches, support matches) for a set of traits."""

    trait_set = {str(trait) for trait in traits}
    return (
        len(trait_set & APPROACH_PRIMARY[approach]),
        len(trait_set & APPROACH_SUPPORT[approach]),
    )


def base_difficulty(job: JobDefinition, step_index: int) -> float:
    """Return a step's starting difficulty from its job tier and position."""

    return BASE_DIFFICULTY + job.tier * BASE_PER_TIER + step_index * BASE_PER_STEP


def exhaustion(energy: float) -> float:
    """Return 0 (fine) to 1 (ready to drop) for an energy value."""

    return _clamp((REST_ENERGY - float(energy)) / REST_ENERGY, 0.0, 1.0)


def energy_modifier(energy: float) -> float:
    """Return the difficulty shift for one energy level.

    Rested peeps earn a small bonus; below the rest line the penalty grows
    faster than linearly so a drained peep is clearly the wrong pick.
    """

    value = _clamp(float(energy), 0.0, 100.0)
    if value >= REST_ENERGY:
        return -MAX_REST_BONUS * (value - REST_ENERGY) / (100.0 - REST_ENERGY)
    return MAX_EXHAUSTION_PENALTY * exhaustion(value) ** EXHAUSTION_CURVE


def lead_modifier(player: dict[str, Any], lead: dict[str, Any], challenge: str) -> float:
    """Return the combined trait, energy, and vibe modifier for one lead."""

    primary, support = trait_matches(lead.get("traits", ()), challenge)
    trait_mod = -min(TRAIT_PRIMARY_CAP, TRAIT_PRIMARY_BONUS * primary) - min(
        TRAIT_SUPPORT_CAP, TRAIT_SUPPORT_BONUS * support
    )
    if primary == 0 and support == 0:
        trait_mod += TRAIT_MISMATCH_PENALTY
    lead_energy = energy_modifier(_value(lead, "energy", REST_ENERGY))
    if lead.get("is_player"):
        return trait_mod + lead_energy
    support_energy = PLAYER_SUPPORT_WEIGHT * energy_modifier(_value(player, "energy", REST_ENERGY))
    mutual = (_value(lead, "vibe") + _value(lead, "vibe_back")) / 2.0
    return trait_mod + lead_energy + support_energy - mutual / VIBE_DIVISOR


def difficulty_for(
    job: JobDefinition,
    step_index: int,
    player: dict[str, Any],
    lead: dict[str, Any],
) -> float:
    """Return the hidden 1-10 difficulty for one lead on one step."""

    challenge = step_challenge(job.steps[step_index])
    raw = base_difficulty(job, step_index) + lead_modifier(player, lead, challenge)
    return _clamp(raw, MIN_DIFFICULTY, MAX_DIFFICULTY)


def fit_for(
    job: JobDefinition,
    step_index: int,
    player: dict[str, Any],
    lead: dict[str, Any],
) -> dict[str, Any]:
    """Return the qualitative fit label and meter pips shown in the picker."""

    challenge = step_challenge(job.steps[step_index])
    modifier = lead_modifier(player, lead, challenge)
    difficulty = difficulty_for(job, step_index, player, lead)
    if modifier <= FIT_GREAT_MODIFIER:
        label = FIT_LABELS[0]
    elif modifier <= FIT_SOLID_MODIFIER:
        label = FIT_LABELS[1]
    else:
        label = FIT_LABELS[2]
    return {"label": label, "pips": max(1, min(5, math.ceil(difficulty / DIFFICULTY_PER_PIP)))}


def choose_approach(job_step: JobStep, lead: dict[str, Any]) -> int:
    """Pick the authored narration that best matches the lead's personality."""

    challenge = step_challenge(job_step)
    traits = {str(trait) for trait in lead.get("traits", ())}
    best_index = 0
    best_key = (-1.0, 0)
    for index, choice in enumerate(job_step.choices):
        score = NARRATION_PRIMARY_WEIGHT * len(traits & APPROACH_PRIMARY[choice.approach])
        score += NARRATION_SUPPORT_WEIGHT * len(traits & APPROACH_SUPPORT[choice.approach])
        on_challenge = 1 if choice.approach == challenge else 0
        key = (score + on_challenge, on_challenge)
        if key > best_key:
            best_key = key
            best_index = index
    return best_index


def game_params(game: str, difficulty: float, seed: int, fatigue: float = 0.0) -> dict[str, Any]:
    """Map a difficulty onto one minigame template's tuning values.

    ``t`` runs from 0 (difficulty 1) to 1 (difficulty 10); each ``_lerp(easy, hard, t)``
    below interpolates one tuning knob between those ends. Common outputs:
    ``required`` (hits needed to pass the scene), ``max_score`` (most hits possible,
    anything higher from a client is rejected), and ``expected_ms`` (a typical
    duration, used only for the too-fast check). Per game, harder means:

    - drop-catch: faster fall, thinner target band, more tokens, tighter spacing.
    - sweep-stop: faster needle, narrower arcs, all three stops needed past t=0.5.
    - ring-match: faster growth, tighter tolerance, all three rings needed past t=0.4.
    - rhythm-lane: more notes, shorter travel/gap, a smaller timing window (ms).
    - pop-whack: shorter time visible, more decoys (tapping one costs a hit),
      a larger share of targets needed.
    - hold-meter: faster fill and a narrower release band (always 2 of 3 holds).

    ``fatigue`` (0-1) does not change the numbers; it only drives the drowsy visuals.
    """

    t = _clamp((float(difficulty) - 1.0) / 9.0, 0.0, 1.0)
    params: dict[str, Any] = {
        "game": game,
        "seed": int(seed),
        "difficulty": round(float(difficulty), 2),
        "fatigue": round(_clamp(float(fatigue), 0.0, 1.0), 2),
    }
    if game == "drop-catch":
        total = round(_lerp(6, 10, t))
        speed = _lerp(0.55, 1.45, t)
        interval = _lerp(1.0, 0.7, t)
        params.update(
            total=total,
            required=round(_lerp(4, 6, t)),
            speed=round(speed, 3),
            band=round(_lerp(0.24, 0.12, t), 3),
            interval=round(interval, 3),
            max_score=total,
            expected_ms=int((0.6 + total * interval + 1.0 / speed) * 1000),
        )
    elif game == "sweep-stop":
        rev = _lerp(0.55, 1.45, t)
        params.update(
            stops=3,
            required=2 if t < 0.5 else 3,
            rev_per_sec=round(rev, 3),
            arc_deg=round(_lerp(32, 12, t), 1),
            max_score=3,
            expected_ms=int(3 * 0.5 / rev * 1000),
        )
    elif game == "ring-match":
        speed = _lerp(0.55, 1.35, t)
        params.update(
            rings=3,
            required=2 if t < 0.4 else 3,
            speed=round(speed, 3),
            tolerance=round(_lerp(22, 8, t), 1),
            max_score=3,
            expected_ms=int(3 * 0.5 / speed * 1000),
        )
    elif game == "rhythm-lane":
        notes = round(_lerp(7, 10, t))
        gap = _lerp(0.75, 0.5, t)
        travel = _lerp(2.2, 1.0, t)
        params.update(
            notes=notes,
            required=math.ceil(notes * 0.7),
            travel=round(travel, 3),
            window_ms=round(_lerp(180, 80, t)),
            gap=round(gap, 3),
            max_score=notes,
            expected_ms=int((1.0 + travel + notes * gap) * 1000),
        )
    elif game == "pop-whack":
        targets = round(_lerp(5, 7, t))
        visible = _lerp(1.1, 0.5, t)
        params.update(
            targets=targets,
            required=max(3, round(targets * _lerp(0.6, 0.8, t))),
            visible=round(visible, 3),
            decoys=round(_lerp(0, 3, t)),
            max_score=targets,
            expected_ms=int((0.8 + targets * (visible + 0.35)) * 1000),
        )
    elif game == "hold-meter":
        fill = _lerp(0.55, 1.3, t)
        params.update(
            holds=3,
            required=2,
            fill=round(fill, 3),
            band=round(_lerp(0.28, 0.12, t), 3),
            max_score=3,
            expected_ms=int(3 * 0.45 / fill * 1000),
        )
    else:
        raise ValueError(f"Unknown minigame '{game}'.")
    return params


def generate_run(
    job: JobDefinition,
    library: JobLibrary,
    player: dict[str, Any],
    helpers: list[dict[str, Any]],
    seed: str,
) -> dict[str, Any]:
    """Build a deterministic run state from content, participants, and a seed."""

    rng = random.Random(seed)
    used_complications: set[str] = set()
    steps: list[dict[str, Any]] = []
    for index, step in enumerate(job.steps):
        pool = library.complications[step.pool]
        available = [entry for entry in pool if entry.id not in used_complications] or list(pool)
        complication = rng.choice(available)
        used_complications.add(complication.id)
        steps.append(
            {
                "index": index,
                "complication": complication.id,
                "complication_text": complication.text,
                "detail": rng.choice(library.details),
                "seed": rng.randrange(1, 2**31 - 1),
                "challenge": None,
                "passed": None,
                "lead_id": None,
                "choice": None,
            }
        )
    return {
        "job_id": job.id,
        "player": player,
        "helpers": helpers,
        "steps": steps,
        "step_index": 0,
        "steps_passed": 0,
        "completed": False,
    }


def current_step(run: dict[str, Any]) -> dict[str, Any] | None:
    """Return the current unresolved step, or None when the run is complete."""

    index = int(run.get("step_index", 0))
    steps = run.get("steps", [])
    if index < 0 or index >= len(steps):
        return None
    return steps[index]


def present_task(step: dict[str, Any], job_step: JobStep) -> str:
    """Compose the visible task from its authored and procedural pieces."""

    return f"{job_step.setup} {step['complication_text']} {step['detail']}".strip()


def used_lead_ids(run: dict[str, Any]) -> set[str]:
    """Return the roommates who already took a scene on this shift."""

    return {
        str(step["lead_id"])
        for step in run.get("steps", [])
        if step.get("lead_id") and step.get("passed") is not None
    }


def lead_for(run: dict[str, Any], helper_id: str | None) -> dict[str, Any]:
    """Return the participant who leads a step: the player, or one invited roommate."""

    if not helper_id:
        return run["player"]
    for helper in run.get("helpers", []):
        if str(helper.get("npc_id")) == str(helper_id):
            return helper
    raise ValueError("That roommate did not come along on this shift.")


def prepare_challenge(
    run: dict[str, Any],
    job: JobDefinition,
    helper_id: str | None,
    challenge_id: str,
) -> dict[str, Any]:
    """Store and return the minigame challenge for the current step."""

    step = current_step(run)
    if step is None:
        raise ValueError("This shift is already finished.")
    lead = lead_for(run, helper_id)
    if not lead.get("is_player") and str(lead["npc_id"]) in used_lead_ids(run):
        raise ValueError(f"{lead.get('name', 'That roommate')} already took a scene on this shift.")
    job_step = job.steps[step["index"]]
    difficulty = difficulty_for(job, step["index"], run["player"], lead)
    params = game_params(
        job_step.game,
        difficulty,
        int(step["seed"]),
        exhaustion(_value(lead, "energy", REST_ENERGY)),
    )
    challenge = {
        "id": challenge_id,
        "lead_id": None if lead.get("is_player") else str(lead["npc_id"]),
        "choice": choose_approach(job_step, lead),
        "params": params,
        "resolved": False,
    }
    step["challenge"] = challenge
    return challenge


def resolve_challenge(
    run: dict[str, Any],
    job: JobDefinition,
    challenge_id: str,
    score: int,
    elapsed_ms: int,
) -> StepResolution:
    """Resolve the current challenge from a reported score and apply fatigue."""

    step = current_step(run)
    if step is None:
        raise ValueError("This shift is already finished.")
    challenge = step.get("challenge")
    if not challenge or challenge.get("resolved") or challenge.get("id") != challenge_id:
        raise ValueError("That challenge is no longer active.")
    params = challenge["params"]
    if not 0 <= int(score) <= int(params["max_score"]):
        raise ValueError("That score is not possible for this challenge.")
    elapsed = int(elapsed_ms)
    if elapsed < 0 or elapsed > MAX_ELAPSED_MS:
        raise ValueError("That challenge result was not accepted.")
    too_fast = elapsed < int(params["expected_ms"] * MIN_ELAPSED_RATIO)
    score = 0 if too_fast else int(score)
    passed = score >= int(params["required"])
    job_step = job.steps[step["index"]]
    choice = job_step.choices[int(challenge["choice"])]
    lead_id = challenge["lead_id"]
    lead = lead_for(run, lead_id)
    challenge["resolved"] = True
    step["passed"] = passed
    step["lead_id"] = lead_id
    step["choice"] = int(challenge["choice"])
    if passed:
        run["steps_passed"] = int(run.get("steps_passed", 0)) + 1
    if not lead.get("is_player"):
        lead["energy"] = max(0.0, _value(lead, "energy", 50.0) - FATIGUE_PER_STEP)
    run["step_index"] = int(run["step_index"]) + 1
    completed = int(run["step_index"]) >= len(run["steps"])
    run["completed"] = completed
    return StepResolution(
        passed=passed,
        text=choice.success if passed else choice.failure,
        approach_label=choice.label,
        lead_name=str(lead.get("name", "You")),
        lead_id=lead_id or "",
        step_index=int(step["index"]),
        steps_passed=int(run["steps_passed"]),
        completed=completed,
        score=int(score),
        required=int(params["required"]),
        total=int(params["max_score"]),
    )
