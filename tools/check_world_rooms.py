"""Repeatable room-layout QA for world content.

Loads a world definition and reports, per room, prop bounding boxes (from
authored footprints, instance scale, and yaw rotation), out-of-bounds
placements, pairwise overlaps, scale outliers, zone coverage, and peep
distribution.

Usage:
    python tools/check_world_rooms.py [world-path ...]

Exit status is 1 when any error-level finding exists; warnings never fail.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from server.services.sprite_rooms import (  # noqa: E402
    BOARD_X_PER_PERCENT,
    BOARD_Z_PER_PERCENT,
    _prop_block,
)

OVERLAP_ERROR_AREA = 12.0
OVERLAP_WARN_AREA = 2.0
BOUNDS_MARGIN = 2.0
MIN_INSTANCE_SCALE = 0.5
MAX_INSTANCE_SCALE = 2.0


@dataclass
class Finding:
    """One QA observation for a room."""

    level: str
    room_id: str
    message: str


@dataclass
class RoomReport:
    """All QA output for a single room."""

    room_id: str
    label: str
    findings: list[Finding] = field(default_factory=list)
    prop_count: int = 0
    peep_count: int = 0


def _to_percent(block) -> tuple[float, float, float, float]:
    """Convert a world-unit block to board-percent (x0, y0, x1, y1)."""

    cx = block.x / BOARD_X_PER_PERCENT + 50.0
    cy = block.z / BOARD_Z_PER_PERCENT + 50.0
    hx = block.half_x / BOARD_X_PER_PERCENT
    hy = block.half_z / BOARD_Z_PER_PERCENT
    return (cx - hx, cy - hy, cx + hx, cy + hy)


def _overlap_area(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    return width * height


RUG_TAGS = frozenset({"rug", "carpet"})
WALL_TAGS = frozenset({"wall", "door", "window", "doorway", "wallpaper"})


def _tags_of(world, instance) -> frozenset[str]:
    definition = world.props.get(instance.prop_id)
    return frozenset(definition.tags) if definition is not None else frozenset()


def _is_wall_mounted(world, instance) -> bool:
    return bool(_tags_of(world, instance) & WALL_TAGS)


def check_room(world, room_id: str, peep_counts: dict[str, int]) -> RoomReport:
    """Collect layout findings for one room."""

    room = world.rooms[room_id]
    report = RoomReport(room_id=room_id, label=room.label)
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for instance_id, instance in room.props.items():
        definition = world.props.get(instance.prop_id)
        label = definition.label if definition is not None else instance.prop_id
        report.prop_count += 1
        if not math.isfinite(instance.scale) or not (
            MIN_INSTANCE_SCALE <= instance.scale <= MAX_INSTANCE_SCALE
        ):
            report.findings.append(
                Finding(
                    "warning",
                    room_id,
                    f"prop '{instance_id}' ({label}) has unusual scale {instance.scale}",
                )
            )
        box = _to_percent(_prop_block(world, instance))
        boxes[instance_id] = box
        overhang = (
            max(0.0 - box[0], 0.0)
            + max(box[2] - 100.0, 0.0)
            + max(0.0 - box[1], 0.0)
            + max(box[3] - 100.0, 0.0)
        )
        if overhang > BOUNDS_MARGIN:
            # Wall, door, and window dressing hangs past the board edge by
            # design; anything else leaving the board is a real error.
            level = "error"
            if _is_wall_mounted(world, instance) and box[0] >= 0.0 and box[2] <= 100.0:
                level = "warning"
            report.findings.append(
                Finding(
                    level,
                    room_id,
                    f"prop '{instance_id}' ({label}) hangs off the board "
                    f"(box {[round(v, 1) for v in box]})",
                )
            )
    instances = list(boxes)
    for index, first in enumerate(instances):
        for second in instances[index + 1 :]:
            # Rugs and carpets lie flat under furniture by design.
            if _tags_of(world, room.props[first]) & RUG_TAGS:
                continue
            if _tags_of(world, room.props[second]) & RUG_TAGS:
                continue
            area = _overlap_area(boxes[first], boxes[second])
            if area <= 0:
                continue
            first_label = world.props[room.props[first].prop_id].label
            second_label = world.props[room.props[second].prop_id].label
            message = (
                f"props '{first}' ({first_label}) and '{second}' ({second_label}) "
                f"overlap by ~{area:.1f} board-percent^2"
            )
            level = "error" if area > OVERLAP_ERROR_AREA else "warning"
            report.findings.append(Finding(level, room_id, message))
    zones = [[0 for _ in range(3)] for _ in range(3)]
    for box in boxes.values():
        center_x = min(99.9, max(0.0, (box[0] + box[2]) / 2.0))
        center_y = min(99.9, max(0.0, (box[1] + box[3]) / 2.0))
        zones[int(center_y // (100.0 / 3))][int(center_x // (100.0 / 3))] += 1
    empty = sum(1 for row in zones for cell in row if cell == 0)
    crowded = sum(1 for row in zones for cell in row if cell > 4)
    if empty >= 6:
        report.findings.append(
            Finding("warning", room_id, f"{empty}/9 board zones have no props (sparse)")
        )
    if crowded:
        report.findings.append(
            Finding("warning", room_id, f"{crowded} board zone(s) hold 5+ props (crowded)")
        )
    if report.prop_count < 3:
        report.findings.append(
            Finding("warning", room_id, f"only {report.prop_count} props placed")
        )
    if report.prop_count > 14:
        report.findings.append(
            Finding("warning", room_id, f"{report.prop_count} props placed (busy)")
        )
    report.peep_count = peep_counts.get(room_id, 0)
    if report.peep_count > 5:
        report.findings.append(
            Finding("warning", room_id, f"{report.peep_count} peeps share this room")
        )
    return report


def check_world(world) -> tuple[list[RoomReport], list[Finding]]:
    """Check every room in *world*; return reports plus world-level findings."""

    peep_counts: dict[str, int] = {}
    for peep in world.peeps.values():
        peep_counts[peep.room_id] = peep_counts.get(peep.room_id, 0) + 1
    reports = [check_room(world, room_id, peep_counts) for room_id in world.rooms]
    world_findings: list[Finding] = []
    rooms_without_peeps = sorted(
        room_id for room_id in world.rooms if peep_counts.get(room_id, 0) == 0
    )
    if rooms_without_peeps:
        world_findings.append(
            Finding(
                "info",
                "",
                f"rooms without peeps: {', '.join(rooms_without_peeps)}",
            )
        )
    return reports, world_findings


def load_world(world_path: Path):
    """Load a world definition the same way the test suite does."""

    from server.config import KNOWN_FEATURES
    from server.content.cards import cutscene_card_references, load_card_catalog
    from server.content.sounds import load_sound_names, world_sound_names
    from server.content.worlds import load_world_definition
    from tests.common import (
        load_world_activities,
        load_world_cutscene_roots,
        load_world_cutscenes,
        load_world_mod_props,
        load_world_propsets,
    )

    catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", world_path)
    known_sounds = load_sound_names(REPO_ROOT / "data" / "sounds") | world_sound_names(
        world_path
    )
    shared_propsets: list[Path] = []
    candidate = world_path.parents[1] / "propsets" if len(world_path.parents) > 1 else None
    if candidate is not None and candidate.is_dir():
        # Out-of-tree workshop worlds keep their propsets beside the world.
        shared_propsets.append(candidate)
    return load_world_definition(
        world_path,
        set(catalog.cards),
        core_activities=load_world_activities(),
        core_cutscenes=load_world_cutscenes(),
        cutscene_cards=cutscene_card_references(catalog),
        cutscene_roots=load_world_cutscene_roots(),
        known_features=KNOWN_FEATURES,
        propsets_root=load_world_propsets(),
        shared_propsets_root=shared_propsets,
        mod_props=load_world_mod_props(),
        fx_root=REPO_ROOT / "data" / "fx",
        extra_recipes=catalog.recipes,
        known_sounds=known_sounds,
    )


def render(reports: list[RoomReport], world_findings: list[Finding]) -> str:
    """Render a human-readable QA report."""

    lines: list[str] = []
    errors = warnings = 0
    for report in reports:
        lines.append(f"## {report.room_id} — {report.label}")
        lines.append(f"props: {report.prop_count}, peeps: {report.peep_count}")
        if not report.findings:
            lines.append("clean")
        for finding in report.findings:
            lines.append(f"[{finding.level}] {finding.message}")
            if finding.level == "error":
                errors += 1
            elif finding.level == "warning":
                warnings += 1
        lines.append("")
    for finding in world_findings:
        lines.append(f"[{finding.level}] {finding.message}")
    lines.append(f"totals: {errors} error(s), {warnings} warning(s)")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    """Run the room QA check over one or more world directories."""

    parser = argparse.ArgumentParser(description="Room-layout QA for world content.")
    parser.add_argument(
        "world", nargs="*", default=["../tinyrooms-workshop/worlds/bobs-burgers"]
    )
    args = parser.parse_args(argv)
    failed = False
    for raw in args.world:
        world_path = (REPO_ROOT / raw).resolve() if not Path(raw).is_absolute() else Path(raw)
        world = load_world(world_path)
        reports, world_findings = check_world(world)
        print(f"# world: {world.id}")
        print(render(reports, world_findings))
        if any(
            finding.level == "error"
            for report in reports
            for finding in report.findings
        ):
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
