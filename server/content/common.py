"""Shared strict-loading helpers for Tinyrooms content definitions."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml


LOGGER = logging.getLogger("tinyrooms.content")


class ContentError(ValueError):
    """Raised when content definitions are malformed."""


def load_yaml_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def require_mapping(payload: Any, path: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ContentError(f"{path} must contain a top-level mapping.")
    return payload


def require_int(value: Any, label: str, minimum: int | None = None, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContentError(f"{label} must be an integer.")
    if minimum is not None and value < minimum:
        raise ContentError(f"{label} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise ContentError(f"{label} must be <= {maximum}.")
    return value


def warn_unknown_card(reference: str, card_id: object) -> None:
    """Warn that content references a card id absent from the catalog."""

    LOGGER.warning("%s references unknown card '%s'; dropping the reference.", reference, card_id)


def drop_unknown_card_ids(
    card_ids: Iterable[str],
    known_cards: set[str],
    reference: str,
) -> list[str]:
    """Return *card_ids* without any missing from *known_cards*, warning for each."""

    kept: list[str] = []
    for card_id in card_ids:
        if card_id in known_cards:
            kept.append(card_id)
        else:
            warn_unknown_card(reference, card_id)
    return kept
