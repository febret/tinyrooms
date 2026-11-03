"""Guard presence and suspicion state for Tiny Vault heists."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class GuardState:
    """Mutable suspicion state for one staged guard."""

    peep_id: str
    room_id: str
    state: str = "patrol"
    suspicion: float = 0.0
