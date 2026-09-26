"""Shared measurement plumbing for the performance suite.

Two kinds of assertions live here and they play different roles:

* **Deterministic counts** -- SQL statements issued, objects allocated, bytes
  serialised, tasks created. These are asserted inline against an absolute
  ceiling so a regression fails the test that caused it, with a useful message.
* **Wall-clock timings** -- microseconds per snapshot, event-loop stall. These
  vary with the machine, so inline they only get a deliberately loose ceiling
  and the real gate happens in ``tools/perf_report.py``, which compares the
  recorded value against the checked-in baseline in
  ``tests/perf/baselines/perf-baselines.json``.

Every tier (Python, node, browser) writes the same JSON shape to the path in
``TR_PERF_OUT``; ``tools/run_perf.py`` merges them and ``tools/perf_report.py``
renders the comparison.
"""

from __future__ import annotations

import atexit
import json
import os
import sqlite3
import statistics
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, TypeVar

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO_ROOT / "tests" / "perf" / "baselines" / "perf-baselines.json"

#: Values are compared against the baseline; anything slower than this fails.
DEFAULT_TOLERANCE = 0.20

T = TypeVar("T")

_records: dict[str, dict[str, object]] = {}


def record(
    name: str,
    value: float,
    *,
    unit: str = "ms",
    ceiling: float | None = None,
    lower_is_better: bool = True,
    note: str = "",
) -> None:
    """Record a metric and, when given, assert it against an absolute ceiling.

    ``ceiling`` is meant for values that are exactly reproducible (query
    counts, allocation counts) or for a deliberately loose sanity bound on a
    timing. A regression well past the ceiling is always worth failing on
    inline, because it points straight at the responsible test.
    """

    _records[name] = {
        "value": round(float(value), 4),
        "unit": unit,
        "lower_is_better": lower_is_better,
        "note": note,
    }
    if ceiling is not None:
        if not lower_is_better:
            if value < ceiling:
                raise AssertionError(
                    f"{name}: {value:g}{unit} is below the required floor of {ceiling:g}{unit}. {note}"
                )
            return
        if value > ceiling:
            raise AssertionError(
                f"{name}: {value:g}{unit} exceeds the absolute ceiling of {ceiling:g}{unit}. {note}"
            )


def records() -> dict[str, dict[str, object]]:
    """Return every metric recorded so far in this process."""

    return dict(_records)


def _flush() -> None:
    target = os.environ.get("TR_PERF_OUT")
    if not target:
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged: dict[str, dict[str, object]] = {}
    if path.is_file():
        try:
            merged = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            merged = {}
    merged.update(_records)
    path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")


atexit.register(_flush)


@contextmanager
def sql_counter(connection: sqlite3.Connection) -> Iterator[list[str]]:
    """Count the SQL statements issued on *connection* inside the block.

    Uses SQLite's own trace hook, so it needs no changes to the repositories
    under test and sees statements issued inside transactions as well.
    """

    statements: list[str] = []

    def trace(statement: str) -> None:
        statements.append(statement)

    connection.set_trace_callback(trace)
    try:
        yield statements
    finally:
        connection.set_trace_callback(None)


def timeit(
    func: Callable[[], T],
    *,
    iterations: int = 25,
    warmup: int = 3,
) -> tuple[T, float]:
    """Return ``(last_result, median_seconds)`` for *func*.

    The median is used rather than the mean so that a single GC pause or a
    background thread does not dominate the recorded figure.
    """

    for _ in range(warmup):
        func()
    samples: list[float] = []
    result: T = None  # type: ignore[assignment]
    for _ in range(iterations):
        started = time.perf_counter()
        result = func()
        samples.append(time.perf_counter() - started)
    return result, statistics.median(samples)


def elapsed_ms(clock: Callable[[], float]) -> float:
    """Return milliseconds since *clock* was sampled."""

    return (time.perf_counter() - clock()) * 1000.0


class PerfCase(unittest.IsolatedAsyncioTestCase):
    """Base class for async performance tests with shared measurement helpers."""

    def measure(
        self,
        name: str,
        value: float,
        *,
        unit: str = "ms",
        ceiling: float | None = None,
        lower_is_better: bool = True,
        note: str = "",
    ) -> None:
        """Record *value* and surface failures as a normal test failure."""

        try:
            record(name, value, unit=unit, ceiling=ceiling, lower_is_better=lower_is_better, note=note)
        except AssertionError as error:
            self.fail(str(error))

    def assert_scales(
        self,
        name: str,
        small: float,
        large: float,
        *,
        factor: float,
        max_factor: float,
        small_n: int,
        large_n: int,
    ) -> None:
        """Assert that doubling the workload costs at most ``max_factor`` times more.

        This is the workhorse guard against accidentally reintroducing an
        ``O(n^2)`` loop. A linear pass doubles; a quadratic pass quadruples.
        Ratios are noisy for very small inputs, so a floor is added to the
        denominator to keep the check meaningful at low N.
        """

        growth = (large + 0.05) / (small + 0.05)
        expected = factor * max_factor
        if growth > expected:
            self.fail(
                f"{name}: {large_n} units cost {growth:.2f}x the {small_n}-unit case "
                f"({small:.3f} -> {large:.3f}{'' if small else ''}), which exceeds the "
                f"{expected:.2f}x allowed for a {factor}x workload increase. "
                "This usually means an inner loop is scanning the whole collection."
            )
        self.measure(f"perf/{name}/growth", growth, unit="ratio", lower_is_better=True)
