"""Deterministic procedural selection for Tiny Vault job runs."""

from __future__ import annotations

import random
from dataclasses import dataclass

from mods.tinyvault.content import CameraSpec, JobTemplate, LaserSpec, LootSpec, RouteSpec


@dataclass(frozen=True, slots=True)
class GuardSetup:
    """One staged guard with its patrol route and vision tuning."""

    peep_id: str
    room_id: str
    route: RouteSpec
    elite: bool = False


@dataclass(frozen=True, slots=True)
class GeneratedJob:
    """Authored selections for one seeded job run."""

    guards: tuple[GuardSetup, ...]
    reinforcements: tuple[GuardSetup, ...]
    cameras: tuple[CameraSpec, ...]
    lasers: tuple[LaserSpec, ...]
    loot: tuple[LootSpec, ...]


def _shuffled(randomizer: random.Random, items: tuple[object, ...]) -> list[object]:
    ordered = list(items)
    randomizer.shuffle(ordered)
    return ordered


def _weighted_loot(randomizer: random.Random, loot: tuple[LootSpec, ...], count: int) -> list[LootSpec]:
    remaining = list(loot)
    chosen: list[LootSpec] = []
    while remaining and len(chosen) < count:
        weights = [max(1, spot.weight) if spot.weight else 0 for spot in remaining]
        if not any(weights):
            weights = [1 for _ in remaining]
        pick = randomizer.choices(remaining, weights=weights, k=1)[0]
        chosen.append(pick)
        remaining.remove(pick)
    return chosen


def generate_job(template: JobTemplate, seed: str) -> GeneratedJob:
    """Select guards, security, and loot deterministically from *seed*."""

    randomizer = random.Random(f"{template.id}:{seed}")
    pool = _shuffled(randomizer, template.guard_pool)
    guards = tuple(
        GuardSetup(
            peep_id=str(peep_id),
            room_id=template.routes[str(peep_id)].room_id,
            route=template.routes[str(peep_id)],
            elite=str(peep_id) == "guard-elite",
        )
        for peep_id in pool[: template.guard_count]
    )
    reinforcements = tuple(
        GuardSetup(
            peep_id=str(peep_id),
            room_id=template.routes[str(peep_id)].room_id,
            route=template.routes[str(peep_id)],
        )
        for peep_id in template.reinforcement_pool
    )
    cameras = tuple(_shuffled(randomizer, template.cameras)[: template.camera_count])
    lasers = tuple(_shuffled(randomizer, template.lasers)[: template.laser_count])
    loot = tuple(_weighted_loot(randomizer, template.loot, template.loot_count))
    return GeneratedJob(
        guards=guards,
        reinforcements=reinforcements,
        cameras=cameras,
        lasers=lasers,
        loot=loot,
    )


def describe_generated(template: JobTemplate, generated: GeneratedJob) -> dict[str, object]:
    """Summarize a generated job for the board without revealing patrol secrets."""

    return {
        "id": template.id,
        "label": template.label,
        "description": template.description,
        "min_crew": template.min_crew,
        "max_crew": template.max_crew,
        "heat_tier": template.heat_tier,
        "guard_count": len(generated.guards),
        "reinforcements": len(generated.reinforcements),
        "camera_count": len(generated.cameras),
        "laser_count": len(generated.lasers),
        "loot_count": len(generated.loot),
        "estimated_loot": sum(spot.value for spot in generated.loot),
        "deposit": template.deposit,
        "rewards": {"bops": template.rewards.bops, "kudos": template.rewards.kudos},
        "time_limit_seconds": template.time_limit_seconds,
        "escape_rooms": list(template.escape_rooms),
        "objectives": [
            {"id": objective.id, "label": objective.label, "kind": objective.kind}
            for objective in template.objectives
        ],
    }
