"""Validated loader for Tiny Vault job, tool, and bot content."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.content.common import ContentError, load_yaml_file, require_mapping


TOOL_KINDS = frozenset({"reusable", "consumable"})
OBJECTIVE_KINDS = frozenset({"ghost", "speed", "loot_card", "loot_prop"})
MIN_BOARD = 6.0
MAX_BOARD = 94.0


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One purchasable heist tool and its gameplay tuning."""

    id: str
    label: str
    price: int
    kind: str
    cooldown_seconds: float
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class BotSpec:
    """One hireable bot crewmate and its passive effect."""

    id: str
    label: str
    peep_id: str
    price: int
    description: str


@dataclass(frozen=True, slots=True)
class DoorSpec:
    """One pickable or alarm-lockable door mapped to a room exit."""

    room_id: str
    prop_instance_id: str
    exit_id: str
    locked: bool
    alarm_lock: bool


@dataclass(frozen=True, slots=True)
class CameraSpec:
    """One authored camera mount with a server-side vision cone."""

    room_id: str
    prop_instance_id: str
    position: tuple[float, float]
    facing: float
    vision_range: float
    vision_cone: float


@dataclass(frozen=True, slots=True)
class LaserSpec:
    """One laser grid mapped to a room exit."""

    room_id: str
    prop_instance_id: str
    exit_id: str
    locked: bool


@dataclass(frozen=True, slots=True)
class LootSpec:
    """One loot placement with its payout and procedural weight."""

    room_id: str
    prop_instance_id: str
    card_id: str
    value: int
    weight: int


@dataclass(frozen=True, slots=True)
class RouteSpec:
    """One guard's patrol loop inside a single room."""

    room_id: str
    waypoints: tuple[tuple[float, float], ...]
    speed: float
    pause_seconds: float
    vision_range: float
    vision_cone: float


@dataclass(frozen=True, slots=True)
class ObjectiveSpec:
    """One optional job objective evaluated at completion."""

    id: str
    kind: str
    label: str
    card_id: str | None = None
    prop_instance_id: str | None = None
    seconds: float | None = None


@dataclass(frozen=True, slots=True)
class JobRewards:
    """Base crew payout for a finished job."""

    bops: int
    kudos: int


@dataclass(frozen=True, slots=True)
class JobTemplate:
    """One validated heist template before procedural selection."""

    id: str
    label: str
    description: str
    min_crew: int
    max_crew: int
    heat_tier: int
    guard_count: int
    security_budget: int
    deposit: int
    rewards: JobRewards
    time_limit_seconds: float
    target_rooms: tuple[str, ...]
    entry_room_id: str
    vault_room_id: str
    escape_rooms: tuple[str, ...]
    guard_pool: tuple[str, ...]
    reinforcement_pool: tuple[str, ...]
    camera_count: int
    laser_count: int
    loot_count: int
    objectives: tuple[ObjectiveSpec, ...]
    routes: dict[str, RouteSpec]
    cameras: tuple[CameraSpec, ...]
    lasers: tuple[LaserSpec, ...]
    doors: tuple[DoorSpec, ...]
    loot: tuple[LootSpec, ...]


@dataclass(frozen=True, slots=True)
class HeistContent:
    """All validated Tiny Vault content for one world load."""

    tools: dict[str, ToolSpec]
    bots: dict[str, BotSpec]
    jobs: dict[str, JobTemplate]


def _as_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContentError(label)
    return text


