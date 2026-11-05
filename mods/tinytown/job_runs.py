"""Per-cycle offers and in-memory run lifecycle for TinyTown Job Office runs.

Runs and the per-cycle "already filed" list live in memory on purpose: a server
restart forgets any shift in progress and resets the board's taken jobs. Rewards
still go through the persistent progression ledger, whose per-cycle key keeps a
Bops payout from repeating.
"""

from __future__ import annotations

import logging
import random
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mods.tinytown.catalog import TRAITS_BY_ID
from mods.tinytown.job_engine import (
    FATIGUE_PER_STEP,
    current_step,
    ending_key,
    exhaustion,
    fit_for,
    generate_run,
    lead_for,
    prepare_challenge,
    present_task,
    resolve_challenge,
    reward_for,
    used_lead_ids,
)
from mods.tinytown.job_library import JobDefinition, JobLibrary, load_job_library
from mods.tinytown.roommate_dialog import condition_label
from server.content.lighting import (
    DAY_NIGHT_CYCLE_SECONDS,
    cycle_index,
    cycle_phase,
    cycle_remaining,
    phase_to_environment,
)
from server.services.vibes import describe_vibe

JOB_ENERGY_COST = 50
MAX_HELPERS = 3
OFFERS_PER_CYCLE = 3
OFFER_TIER_MIX = ((1, 1), (2, 1), (3, 1))
VIBE_GATE = -50
MOD_ROOT = Path(__file__).resolve().parent
LOGGER = logging.getLogger("tinyrooms.mod.tinytown")


@dataclass(slots=True)
class ActiveRun:
    """One shift in progress. ``state`` is the engine's mutable run dict."""

    run_id: str
    cycle: int
    job_id: str
    state: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FiledShift:
    """How a job on the current board ended."""

    status: str
    steps_passed: int


