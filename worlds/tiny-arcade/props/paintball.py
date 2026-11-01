"""World-authored Paintball Arena rules for The Arcade.

The arena is a 2D top-down shooter. The server owns round timing, obstacle
layouts, participants, projectiles, scores, vending, counters, and podium
rewards. Activity clients render that state and send movement/aim input.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import math
import random
from typing import Any

from server.behaviors.events import PeepRef
from server.game.activity_arena import (
    hits_obstacle,
    move_body,
    sweep_hits_obstacle,
)


STATE_KEY = "paintball"
STATE_VERSION = 4
INPUT_TIMEOUT_SECONDS = 0.7

DEFAULT_ROUND_SECONDS = 120
DEFAULT_INTERMISSION_SECONDS = 30
DEFAULT_REWARDS = (10, 5, 1)
DEFAULT_QUALITY = 1
DEFAULT_ARENA_WIDTH = 100.0
DEFAULT_ARENA_HEIGHT = 100.0
DEFAULT_PLAYER_RADIUS = 1.8
DEFAULT_PLAYER_SPEED = 24.0
DEFAULT_BOT_SPEED = 16.0
DEFAULT_PROJECTILE_SPEED = 70.0
DEFAULT_PROJECTILE_LIFETIME = 1.1
DEFAULT_PROJECTILE_RADIUS = 1.1
DEFAULT_PROJECTILE_BOOST = 1.5
DEFAULT_PROJECTILE_DRAG = 0.9
DEFAULT_MOVE_ACCEL = 160.0
DEFAULT_MOVE_FRICTION = 220.0
DEFAULT_FIRE_COOLDOWN = 0.45
DEFAULT_OBSTACLE_COUNT = (3, 5)
DEFAULT_SHOT_SPREAD = {1: 0.095, 2: 0.060, 3: 0.030}
DEFAULT_BOT_WAYPOINT_SECONDS = (2.0, 5.0)
DEFAULT_AMMO = (
    {"card": "paintball-cherry", "color": "#ff4d6d"},
    {"card": "paintball-berry", "color": "#4ea8ff"},
    {"card": "paintball-lime", "color": "#5cf29a"},
    {"card": "paintball-lemon", "color": "#ffe066"},
    {"card": "paintball-grape", "color": "#c77dff"},
)
DEFAULT_VENDING = (
    {"card": "paintball-blaster-splash", "quantity": 1, "bops": 1},
    {"card": "paintball-blaster-neon", "quantity": 1, "bops": 8},
    {"card": "paintball-blaster-prism", "quantity": 1, "bops": 20},
    {"card": "paintball-cherry", "quantity": 10, "bops": 1},
    {"card": "paintball-berry", "quantity": 10, "bops": 1},
    {"card": "paintball-lime", "quantity": 10, "bops": 1},
    {"card": "paintball-lemon", "quantity": 10, "bops": 1},
    {"card": "paintball-grape", "quantity": 10, "bops": 1},
)
DEFAULT_BOT_IDS = (
    "paintbot-pip",
    "paintbot-bolt",
    "paintbot-mim",
    "paintbot-cog",
)
DEFAULT_TARGET_PLAYERS = 4
DEFAULT_BOT_QUALITY = 2
DEFAULT_BOT_SHOT_SECONDS = (5.5, 9.5)
MAX_PROJECTILES = 48
MAX_SPLATS = 80
PAINT_DECAL_ID = "paint"
PAINT_DECAL_KIND = "paint"
CUTSCENE_ID = "paintball-podium"
USER = "user"
BOT = "bot"
SPAWN_SLOTS = (
    (10.0, 10.0),
    (90.0, 10.0),
    (10.0, 90.0),
    (90.0, 90.0),
    (50.0, 8.0),
    (50.0, 92.0),
    (8.0, 50.0),
    (92.0, 50.0),
    (28.0, 28.0),
    (72.0, 28.0),
    (28.0, 72.0),
    (72.0, 72.0),
)


def _activity(context) -> dict[str, Any]:
    room = getattr(context, "room", None)
    if not isinstance(room, dict):
        return {}
    activities = room.get("activities")
    if isinstance(activities, dict):
        activity = activities.get("paintball")
        if isinstance(activity, dict):
            return activity
    activity = room.get("activity")
    return activity if isinstance(activity, dict) else {}


def _config(context) -> dict[str, Any]:
    activity = _activity(context)
    config = activity.get("config")
    return config if isinstance(config, dict) else {}


def _config_int(config: dict[str, Any], key: str, default: int) -> int:
    try:
        return max(1, int(config.get(key, default)))
    except (TypeError, ValueError):
        return default


def _config_float(config: dict[str, Any], key: str, default: float) -> float:
    try:
        return max(0.01, float(config.get(key, default)))
    except (TypeError, ValueError):
        return default


def _config_float_pair(config: dict[str, Any], key: str, default: tuple[float, float]) -> tuple[float, float]:
    raw = config.get(key, default)
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return default
    try:
        low, high = float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        return default
    return (max(0.01, min(low, high)), max(low, high))


def _rewards(config: dict[str, Any]) -> tuple[int, ...]:
    raw = config.get("rewards")
    if not isinstance(raw, list):
        return DEFAULT_REWARDS
    values = tuple(int(value) for value in raw if isinstance(value, (int, float)))
    return values or DEFAULT_REWARDS


def _ammo(config: dict[str, Any]) -> tuple[dict[str, str], ...]:
    raw = config.get("ammo")
    if not isinstance(raw, list):
        return DEFAULT_AMMO
    entries = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        card = str(entry.get("card", "")).strip()
        color = str(entry.get("color", "")).strip()
        if card and color:
            entries.append({"card": card, "color": color})
    return tuple(entries) or DEFAULT_AMMO


def _vending(config: dict[str, Any]) -> tuple[dict[str, object], ...]:
    raw = config.get("vending")
    if not isinstance(raw, list):
        return DEFAULT_VENDING
    entries = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        card = str(entry.get("card", "")).strip()
        if not card:
            continue
        entries.append(
            {
                "card": card,
                "quantity": max(1, int(entry.get("quantity", 1) or 1)),
                "bops": max(0, int(entry.get("bops", 0) or 0)),
            }
        )
    return tuple(entries) or DEFAULT_VENDING


def _bot_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("bots")
    if not isinstance(raw, dict):
        raw = {}
    ids = raw.get("ids")
    bot_ids = tuple(str(value) for value in ids) if isinstance(ids, list) else DEFAULT_BOT_IDS
    shot_seconds = raw.get("shot_seconds")
    if not isinstance(shot_seconds, list) or len(shot_seconds) != 2:
        shot_seconds = list(DEFAULT_BOT_SHOT_SECONDS)
    try:
        low, high = float(shot_seconds[0]), float(shot_seconds[1])
    except (TypeError, ValueError):
        low, high = DEFAULT_BOT_SHOT_SECONDS
    return {
        "ids": bot_ids,
        "target_players": max(1, int(raw.get("target_players", DEFAULT_TARGET_PLAYERS) or DEFAULT_TARGET_PLAYERS)),
        "quality": int(raw.get("quality", DEFAULT_BOT_QUALITY) or DEFAULT_BOT_QUALITY),
        "shot_seconds": (max(0.2, min(low, high)), max(low, high)),
    }


def _reset_powers(context) -> tuple[str, ...]:
    activity = _activity(context)
    values = activity.get("reset_powers")
    if isinstance(values, list):
        return tuple(str(value) for value in values)
    return ("admin", "moderator", "game-master")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _arena(config: dict[str, Any]) -> tuple[float, float]:
    width = _config_float(config, "arena_width", DEFAULT_ARENA_WIDTH)
    height = _config_float(config, "arena_height", DEFAULT_ARENA_HEIGHT)
    return max(20.0, width), max(20.0, height)


def _obstacle_count(config: dict[str, Any]) -> tuple[int, int]:
    raw = config.get("obstacle_count")
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            low = max(0, int(raw[0]))
            high = max(low, int(raw[1]))
            return low, min(12, high)
        except (TypeError, ValueError):
            pass
    return DEFAULT_OBSTACLE_COUNT


def _generate_obstacles(seed: int, config: dict[str, Any], arena: tuple[float, float]) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    width, height = arena
    low, high = _obstacle_count(config)
    count = rng.randint(low, high) if high >= low else low
    obstacles: list[dict[str, Any]] = []
    spawn_clearance = DEFAULT_PLAYER_RADIUS + 3.0
    for index in range(count):
        for _ in range(80):
            radius = rng.uniform(5.0, 9.0)
            x = rng.uniform(6.0 + radius, max(7.0 + radius, width - 6.0 - radius))
            y = rng.uniform(6.0 + radius, max(7.0 + radius, height - 6.0 - radius))
            if any(
                math.hypot(x - slot_x, y - slot_y) <= spawn_clearance + radius
                for slot_x, slot_y in SPAWN_SLOTS
            ):
                continue
            if any(math.hypot(x - other["x"], y - other["y"]) < 14.0 for other in obstacles):
                continue
            if hits_obstacle(x, y, 1.0, obstacles):
                continue
            obstacles.append(
                {"id": f"obstacle-{index}", "kind": "circle", "x": round(x, 2), "y": round(y, 2), "r": round(radius, 2)}
            )
            break
    return obstacles


def _new_state(context) -> dict[str, Any]:
    config = _config(context)
    intermission = _config_int(config, "intermission_seconds", DEFAULT_INTERMISSION_SECONDS)
    now = context.now
    width, height = _arena(config)
    return {
        "version": STATE_VERSION,
        "phase": "intermission",
        "round": 0,
        "phase_ends_at": (now + timedelta(seconds=intermission)).isoformat(),
        "round_started_at": "",
        "arena": {"width": width, "height": height},
        "arena_seed": 0,
        "obstacles": [],
        "participants": {},
        "projectiles": [],
        "projectile_seq": 0,
        "scores": {},
        "splats": [],
        "last_round": None,
        "records": {"games": 0, "best_hits": 0, "best_name": ""},
        "last_sim_at": now.isoformat(),
    }


def _load_state(context) -> dict[str, Any] | None:
    raw = context.state.get(STATE_KEY)
    if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
        return None
    if raw.get("phase") not in {"active", "intermission"}:
        return None
    if not isinstance(raw.get("scores"), dict):
        return None
    raw.setdefault("participants", {})
    raw.setdefault("projectiles", [])
    raw.setdefault("obstacles", [])
    raw.setdefault("last_sim_at", context.now.isoformat())
    return raw


def _state_for(context) -> dict[str, Any]:
    state = _load_state(context)
    if state is None:
        state = _new_state(context)
        context.state[STATE_KEY] = state
    return state


def _seconds_left(state: dict[str, Any], now: datetime) -> int:
    end = _parse_timestamp(state.get("phase_ends_at"))
    if end is None:
        return 0
    return max(0, int(math.ceil((end - now).total_seconds())))


def _now_ms(now: datetime) -> int:
    try:
        return int(now.timestamp() * 1000)
    except (TypeError, ValueError, OSError, OverflowError):
        return 0


def _ranking(state: dict[str, Any]) -> list[dict[str, Any]]:
    scores = state.get("scores") if isinstance(state.get("scores"), dict) else {}
    rows: list[dict[str, Any]] = []
    for account_id, entry in scores.items():
        if not isinstance(entry, dict):
            continue
        hits = max(0, int(entry.get("hits", 0) or 0))
        if hits <= 0:
            continue
        shots = max(1, int(entry.get("shots", 0) or 0))
        rows.append(
            {
                "id": str(account_id),
                "name": str(entry.get("name", "") or "Peep"),
                "hits": hits,
                "shots": shots,
                "accuracy": round(hits / shots, 3),
                "bot": bool(entry.get("bot")),
            }
        )
    rows.sort(key=lambda row: (-row["hits"], -row["accuracy"], str(row["name"]).casefold()))
    return rows


def _clock_label(seconds: int) -> str:
    minutes, remainder = divmod(max(0, int(seconds)), 60)
    return f"{minutes}:{remainder:02d}"


def _room_description(state: dict[str, Any], now: datetime) -> str:
    del now
    last_round = state.get("last_round")
    winners = ""
    if isinstance(last_round, dict):
        top = last_round.get("top")
        if isinstance(top, list) and top:
            parts = [f"{entry.get('name')} ({int(entry.get('hits', 0) or 0)})" for entry in top[:3] if isinstance(entry, dict)]
            winners = " Last winners: " + ", ".join(parts) + "."
        else:
            winners = " Last round: no confirmed hits."
    else:
        winners = " Last winners: none yet."
    records = state.get("records") if isinstance(state.get("records"), dict) else {}
    best_hits = int(records.get("best_hits", 0) or 0)
    best_name = str(records.get("best_name", "") or "")
    if best_hits > 0 and best_name:
        record = f" Arena record: {best_name} — {best_hits} hits."
    else:
        record = " Arena record: unclaimed."
    games = int(records.get("games", 0) or 0)
    played = f" {games} game{'s' if games != 1 else ''} played." if games else ""
    return f"{winners}{record}{played}".strip()


def _status(state: dict[str, Any], now: datetime) -> str:
    phase = str(state.get("phase", "intermission"))
    if phase == "active":
        return f"Round {int(state.get('round', 0) or 0)} — {_clock_label(_seconds_left(state, now))} left"
    return f"Next round in {_clock_label(_seconds_left(state, now))}"


def _public_participants(state: dict[str, Any]) -> list[dict[str, Any]]:
    participants = state.get("participants") if isinstance(state.get("participants"), dict) else {}
    rows = []
    for participant in participants.values():
        if not isinstance(participant, dict):
            continue
        aim = participant.get("aim") if isinstance(participant.get("aim"), list) else [1.0, 0.0]
        rows.append(
            {
                "id": str(participant.get("id", "")),
                "name": str(participant.get("name", "") or "Peep"),
                "kind": BOT if participant.get("kind") == BOT else USER,
                "x": round(float(participant.get("x", 50.0)), 3),
                "y": round(float(participant.get("y", 50.0)), 3),
                "aim": [round(float(aim[0]) if len(aim) > 0 else 1.0, 3), round(float(aim[1]) if len(aim) > 1 else 0.0, 3)],
                "color": str(participant.get("color", "#ff4d6d")),
                "sprite": str(participant.get("sprite", "") or ""),
                "flash_until": participant.get("flash_until"),
            }
        )
    rows.sort(key=lambda row: (row["kind"] != USER, str(row["name"]).casefold()))
    return rows


def _public_projectiles(state: dict[str, Any]) -> list[dict[str, Any]]:
    projectiles = state.get("projectiles") if isinstance(state.get("projectiles"), list) else []
    rows = []
    for projectile in projectiles:
        if not isinstance(projectile, dict):
            continue
        rows.append(
            {
                "id": projectile.get("id"),
                "owner": str(projectile.get("owner", "")),
                "x": round(float(projectile.get("x", 0.0)), 3),
                "y": round(float(projectile.get("y", 0.0)), 3),
                "vx": round(float(projectile.get("vx", 0.0)), 3),
                "vy": round(float(projectile.get("vy", 0.0)), 3),
                "ttl": round(float(projectile.get("ttl", 0.0)), 3),
                "color": str(projectile.get("color", "#ff4d6d")),
            }
        )
    return rows


def _public_splats(state: dict[str, Any]) -> list[dict[str, Any]]:
    splats = state.get("splats") if isinstance(state.get("splats"), list) else []
    rows = []
    for splat in splats[-MAX_SPLATS:]:
        if not isinstance(splat, dict):
            continue
        rows.append(
            {
                "id": str(splat.get("id", "")),
                "x": round(float(splat.get("x", 0.0)), 3),
                "y": round(float(splat.get("y", 0.0)), 3),
                "color": str(splat.get("color", "#ff4d6d")),
                "size": float(splat.get("size", 1.0)),
                "rotation": float(splat.get("rotation", 0.0)),
            }
        )
    return rows


def _public(state: dict[str, Any], now: datetime, config: dict[str, Any] | None = None, *, seq: int = 0, t: int = 0) -> dict[str, Any]:
    participants = _public_participants(state)
    shop_config = config if isinstance(config, dict) else {}
    return {
        "seq": int(seq),
        "t": int(t),
        "phase": str(state.get("phase", "intermission")),
        "round": int(state.get("round", 0) or 0),
        "phase_ends_at": state.get("phase_ends_at"),
        "seconds_left": _seconds_left(state, now),
        "status": _status(state, now),
        "room_description": _room_description(state, now),
        "arena": state.get("arena"),
        "tuning": {
            "player_radius": DEFAULT_PLAYER_RADIUS,
            "player_speed": _config_float(shop_config, "player_speed", DEFAULT_PLAYER_SPEED),
            "bot_speed": _config_float(shop_config, "bot_speed", DEFAULT_BOT_SPEED),
            "projectile_speed": _config_float(shop_config, "projectile_speed", DEFAULT_PROJECTILE_SPEED),
            "projectile_lifetime": _config_float(shop_config, "projectile_lifetime", DEFAULT_PROJECTILE_LIFETIME),
            "projectile_boost": _config_float(shop_config, "projectile_boost", DEFAULT_PROJECTILE_BOOST),
            "projectile_drag": _config_float(shop_config, "projectile_drag", DEFAULT_PROJECTILE_DRAG),
            "move_accel": _config_float(shop_config, "move_accel", DEFAULT_MOVE_ACCEL),
            "move_friction": _config_float(shop_config, "move_friction", DEFAULT_MOVE_FRICTION),
            "fire_cooldown": _config_float(shop_config, "fire_cooldown", DEFAULT_FIRE_COOLDOWN),
        },
        "obstacles": list(state.get("obstacles", [])),
        "participants": participants,
        "projectiles": _public_projectiles(state),
        "scoreboard": _ranking(state),
        "splats": _public_splats(state),
        "shop": [
            {"card": str(entry.get("card")), "quantity": int(entry.get("quantity", 1) or 1), "bops": int(entry.get("bops", 0) or 0)}
            for entry in _vending(shop_config)
        ],
        "last_round": state.get("last_round"),
        "records": state.get("records"),
    }


_PARTICIPANT_DELTA_FIELDS = ("x", "y", "aim", "color", "flash_until")


def _delta(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any] | None:
    """Build the compact delta between two public snapshots, or None if equal."""

    if not isinstance(previous, dict) or not isinstance(current, dict):
        return None
    delta: dict[str, Any] = {"from": int(previous.get("seq", 0) or 0), "seq": int(current.get("seq", 0) or 0), "t": int(current.get("t", 0) or 0)}
    for key in ("phase", "round", "phase_ends_at", "seconds_left", "status"):
        if previous.get(key) != current.get(key):
            delta[key] = current.get(key)
    scoreboard = current.get("scoreboard")
    if previous.get("scoreboard") != scoreboard:
        delta["scoreboard"] = scoreboard
    previous_participants = {row.get("id"): row for row in previous.get("participants", []) if isinstance(row, dict)}
    current_participants = {row.get("id"): row for row in current.get("participants", []) if isinstance(row, dict)}
    updated: list[dict[str, Any]] = []
    for participant_id, row in current_participants.items():
        before = previous_participants.get(participant_id)
        if not isinstance(before, dict):
            updated.append(dict(row))
            continue
        changed = {"id": participant_id}
        for field in _PARTICIPANT_DELTA_FIELDS:
            if before.get(field) != row.get(field):
                changed[field] = row.get(field)
        if len(changed) > 1:
            updated.append(changed)
    removed = sorted(participant_id for participant_id in previous_participants if participant_id not in current_participants)
    if updated:
        delta["participants"] = updated
    if removed:
        delta["participants_remove"] = removed
    previous_projectiles = {entry.get("id"): entry for entry in previous.get("projectiles", []) if isinstance(entry, dict)}
    current_projectiles = {entry.get("id"): entry for entry in current.get("projectiles", []) if isinstance(entry, dict)}
    spawned = []
    for projectile_id, entry in current_projectiles.items():
        if projectile_id in previous_projectiles:
            continue
        spawned.append(
            {
                "id": projectile_id,
                "owner": str(entry.get("owner", "")),
                "x": entry.get("x"),
                "y": entry.get("y"),
                "vx": entry.get("vx"),
                "vy": entry.get("vy"),
                "ttl": entry.get("ttl"),
                "color": entry.get("color"),
            }
        )
    removed_projectiles = sorted(projectile_id for projectile_id in previous_projectiles if projectile_id not in current_projectiles)
    if spawned:
        delta["projectiles_add"] = spawned
    if removed_projectiles:
        delta["projectiles_remove"] = removed_projectiles
    previous_splats = {entry.get("id") for entry in previous.get("splats", []) if isinstance(entry, dict)}
    added_splats = [entry for entry in current.get("splats", []) if isinstance(entry, dict) and entry.get("id") not in previous_splats]
    if added_splats:
        delta["splats_add"] = [dict(entry) for entry in added_splats]
    if len(delta) <= 3:
        return None
    return delta


def _publish(context, state: dict[str, Any], *, force_full: bool = False) -> bool:
    """Publish the public snapshot, or a compact delta when only it changed.

    Revision numbers live on the wire snapshot only; the simulation state
    stays clean so an unchanged tick publishes nothing and touches nothing.
    """

    config = _config(context)
    previous = context.room_activity_state("paintball")
    if not isinstance(previous, dict):
        previous = {}
    seq = int(previous.get("seq", 0) or 0) + 1
    current = _public(state, context.now, config, seq=seq, t=_now_ms(context.now))
    full = bool(force_full) or previous.get("seq") is None
    for key in ("round", "phase", "arena", "tuning", "obstacles", "shop", "last_round", "records", "room_description"):
        if previous.get(key) != current.get(key):
            full = True
            break
    if full:
        context.set_room_activity_state(current, kind="paintball")
        return True
    delta = _delta(previous, current)
    if delta is None:
        return False
    context.set_room_activity_state(current, kind="paintball", delta=delta)
    return True


def _participant_scores(state: dict[str, Any]) -> dict[str, Any]:
    scores = state.get("scores")
    if not isinstance(scores, dict):
        scores = {}
        state["scores"] = scores
    return scores


def _ensure_participant(
    state: dict[str, Any],
    *,
    participant_id: str,
    name: str,
    kind: str,
    x: float,
    y: float,
    color: str = "#ff4d6d",
    sprite: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    participants = state.get("participants")
    if not isinstance(participants, dict):
        participants = {}
        state["participants"] = participants
    participant = participants.get(participant_id)
    if not isinstance(participant, dict):
        participant = {
            "id": participant_id,
            "name": name,
            "kind": kind,
            "x": x,
            "y": y,
            "aim": [1.0, 0.0],
            "move": [0.0, 0.0],
            "fire": False,
            "vx": 0.0,
            "vy": 0.0,
            "color": color,
            "sprite": sprite,
            "shots": 0,
            "hits": 0,
            "cleanliness": 100.0,
            "max_cleanliness": 100.0,
            "next_shot_at": None,
            "last_input_at": None,
            "waypoint": None,
            "waypoint_until": None,
            "flash_until": None,
        }
        participants[participant_id] = participant
    participant["name"] = name
    participant["kind"] = kind
    if sprite:
        participant["sprite"] = sprite
    if now is not None:
        participant.setdefault("next_shot_at", None)
    return participant


def _move_body(
    entry: dict[str, Any],
    desired_x: float,
    desired_y: float,
    *,
    step: float,
    arena: tuple[float, float],
    obstacles: list[dict[str, Any]],
    accel: float,
    friction: float,
) -> None:
    """Ease a peep toward its desired velocity and slide it through the arena."""

    entry["vx"], entry["vy"] = _approach_velocity(
        float(entry.get("vx", 0.0)), float(entry.get("vy", 0.0)), desired_x, desired_y, accel, friction, step,
    )
    if math.hypot(float(entry.get("vx", 0.0)), float(entry.get("vy", 0.0))) > 1e-6:
        entry["x"], entry["y"] = move_body(
            float(entry.get("x", 50.0)),
            float(entry.get("y", 50.0)),
            float(entry.get("vx", 0.0)) * step,
            float(entry.get("vy", 0.0)) * step,
            DEFAULT_PLAYER_RADIUS,
            arena,
            obstacles,
        )


def _free_spawn(state: dict[str, Any], index: int) -> tuple[float, float]:
    obstacles = state.get("obstacles") if isinstance(state.get("obstacles"), list) else []
    participants = state.get("participants") if isinstance(state.get("participants"), dict) else {}
    taken = [(float(entry.get("x", 0.0)), float(entry.get("y", 0.0))) for entry in participants.values() if isinstance(entry, dict)]
    for offset in range(len(SPAWN_SLOTS)):
        slot = SPAWN_SLOTS[(index + offset) % len(SPAWN_SLOTS)]
        if hits_obstacle(slot[0], slot[1], DEFAULT_PLAYER_RADIUS + 2.0, obstacles):
            continue
        if any(math.hypot(slot[0] - x, slot[1] - y) < 8.0 for x, y in taken):
            continue
        return slot
    return SPAWN_SLOTS[index % len(SPAWN_SLOTS)]


def _sync_users(state: dict[str, Any], context, room_id: str) -> bool:
    """Sync human participants from open paintball sessions; memory only.

    Returns True when the roster changed (a participant was added/removed).
    """

    participants = state.get("participants")
    if not isinstance(participants, dict):
        participants = {}
        state["participants"] = participants
    changed = False
    sessions = context.activity_users(room_id, "paintball") if hasattr(context, "activity_users") else []
    live = {str(user.get("id")): str(user.get("name", "") or "Peep") for user in sessions if str(user.get("id", ""))}
    for user_id, name in live.items():
        existing = participants.get(user_id)
        if isinstance(existing, dict) and existing.get("kind") == USER:
            if existing.get("name") != name:
                existing["name"] = name
                changed = True
            continue
        slot = _free_spawn(state, len(participants))
        _ensure_participant(
            state,
            participant_id=user_id,
            name=name,
            kind=USER,
            x=slot[0],
            y=slot[1],
        )
        changed = True
    for participant_id in [key for key, entry in participants.items() if isinstance(entry, dict) and entry.get("kind") == USER]:
        if participant_id not in live:
            del participants[participant_id]
            changed = True
    return changed


def _spread_for_quality(quality: int) -> float:
    spread = DEFAULT_SHOT_SPREAD.get(int(quality), DEFAULT_SHOT_SPREAD[DEFAULT_QUALITY])
    return max(0.012, float(spread))


def _equipped_blaster(context) -> tuple[str, int] | None:
    best: tuple[str, int] | None = None
    for entry in _vending(_config(context)):
        card_id = str(entry.get("card", ""))
        if not card_id.startswith("paintball-blaster"):
            continue
        if not context.has_equipped_card(card_id):
            continue
        view = context.card_definition(card_id)
        quality = int(view.quality) if view is not None else DEFAULT_QUALITY
        if best is None or quality > best[1]:
            best = (card_id, max(1, quality))
    return best


def _ammo_for(context) -> dict[str, str] | None:
    for entry in _ammo(_config(context)):
        if context.has_equipped_card(entry["card"]):
            return entry
    return None


def _move_tuning(config: dict[str, Any]) -> tuple[float, float]:
    accel = _config_float(config, "move_accel", DEFAULT_MOVE_ACCEL)
    friction = _config_float(config, "move_friction", DEFAULT_MOVE_FRICTION)
    return max(1.0, accel), max(1.0, friction)


def _approach_velocity(
    vx: float,
    vy: float,
    target_x: float,
    target_y: float,
    accel: float,
    friction: float,
    step: float,
) -> tuple[float, float]:
    """Ease the current velocity toward the target velocity.

    Acceleration applies while driving; the stronger friction rate applies
    when braking to a stop, giving peeps weight without feeling sluggish.
    """

    rate = friction if target_x == 0.0 and target_y == 0.0 else accel
    dx, dy = target_x - vx, target_y - vy
    distance = math.hypot(dx, dy)
    limit = rate * step
    if distance <= limit or distance < 1e-9:
        return target_x, target_y
    scale = limit / distance
    return vx + dx * scale, vy + dy * scale


def _fire_projectile(
    context,
    state: dict[str, Any],
    shooter: dict[str, Any],
    *,
    now: datetime,
    direction: tuple[float, float],
    color: str,
    quality: int,
) -> bool:
    config = _config(context)
    cooldown = _config_float(config, "fire_cooldown", DEFAULT_FIRE_COOLDOWN)
    last = _parse_timestamp(shooter.get("last_shot_at"))
    if last is not None and (now - last).total_seconds() < cooldown:
        return False
    if len(state.get("projectiles", [])) >= MAX_PROJECTILES:
        return False
    dx, dy = direction
    length = math.hypot(dx, dy)
    if length < 1e-6:
        stored = shooter.get("aim") or [1.0, 0.0]
        dx, dy = float(stored[0]), float(stored[1])
        length = math.hypot(dx, dy) or 1.0
    angle = math.atan2(dy / length, dx / length) + random.gauss(0.0, _spread_for_quality(quality))
    speed = _config_float(config, "projectile_speed", DEFAULT_PROJECTILE_SPEED)
    boost = _config_float(config, "projectile_boost", DEFAULT_PROJECTILE_BOOST)
    lifetime = _config_float(config, "projectile_lifetime", DEFAULT_PROJECTILE_LIFETIME)
    muzzle = max(speed, speed * boost)
    state["projectile_seq"] = int(state.get("projectile_seq", 0) or 0) + 1
    projectiles = state.get("projectiles")
    if not isinstance(projectiles, list):
        projectiles = []
        state["projectiles"] = projectiles
    projectiles.append(
        {
            "id": state["projectile_seq"],
            "owner": str(shooter.get("id", "")),
            "x": float(shooter.get("x", 50.0)),
            "y": float(shooter.get("y", 50.0)),
            "vx": math.cos(angle) * muzzle,
            "vy": math.sin(angle) * muzzle,
            "ttl": lifetime,
            "color": color,
        }
    )
    shooter["last_shot_at"] = now.isoformat()
    shooter["shots"] = int(shooter.get("shots", 0) or 0) + 1
    scores = _participant_scores(state)
    entry = scores.setdefault(
        str(shooter.get("id", "")),
        {"name": str(shooter.get("name", "") or "Peep"), "hits": 0, "shots": 0, "bot": shooter.get("kind") == BOT},
    )
    entry["bot"] = shooter.get("kind") == BOT
    entry["shots"] = int(entry.get("shots", 0) or 0) + 1
    return True


def _add_splat(state: dict[str, Any], x: float, y: float, color: str) -> None:
    splats = state.get("splats")
    if not isinstance(splats, list):
        splats = []
        state["splats"] = splats
    splats.append(
        {
            "id": f"{int(state.get('projectile_seq', 0) or 0)}:{len(splats)}",
            "x": float(x),
            "y": float(y),
            "color": color,
            "size": round(random.uniform(0.72, 1.12), 3),
            "rotation": round(random.uniform(0.0, math.tau), 3),
        }
    )
    state["splats"] = splats[-MAX_SPLATS:]


def _apply_hit(context, state: dict[str, Any], victim: dict[str, Any], x: float, y: float, color: str, now: datetime) -> None:
    victim["hits_taken"] = int(victim.get("hits_taken", 0) or 0) + 1
    victim["flash_until"] = (now + timedelta(milliseconds=650)).isoformat()
    if victim.get("kind") == USER:
        victim_ref = PeepRef(kind="user", peep_id=None, account_id=str(victim.get("id")))
        try:
            cleanliness = float(victim.get("cleanliness", 100.0)) - 10.0
            maximum = float(victim.get("max_cleanliness", 100.0))
        except (TypeError, ValueError):
            cleanliness, maximum = 90.0, 100.0
        victim["cleanliness"] = max(0.0, cleanliness)
        victim["max_cleanliness"] = maximum
        context.apply_counter("health", -1, target=victim_ref)
        context.apply_counter("cleanliness", -10, target=victim_ref)
        context.apply_decal(
            PAINT_DECAL_ID,
            PAINT_DECAL_KIND,
            count=_paint_decal_count(cleanliness, maximum),
            color=color,
            target=victim_ref,
        )
    _add_splat(state, x, y, color)


def _paint_decal_count(cleanliness: float, max_cleanliness: float) -> int:
    """Return a paint-splat count based on missing Cleanliness."""

    maximum = float(max_cleanliness)
    if maximum <= 0:
        return 1
    missing = min(1.0, max(0.0, (maximum - float(cleanliness)) / maximum))
    if missing >= 0.5:
        return 3
    if missing >= 0.2:
        return 2
    return 1


def _nearest_target(participants: list[dict[str, Any]], bot: dict[str, Any]) -> dict[str, Any] | None:
    targets = [entry for entry in participants if entry.get("id") != bot.get("id")]
    if not targets:
        return None
    humans = [entry for entry in targets if entry.get("kind") == USER]
    if humans and random.random() < 0.75:
        targets = humans
    return min(
        targets,
        key=lambda entry: math.hypot(float(entry.get("x", 0.0)) - float(bot.get("x", 0.0)), float(entry.get("y", 0.0)) - float(bot.get("y", 0.0))),
    )


def _update_bot(
    context,
    state: dict[str, Any],
    bot: dict[str, Any],
    participants: list[dict[str, Any]],
    *,
    now: datetime,
    step: float,
    arena: tuple[float, float],
    obstacles: list[dict[str, Any]],
) -> None:
    config = _config(context)
    bot_speed = _config_float(config, "bot_speed", DEFAULT_BOT_SPEED)
    accel, friction = _move_tuning(config)
    low, high = _config_float_pair(config, "bot_waypoint_seconds", DEFAULT_BOT_WAYPOINT_SECONDS)
    waypoint_until = _parse_timestamp(bot.get("waypoint_until"))
    waypoint = bot.get("waypoint") if isinstance(bot.get("waypoint"), list) else None
    if waypoint is None or waypoint_until is None or now >= waypoint_until:
        waypoint = [random.uniform(8.0, arena[0] - 8.0), random.uniform(8.0, arena[1] - 8.0)]
        bot["waypoint"] = waypoint
        bot["waypoint_until"] = (now + timedelta(seconds=random.uniform(low, high))).isoformat()
    target = _nearest_target(participants, bot)
    if target is not None:
        bot["aim"] = [float(target.get("x", 0.0)) - float(bot.get("x", 0.0)), float(target.get("y", 0.0)) - float(bot.get("y", 0.0))]
    dx = float(waypoint[0]) - float(bot.get("x", 0.0))
    dy = float(waypoint[1]) - float(bot.get("y", 0.0))
    distance = math.hypot(dx, dy)
    if distance > 0.5:
        desired_x, desired_y = dx / distance * bot_speed, dy / distance * bot_speed
    else:
        desired_x, desired_y = 0.0, 0.0
    _move_body(bot, desired_x, desired_y, step=step, arena=arena, obstacles=obstacles, accel=accel, friction=friction)
    bot_config = _bot_config(config)
    next_shot = _parse_timestamp(bot.get("next_shot_at"))
    if target is not None and (next_shot is None or now >= next_shot):
        colors = [entry["color"] for entry in _ammo(config)]
        fired = _fire_projectile(
            context,
            state,
            bot,
            now=now,
            direction=(float(target.get("x", 0.0)) - float(bot.get("x", 0.0)), float(target.get("y", 0.0)) - float(bot.get("y", 0.0))),
            color=random.choice(colors) if colors else "#ff4d6d",
            quality=int(bot_config["quality"]),
        )
        low_shot, high_shot = bot_config["shot_seconds"]
        bot["next_shot_at"] = (now + timedelta(seconds=random.uniform(low_shot, high_shot))).isoformat()
        if fired and isinstance(bot.get("waypoint"), list):
            # Sidestep after firing so bots do not stand still in the open.
            bot["waypoint"] = [random.uniform(8.0, arena[0] - 8.0), random.uniform(8.0, arena[1] - 8.0)]


def _advance_projectiles(
    context,
    state: dict[str, Any],
    *,
    step: float,
    arena: tuple[float, float],
    obstacles: list[dict[str, Any]],
    now: datetime,
) -> None:
    projectiles = state.get("projectiles")
    if not isinstance(projectiles, list):
        return
    participants = state.get("participants") if isinstance(state.get("participants"), dict) else {}
    survivors = []
    radius = DEFAULT_PROJECTILE_RADIUS
    config = _config(context)
    drag = _config_float(config, "projectile_drag", DEFAULT_PROJECTILE_DRAG)
    decay = math.exp(-max(0.0, drag) * step)
    for projectile in projectiles:
        if not isinstance(projectile, dict):
            continue
        vx = float(projectile.get("vx", 0.0)) * decay
        vy = float(projectile.get("vy", 0.0)) * decay
        start_x, start_y = float(projectile.get("x", 0.0)), float(projectile.get("y", 0.0))
        end_x = start_x + vx * step
        end_y = start_y + vy * step
        ttl = float(projectile.get("ttl", 0.0)) - step
        victim = None
        for entry in participants.values():
            if not isinstance(entry, dict) or str(entry.get("id")) == str(projectile.get("owner")):
                continue
            victim_x, victim_y = float(entry.get("x", 0.0)), float(entry.get("y", 0.0))
            dx, dy = end_x - start_x, end_y - start_y
            length_squared = dx * dx + dy * dy
            if length_squared < 1e-9:
                within = math.hypot(start_x - victim_x, start_y - victim_y) <= radius + DEFAULT_PLAYER_RADIUS
            else:
                elapsed = max(0.0, min(1.0, ((victim_x - start_x) * dx + (victim_y - start_y) * dy) / length_squared))
                within = math.hypot(start_x + elapsed * dx - victim_x, start_y + elapsed * dy - victim_y) <= radius + DEFAULT_PLAYER_RADIUS
            if within:
                victim = entry
                end_x, end_y = victim_x, victim_y
                break
        if victim is not None:
            _apply_hit(context, state, victim, end_x, end_y, str(projectile.get("color", "#ff4d6d")), now)
            owner = participants.get(str(projectile.get("owner")))
            if isinstance(owner, dict):
                owner["hits"] = int(owner.get("hits", 0) or 0) + 1
                scores = _participant_scores(state)
                entry = scores.setdefault(str(owner.get("id")), {"name": owner.get("name", "Peep"), "hits": 0, "shots": 0, "bot": owner.get("kind") == BOT})
                entry["hits"] = int(entry.get("hits", 0) or 0) + 1
            continue
        if sweep_hits_obstacle(start_x, start_y, end_x, end_y, radius, obstacles):
            _add_splat(state, end_x, end_y, str(projectile.get("color", "#ff4d6d")))
            continue
        if ttl <= 0 or not (0 <= end_x <= arena[0] and 0 <= end_y <= arena[1]):
            if ttl <= 0:
                _add_splat(state, end_x, end_y, str(projectile.get("color", "#ff4d6d")))
            continue
        projectile["x"], projectile["y"], projectile["vx"], projectile["vy"], projectile["ttl"] = end_x, end_y, vx, vy, ttl
        survivors.append(projectile)
    state["projectiles"] = survivors[-MAX_PROJECTILES:]


def _simulate(context, state: dict[str, Any], now: datetime) -> None:
    last = _parse_timestamp(state.get("last_sim_at")) or now
    elapsed = max(0.0, min(1.0, (now - last).total_seconds()))
    state["last_sim_at"] = now.isoformat()
    if state.get("phase") != "active" or elapsed <= 0:
        return
    config = _config(context)
    arena = _arena(config)
    obstacles = state.get("obstacles") if isinstance(state.get("obstacles"), list) else []
    player_speed = _config_float(config, "player_speed", DEFAULT_PLAYER_SPEED)
    accel, friction = _move_tuning(config)
    remaining = elapsed
    while remaining > 1e-6:
        step = min(0.05, remaining)
        remaining -= step
        participants = [entry for entry in state.get("participants", {}).values() if isinstance(entry, dict)]
        for entry in participants:
            if entry.get("kind") == BOT:
                _update_bot(context, state, entry, participants, now=now, step=step, arena=arena, obstacles=obstacles)
                continue
            move = entry.get("move") if isinstance(entry.get("move"), list) else [0.0, 0.0]
            last_input = _parse_timestamp(entry.get("last_input_at"))
            if last_input is None or (now - last_input).total_seconds() > INPUT_TIMEOUT_SECONDS:
                move = [0.0, 0.0]
            dx, dy = float(move[0]), float(move[1])
            length = math.hypot(dx, dy)
            if length > 1e-6:
                scale = min(1.0, 1.0 / length)
                desired_x, desired_y = dx * scale * player_speed, dy * scale * player_speed
            else:
                desired_x, desired_y = 0.0, 0.0
            _move_body(entry, desired_x, desired_y, step=step, arena=arena, obstacles=obstacles, accel=accel, friction=friction)
        _advance_projectiles(context, state, step=step, arena=arena, obstacles=obstacles, now=now)


def _try_human_fire(context, state: dict[str, Any], participant: dict[str, Any], *, now: datetime) -> bool:
    blaster = _equipped_blaster(context)
    ammo = _ammo_for(context)
    if blaster is None or ammo is None:
        warned_at = _parse_timestamp(participant.get("warned_at"))
        if warned_at is None or (now - warned_at).total_seconds() >= 5:
            participant["warned_at"] = now.isoformat()
            context.feedback("Equip a paint blaster and paintballs to shoot.", "info")
        return False
    participant["color"] = ammo["color"]
    aim = participant.get("aim") if isinstance(participant.get("aim"), list) else [1.0, 0.0]
    fired = _fire_projectile(
        context,
        state,
        participant,
        now=now,
        direction=(float(aim[0]), float(aim[1])),
        color=ammo["color"],
        quality=blaster[1],
    )
    if fired:
        target = PeepRef(kind="user", peep_id=None, account_id=str(participant.get("id", "")))
        context.remove_card(ammo["card"], 1, target=target)
        return True
    return False


def _reset_human(human: dict[str, Any], slot: tuple[float, float]) -> None:
    """Respawn a returning player for the next round."""

    human["x"], human["y"] = slot
    human["move"] = [0.0, 0.0]
    human["aim"] = [1.0, 0.0]
    human["fire"] = False
    human["vx"] = 0.0
    human["vy"] = 0.0
    human["shots"] = 0
    human["hits"] = 0
    human["last_input_at"] = None
    human["warned_at"] = None
    human["flash_until"] = None
    human["waypoint"] = None
    human["waypoint_until"] = None


async def _start_round(context, state: dict[str, Any], now: datetime) -> None:
    config = _config(context)
    duration = _config_int(config, "round_seconds", DEFAULT_ROUND_SECONDS)
    seed = random.SystemRandom().randrange(1, 1_000_000_000)
    width, height = _arena(config)
    state["round"] = int(state.get("round", 0) or 0) + 1
    state["phase"] = "active"
    state["round_started_at"] = now.isoformat()
    state["phase_ends_at"] = (now + timedelta(seconds=duration)).isoformat()
    state["arena"] = {"width": width, "height": height}
    state["arena_seed"] = seed
    state["obstacles"] = _generate_obstacles(seed, config, (width, height))
    room_id = str(context.room.get("id", ""))
    _sync_users(state, context, room_id)
    participants = state.get("participants") if isinstance(state.get("participants"), dict) else {}
    for participant_id in [key for key, entry in participants.items() if isinstance(entry, dict) and entry.get("kind") == BOT]:
        del participants[participant_id]
    humans = [entry for entry in participants.values() if isinstance(entry, dict) and entry.get("kind") == USER]
    for index, human in enumerate(humans):
        _reset_human(human, _free_spawn(state, 200 + index))
    state["participants"] = participants
    state["projectiles"] = []
    state["scores"] = {}
    state["splats"] = []
    state["last_sim_at"] = now.isoformat()
    bot_config = _bot_config(config)
    colors = [entry["color"] for entry in _ammo(config)]
    human_count = sum(1 for entry in state["participants"].values() if isinstance(entry, dict) and entry.get("kind") == USER)
    for index, bot_id in enumerate(bot_config["ids"][: max(0, int(bot_config["target_players"]) - human_count)]):
        slot = _free_spawn(state, 100 + index)
        bot = _ensure_participant(
            state,
            participant_id=str(bot_id),
            name=str(bot_id.replace("paintbot-", "").title() or bot_id),
            kind=BOT,
            x=slot[0],
            y=slot[1],
            color=random.choice(colors) if colors else "#ff4d6d",
            sprite=str(bot_id),
            now=now,
        )
        low, high = bot_config["shot_seconds"]
        bot["next_shot_at"] = (now + timedelta(seconds=random.uniform(low, high))).isoformat()


def _finish_round(context, state: dict[str, Any], now: datetime) -> None:
    config = _config(context)
    ranking = _ranking(state)
    top = ranking[:3]
    state["last_round"] = {"round": int(state.get("round", 0) or 0), "top": top}
    records = state.get("records")
    if not isinstance(records, dict):
        records = {"games": 0, "best_hits": 0, "best_name": ""}
        state["records"] = records
    records["games"] = int(records.get("games", 0) or 0) + 1
    if top and int(top[0]["hits"]) > int(records.get("best_hits", 0) or 0):
        records["best_hits"] = int(top[0]["hits"])
        records["best_name"] = str(top[0]["name"])
    rewards = _rewards(config)
    game_key = str(state.get("round_started_at", "") or now.isoformat())
    for index, entry in enumerate(top):
        amount = rewards[index] if index < len(rewards) else 0
        if not amount or entry.get("bot"):
            continue
        context.grant(
            bops=amount,
            ledger_key=f"paintball:{game_key}:{entry['id']}",
            target=PeepRef(kind="user", peep_id=None, account_id=entry["id"]),
        )
    if top:
        params: dict[str, object] = {}
        for index, key in enumerate(("first", "second", "third")):
            if index >= len(top):
                continue
            token = "$peep" if top[index].get("bot") else "$user"
            params[key] = f"{token}:{top[index]['id']}"
            params[f"{key}_name"] = top[index]["name"]
            params[f"{key}_hits"] = top[index]["hits"]
        context.cutscene(CUTSCENE_ID, audience="room", params=params)


async def _advance(context, state: dict[str, Any], now: datetime) -> None:
    """Apply at most one phase transition for the elapsed wall-clock time."""

    end = _parse_timestamp(state.get("phase_ends_at"))
    if end is None or now < end:
        return
    config = _config(context)
    if state.get("phase") == "active":
        _simulate(context, state, end)
        _finish_round(context, state, now)
        intermission = _config_int(config, "intermission_seconds", DEFAULT_INTERMISSION_SECONDS)
        state["phase"] = "intermission"
        state["phase_ends_at"] = (now + timedelta(seconds=intermission)).isoformat()
        state["projectiles"] = []
    else:
        await _start_round(context, state, now)


def _parse_input(action: str) -> tuple[float, float, float, float, bool] | None:
    if not action.startswith("input:"):
        return None
    parts = action.split(":")[1:]
    if len(parts) != 5:
        return None
    try:
        move_x, move_y, aim_x, aim_y = (max(-1.0, min(1.0, float(parts[index]) / 1000.0)) for index in range(4))
        fire = parts[4].strip() == "1"
    except (TypeError, ValueError):
        return None
    if math.hypot(aim_x, aim_y) < 1e-6:
        aim_x, aim_y = 0.0, 0.0
    return move_x, move_y, aim_x, aim_y, fire


async def _run_room_tick(context, state: dict[str, Any], *, force_full: bool = False) -> bool:
    """Advance one room tick: phases, roster, simulation, then one publish."""

    room_id = str(context.room.get("id", ""))
    if not context.activity_users(room_id, "paintball"):
        return False
    await _advance(context, state, context.now)
    if state.get("phase") == "active":
        _sync_users(state, context, room_id)
        _simulate(context, state, context.now)
    return _publish(context, state, force_full=force_full)


async def on_enter(context, event):
    """Initialize or refresh the arena when someone walks in."""

    del event
    await _run_room_tick(context, _state_for(context), force_full=True)


async def on_tick(context, event):
    """Advance the round clock, simulate play, and publish live state."""

    del event
    await _run_room_tick(context, _state_for(context))


async def on_activity_tick(context, event):
    """Advance the arena at the realtime stream rate (memory only)."""

    del event
    await _run_room_tick(context, _state_for(context))


async def on_quick_action(context, event):
    """Handle movement/aim input, vending, joins, and the staff round reset."""

    action = str(event.action or "").strip()
    room_id = str(context.room.get("id", ""))
    if action == "reset":
        if not any(context.has_power(power) for power in _reset_powers(context)):
            context.feedback("Only an admin, moderator, or game master can reset the arena.", "error")
            return
        state = _new_state(context)
        context.state[STATE_KEY] = state
        _publish(context, state, force_full=True)
        context.feedback("Paintball arena reset. Next round starts shortly.", "success")
        return
    if action == "join":
        await _run_room_tick(context, _state_for(context), force_full=True)
        return
    if not action.startswith("buy:"):
        parsed = _parse_input(action)
        if parsed is None:
            return
        actor_id = getattr(context.actor, "account_id", None)
        if not actor_id:
            return
        state = _state_for(context)
        await _advance(context, state, context.now)
        if state.get("phase") != "active":
            return
        roster_changed = _sync_users(state, context, room_id)
        participant = state.get("participants", {}).get(actor_id)
        if not isinstance(participant, dict):
            return
        move_x, move_y, aim_x, aim_y, fire = parsed
        participant["move"] = [move_x, move_y]
        participant["last_input_at"] = context.now.isoformat()
        if math.hypot(aim_x, aim_y) > 1e-6:
            participant["aim"] = [aim_x, aim_y]
        participant["fire"] = fire
        fired = _try_human_fire(context, state, participant, now=context.now) if fire else False
        if fired or roster_changed:
            _publish(context, state)
        return
    state = _state_for(context)
    card_id = action[4:]
    entry = next((item for item in _vending(_config(context)) if item["card"] == card_id), None)
    if entry is None:
        context.feedback("That vending slot is empty.", "error")
        return
    if card_id.startswith("paintball-blaster") and context.has_card(card_id):
        context.feedback("You already own that blaster.", "info")
        return
    cost = int(entry.get("bops", 0) or 0)
    if context.bops < cost:
        context.feedback(f"You need {cost - context.bops} more Bops.", "error")
        return
    context.purchase_card(
        card_id,
        quantity=int(entry.get("quantity", 1) or 1),
        bops=cost,
    )
