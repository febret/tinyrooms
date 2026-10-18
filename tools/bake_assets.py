"""Bake Tinyrooms game assets through the delphi-comfyui batch runner.

Usage:
    python tools/bake_assets.py [bake-json-path ...]
        [--dryrun] [--filter PATTERN] [--progress] [--force] [--reseed]

Each input is a JSON task list understood by ``bake.py``
(``<repo>/../delphi-comfyui/bake.py``; point elsewhere with the ``TR_BAKE_DIR``
environment variable). With no paths, every ``bake.json`` under ``data/`` and
``worlds/`` is used. See ``../delphi-comfyui/bake-skill.md`` for the task format.

Options:
    --dryrun            preview the run without writing any asset
    --filter PATTERN    only bake tasks matching the glob (repeatable)
    --progress          show an updating progress bar instead of full output
    --force             re-render tasks whose output already exists
    --reseed            randomize pinned ``seed`` args, then force a re-render

``--reseed`` rewrites the input JSON in place, replacing every integer
``args.seed`` with a fresh random value while preserving the file's formatting.
Tasks without a pinned seed are left alone because they already vary per run.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BAKE_DIR = REPO_ROOT.parent / "delphi-comfyui"
DISCOVERY_GLOBS = ("data/**/bake.json", "worlds/**/bake.json")
EXCLUDED_PARTS = frozenset(
    {".local", "attic", "releases", "node_modules", ".venv", "__pycache__"}
)
SEED_MAX = 2**31 - 1
BAR_WIDTH = 30
LABEL_WIDTH = 37

SEED_RE = re.compile(r'("seed"\s*:\s*)(-?\d+)')
PROGRESS_RE = re.compile(r"^\[bake\] \((\d+)/(\d+)\) #\d+ (.+)$")


class BakeError(RuntimeError):
    """A setup or input problem that prevents baking."""


def resolve_bake_dir() -> Path:
    override = os.environ.get("TR_BAKE_DIR")
    return Path(override).expanduser().resolve() if override else DEFAULT_BAKE_DIR


def discover_inputs() -> list[Path]:
    found: list[Path] = []
    for pattern in DISCOVERY_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            if EXCLUDED_PARTS.isdisjoint(path.parts):
                found.append(path)
    return found


def resolve_inputs(raw_paths: list[str]) -> list[Path]:
    if raw_paths:
        candidates = [Path(raw).expanduser() for raw in raw_paths]
    else:
        candidates = discover_inputs()
    if not candidates:
        raise BakeError(
            "no bake.json inputs given and none discovered under data/ or worlds/"
        )
    resolved: list[Path] = []
    for candidate in candidates:
        if candidate.is_absolute():
            full = candidate.resolve()
        else:
            full = (Path.cwd() / candidate).resolve()
            if not full.is_file() and (REPO_ROOT / candidate).is_file():
                full = (REPO_ROOT / candidate).resolve()
        if not full.is_file():
            raise BakeError(f"input not found: {candidate}")
        resolved.append(full)
    return resolved


def load_bake_module(bake_py: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("delphi_bake", bake_py)
    if spec is None or spec.loader is None:
        raise BakeError(f"cannot load {bake_py}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["delphi_bake"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - report any import failure
        raise BakeError(f"cannot import {bake_py}: {exc}")
    return module


def select_tasks(bake_mod: ModuleType, path: Path, patterns: list[str]) -> int:
    _styles, _templates, tasks, _document = bake_mod.load_tasks(str(path))
    return len(bake_mod.select_tasks(tasks, patterns, []))


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _collect_seed_values(data: object) -> list[int]:
    entries = data.get("tasks") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise BakeError("bake.json must be a JSON array or an object with 'tasks'")
    values: list[int] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        args = entry.get("args")
        if not isinstance(args, dict):
            continue
        seed = args.get("seed")
        if isinstance(seed, int) and not isinstance(seed, bool):
            values.append(seed)
    return values


def reseed_file(path: Path, dry_run: bool) -> list[tuple[int, int]]:
    text = path.read_bytes().decode("utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BakeError(f"{_display(path)}: invalid JSON: {exc}")
    old_values = _collect_seed_values(data)
    if not old_values:
        return []
    matches = list(SEED_RE.finditer(text))
    if len(matches) != len(old_values):
        raise BakeError(
            f"{_display(path)}: found {len(matches)} 'seed' entries in the text "
            f"but {len(old_values)} integer seeds in the JSON; refusing to rewrite"
        )
    changes: list[tuple[int, int]] = []
    parts: list[str] = []
    last = 0
    for match in matches:
        old = int(match.group(2))
        new = random.randint(1, SEED_MAX)
        while new == old:
            new = random.randint(1, SEED_MAX)
        changes.append((old, new))
        parts.append(text[last:match.start()])
        parts.append(match.group(1) + str(new))
        last = match.end()
    parts.append(text[last:])
    if not dry_run:
        path.write_bytes("".join(parts).encode("utf-8"))
    return changes


def render_bar(done: int, total: int, label: str) -> None:
    filled = BAR_WIDTH * done // total if total else BAR_WIDTH
    bar = "#" * filled + "-" * (BAR_WIDTH - filled)
    if len(label) > LABEL_WIDTH:
        label = label[: LABEL_WIDTH - 1] + "\u2026"
    sys.stderr.write(f"\r[{bar}] {done}/{total} {label:<{LABEL_WIDTH}}")
    sys.stderr.flush()


def run_file(
    bake_py: Path,
    path: Path,
    patterns: list[str],
    *,
    force: bool,
    dry_run: bool,
    progress: bool,
    offset: int,
    total: int,
) -> int:
    command = [sys.executable, "-u", str(bake_py), str(path)]
    for pattern in patterns:
        command += ["--only", pattern]
    if force:
        command.append("--force")
    if dry_run:
        command.append("--dry-run")
    if not progress:
        return subprocess.run(command).returncode

    captured: list[str] = []
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        captured.append(line)
        match = PROGRESS_RE.match(line.strip())
        if match:
            done = offset + int(match.group(1))
            label = match.group(3)
            if label.endswith("]"):
                label = label.rsplit(" [", 1)[0]
            render_bar(done, total, label)
    returncode = proc.wait()
    sys.stderr.write("\n")
    sys.stderr.flush()
    if returncode != 0:
        sys.stderr.write("".join(captured))
        sys.stderr.flush()
    return returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="bake-json-path",
        help="bake.json file(s); default: all under data/ and worlds/",
    )
    parser.add_argument(
        "--dryrun", action="store_true", help="preview without writing any asset"
    )
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="PATTERN",
        help="only bake tasks matching the glob (repeatable)",
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="show an updating progress bar instead of full output",
    )
    parser.add_argument(
        "--force", action="store_true", help="re-render tasks whose output exists"
    )
    parser.add_argument(
        "--reseed",
        action="store_true",
        help="randomize pinned seed args, then force a re-render",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    bake_py = resolve_bake_dir() / "bake.py"
    if not bake_py.is_file():
        print(
            f"bake_assets: bake.py not found at {bake_py} (set TR_BAKE_DIR)",
            file=sys.stderr,
        )
        return 2

    try:
        inputs = resolve_inputs(args.paths)
        bake_mod = load_bake_module(bake_py)
        planned = [(path, select_tasks(bake_mod, path, args.filter)) for path in inputs]
    except (BakeError, ValueError, OSError) as exc:
        print(f"bake_assets: {exc}", file=sys.stderr)
        return 2

    active = [(path, count) for path, count in planned if count]
    for path, count in planned:
        if not count:
            print(f"[bake_assets] skip {_display(path)}: no tasks matched")
    if not active:
        print("bake_assets: no tasks matched the selection", file=sys.stderr)
        return 2

    force = args.force
    if args.reseed:
        for path, _count in active:
            try:
                changes = reseed_file(path, args.dryrun)
            except BakeError as exc:
                print(f"bake_assets: {exc}", file=sys.stderr)
                return 2
            if not changes:
                print(f"[bake_assets] reseed {_display(path)}: no pinned seeds")
                continue
            verb = "would reseed" if args.dryrun else "reseeded"
            print(f"[bake_assets] {verb} {_display(path)}: {len(changes)} seed(s)")
            for old, new in changes:
                print(f"    seed {old} -> {new}")
        if not args.dryrun:
            force = True

    total = sum(count for _path, count in active)
    flags = " [dry-run]" if args.dryrun else ""
    flags += " [forced]" if force else ""
    print(
        f"[bake_assets] {len(active)} file(s), {total} task(s){flags}"
    )

    failed = False
    offset = 0
    for path, count in active:
        print(f"\n[bake_assets] {_display(path)} ({count} task(s))")
        try:
            returncode = run_file(
                bake_py,
                path,
                args.filter,
                force=force,
                dry_run=args.dryrun,
                progress=args.progress,
                offset=offset,
                total=total,
            )
        except KeyboardInterrupt:
            print("\nbake_assets: interrupted", file=sys.stderr)
            return 130
        if returncode != 0:
            failed = True
        offset += count

    print(f"\n[bake_assets] {'FAILED' if failed else 'done'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