class JobRuns:
    """Own the job board (refreshed every day-night cycle) and every run's state."""

    def __init__(self, service: object) -> None:
        self.service = service
        self.runtime = service.runtime
        self.hub = self.runtime.hub
        self.profiles = self.runtime.profiles
        self.stats = self.runtime.stats
        self.progression = self.runtime.progression
        self.npcs = service.npcs
        self.vibes = getattr(self.npcs, "vibes", None)
        self._library: JobLibrary | None = None
        self._clock = time.time
        self._active: dict[str, ActiveRun] = {}
        self._filed: dict[tuple[str, int], dict[str, FiledShift]] = {}

    @property
    def available(self) -> bool:
        return bool(getattr(self.service, "available", False))

    @property
    def library(self) -> JobLibrary:
        if self._library is None:
            jobs_root = MOD_ROOT / "activities" / "jobs"
            self._library = load_job_library(
                MOD_ROOT / "content" / "jobs",
                art_root=jobs_root / "art",
                sprite_root=jobs_root / "sprites",
                arena_root=jobs_root / "arenas",
            )
        return self._library

    # -- setup ---------------------------------------------------------------

    def prepare(self) -> None:
        if not self.available:
            return
        _ = self.library

    # -- dates and offers ----------------------------------------------------

    def _cycle(self) -> int:
        """Return the current day-night cycle number (the board's refresh period)."""

        return cycle_index(self._clock())

    @staticmethod
    def _cycle_key(cycle: int) -> str:
        return f"cycle-{cycle}"

    def _prune_filed(self, cycle: int) -> None:
        """Forget filed shifts from cycles that can no longer be on any board."""

        for key in [key for key in self._filed if key[1] < cycle - 1]:
            del self._filed[key]

    def _cycle_payload(self) -> dict[str, Any]:
        now = self._clock()
        phase = cycle_phase(now)
        return {
            "index": cycle_index(now),
            "seconds": DAY_NIGHT_CYCLE_SECONDS,
            "remaining": round(cycle_remaining(now), 2),
            "phase": round(phase, 4),
            "environment": phase_to_environment(phase),
        }

    def _offers_for(self, account_id: str, day_key: str) -> list[JobDefinition]:
        by_tier: dict[int, list[JobDefinition]] = {1: [], 2: [], 3: []}
        for job in self.library.jobs.values():
            by_tier[job.tier].append(job)
        rng = random.Random(f"tinytown-jobs:{account_id}:{day_key}")
        chosen: list[JobDefinition] = []
        for tier, count in OFFER_TIER_MIX:
            pool = list(by_tier[tier])
            rng.shuffle(pool)
            chosen.extend(pool[:count])
        chosen_ids = {job.id for job in chosen}
        remaining = [job for job in self.library.jobs.values() if job.id not in chosen_ids]
        rng.shuffle(remaining)
        chosen.extend(remaining[: OFFERS_PER_CYCLE - len(chosen)])
        rng.shuffle(chosen)
        return chosen[:OFFERS_PER_CYCLE]

    # -- account payloads ----------------------------------------------------

    def _player_payload(self, account: object, snapshot: object | None = None) -> dict[str, Any]:
        snapshot = snapshot or self.stats.snapshot(account.id)
        return {
            "name": account.username_display,
            "traits": (),
            "energy": snapshot.energy,
            "health": snapshot.health,
            "cleanliness": snapshot.cleanliness,
            "vibe": 0.0,
            "level": int(account.level),
            "is_player": True,
        }

    def _helper_payload(self, account: object, record: object) -> dict[str, Any]:
        vibe = 0
        vibe_back = 0
        if self.vibes is not None:
            try:
                vibe = int(self.vibes.get(record.npc_id, account.id))
                vibe_back = int(self.vibes.get(account.id, record.npc_id))
            except Exception:
                LOGGER.debug("tinytown.job_vibe_read_failed", exc_info=True)
        return {
            "npc_id": record.npc_id,
            "name": record.name,
            "avatar_url": f"/assets/world/{self.runtime.world.id}/peeps/{self.npcs._avatar_file(record.avatar)}",
            "traits": tuple(record.traits),
            "energy": float(record.stats.get("energy", 70.0)),
            "health": float(record.stats.get("health", 80.0)),
            "cleanliness": float(record.stats.get("cleanliness", 80.0)),
            "vibe": float(vibe),
            "vibe_back": float(vibe_back),
            "level": 0,
            "is_player": False,
        }

    def _helpers(self, account: object) -> list[dict[str, Any]]:
        return [
            self._helper_payload(account, record)
            for record in self.npcs.records_for_owner(account.id)
        ]

    def _helper_cards(
        self,
        helpers: list[dict[str, Any]],
        *,
        job: JobDefinition | None = None,
        step_index: int | None = None,
        player: dict[str, Any] | None = None,
        used: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for helper in helpers:
            vibe = int(helper.get("vibe", 0))
            fit = (
                fit_for(job, step_index, player, helper)
                if job is not None and step_index is not None and player is not None
                else None
            )
            cards.append(
                {
                    "id": helper["npc_id"],
                    "name": helper["name"],
                    "avatar_url": helper["avatar_url"],
                    "traits": [
                        {"id": trait, "label": TRAITS_BY_ID[trait].label}
                        for trait in helper.get("traits", ())
                        if trait in TRAITS_BY_ID
                    ],
                    "condition": {
                        "energy": condition_label(helper.get("energy", 70.0)),
                        "health": condition_label(helper.get("health", 80.0)),
                        "cleanliness": condition_label(helper.get("cleanliness", 80.0)),
                    },
                    "vibe": {
                        "label": describe_vibe(vibe),
                        "willing": vibe > VIBE_GATE,
                    },
                    "fit": fit,
                    "fatigue": round(exhaustion(helper.get("energy", 70.0)), 2),
                    "used": helper["npc_id"] in (used or set()),
                }
            )
        cards.sort(key=lambda card: (not card["vibe"]["willing"], card["name"].casefold()))
        return cards

    def _job_summary(self, job: JobDefinition) -> dict[str, Any]:
        return {
            "id": job.id,
            "title": job.title,
            "profession": job.profession,
            "tier": job.tier,
            "accent": job.accent,
            "blurb": job.blurb,
            "preview_art": job.preview_art,
            "step_count": len(job.steps),
        }

    # -- run state -----------------------------------------------------------

    def _filed_for(self, account_id: str, cycle: int) -> dict[str, FiledShift]:
        return self._filed.get((account_id, cycle), {})

    # -- board ---------------------------------------------------------------

    def board(self, account: object) -> dict[str, Any]:
        self._require_available()
        cycle = self._cycle()
        self._prune_filed(cycle)
        day_key = self._cycle_key(cycle)
        offers = self._offers_for(account.id, day_key)
        filed = self._filed_for(account.id, cycle)
        active = self._active.get(account.id)
        snapshot = self.stats.snapshot(account.id)
        offers_payload = []
        for job in offers:
            shift = filed.get(job.id)
            if shift is None and active is not None and active.cycle == cycle and active.job_id == job.id:
                status, steps_passed = "active", 0
            else:
                status = shift.status if shift is not None else "open"
                steps_passed = shift.steps_passed if shift is not None else 0
            offers_payload.append({**self._job_summary(job), "status": status, "steps_passed": steps_passed})
        active_payload = None
        if active is not None:
            job = self.library.jobs.get(active.job_id)
            if job is not None:
                active_payload = {
                    "run_id": active.run_id,
                    "job": self._job_summary(job),
                    "step_number": min(4, int(active.state.get("step_index", 0)) + 1),
                    "steps_passed": int(active.state.get("steps_passed", 0)),
                }
        return {
            "day_key": day_key,
            "cycle": self._cycle_payload(),
            "energy": snapshot.energy,
            "energy_cost": JOB_ENERGY_COST if self.stats.energy_enabled else 0,
            "max_helpers": MAX_HELPERS,
            "vibe_gate": VIBE_GATE,
            "player_condition": {
                "energy": condition_label(snapshot.energy),
                "health": condition_label(snapshot.health),
                "cleanliness": condition_label(snapshot.cleanliness),
            },
            "offers": offers_payload,
            "completed_count": len(filed),
            "active_run": active_payload,
            "helpers": self._helper_cards(self._helpers(account)),
        }

    # -- run payloads --------------------------------------------------------

    def _run_payload(self, job: JobDefinition, run: dict[str, Any], run_id: str) -> dict[str, Any]:
        step = current_step(run)
        if step is None:
            raise ValueError("This shift is already finished.")
        job_step = job.steps[step["index"]]
        pips = [None if entry.get("passed") is None else bool(entry["passed"]) for entry in run.get("steps", [])]
        helpers = run.get("helpers", [])
        you_fit = fit_for(job, step["index"], run["player"], run["player"])
        names = {str(helper["npc_id"]): str(helper["name"]) for helper in helpers}
        log = [
            {
                "title": job.steps[index].title,
                "passed": bool(entry["passed"]),
                "lead": names.get(str(entry.get("lead_id")), str(run["player"].get("name", "You"))),
            }
            for index, entry in enumerate(run.get("steps", []))
            if entry.get("passed") is not None
        ]
        return {
            "run_id": run_id,
            "job": self._job_summary(job),
            "step": {
                "index": int(step["index"]),
                "number": int(step["index"]) + 1,
                "title": job_step.title,
                "task": present_task(step, job_step),
                "art_url": job.step_art(int(step["index"])),
                "sprite_url": job.step_sprite(int(step["index"])),
                "arena_url": job.step_arena(int(step["index"])),
                "solo": not helpers,
                "you_fit": you_fit,
                "you_fatigue": round(exhaustion(run["player"].get("energy", 70.0)), 2),
            },
            "pips": pips,
            "player_name": str(run["player"].get("name", "You")),
            "log": log,
            "steps_passed": int(run.get("steps_passed", 0)),
            "completed": False,
            "helpers": self._helper_cards(
                helpers,
                job=job,
                step_index=int(step["index"]),
                player=run["player"],
                used=used_lead_ids(run),
            ),
        }

    def _outcome_payload(
        self,
        job: JobDefinition,
        run: dict[str, Any],
        *,
        bops: int,
        vibe_delta: int,
        status: str,
        updated_vibes: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        steps_passed = int(run.get("steps_passed", 0))
        key = ending_key(steps_passed)
        helper_results = []
        for helper in run.get("helpers", []):
            npc_id = str(helper["npc_id"])
            helper_results.append(
                {
                    "id": npc_id,
                    "name": helper["name"],
                    "avatar_url": helper["avatar_url"],
                    "vibe_delta": vibe_delta,
                    "vibe_label": describe_vibe((updated_vibes or {}).get(npc_id, int(helper.get("vibe", 0)))),
                }
            )
        return {
            "run_id": "",
            "job": self._job_summary(job),
            "completed": True,
            "abandoned": status == "abandoned",
            "steps_passed": steps_passed,
            "ending_key": key,
            "ending": job.endings[key],
            "bops": bops,
            "vibe_delta": vibe_delta,
            "art_url": job.success_art if steps_passed > 0 else job.fail_art,
            "pips": [bool(entry.get("passed")) for entry in run.get("steps", [])],
            "helpers": helper_results,
        }

    # -- start ---------------------------------------------------------------

    def start(self, account: object, job_id: str, helper_ids: list[str]) -> dict[str, Any]:
        self._require_available()
        cycle = self._cycle()
        offers = {job.id: job for job in self._offers_for(account.id, self._cycle_key(cycle))}
        job = offers.get(job_id)
        if job is None:
            raise ValueError("That job is not on the board right now.")
        if account.id in self._active:
            raise ValueError("Finish or quit your current shift first.")
        if job.id in self._filed_for(account.id, cycle):
            raise ValueError("That shift is already done this cycle.")
        unique_helpers = list(dict.fromkeys(str(helper_id) for helper_id in helper_ids if str(helper_id)))
        if len(unique_helpers) > MAX_HELPERS:
            raise ValueError(f"You can take at most {MAX_HELPERS} helpers.")
        records = {record.npc_id: record for record in self.npcs.records_for_owner(account.id)}
        helpers: list[dict[str, Any]] = []
        for helper_id in unique_helpers:
            record = records.get(helper_id)
            if record is None:
                raise ValueError("That roommate is not part of your household.")
            payload = self._helper_payload(account, record)
            if int(payload["vibe"]) <= VIBE_GATE:
                raise ValueError(f"{record.name} would rather not work with you right now.")
            helpers.append(payload)
        cost = JOB_ENERGY_COST if self.stats.energy_enabled else 0
        with self.hub.transaction() as connection:
            if cost:
                snapshot = self.stats.charge_in_transaction(connection, account.id, cost)
            else:
                snapshot = self.stats.snapshot(account.id)
        player = self._player_payload(account, snapshot)
        run = generate_run(job, self.library, player, helpers, secrets.token_hex(16))
        active = ActiveRun(run_id=f"ttjob:{secrets.token_hex(16)}", cycle=cycle, job_id=job.id, state=run)
        self._active[account.id] = active
        return self._run_payload(job, run, active.run_id)

    # -- choose / resume / quit ----------------------------------------------

    def _load_active(self, account: object) -> tuple[ActiveRun, JobDefinition]:
        self._require_available()
        active = self._active.get(account.id)
        if active is None:
            raise ValueError("You do not have a shift in progress.")
        job = self.library.jobs.get(active.job_id)
        if job is None:
            self._active.pop(account.id, None)
            raise ValueError("That job is no longer available.")
        return active, job

    def challenge(self, account: object, helper_id: str | None) -> dict[str, Any]:
        """Start the current step's minigame with the chosen lead (a roommate or the player)."""

        active, job = self._load_active(account)
        run = active.state
        challenge = prepare_challenge(run, job, helper_id, f"ttch:{secrets.token_hex(12)}")
        step = current_step(run)
        lead = lead_for(run, challenge["lead_id"])
        job_step = job.steps[int(step["index"])]
        return {
            "challenge": {
                "id": challenge["id"],
                "step_index": int(step["index"]),
                "lead": {
                    "id": challenge["lead_id"] or "",
                    "name": str(lead.get("name", "You")),
                    "avatar_url": str(lead.get("avatar_url", "")),
                },
                "game": job_step.game,
                "params": challenge["params"],
                "sprite_url": job.step_sprite(int(step["index"])),
                "arena_url": job.step_arena(int(step["index"])),
                "art_url": job.step_art(int(step["index"])),
            }
        }

    def resolve(
        self,
        account: object,
        challenge_id: str,
        score: int,
        elapsed_ms: int,
    ) -> dict[str, Any]:
        """Record a finished minigame, apply fatigue, and advance or finish the shift."""

        active, job = self._load_active(account)
        run = active.state
        result = resolve_challenge(run, job, challenge_id, int(score), int(elapsed_ms))
        if result.lead_id:
            self._apply_fatigue(result.lead_id)
        payload_result = {
            "passed": result.passed,
            "text": result.text,
            "approach": result.approach_label,
            "lead_name": result.lead_name,
            "step_index": result.step_index,
            "score": result.score,
            "required": result.required,
            "total": result.total,
        }
        if not result.completed:
            return {"result": payload_result, "run": self._run_payload(job, run, active.run_id), "outcome": None}
        outcome = self._finalize(account, active, job, status="completed")
        return {"result": payload_result, "run": None, "outcome": outcome}

    def _apply_fatigue(self, npc_id: str) -> None:
        """Persist the energy a roommate spends leading one scene."""

        record = self.npcs.record_for(npc_id)
        if record is None:
            return
        stats = dict(record.stats)
        stats["energy"] = self.npcs._clamp(stats.get("energy", 70.0) - FATIGUE_PER_STEP)
        try:
            self.npcs._write(self.npcs._with(record, stats=stats), created=False)
        except Exception:
            LOGGER.warning("tinytown.job_fatigue_failed npc_id=%s", npc_id, exc_info=True)

    def resume(self, account: object) -> dict[str, Any]:
        active, job = self._load_active(account)
        return self._run_payload(job, active.state, active.run_id)

    def quit(self, account: object) -> dict[str, Any]:
        active, job = self._load_active(account)
        return self._finalize(account, active, job, status="abandoned")

    # -- finalization --------------------------------------------------------

    def _finalize(
        self,
        account: object,
        active: ActiveRun,
        job: JobDefinition,
        *,
        status: str,
    ) -> dict[str, Any]:
        """Settle a shift once: pay Bops and vibes, then file it on the board."""

        if self._active.get(account.id) is not active:
            raise ValueError("You do not have a shift in progress.")
        run = active.state
        steps_passed = int(run.get("steps_passed", 0))
        bops, vibe_delta = reward_for(steps_passed)
        updated_vibes: dict[str, int] = {}
        del self._active[account.id]
        try:
            with self.hub.transaction() as connection:
                if bops:
                    self.progression.grant_in_transaction(
                        connection,
                        account.id,
                        bops=bops,
                        ledger_key=f"tinytown-job:{account.id}:{self._cycle_key(active.cycle)}:{active.job_id}",
                        kind="tinytown-job",
                    )
                if vibe_delta and self.vibes is not None:
                    pair_deltas = [
                        (str(helper["npc_id"]), account.id, vibe_delta)
                        for helper in run.get("helpers", [])
                    ]
                    updated_vibes = {
                        source: value
                        for (source, _target), value in self.vibes.adjust_many_in_transaction(
                            connection, pair_deltas
                        ).items()
                    }
        except Exception:
            self._active[account.id] = active
            raise
        self._filed.setdefault((account.id, active.cycle), {})[active.job_id] = FiledShift(
            status=status, steps_passed=steps_passed
        )
        return self._outcome_payload(
            job,
            run,
            bops=bops,
            vibe_delta=vibe_delta,
            status=status,
            updated_vibes=updated_vibes,
        )

    def _require_available(self) -> None:
        if not self.available:
            raise ValueError("TinyTown Job Office is not available here.")
