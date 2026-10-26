"""Shared Tiny Vault job models and tuning constants."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from mods.tinyvault.content import JobTemplate
from mods.tinyvault.jobs import GeneratedJob
from server.security import utc_now


MOD_ID = "tinyvault"
WORLD_ID = "tiny-vault"
HIDEOUT_ROOM = "hideout"
HANGAR_ROOM = "guard-hangar"
META_KEY = "tinyvault_meta"
MOVE_SPEED_PER_SECOND = 45.0
MOVE_BURST = 12.0
CATCH_DISTANCE = 5.0
ESCAPE_DISTANCE = 8.0
LOCKDOWN_SECONDS = 90.0
BRIEFING_SECONDS = 900.0
SAFECRACK_SECONDS = 75.0
SAFECRACK_MIN_SECONDS = 2.0
CONSOLE_COOLDOWN = 60.0
GUARD_BUBBLE_SECONDS = 6.0
RECOVERY_PEEPS = (
    "guard-ledger",
    "guard-marble",
    "guard-slate",
    "guard-onyx",
    "guard-crane",
    "guard-elite",
    "bot-lookout",
    "bot-muscle",
    "bot-slicer",
)
TARGET_ROOMS = (
    "bank-lobby",
    "bank-offices",
    "bank-security",
    "bank-vault",
    "bank-alley",
    "bank-roof",
)


@dataclass(slots=True)
class LootAward:
    """One provisional loot item awaiting a successful escape."""

    prop_instance_id: str
    card_id: str
    value: int


@dataclass(slots=True)
class CrewMember:
    """One human crew slot in the active job."""

    account_id: str
    username: str
    leader: bool = False
    status: str = "active"
    joined_at: float = 0.0
    provisional: list[LootAward] = field(default_factory=list)


@dataclass(slots=True)
class BotCrew:
    """One hired bot companion and its passive effect."""

    role_id: str
    peep_id: str
    label: str
    account_id: str = ""


@dataclass(slots=True)
class VaultAttempt:
    """One live safe-cracking attempt."""

    status: str = "locked"
    cracker_id: str = ""
    started_at: float = 0.0
    session_id: str = ""
    attempts: int = 0


@dataclass(slots=True)
class ActiveJob:
    """All mutable state for the world's one active heist."""

    run_id: str
    seed: str
    template: JobTemplate
    generated: GeneratedJob
    crew: dict[str, CrewMember] = field(default_factory=dict)
    leader_id: str = ""
    bot: BotCrew | None = None
    phase: str = "briefing"
    staged: bool = False
    entered: bool = False
    infiltrated_at: float = 0.0
    alarm_stage: str = "calm"
    alarm_score: float = 0.0
    alarm_at: float = 0.0
    lockdown_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    deposit_account_id: str = ""
    deposit: int = 0
    guards: dict[str, Any] = field(default_factory=dict)
    reinforcements: list[str] = field(default_factory=list)
    cameras_disabled_until: dict[str, float] = field(default_factory=dict)
    cameras_permanent: set[str] = field(default_factory=set)
    lasers_disabled_until: dict[str, float] = field(default_factory=dict)
    lasers_permanent: set[str] = field(default_factory=set)
    doors_unlocked: set[str] = field(default_factory=set)
    exit_blocks: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    loot_active: dict[str, dict[str, object]] = field(default_factory=dict)
    loot_taken: set[str] = field(default_factory=set)
    cooldowns: dict[tuple[str, str], float] = field(default_factory=dict)
    disguised_until: dict[str, float] = field(default_factory=dict)
    smoke_until: dict[str, float] = field(default_factory=dict)
    decoy_until: float = 0.0
    decoy_position: tuple[float, float] | None = None
    jammer_until: float = 0.0
    jammer_used: bool = False
    console_ready_at: float = 0.0
    vault: VaultAttempt = field(default_factory=VaultAttempt)
    paid_total: int = 0
    objectives_done: set[str] = field(default_factory=set)
    cards_stolen: set[str] = field(default_factory=set)
    props_stolen: set[str] = field(default_factory=set)
    alarm_raised: bool = False


@dataclass(slots=True)
class HeistResult:
    """Command-facing outcome produced by the heist service."""

    message: str | None = None
    payload: dict[str, object] = field(default_factory=dict)
    private_events: list[dict[str, object]] = field(default_factory=list)
    room_broadcasts: list[Any] = field(default_factory=list)
    navigation: Any | None = None
    refresh_user: bool = False


def monotonic_now() -> float:
    """Return the clock used for patrol, cooldown, and alarm timing."""

    return time.monotonic()


def iso_now() -> str:
    """Return the timestamp used for persistent heist history."""

    return utc_now().isoformat()
