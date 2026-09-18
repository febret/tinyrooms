"""Shared strict-loading helpers for Tinyrooms content definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml


class ContentError(ValueError):
    """Raised when content definitions are malformed."""


def load_yaml_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def require_mapping(payload: Any, path: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ContentError(f"{path} must contain a top-level mapping.")
    return payload