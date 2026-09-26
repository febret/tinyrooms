"""Run the whole performance suite and report the outcome.

Each tier writes its metrics to its own fragment file so a failure in one tier
does not lose the others' measurements. Fragments are merged, compared against
the checked-in baseline by ``tools/perf_report.py``, and the exit code is
non-zero if any tier failed or any metric regressed.

    python tools/run_perf.py                # everything
    python tools/run_perf.py --tiers server # just the in-process benchmarks
    TR_UPDATE_PERF_BASELINES=1 python tools/run_perf.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "tests" / "perf" / "baselines" / "perf-baselines.json"

TIERS = {
    "server": "In-process service, snapshot, broadcast, and leak benchmarks",
    "client": "Client state reducer benchmarks under node --test",
    "browser": "Browser board and DOM budgets under Playwright",
}


def _python() -> str:
    local = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    if local.is_file():
        return str(local)
    return sys.executable


def _run(label: str, command: list[str], env: dict[str, str]) -> tuple[str, float, bool]:
    print(f"\n--- {label} ---", flush=True)
    print(" ".join(str(part) for part in command), flush=True)
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=REPO_ROOT, env=env)
    elapsed = time.perf_counter() - started
    print(f"--- {label}: {'ok' if completed.returncode == 0 else 'FAILED'} in {elapsed:.1f}s ---", flush=True)
    return label, elapsed, completed.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tiers",
        nargs="*",
        choices=sorted(TIERS),
        default=sorted(TIERS),
        help="Subset of tiers to run (default: all).",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Record the run as the new baseline.",
    )
    parser.add_argument(
        "--skip-report",
        action="store_true",
        help="Run the tiers without comparing against the baseline.",
    )
    args = parser.parse_args(argv)

    update = args.update or os.environ.get("TR_UPDATE_PERF_BASELINES") == "1"
    workdir = Path(tempfile.mkdtemp(prefix="perf-run-"))
    results: dict[str, dict] = {}
    timings: list[tuple[str, float, bool]] = []
    try:
        for tier in args.tiers:
            fragment = workdir / f"{tier}.json"
            env = {**os.environ, "TR_PERF_OUT": str(fragment)}
            if tier == "server":
                command = [
                    _python(), "-m", "unittest", "discover",
                    "-s", "tests", "-t", ".", "-p", "perf_*.py", "-v",
                ]
            elif tier == "client":
                command = ["node", "--test", "tests/perf/client/state-perf.test.js"]
            else:
                command = ["npx", "playwright", "test", "--config=playwright.perf.config.js"]
            timings.append(_run(TIERS[tier], command, env))
            if fragment.is_file():
                try:
                    results.update(json.loads(fragment.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    pass

        merged = workdir / "merged.json"
        merged.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        print("\n=== tier summary ===")
        for label, elapsed, ok in timings:
            print(f"  {'ok  ' if ok else 'FAIL'}  {elapsed:6.1f}s  {label}")
        print(f"  {len(results)} metrics recorded")
        print(f"  baseline: {BASELINE_PATH}")

        if args.skip_report:
            return 0 if all(ok for _label, _elapsed, ok in timings) else 1

        report_command = [
            _python(),
            "tools/perf_report.py",
            "--results", str(merged),
            "--baseline", str(BASELINE_PATH),
        ]
        if update:
            report_command.append("--update")
        completed = subprocess.run(report_command, cwd=REPO_ROOT, env=os.environ)
        tiers_ok = all(ok for _label, _elapsed, ok in timings)
        return completed.returncode or (0 if tiers_ok else 1)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
