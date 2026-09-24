"""Filesystem staging helpers for atomic world publishes and validation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import os
import shutil

import yaml


def dump_yaml(payload: object) -> str:
    """Serialize *payload* to readable YAML."""

    return yaml.safe_dump(
        payload,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def _link_or_copy(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def stage_world(
    source_world: Path,
    destination: Path,
    yaml_overrides: Mapping[str, object],
) -> None:
    """Mirror *source_world* into *destination*, replacing the overridden YAML.

    Assets are hardlinked when the filesystem allows it and copied otherwise, so
    validation and publish never mutate the live world directory.
    """

    destination.mkdir(parents=True, exist_ok=True)
    override_names = set(yaml_overrides)
    for current_root, directory_names, file_names in os.walk(source_world):
        directory_names[:] = [name for name in directory_names if name != "__pycache__"]
        root_path = Path(current_root)
        relative_root = root_path.relative_to(source_world)
        target_root = destination / relative_root
        target_root.mkdir(parents=True, exist_ok=True)
        for file_name in file_names:
            relative_name = (relative_root / file_name).as_posix()
            if relative_name in override_names:
                continue
            _link_or_copy(root_path / file_name, target_root / file_name)
    for relative_name, payload in yaml_overrides.items():
        target = destination / relative_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dump_yaml(payload), encoding="utf-8")
