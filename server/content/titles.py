"""Strict loader for global title definitions (salutations, nicknames, suffixes)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.content.common import ContentError, load_yaml_file, require_mapping


TITLE_SLOTS = ("salutation", "nickname", "suffix")
TITLE_SLOT_KEYS = {"salutation": "salutations", "nickname": "nicknames", "suffix": "suffixes"}
TITLE_UNLOCK_KINDS = frozenset({"level", "task", "cook", "teach"})

MAX_TITLE_LABEL_LENGTH = 40
MAX_TITLE_ID_LENGTH = 64


@dataclass(frozen=True, slots=True)
class TitleUnlock:
    """How a single title part is unlocked."""

    kind: str
    level: int | None = None
    task_id: str | None = None
    count: int | None = None

    def to_payload(self) -> dict[str, object]:
        """Serialize the unlock requirement for the client."""

        payload: dict[str, object] = {"kind": self.kind}
        if self.level is not None:
            payload["level"] = self.level
        if self.task_id is not None:
            payload["task_id"] = self.task_id
        if self.count is not None:
            payload["count"] = self.count
        return payload


@dataclass(frozen=True, slots=True)
class TitlePart:
    """One selectable title part in a fixed slot."""

    id: str
    label: str
    slot: str
    unlock: TitleUnlock

    def to_payload(self) -> dict[str, object]:
        """Serialize the part for the client."""

        return {
            "id": self.id,
            "label": self.label,
            "slot": self.slot,
            "unlock": self.unlock.to_payload(),
        }


@dataclass(frozen=True, slots=True)
class TitlesContent:
    """All global title parts keyed by part id."""

    parts: dict[str, TitlePart]

    def by_slot(self, slot: str) -> tuple[TitlePart, ...]:
        """Return parts for *slot* in definition order."""

        return tuple(part for part in self.parts.values() if part.slot == slot)

    def get(self, part_id: str) -> TitlePart | None:
        """Return the part for *part_id*, if any."""

        return self.parts.get(part_id)


def _parse_unlock(raw: Any, *, reference: str, path: Path) -> TitleUnlock:
    if not isinstance(raw, dict):
        raise ContentError(f"{path} {reference} unlock must be a mapping.")
    kind = str(raw.get("kind", "")).strip()
    if kind not in TITLE_UNLOCK_KINDS:
        raise ContentError(f"{path} {reference} has an unknown unlock kind {kind!r}.")
    if kind == "level":
        level = raw.get("level")
        if isinstance(level, bool) or not isinstance(level, int) or level < 0:
            raise ContentError(f"{path} {reference} has an invalid unlock level {level!r}.")
        return TitleUnlock(kind=kind, level=level)
    if kind == "task":
        task_id = str(raw.get("task_id", "")).strip()
        if not task_id:
            raise ContentError(f"{path} {reference} task unlock must define a task_id.")
        return TitleUnlock(kind=kind, task_id=task_id)
    count = raw.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ContentError(f"{path} {reference} {kind} unlock must define a count >= 1.")
    return TitleUnlock(kind=kind, count=count)


def _parse_part(raw: Any, *, slot: str, path: Path) -> TitlePart:
    if not isinstance(raw, dict):
        raise ContentError(f"{path} {slot} entries must be mappings.")
    part_id = str(raw.get("id", "")).strip()
    if not part_id or len(part_id) > MAX_TITLE_ID_LENGTH:
        raise ContentError(f"{path} {slot} entries must define an id up to {MAX_TITLE_ID_LENGTH} chars.")
    label = str(raw.get("label", "")).strip()
    if not label or len(label) > MAX_TITLE_LABEL_LENGTH:
        raise ContentError(f"{path} {slot} '{part_id}' must define a label up to {MAX_TITLE_LABEL_LENGTH} chars.")
    if "unlock" not in raw:
        raise ContentError(f"{path} {slot} '{part_id}' must define an unlock.")
    return TitlePart(id=part_id, label=label, slot=slot, unlock=_parse_unlock(raw["unlock"], reference=f"{slot} '{part_id}'", path=path))


def load_titles_content(path: Path) -> TitlesContent:
    """Load and validate global title parts from *path* (titles.yaml)."""

    payload = require_mapping(load_yaml_file(path), path)
    parts: dict[str, TitlePart] = {}
    for slot in TITLE_SLOTS:
        raw_entries = payload.get(TITLE_SLOT_KEYS[slot], [])
        if raw_entries is None:
            raw_entries = []
        if not isinstance(raw_entries, list):
            raise ContentError(f"{path} '{slot}s' must be a list.")
        for raw in raw_entries:
            part = _parse_part(raw, slot=slot, path=path)
            if part.id in parts:
                raise ContentError(f"{path} has a duplicate title id '{part.id}'.")
            parts[part.id] = part
    return TitlesContent(parts=parts)
