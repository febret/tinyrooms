"""Trait system for tinyrooms.

Traits are long-term modifiers applied to user peeps.  They are defined in
YAML files under ``data/traits/`` and loaded by :class:`TraitRepository`.

Each trait can apply one or more stat buffs (permanent while the trait is
active), modify kudos/juice rates, and contribute a vibe modifier when two
peeps share the same or opposite traits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


_UNSET = object()
_DATA_ROOT = Path(__file__).parent.parent / "data"


@dataclass
class TraitBuff:
    """A single buff applied by a trait."""
    stat: str
    amount: float


@dataclass
class TraitDef:
    """Definition of a single trait."""
    trait_id: str
    label: str
    description: str
    opposite: str | None = None
    buffs: list[TraitBuff] = field(default_factory=list)
    vibe_modifier: float = 0.0
    kudos_rate_modifier: float = 1.0
    juice_rate_modifier: float = 1.0


def _parse_trait(trait_id: str, raw: dict[str, Any]) -> TraitDef:
    buffs: list[TraitBuff] = []
    for entry in raw.get("buffs") or []:
        if isinstance(entry, dict):
            stat = str(entry.get("stat", "")).strip()
            try:
                amount = float(entry.get("amount", 0))
            except (TypeError, ValueError):
                amount = 0.0
            if stat:
                buffs.append(TraitBuff(stat=stat, amount=amount))
    return TraitDef(
        trait_id=trait_id,
        label=str(raw.get("label") or trait_id),
        description=str(raw.get("description") or ""),
        opposite=str(raw["opposite"]) if raw.get("opposite") else None,
        buffs=buffs,
        vibe_modifier=float(raw.get("vibe_modifier") or 0.0),
        kudos_rate_modifier=float(raw.get("kudos_rate_modifier") or 1.0),
        juice_rate_modifier=float(raw.get("juice_rate_modifier") or 1.0),
    )


class TraitRepository:
    """Load and index trait definitions from YAML files in a traits directory."""

    def __init__(self, traits_root: Path | None = None):
        self._root = traits_root or (_DATA_ROOT / "traits")
        self._index: dict[str, TraitDef] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._index = {}
        if not self._root.exists():
            self._loaded = True
            return
        for yaml_path in sorted(self._root.glob("*.yaml")):
            try:
                with open(yaml_path, "r", encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh) or {}
                if not isinstance(raw, dict):
                    continue
                for trait_id, trait_raw in raw.items():
                    if not isinstance(trait_raw, dict):
                        continue
                    self._index[str(trait_id)] = _parse_trait(str(trait_id), trait_raw)
            except Exception as exc:
                print(f"traits: failed to load {yaml_path}: {exc}")
        self._loaded = True

    def reload(self) -> None:
        """Force a reload from disk on the next access."""
        self._loaded = False

    def get(self, trait_id: str) -> TraitDef | None:
        """Return the TraitDef for *trait_id*, or None if unknown."""
        self._ensure_loaded()
        return self._index.get(trait_id)

    def all(self) -> dict[str, TraitDef]:
        """Return all loaded trait definitions keyed by id."""
        self._ensure_loaded()
        return dict(self._index)

    def list_ids(self) -> list[str]:
        """Return a sorted list of all known trait ids."""
        self._ensure_loaded()
        return sorted(self._index)


# Module-level singleton
_repo: TraitRepository | None = None


def _get_repo() -> TraitRepository:
    global _repo
    if _repo is None:
        _repo = TraitRepository()
    return _repo


def load_trait(trait_id: str) -> TraitDef | None:
    """Return the TraitDef for *trait_id* using the module-level repository."""
    return _get_repo().get(trait_id)


def get_buffs_for_traits(trait_ids: list[str]) -> dict[str, float]:
    """Return a merged ``{stat: total_amount}`` dict for all given trait ids.

    Unknown trait ids are silently ignored.
    """
    merged: dict[str, float] = {}
    repo = _get_repo()
    for tid in trait_ids:
        td = repo.get(tid)
        if td is None:
            continue
        for buff in td.buffs:
            merged[buff.stat] = merged.get(buff.stat, 0.0) + buff.amount
    return merged


def get_kudos_rate_modifier(trait_ids: list[str]) -> float:
    """Return the combined kudos rate multiplier for a set of traits.

    Multipliers are multiplied together (e.g., 1.5 * 0.8 = 1.2).
    """
    result = 1.0
    repo = _get_repo()
    for tid in trait_ids:
        td = repo.get(tid)
        if td is not None:
            result *= td.kudos_rate_modifier
    return result


def get_juice_rate_modifier(trait_ids: list[str]) -> float:
    """Return the combined juice rate multiplier for a set of traits."""
    result = 1.0
    repo = _get_repo()
    for tid in trait_ids:
        td = repo.get(tid)
        if td is not None:
            result *= td.juice_rate_modifier
    return result


def get_vibe_modifier(trait_ids_a: list[str], trait_ids_b: list[str]) -> float:
    """Compute the vibe modifier between two sets of traits.

    - Matching trait: +vibe_modifier from that trait
    - Opposite trait: −vibe_modifier from that trait

    The result is the sum of all contributions.
    """
    repo = _get_repo()
    set_b = set(trait_ids_b)
    total = 0.0
    for tid in trait_ids_a:
        td = repo.get(tid)
        if td is None:
            continue
        if tid in set_b:
            # Peep B also has this trait — positive resonance
            total += td.vibe_modifier
        elif td.opposite and td.opposite in set_b:
            # Peep B has the opposite trait — negative resonance
            total -= td.vibe_modifier
    return total
