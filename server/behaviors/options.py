"""Selectable prop behavior options shared by the World and Prop Editors."""

from __future__ import annotations

from pathlib import Path

from server.behaviors import builtin as builtin_behaviors_module
from server.behaviors.builtin import BUILTIN_BEHAVIORS


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def behavior_options(world_root: Path, repo_root: Path) -> list[dict[str, str]]:
    """List selectable prop behaviors: built-ins plus world ``props/*.py`` scripts."""

    builtin_source = _display_path(Path(builtin_behaviors_module.__file__), repo_root)
    options = [
        {"id": name, "kind": "builtin", "source": builtin_source}
        for name in sorted(BUILTIN_BEHAVIORS)
    ]
    props_dir = world_root / "props"
    if props_dir.is_dir():
        scripts = sorted(
            entry for entry in props_dir.iterdir()
            if entry.is_file() and entry.suffix == ".py" and not entry.name.startswith("_")
        )
        options.extend(
            {"id": entry.stem, "kind": "script", "source": _display_path(entry, repo_root)}
            for entry in scripts
            if entry.stem not in BUILTIN_BEHAVIORS
        )
    return options