def _as_count(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContentError(f"{label} must be an integer at least {minimum}.")
    return value


def _as_number(value: Any, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < minimum:
        raise ContentError(f"{label} must be a number at least {minimum}.")
    return float(value)


def _as_coordinate(value: Any, label: str) -> float:
    number = _as_number(value, label, minimum=MIN_BOARD)
    if number > MAX_BOARD:
        raise ContentError(f"{label} must be between {MIN_BOARD} and {MAX_BOARD}.")
    return number


def _waypoint(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ContentError(f"{label} must be an [x, y] waypoint.")
    return (_as_coordinate(value[0], label), _as_coordinate(value[1], label))


def _string_list(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ContentError(f"{label} must be a non-empty list.")
    items: list[str] = []
    for entry in value:
        text = str(entry or "").strip()
        if not text or text in items:
            raise ContentError(f"{label} must contain unique non-empty strings.")
        items.append(text)
    return tuple(items)


def load_heist_content(path: Path, *, world: Any, catalog: Any) -> HeistContent:
    """Load and validate Tiny Vault jobs against world rooms, props, and cards."""

    payload = require_mapping(load_yaml_file(path), path)
    tools = _load_tools(payload.get("tools"), path, catalog)
    bots = _load_bots(payload.get("bot_roles"), path, world)
    jobs = _load_jobs(payload.get("jobs"), path, world=world, catalog=catalog)
    return HeistContent(tools=tools, bots=bots, jobs=jobs)


def _load_tools(raw_value: Any, path: Path, catalog: Any) -> dict[str, ToolSpec]:
    if not isinstance(raw_value, dict) or not raw_value:
        raise ContentError(f"{path} must define a non-empty tools mapping.")
    tools: dict[str, ToolSpec] = {}
    for tool_id, raw_tool in raw_value.items():
        if not isinstance(tool_id, str) or not isinstance(raw_tool, dict):
            raise ContentError(f"{path} contains an invalid tool entry.")
        if tool_id not in catalog.cards:
            raise ContentError(f"{path} tool '{tool_id}' has no matching world card.")
        kind = _as_text(raw_tool.get("kind"), f"{path} tool '{tool_id}' kind")
        if kind not in TOOL_KINDS:
            raise ContentError(f"{path} tool '{tool_id}' has unknown kind '{kind}'.")
        tools[tool_id] = ToolSpec(
            id=tool_id,
            label=_as_text(raw_tool.get("label"), f"{path} tool '{tool_id}' label"),
            price=_as_count(raw_tool.get("price"), f"{path} tool '{tool_id}' price"),
            kind=kind,
            cooldown_seconds=_as_number(raw_tool.get("cooldown_seconds", 0), f"{path} tool '{tool_id}' cooldown"),
            duration_seconds=_as_number(raw_tool.get("duration_seconds", 0), f"{path} tool '{tool_id}' duration"),
        )
    expected = {
        "heist-lockpick",
        "heist-disguise",
        "heist-smoke",
        "heist-emp",
        "heist-decoy",
        "heist-jammer",
        "heist-drill",
        "heist-grapple",
    }
    missing = sorted(expected - set(tools))
    if missing:
        raise ContentError(f"{path} is missing required tools: {', '.join(missing)}.")
    return tools


def _load_bots(raw_value: Any, path: Path, world: Any) -> dict[str, BotSpec]:
    if not isinstance(raw_value, dict) or not raw_value:
        raise ContentError(f"{path} must define a non-empty bot_roles mapping.")
    bots: dict[str, BotSpec] = {}
    for bot_id, raw_bot in raw_value.items():
        if not isinstance(bot_id, str) or not isinstance(raw_bot, dict):
            raise ContentError(f"{path} contains an invalid bot entry.")
        peep_id = _as_text(raw_bot.get("peep"), f"{path} bot '{bot_id}' peep")
        if peep_id not in world.peeps:
            raise ContentError(f"{path} bot '{bot_id}' references unknown peep '{peep_id}'.")
        bots[bot_id] = BotSpec(
            id=bot_id,
            label=_as_text(raw_bot.get("label"), f"{path} bot '{bot_id}' label"),
            peep_id=peep_id,
            price=_as_count(raw_bot.get("price"), f"{path} bot '{bot_id}' price"),
            description=_as_text(raw_bot.get("description"), f"{path} bot '{bot_id}' description"),
        )
    return bots


def _instance_rooms(world: Any) -> dict[str, str]:
    rooms: dict[str, str] = {}
    for room_id, room in world.rooms.items():
        for instance_id in room.props:
            if instance_id in rooms:
                raise ContentError(f"Prop instance '{instance_id}' appears in multiple rooms.")
            rooms[instance_id] = room_id
    return rooms


def _require_tag(world: Any, prop_instance_id: str, room_id: str, tag: str | tuple[str, ...], path: Path) -> None:
    definition = world.props[world.rooms[room_id].props[prop_instance_id].prop_id]
    wanted = (tag,) if isinstance(tag, str) else tag
    if not any(name in definition.tags for name in wanted):
        raise ContentError(f"{path} prop instance '{prop_instance_id}' must use a '{wanted[0]}' prop.")


def _load_jobs(raw_value: Any, path: Path, *, world: Any, catalog: Any) -> dict[str, JobTemplate]:
    if not isinstance(raw_value, dict) or not raw_value:
        raise ContentError(f"{path} must define a non-empty jobs mapping.")
    instances = _instance_rooms(world)
    jobs: dict[str, JobTemplate] = {}
    for job_id, raw_job in raw_value.items():
        if not isinstance(job_id, str) or not isinstance(raw_job, dict):
            raise ContentError(f"{path} contains an invalid job entry.")
        jobs[job_id] = _load_job(job_id, raw_job, path, world=world, catalog=catalog, instances=instances)
    return jobs


def _load_job(
    job_id: str,
    raw_job: dict[str, Any],
    path: Path,
    *,
    world: Any,
    catalog: Any,
    instances: dict[str, str],
) -> JobTemplate:
    label = f"{path} job '{job_id}'"
    min_crew = _as_count(raw_job.get("min_crew"), f"{label} min_crew", minimum=1)
    max_crew = _as_count(raw_job.get("max_crew"), f"{label} max_crew", minimum=min_crew)
    if max_crew > 4:
        raise ContentError(f"{label} max_crew must be four or fewer.")
    heat_tier = _as_count(raw_job.get("heat_tier"), f"{label} heat_tier", minimum=0)
    if heat_tier > 3:
        raise ContentError(f"{label} heat_tier must be between zero and three.")
    guard_count = _as_count(raw_job.get("guard_count"), f"{label} guard_count", minimum=1)
    target_rooms = _string_list(raw_job.get("target_rooms"), f"{label} target_rooms")
    for room_id in target_rooms:
        if room_id not in world.rooms:
            raise ContentError(f"{label} references unknown room '{room_id}'.")
    entry_room = _as_text(raw_job.get("entry_room"), f"{label} entry_room")
    vault_room = _as_text(raw_job.get("vault_room"), f"{label} vault_room")
    escape_rooms = _string_list(raw_job.get("escape_rooms"), f"{label} escape_rooms")
    for room_id in (entry_room, vault_room, *escape_rooms):
        if room_id not in target_rooms:
            raise ContentError(f"{label} room '{room_id}' must be listed in target_rooms.")
    guard_pool = _string_list(raw_job.get("guard_pool"), f"{label} guard_pool")
    for peep_id in guard_pool:
        if peep_id not in world.peeps:
            raise ContentError(f"{label} references unknown guard '{peep_id}'.")
    if guard_count > len(guard_pool):
        raise ContentError(f"{label} guard_count exceeds its guard pool.")
    reinforcements = tuple(
        str(entry or "").strip()
        for entry in (raw_job.get("reinforcement_pool") or [])
        if str(entry or "").strip()
    )
    for peep_id in reinforcements:
        if peep_id not in world.peeps or peep_id in guard_pool:
            raise ContentError(f"{label} has an invalid reinforcement '{peep_id}'.")
    routes = _load_routes(raw_job.get("routes"), label, world=world)
    for peep_id in (*guard_pool, *reinforcements):
        if peep_id not in routes:
            raise ContentError(f"{label} is missing a route for '{peep_id}'.")
    cameras = _load_cameras(raw_job.get("cameras"), label, world=world, instances=instances)
    lasers = _load_lasers(raw_job.get("lasers"), label, world=world, instances=instances)
    doors = _load_doors(raw_job.get("doors"), label, world=world, instances=instances)
    loot = _load_loot(raw_job.get("loot"), label, world=world, catalog=catalog, instances=instances)
    camera_count = _as_count(raw_job.get("camera_count"), f"{label} camera_count")
    laser_count = _as_count(raw_job.get("laser_count"), f"{label} laser_count")
    loot_count = _as_count(raw_job.get("loot_count"), f"{label} loot_count", minimum=1)
    if camera_count > len(cameras) or laser_count > len(lasers) or loot_count > len(loot):
        raise ContentError(f"{label} selection counts exceed authored security or loot.")
    raw_rewards = raw_job.get("rewards")
    if not isinstance(raw_rewards, dict):
        raise ContentError(f"{label} rewards must be a mapping.")
    return JobTemplate(
        id=job_id,
        label=_as_text(raw_job.get("label"), f"{label} label"),
        description=_as_text(raw_job.get("description"), f"{label} description"),
        min_crew=min_crew,
        max_crew=max_crew,
        heat_tier=heat_tier,
        guard_count=guard_count,
        security_budget=_as_count(raw_job.get("security_budget"), f"{label} security_budget", minimum=1),
        deposit=_as_count(raw_job.get("deposit"), f"{label} deposit"),
        rewards=JobRewards(
            bops=_as_count(raw_rewards.get("bops"), f"{label} reward bops"),
            kudos=_as_count(raw_rewards.get("kudos"), f"{label} reward kudos"),
        ),
        time_limit_seconds=_as_number(raw_job.get("time_limit_seconds"), f"{label} time limit", minimum=60.0),
        target_rooms=target_rooms,
        entry_room_id=entry_room,
        vault_room_id=vault_room,
        escape_rooms=escape_rooms,
        guard_pool=guard_pool,
        reinforcement_pool=reinforcements,
        camera_count=camera_count,
        laser_count=laser_count,
        loot_count=loot_count,
        objectives=_load_objectives(raw_job.get("objectives"), label, catalog=catalog, instances=instances),
        routes=routes,
        cameras=cameras,
        lasers=lasers,
        doors=doors,
        loot=loot,
    )


def _load_routes(raw_value: Any, label: str, *, world: Any) -> dict[str, RouteSpec]:
    if not isinstance(raw_value, dict) or not raw_value:
        raise ContentError(f"{label} routes must be a non-empty mapping.")
    routes: dict[str, RouteSpec] = {}
    for peep_id, raw_route in raw_value.items():
        entry = f"{label} route '{peep_id}'"
        if not isinstance(raw_route, dict):
            raise ContentError(f"{entry} must be a mapping.")
        room_id = _as_text(raw_route.get("room"), f"{entry} room")
        if room_id not in world.rooms:
            raise ContentError(f"{entry} references unknown room '{room_id}'.")
        raw_waypoints = raw_route.get("waypoints")
        if not isinstance(raw_waypoints, list) or len(raw_waypoints) < 2 or len(raw_waypoints) > 12:
            raise ContentError(f"{entry} must list two to twelve waypoints.")
        waypoints = tuple(
            _waypoint(raw_point, f"{entry} waypoint {index + 1}")
            for index, raw_point in enumerate(raw_waypoints)
        )
        routes[str(peep_id)] = RouteSpec(
            room_id=room_id,
            waypoints=waypoints,
            speed=_as_number(raw_route.get("speed"), f"{entry} speed", minimum=1.0),
            pause_seconds=_as_number(raw_route.get("pause_seconds"), f"{entry} pause"),
            vision_range=_as_number(raw_route.get("vision_range"), f"{entry} vision range", minimum=5.0),
            vision_cone=_as_number(raw_route.get("vision_cone"), f"{entry} vision cone", minimum=10.0),
        )
    return routes


def _check_instance(label: str, instances: dict[str, str], instance_id: Any, room_id: str) -> str:
    name = _as_text(instance_id, f"{label} prop")
    if instances.get(name) != room_id:
        raise ContentError(f"{label} prop '{name}' is not placed in room '{room_id}'.")
    return name


def _load_cameras(raw_value: Any, label: str, *, world: Any, instances: dict[str, str]) -> tuple[CameraSpec, ...]:
    entries = raw_value or []
    if not isinstance(entries, list):
        raise ContentError(f"{label} cameras must be a list.")
    cameras: list[CameraSpec] = []
    for index, raw_camera in enumerate(entries):
        entry = f"{label} camera {index + 1}"
        if not isinstance(raw_camera, dict):
            raise ContentError(f"{entry} must be a mapping.")
        room_id = _as_text(raw_camera.get("room"), f"{entry} room")
        if room_id not in world.rooms:
            raise ContentError(f"{entry} references unknown room '{room_id}'.")
        prop = _check_instance(entry, instances, raw_camera.get("prop"), room_id)
        _require_tag(world, prop, room_id, "heist-camera", entry)
        cameras.append(
            CameraSpec(
                room_id=room_id,
                prop_instance_id=prop,
                position=(_as_coordinate(raw_camera.get("x"), f"{entry} x"), _as_coordinate(raw_camera.get("y"), f"{entry} y")),
                facing=_as_number(raw_camera.get("facing"), f"{entry} facing"),
                vision_range=_as_number(raw_camera.get("range"), f"{entry} range", minimum=5.0),
                vision_cone=_as_number(raw_camera.get("cone"), f"{entry} cone", minimum=10.0),
            )
        )
    return tuple(cameras)


def _load_lasers(raw_value: Any, label: str, *, world: Any, instances: dict[str, str]) -> tuple[LaserSpec, ...]:
    entries = raw_value or []
    if not isinstance(entries, list):
        raise ContentError(f"{label} lasers must be a list.")
    lasers: list[LaserSpec] = []
    for index, raw_laser in enumerate(entries):
        entry = f"{label} laser {index + 1}"
        if not isinstance(raw_laser, dict):
            raise ContentError(f"{entry} must be a mapping.")
        room_id = _as_text(raw_laser.get("room"), f"{entry} room")
        if room_id not in world.rooms:
            raise ContentError(f"{entry} references unknown room '{room_id}'.")
        prop = _check_instance(entry, instances, raw_laser.get("prop"), room_id)
        _require_tag(world, prop, room_id, "heist-laser", entry)
        exit_id = _as_text(raw_laser.get("exit"), f"{entry} exit")
        if exit_id not in world.rooms[room_id].exits:
            raise ContentError(f"{entry} references unknown exit '{exit_id}'.")
        lasers.append(
            LaserSpec(
                room_id=room_id,
                prop_instance_id=prop,
                exit_id=exit_id,
                locked=bool(raw_laser.get("locked", True)),
            )
        )
    return tuple(lasers)


def _load_doors(raw_value: Any, label: str, *, world: Any, instances: dict[str, str]) -> tuple[DoorSpec, ...]:
    if not isinstance(raw_value, list) or not raw_value:
        raise ContentError(f"{label} doors must be a non-empty list.")
    doors: list[DoorSpec] = []
    for index, raw_door in enumerate(raw_value):
        entry = f"{label} door {index + 1}"
        if not isinstance(raw_door, dict):
            raise ContentError(f"{entry} must be a mapping.")
        room_id = _as_text(raw_door.get("room"), f"{entry} room")
        if room_id not in world.rooms:
            raise ContentError(f"{entry} references unknown room '{room_id}'.")
        prop = _check_instance(entry, instances, raw_door.get("prop"), room_id)
        _require_tag(world, prop, room_id, ("heist-door", "heist-getaway"), entry)
        exit_id = _as_text(raw_door.get("exit"), f"{entry} exit")
        if exit_id not in world.rooms[room_id].exits:
            raise ContentError(f"{entry} references unknown exit '{exit_id}'.")
        doors.append(
            DoorSpec(
                room_id=room_id,
                prop_instance_id=prop,
                exit_id=exit_id,
                locked=bool(raw_door.get("locked", True)),
                alarm_lock=bool(raw_door.get("alarm_lock", False)),
            )
        )
    return tuple(doors)


def _load_loot(
    raw_value: Any,
    label: str,
    *,
    world: Any,
    catalog: Any,
    instances: dict[str, str],
) -> tuple[LootSpec, ...]:
    if not isinstance(raw_value, list) or not raw_value:
        raise ContentError(f"{label} loot must be a non-empty list.")
    loot: list[LootSpec] = []
    for index, raw_spot in enumerate(raw_value):
        entry = f"{label} loot {index + 1}"
        if not isinstance(raw_spot, dict):
            raise ContentError(f"{entry} must be a mapping.")
        room_id = _as_text(raw_spot.get("room"), f"{entry} room")
        if room_id not in world.rooms:
            raise ContentError(f"{entry} references unknown room '{room_id}'.")
        prop = _check_instance(entry, instances, raw_spot.get("prop"), room_id)
        _require_tag(world, prop, room_id, "heist-loot", entry)
        card_id = _as_text(raw_spot.get("card"), f"{entry} card")
        if card_id not in catalog.cards:
            raise ContentError(f"{entry} references unknown card '{card_id}'.")
        loot.append(
            LootSpec(
                room_id=room_id,
                prop_instance_id=prop,
                card_id=card_id,
                value=_as_count(raw_spot.get("value"), f"{entry} value", minimum=1),
                weight=_as_count(raw_spot.get("weight"), f"{entry} weight"),
            )
        )
    return tuple(loot)


def _load_objectives(raw_value: Any, label: str, *, catalog: Any, instances: dict[str, str]) -> tuple[ObjectiveSpec, ...]:
    entries = raw_value or []
    if not isinstance(entries, list):
        raise ContentError(f"{label} objectives must be a list.")
    objectives: list[ObjectiveSpec] = []
    for index, raw_objective in enumerate(entries):
        entry = f"{label} objective {index + 1}"
        if not isinstance(raw_objective, dict):
            raise ContentError(f"{entry} must be a mapping.")
        kind = _as_text(raw_objective.get("kind"), f"{entry} kind")
        if kind not in OBJECTIVE_KINDS:
            raise ContentError(f"{entry} has unknown kind '{kind}'.")
        card_id = raw_objective.get("card")
        prop_id = raw_objective.get("prop")
        seconds = raw_objective.get("seconds")
        if kind == "loot_card" and (not isinstance(card_id, str) or card_id not in catalog.cards):
            raise ContentError(f"{entry} needs a known loot card.")
        if kind == "loot_prop" and (not isinstance(prop_id, str) or prop_id not in instances):
            raise ContentError(f"{entry} needs a placed loot prop.")
        if kind == "speed":
            seconds = _as_number(seconds, f"{entry} seconds", minimum=30.0)
        objectives.append(
            ObjectiveSpec(
                id=_as_text(raw_objective.get("id"), f"{entry} id"),
                kind=kind,
                label=_as_text(raw_objective.get("label"), f"{entry} label"),
                card_id=str(card_id) if isinstance(card_id, str) else None,
                prop_instance_id=str(prop_id) if isinstance(prop_id, str) else None,
                seconds=float(seconds) if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) else None,
            )
        )
    return tuple(objectives)
