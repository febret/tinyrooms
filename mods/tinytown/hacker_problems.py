"""Seeded maths screens for the Hacker Collective educational nodes.

Every screen is a plain dict so it can be stored in a run's JSON state and sent
to the iframe. Generators are pure: the caller supplies a ``random.Random``.
"""

from __future__ import annotations

import random
from typing import Any

GRADE_SCREENS: dict[int, tuple[str, ...]] = {
    1: ("type-in", "match", "fill-gap", "spot-glitch"),
    5: ("quick-pick", "long-mult", "long-mult-small", "area-model", "estimate-lock"),
}

SCREEN_COPY: dict[str, tuple[str, str]] = {
    "type-in": ("DECRYPT TERMINAL", "Type each result. Correct lines turn green."),
    "match": ("PACKET MATCH", "Match every operation to its result. Some results are decoys."),
    "fill-gap": ("PATCH THE GAP", "One number is missing from each line. Type it in."),
    "spot-glitch": ("SPOT THE GLITCH", "Three of these equations are corrupted. Flag them."),
    "quick-pick": ("QUICK PICK", "Pick each product before the timer wipes the screen."),
    "long-mult": ("LONG MULTIPLICATION", "Fill every digit of the working and the product."),
    "long-mult-small": ("SHORT MULTIPLICATION", "Two two-digit products. Fill every digit."),
    "area-model": ("AREA MODEL BREAKER", "Break the rectangle into four products, then add."),
    "estimate-lock": ("ESTIMATE LOCK", "Pick the closest estimate. No calculators."),
}

QUICK_PICK_MS = 15_000
SPOT_GLITCH_TARGET = 3
POLARITY = ("bad", "ok")


def _options(rng: random.Random, correct: int, candidates: list[int], count: int = 3) -> list[int]:
    """Return distinct labels that always include the correct value."""

    wrong = [
        value
        for value in dict.fromkeys(int(candidate) for candidate in candidates)
        if value > 0 and value != correct
    ]
    rng.shuffle(wrong)
    labels = [correct, *wrong[: count - 1]]
    attempts = 0
    while len(labels) < count and attempts < 40:
        attempts += 1
        candidate = correct + rng.choice((-12, -9, -6, -3, 3, 6, 9, 12))
        if candidate > 0 and candidate not in labels:
            labels.append(candidate)
    rng.shuffle(labels)
    return labels


def _choice_ids(rng: random.Random, labels: list[int]) -> list[dict[str, str]]:
    entries = [{"id": f"c{index + 1}", "label": str(label)} for index, label in enumerate(labels)]
    rng.shuffle(entries)
    return entries


def _screen(screen_id: str, screen_type: str, payload: dict[str, Any], answers: dict[str, str]) -> dict[str, Any]:
    title, brief = SCREEN_COPY[screen_type]
    return {
        "id": screen_id,
        "type": screen_type,
        "title": title,
        "brief": brief,
        "payload": payload,
        "answers": {str(key): str(value) for key, value in answers.items()},
        "passed": False,
    }


def _type_in(rng: random.Random, screen_id: str, count: int = 4) -> dict[str, Any]:
    prompts = []
    answers: dict[str, str] = {}
    used: set[str] = set()
    while len(prompts) < count:
        operator = rng.choice(("+", "-"))
        left = rng.randint(1, 9)
        right = rng.randint(1, 9)
        if operator == "-" and left < right:
            left, right = right, left
        text = f"{left} {operator} {right}"
        if text in used:
            continue
        used.add(text)
        key = f"p{len(prompts) + 1}"
        prompts.append({"id": key, "text": text, "digits": 2})
        answers[key] = str(left + right if operator == "+" else left - right)
    return _screen(
        screen_id,
        "type-in",
        {"kind": "type-in", "prompts": prompts},
        answers,
    )


def _match(rng: random.Random, screen_id: str) -> dict[str, Any]:
    prompts = []
    answers: dict[str, str] = {}
    correct: list[int] = []
    used: set[str] = set()
    used_results: set[int] = set()
    while len(prompts) < 3:
        operator = rng.choice(("+", "-"))
        left = rng.randint(12, 89)
        right = rng.randint(2, 9)
        if operator == "-" and left - right < 1:
            continue
        text = f"{left} {operator} {right}"
        if text in used:
            continue
        result = left + right if operator == "+" else left - right
        if result in used_results:
            continue
        used.add(text)
        used_results.add(result)
        key = f"p{len(prompts) + 1}"
        prompts.append({"id": key, "text": text})
        answers[key] = str(result)
        correct.append(result)
    decoys = [value + rng.choice((-11, -10, -9, -2, -1, 1, 2, 9, 10)) for value in correct[:2]]
    decoys = [value for value in decoys if value > 0]
    labels = list(dict.fromkeys(correct + decoys))
    rng.shuffle(labels)
    choices = _choice_ids(rng, labels)
    by_label = {choice["label"]: choice["id"] for choice in choices}
    resolved = {key: by_label[value] for key, value in answers.items()}
    return _screen(
        screen_id,
        "match",
        {"kind": "match", "prompts": prompts, "choices": choices},
        resolved,
    )


