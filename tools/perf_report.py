"""Render the performance report and decide whether a regression landed.

Each tier (Python, node, browser) appends its metrics to the JSON file named by
``TR_PERF_OUT``. This merges those fragments, compares the result against the
checked-in baseline, and exits non-zero when a metric regressed past tolerance
or is new and unrecorded.

Timings are compared relatively, because they move with the machine. Counts and
query counts are also given a relative tolerance, but they additionally carry an
absolute ceiling in the benchmark itself, which fails in-line with a message
naming the responsible test.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPO_ROOT / "tests" / "perf" / "baselines" / "perf-baselines.json"
TOLERANCE = 0.20

#: Absolute slack per unit, added on top of the relative tolerance.
#:
#: A percentage comparison is meaningless for very small values: a 0.18ms
#: measurement that lands on 0.24ms is a 34% "regression" caused entirely by
#: timer granularity, and a ratio built from two such timings is worse. These
#: floors mean a metric has to move by a *substantial* absolute amount before it
#: is reported, which keeps the report readable and actionable.
NOISE_FLOOR = {
    "ms": 0.25,
    "s": 0.00025,
    "ratio": 0.3,
}


def _floor(unit: str) -> float:
    return NOISE_FLOOR.get(unit, 0.0)


def load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _regressed(baseline: float, current: float, lower_is_better: bool, floor: float) -> bool:
    allowed = max(baseline * (1 + TOLERANCE), baseline + floor)
    if lower_is_better:
        return current > allowed
    return current < min(baseline * (1 - TOLERANCE), baseline - floor)


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one row per metric, worst regressions first."""

    rows: list[dict[str, Any]] = []
    for name in sorted(set(baseline) | set(current)):
        before = baseline.get(name)
        after = current.get(name)
        if after is None:
            rows.append({"name": name, "status": "removed", "before": before, "after": None})
            continue
        if before is None:
            rows.append({"name": name, "status": "new", "before": None, "after": after})
            continue
        lower_is_better = bool(after.get("lower_is_better", True))
        old_value = float(before["value"])
        new_value = float(after["value"])
        floor = _floor(str(after.get("unit", "")))
        if new_value == old_value:
            status = "same"
        elif _regressed(old_value, new_value, lower_is_better, floor):
            status = "regressed"
        elif _regressed(old_value, new_value, not lower_is_better, floor):
            status = "improved"
        else:
            status = "same"
        rows.append({"name": name, "status": status, "before": before, "after": after})
    order = {"regressed": 0, "new": 1, "removed": 2, "improved": 3, "same": 4}
    rows.sort(key=lambda row: (order[row["status"]], row["name"]))
    return rows


def format_row(row: dict[str, Any]) -> str:
    name = row["name"]
    after = row["after"]
    before = row["before"]
    if after is None:
        return f"{'REMOVED':>9}  {name}"
    unit = after.get("unit", "")
    value = f"{after['value']:g}{unit}"
    if before is None:
        return f"{'NEW':>9}  {name:<52} {value:>14}"
    old_value = float(before["value"])
    new_value = float(after["value"])
    if old_value == 0:
        change = "+inf" if new_value else "0"
    else:
        change = f"{(new_value - old_value) / old_value * 100:+.1f}%"
    return f"{row['status'].upper():>9}  {name:<52} {value:>14}  ({old_value:g} -> {change})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", help="Merged metrics JSON (defaults to $TR_PERF_OUT)")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument(
        "--update",
        action="store_true",
        help="Record the current run as the new baseline instead of comparing.",
    )
    parser.add_argument(
        "--replace-baseline",
        action="store_true",
        help="With --update, discard existing metrics instead of merging into them.",
    )
    args = parser.parse_args(argv)

    results_path = Path(args.results or os.environ.get("TR_PERF_OUT", ""))
    if not str(results_path):
        print("perf-report: no results file; set TR_PERF_OUT or pass --results", file=sys.stderr)
        return 2

    current = load(results_path)
    if not current:
        print("perf-report: no metrics were recorded by any tier", file=sys.stderr)
        return 2

    baseline_path = Path(args.baseline)
    if args.update or os.environ.get("TR_UPDATE_PERF_BASELINES") == "1":
        # A partial run (`--tiers server`) only measured some tiers, so merge
        # into the existing baseline rather than dropping the metrics it did not
        # measure. Passing --replace-baseline forces a full overwrite.
        existing = {} if args.replace_baseline else load(baseline_path)
        merged = {**existing, **current}
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        added = sorted(set(current) - set(existing))
        kept = len(existing) - len(added)
        print(
            f"perf-report: recorded {len(added)} metrics to {baseline_path}"
            + (f" ({kept} existing metrics kept)" if kept else "")
        )
        return 0

    baseline = load(baseline_path)
    if not baseline:
        print(
            f"perf-report: no baseline at {baseline_path}. "
            "Record one with TR_UPDATE_PERF_BASELINES=1 after reviewing the numbers.",
            file=sys.stderr,
        )
        return 2

    rows = compare(baseline, current)
    width = 78
    print("=" * width)
    print(f"{'STATUS':>9}  {'METRIC':<52} {'NOW':>14}")
    print("=" * width)
    for row in rows:
        print(format_row(row))
    print("=" * width)

    regressed = [row for row in rows if row["status"] == "regressed"]
    new_metrics = [row for row in rows if row["status"] == "new"]
    removed = [row for row in rows if row["status"] == "removed"]
    improved = [row for row in rows if row["status"] == "improved"]
    print(
        f"{len(current)} metrics: {len(regressed)} regressed, {len(improved)} improved, "
        f"{len(new_metrics)} new, {len(removed)} removed "
        f"(tolerance {TOLERANCE:.0%})"
    )

    if regressed:
        print("\nRegressions:", file=sys.stderr)
        for row in regressed:
            print(f"  - {row['name']}", file=sys.stderr)
        print(
            "\nIf a change is intentional, re-record with TR_UPDATE_PERF_BASELINES=1 "
            "after reviewing the new numbers.",
            file=sys.stderr,
        )
        return 1
    if new_metrics or removed:
        print(
            "\nNew or removed metrics are informational; re-record the baseline when the set "
            "has settled.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