def _fill_gap(rng: random.Random, screen_id: str, count: int = 5) -> dict[str, Any]:
    prompts = []
    answers: dict[str, str] = {}
    while len(prompts) < count:
        total = rng.randint(4, 18)
        part = rng.randint(1, total - 1)
        operator = rng.choice(("+", "-"))
        missing = rng.choice(("left", "right", "result"))
        if operator == "+":
            left, right, result = part, total - part, total
        else:
            left, right, result = total, part, total - part
        if not 0 <= result <= 20:
            continue
        text = {
            "left": f"□ {operator} {right} = {result}",
            "right": f"{left} {operator} □ = {result}",
            "result": f"{left} {operator} {right} = □",
        }[missing]
        value = {"left": left, "right": right, "result": result}[missing]
        key = f"p{len(prompts) + 1}"
        prompts.append({"id": key, "text": text, "digits": 2})
        answers[key] = str(value)
    return _screen(
        screen_id,
        "fill-gap",
        {"kind": "fill-gap", "prompts": prompts},
        answers,
    )


def _spot_glitch(rng: random.Random, screen_id: str, count: int = 8) -> dict[str, Any]:
    equations = []
    answers: dict[str, str] = {}
    used: set[str] = set()
    while len(equations) < count:
        operator = rng.choice(("+", "-"))
        left = rng.randint(1, 9)
        right = rng.randint(1, 9)
        if operator == "-" and left < right:
            left, right = right, left
        result = left + right if operator == "+" else left - right
        text = f"{left} {operator} {right} = {result}"
        if text in used:
            continue
        used.add(text)
        key = f"e{len(equations) + 1}"
        equations.append({"id": key, "text": text})
        answers[key] = "ok"
    broken = rng.sample(range(count), SPOT_GLITCH_TARGET)
    for index in broken:
        key = equations[index]["id"]
        base = equations[index]["text"]
        head, shown = base.rsplit(" = ", 1)
        drift = rng.choice((-3, -2, -1, 1, 2, 3))
        equations[index]["text"] = f"{head} = {max(0, int(shown) + drift)}"
        answers[key] = "bad"
    return _screen(
        screen_id,
        "spot-glitch",
        {"kind": "spot-glitch", "equations": equations, "target": SPOT_GLITCH_TARGET},
        answers,
    )


def _quick_pick(rng: random.Random, screen_id: str, count: int = 6) -> dict[str, Any]:
    prompts = []
    answers: dict[str, str] = {}
    used: set[str] = set()
    while len(prompts) < count:
        left = rng.randint(2, 9)
        right = rng.randint(2, 9)
        text = f"{left} × {right}"
        if text in used:
            continue
        used.add(text)
        product = left * right
        distractors = [product + rng.choice((-9, -6, -3, 3, 6, 9)), product + left, product - right]
        labels = _options(rng, product, distractors)
        choices = _choice_ids(rng, labels)
        by_label = {choice["label"]: choice["id"] for choice in choices}
        key = f"p{len(prompts) + 1}"
        prompts.append({"id": key, "text": text, "choices": choices})
        answers[key] = by_label[str(product)]
    return _screen(
        screen_id,
        "quick-pick",
        {"kind": "quick-pick", "prompts": prompts, "time_limit_ms": QUICK_PICK_MS},
        answers,
    )


def _long_mult_row(kind: str, label: str, text: str, width: int, *, shift: int = 0) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    start = width - shift - len(text)
    for offset, character in enumerate(text):
        column = start + offset
        cell: dict[str, Any] = {"col": column, "text": character}
        if kind == "input":
            cell["input_id"] = f"{label}-{column}"
        cells.append(cell)
    return {"kind": kind, "label": label, "cells": cells}


def _long_mult_grid(
    rng: random.Random,
    screen_id: str,
    *,
    screen_type: str,
    count: int,
    top_range: tuple[int, int],
    bottom_range: tuple[int, int],
) -> dict[str, Any]:
    problems = []
    answers: dict[str, str] = {}
    for index in range(count):
        top = rng.randint(*top_range)
        while top % 10 == 0:
            top = rng.randint(*top_range)
        bottom = rng.randint(*bottom_range)
        while bottom % 10 == 0:
            bottom = rng.randint(*bottom_range)
        ones = bottom % 10
        tens = bottom // 10
        first = top * ones
        second = top * tens
        total = top * bottom
        width = len(str(top)) + len(str(bottom)) + 1
        label = f"m{index + 1}"
        rows = [
            _long_mult_row("given", f"{label}-top", str(top), width),
            _long_mult_row("given", f"{label}-bottom", str(bottom), width),
            _long_mult_row("input", label, str(first), width),
            _long_mult_row("input", f"{label}-shift", str(second), width, shift=1),
            _long_mult_row("input", f"{label}-total", str(total), width),
        ]
        rows[3]["cells"].append({"col": width - 1, "text": "0"})
        for row in rows[2:]:
            for cell in row["cells"]:
                if "input_id" in cell:
                    answers[cell["input_id"]] = cell["text"]
        problems.append(
            {
                "id": label,
                "top": top,
                "bottom": bottom,
                "width": width,
                "rows": rows,
            }
        )
    return _screen(
        screen_id,
        screen_type,
        {"kind": screen_type, "problems": problems},
        answers,
    )


def _long_mult(rng: random.Random, screen_id: str) -> dict[str, Any]:
    return _long_mult_grid(
        rng,
        screen_id,
        screen_type="long-mult",
        count=1,
        top_range=(1000, 9999),
        bottom_range=(12, 99),
    )


def _long_mult_small(rng: random.Random, screen_id: str) -> dict[str, Any]:
    return _long_mult_grid(
        rng,
        screen_id,
        screen_type="long-mult-small",
        count=2,
        top_range=(12, 99),
        bottom_range=(12, 99),
    )


def _area_model(rng: random.Random, screen_id: str) -> dict[str, Any]:
    top = rng.randint(12, 49)
    side = rng.randint(12, 29)
    top_tens, top_ones = top - top % 10, top % 10
    side_tens, side_ones = side - side % 10, side % 10
    parts = [
        (top_tens, side_tens),
        (top_tens, side_ones),
        (top_ones, side_tens),
        (top_ones, side_ones),
    ]
    entries = []
    answers: dict[str, str] = {}
    for index, (left, right) in enumerate(parts):
        key = f"a{index + 1}"
        entries.append({"id": key, "text": f"{left} × {right}", "digits": 3})
        answers[key] = str(left * right)
    total_key = "total"
    return _screen(
        screen_id,
        "area-model",
        {
            "kind": "area-model",
            "a": top,
            "b": side,
            "a_parts": [top_tens, top_ones],
            "b_parts": [side_tens, side_ones],
            "parts": entries,
            "total": {"id": total_key, "text": f"{top} × {side}", "digits": 4},
        },
        {**answers, total_key: str(top * side)},
    )


def _estimate_lock(rng: random.Random, screen_id: str) -> dict[str, Any]:
    prompts = []
    answers: dict[str, str] = {}
    used: set[str] = set()
    while len(prompts) < 4:
        left = rng.choice((rng.randint(19, 99), rng.randint(101, 899)))
        right = rng.choice((rng.randint(3, 9), rng.randint(11, 29)))
        text = f"{left} × {right}"
        if text in used:
            continue
        used.add(text)
        rounded_left = int(round(left, -1))
        rounded_right = int(round(right, -1))
        estimate = rounded_left * rounded_right
        exact = left * right
        off_by_ten = estimate * 10 if estimate * 10 != estimate else estimate
        near = estimate + rng.choice((-10, -100, 10, 100))
        labels = _options(rng, estimate, [off_by_ten, near, exact])
        choices = _choice_ids(rng, labels)
        by_label = {choice["label"]: choice["id"] for choice in choices}
        key = f"p{len(prompts) + 1}"
        prompts.append(
            {
                "id": key,
                "text": text,
                "rounded": f"≈ {rounded_left} × {rounded_right}",
                "choices": choices,
            }
        )
        answers[key] = by_label[str(estimate)]
    return _screen(
        screen_id,
        "estimate-lock",
        {"kind": "estimate-lock", "prompts": prompts},
        answers,
    )


BUILDERS = {
    "type-in": _type_in,
    "match": _match,
    "fill-gap": _fill_gap,
    "spot-glitch": _spot_glitch,
    "quick-pick": _quick_pick,
    "long-mult": _long_mult,
    "long-mult-small": _long_mult_small,
    "area-model": _area_model,
    "estimate-lock": _estimate_lock,
}


def screen_types_for(grade: int) -> tuple[str, ...]:
    if grade not in GRADE_SCREENS:
        raise ValueError(f"There are no maths screens for grade {grade}.")
    return GRADE_SCREENS[grade]


def build_screen(grade: int, screen_type: str, screen_id: str, rng: random.Random) -> dict[str, Any]:
    """Build one seeded screen for a grade."""

    if screen_type not in screen_types_for(grade):
        raise ValueError(f"Screen '{screen_type}' is not part of grade {grade}.")
    return BUILDERS[screen_type](rng, screen_id)


def build_node_screens(
    grade: int,
    screen_ids: list[str],
    rng: random.Random,
    *,
    screen_types: tuple[str, ...] | list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build a node's screens, keeping the types distinct when possible."""

    pool = list(screen_types or screen_types_for(grade))
    rng.shuffle(pool)
    screens = []
    for index, screen_id in enumerate(screen_ids):
        screen_type = pool[index % len(pool)]
        screens.append(build_screen(grade, screen_type, screen_id, rng))
    return screens


def normalise(value: object) -> str:
    return str(value if value is not None else "").strip().replace(" ", "")


def verify_screen(screen: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    """Compare a submission with the stored answers, key by key."""

    expected: dict[str, str] = screen.get("answers", {})
    correct: dict[str, bool] = {}
    submitted = {str(key): normalise(value) for key, value in (answers or {}).items()}
    for key, value in expected.items():
        correct[key] = submitted.get(key) == normalise(value)
    passed = bool(correct) and all(correct.values())
    return {"passed": passed, "correct": correct}
