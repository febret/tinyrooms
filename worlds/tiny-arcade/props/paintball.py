"""World-authored Paintball Arena rules for The Arcade.

The server core supplies sprite positions, room broadcasts, and generic
counter/purchase intents. Everything below -- the round clock, the raycast, hit
probability, paint splats, and podium rewards -- belongs to this world script.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import math
import random
from typing import Any

from server.behaviors.events import PeepRef


STATE_KEY = "paintball"
STATE_VERSION = 1

DEFAULT_ROUND_SECONDS = 120
DEFAULT_INTERMISSION_SECONDS = 30
DEFAULT_REWARDS = (10, 5, 1)
DEFAULT_MAX_RANGE = 11.0
DEFAULT_PEEP_RADIUS = 0.42
DEFAULT_QUALITY = 1
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
DEFAULT_BOT_HOME = "bot-hangar"
DEFAULT_TARGET_PLAYERS = 4
DEFAULT_BOT_DISMISS_SECONDS = 5
DEFAULT_BOT_DEXTERITY = 2
DEFAULT_BOT_QUALITY = 2
DEFAULT_BOT_SHOT_SECONDS = (5.5, 9.5)
TIME_WARNINGS = (60, 30, 10)
MAX_SHOTS = 12
MAX_SPLATS = 80
X_PER_PERCENT = 0.105
Z_PER_PERCENT = 0.085
GUN_TAG = "paintgun"
PAINT_DECAL_ID = "paint"
PAINT_DECAL_KIND = "paint"
CUTSCENE_ID = "paintball-podium"
HUMAN = "user"
BOT = "bot"


def _config(context) -> dict[str, Any]:
    room = getattr(context, "room", None)
    game = room.get("game") if isinstance(room, dict) else None
    config = game.get("config") if isinstance(game, dict) else None
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
        "home_room": str(raw.get("home_room", DEFAULT_BOT_HOME) or DEFAULT_BOT_HOME),
        "target_players": max(1, int(raw.get("target_players", DEFAULT_TARGET_PLAYERS) or DEFAULT_TARGET_PLAYERS)),
        "dismiss_seconds": max(0, int(raw.get("dismiss_seconds", DEFAULT_BOT_DISMISS_SECONDS) or 0)),
        "dexterity": int(raw.get("dexterity", DEFAULT_BOT_DEXTERITY) or DEFAULT_BOT_DEXTERITY),
        "quality": int(raw.get("quality", DEFAULT_BOT_QUALITY) or DEFAULT_BOT_QUALITY),
        "shot_seconds": (max(0.2, min(low, high)), max(low, high)),
    }


def _reset_powers(context) -> tuple[str, ...]:
    room = getattr(context, "room", None)
    game = room.get("game") if isinstance(room, dict) else None
    values = game.get("reset_powers") if isinstance(game, dict) else None
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


def _world_point(position: object) -> tuple[float, float]:
    values = list(position) if isinstance(position, (list, tuple)) else []
    x = float(values[0]) if values else 50.0
    y = float(values[1]) if len(values) > 1 else 50.0
    return (x - 50.0) * X_PER_PERCENT, (y - 50.0) * Z_PER_PERCENT


def _percent_point(x: float, z: float) -> list[float]:
    return [x / X_PER_PERCENT + 50.0, z / Z_PER_PERCENT + 50.0]


def _new_state(context) -> dict[str, Any]:
    config = _config(context)
    intermission = _config_int(config, "intermission_seconds", DEFAULT_INTERMISSION_SECONDS)
    now = context.now
    return {
        "version": STATE_VERSION,
        "phase": "intermission",
        "round": 0,
        "phase_ends_at": (now + timedelta(seconds=intermission)).isoformat(),
        "round_started_at": "",
        "scores": {},
        "shots": [],
        "splats": [],
        "shot_seq": 0,
        "last_round": None,
        "bots": [],
        "bot_dismiss_at": None,
        "bot_commentary_at": None,
        "bot_commented": False,
        "announced": [],
        "standings": [],
        "standings_at": None,
        "records": {"games": 0, "best_hits": 0, "best_name": ""},
    }


def _load_state(context) -> dict[str, Any] | None:
    raw = context.state.get(STATE_KEY)
    if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
        return None
    if raw.get("phase") not in {"active", "intermission"}:
        return None
    if not isinstance(raw.get("scores"), dict):
        return None
    raw.setdefault("bots", [])
    raw.setdefault("bot_dismiss_at", None)
    raw.setdefault("bot_commentary_at", None)
    raw.setdefault("bot_commented", False)
    raw.setdefault("announced", [])
    raw.setdefault("standings", [])
    raw.setdefault("standings_at", None)
    raw.setdefault("records", {"games": 0, "best_hits": 0, "best_name": ""})
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


def _ranking(state: dict[str, Any], *, include_bots: bool = True) -> list[dict[str, Any]]:
    scores = state.get("scores") if isinstance(state.get("scores"), dict) else {}
    rows: list[dict[str, Any]] = []
    for account_id, entry in scores.items():
        if not isinstance(entry, dict):
            continue
        is_bot = bool(entry.get("bot"))
        if is_bot and not include_bots:
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
                "bot": is_bot,
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


def _public(state: dict[str, Any], now: datetime) -> dict[str, Any]:
    bots = state.get("bots") if isinstance(state.get("bots"), list) else []
    return {
        "phase": str(state.get("phase", "intermission")),
        "round": int(state.get("round", 0) or 0),
        "phase_ends_at": state.get("phase_ends_at"),
        "seconds_left": _seconds_left(state, now),
        "status": _status(state, now),
        "room_description": _room_description(state, now),
        "scoreboard": _ranking(state),
        "shots": list(state.get("shots", []))[-MAX_SHOTS:],
        "splats": list(state.get("splats", []))[-MAX_SPLATS:],
        "last_round": state.get("last_round"),
        "bot_count": len(bots),
        "records": state.get("records"),
    }


def _publish(context, state: dict[str, Any]) -> None:
    context.state[STATE_KEY] = state
    context.set_game_state(_public(state, context.now))


async def _start_round(context, state: dict[str, Any], now: datetime) -> None:
    config = _config(context)
    duration = _config_int(config, "round_seconds", DEFAULT_ROUND_SECONDS)
    _dismiss_bots(context, state)
    state["round"] = int(state.get("round", 0) or 0) + 1
    state["phase"] = "active"
    state["round_started_at"] = now.isoformat()
    state["phase_ends_at"] = (now + timedelta(seconds=duration)).isoformat()
    state["scores"] = {}
    state["shots"] = []
    state["splats"] = []
    state["announced"] = []
    state["standings"] = []
    state["standings_at"] = None
    await _spawn_bots(context, state, now)
    context.room_feedback(
        f"Round {state['round']} begins — {_clock_label(duration)} on the clock!",
        "success",
    )
    bot_count = len(state.get("bots") or [])
    if bot_count:
        context.room_feedback(f"{bot_count} paintbot{'s' if bot_count != 1 else ''} join the arena.", "info")


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
    if state.get("bots"):
        dismiss = _config_int(_bot_config(config), "dismiss_seconds", DEFAULT_BOT_DISMISS_SECONDS)
        commentary_at = now + timedelta(seconds=8)
        state["bot_commentary_at"] = commentary_at.isoformat()
        state["bot_dismiss_at"] = (commentary_at + timedelta(seconds=dismiss)).isoformat()
        state["bot_commented"] = False
    if top:
        winner = top[0]
        context.room_feedback(
            f"Round over! {winner['name']} leads with {winner['hits']} hit(s).",
            "info",
        )
        params: dict[str, object] = {}
        for index, key in enumerate(("first", "second", "third")):
            if index >= len(top):
                continue
            token = "$peep" if top[index].get("bot") else "$user"
            params[key] = f"{token}:{top[index]['id']}"
            params[f"{key}_name"] = top[index]["name"]
            params[f"{key}_hits"] = top[index]["hits"]
        context.cutscene(CUTSCENE_ID, audience="room", params=params)
    else:
        context.room_feedback("Round over — nobody landed a hit.", "info")
    intermission = _config_int(config, "intermission_seconds", DEFAULT_INTERMISSION_SECONDS)
    context.room_feedback(f"Next round in {_clock_label(intermission)}.", "info")


async def _advance(context, state: dict[str, Any], now: datetime) -> None:
    """Apply at most one phase transition for the elapsed wall-clock time."""

    _commentary_due(context, state, now)
    _dismiss_due_bots(context, state, now)
    end = _parse_timestamp(state.get("phase_ends_at"))
    if end is None or now < end:
        _announce_time(context, state, now)
        return
    config = _config(context)
    if state.get("phase") == "active":
        _finish_round(context, state, now)
        intermission = _config_int(config, "intermission_seconds", DEFAULT_INTERMISSION_SECONDS)
        state["phase"] = "intermission"
        state["phase_ends_at"] = (now + timedelta(seconds=intermission)).isoformat()
        state["shots"] = []
        state["announced"] = []
    else:
        await _start_round(context, state, now)


def _raycast(
    shooter_position: object,
    aim_position: object,
    users: list[dict[str, object]],
    *,
    max_range: float,
    radius: float,
) -> tuple[dict[str, object] | None, list[float], float]:
    """Return the first peep the aim line intersects, the endpoint, and distance."""

    sx, sz = _world_point(shooter_position)
    ax, az = _world_point(aim_position)
    dx, dz = ax - sx, az - sz
    length = math.hypot(dx, dz)
    if length < 1e-6:
        return None, _percent_point(sx, sz), 0.0
    ux, uz = dx / length, dz / length
    best: tuple[float, dict[str, object], float, float] | None = None
    for user in users:
        position = user.get("position")
        if not isinstance(position, (list, tuple)):
            continue
        px, pz = _world_point(position)
        rx, rz = px - sx, pz - sz
        along = rx * ux + rz * uz
        if along <= 0 or along > max_range:
            continue
        perpendicular = abs(rx * uz - rz * ux)
        if perpendicular > radius:
            continue
        if best is None or along < best[0]:
            best = (along, user, px, pz)
    if best is None:
        endpoint = (sx + ux * max_range, sz + uz * max_range)
        return None, _percent_point(*endpoint), max_range
    return best[1], _percent_point(best[2], best[3]), best[0]


def _hit_probability(distance: float, dexterity: int, quality: int, max_range: float) -> float:
    ratio = min(1.0, max(0.0, distance / max_range))
    accuracy = 0.42 + 0.05 * int(dexterity) + 0.07 * int(quality) - 0.28 * ratio
    return max(0.12, min(0.95, accuracy))


def _roll() -> float:
    """Return the shot roll; tests patch this for determinism."""

    return random.random()


def _ammo_for(context) -> dict[str, str] | None:
    for entry in _ammo(_config(context)):
        if context.has_equipped_card(entry["card"]):
            return entry
    return None


def _bot_participants(context, state: dict[str, Any]) -> list[dict[str, object]]:
    """Return active bot ids/names/positions from the live NPC sprite map."""

    active = state.get("bots") if isinstance(state.get("bots"), list) else []
    if not active:
        return []
    by_id = {str(peep.get("id")): peep for peep in context.peeps_in(str(context.room.get("id", "")))}
    participants: list[dict[str, object]] = []
    for bot in active:
        if not isinstance(bot, dict):
            continue
        peep = by_id.get(str(bot.get("id", "")))
        if peep is None:
            continue
        participants.append(
            {
                "id": str(bot.get("id", "")),
                "name": str(bot.get("name", "") or bot.get("id", "Paintbot")),
                "position": peep.get("position"),
                "bot": True,
            }
        )
    return participants


def _dismiss_bots(context, state: dict[str, Any]) -> None:
    bots = state.get("bots") if isinstance(state.get("bots"), list) else []
    home = str(_bot_config(_config(context))["home_room"])
    for bot in bots:
        if isinstance(bot, dict) and bot.get("id"):
            context.move_peep(str(bot["id"]), home)
    state["bots"] = []
    state["bot_dismiss_at"] = None
    state["bot_commentary_at"] = None
    state["bot_commented"] = False


def _dismiss_due_bots(context, state: dict[str, Any], now: datetime) -> None:
    if not state.get("bots"):
        return
    dismiss_at = _parse_timestamp(state.get("bot_dismiss_at"))
    if dismiss_at is not None and now >= dismiss_at:
        _dismiss_bots(context, state)


def _commentary_due(context, state: dict[str, Any], now: datetime) -> None:
    if not state.get("bots") or state.get("bot_commented"):
        return
    commentary_at = _parse_timestamp(state.get("bot_commentary_at"))
    if commentary_at is not None and now >= commentary_at:
        _bot_commentary(context, state)
        state["bot_commented"] = True


async def _spawn_bots(context, state: dict[str, Any], now: datetime) -> None:
    """Top the round up to the configured player count with hangar paintbots."""

    if state.get("bots"):
        _dismiss_bots(context, state)
    config = _config(context)
    bot_config = _bot_config(config)
    room_id = str(context.room.get("id", ""))
    users = await context.room_users(room_id)
    needed = max(0, int(bot_config["target_players"]) - len(users))
    if needed <= 0:
        return
    allowed = set(bot_config["ids"])
    available = [
        peep
        for peep in context.peeps_in(str(bot_config["home_room"]))
        if str(peep.get("id", "")) in allowed
    ]
    state["bots"] = []
    low, high = bot_config["shot_seconds"]
    for peep in available[:needed]:
        bot_id = str(peep.get("id", ""))
        if not bot_id:
            continue
        context.move_peep(bot_id, room_id)
        state["bots"].append(
            {
                "id": bot_id,
                "name": str(peep.get("label", "") or bot_id),
                "next_shot_at": (now + timedelta(seconds=random.uniform(low, high))).isoformat(),
            }
        )
    state["bot_dismiss_at"] = None
    state["bot_commentary_at"] = None
    state["bot_commented"] = False


def _bot_commentary(context, state: dict[str, Any]) -> None:
    bots = state.get("bots") if isinstance(state.get("bots"), list) else []
    if not bots:
        return
    ranking = _ranking(state)
    humans = [row for row in ranking if not row["bot"]]
    robots = [row for row in ranking if row["bot"]]
    top_human = humans[0] if humans else None
    top_bot = robots[0] if robots else None
    if top_human is None:
        base = "That round had more paint on the floor than on the players."
    elif top_bot is not None and top_bot["hits"] > top_human["hits"]:
        base = f"{top_human['name']} came closest, but {top_bot['name']} owns this arena."
    elif top_human["hits"] >= 5:
        base = f"{top_human['name']} landed {top_human['hits']} hits. Check that blaster for magnets."
    else:
        base = f"{top_human['name']} takes the humans' crown with {top_human['hits']} hit(s)."
    extra = (
        "My chassis is still dripping.",
        "Same time next round?",
        "I am definitely telling the vending machine about this.",
        "Cleanliness is optional. Accuracy is not.",
    )
    for index, bot in enumerate(bots):
        if not isinstance(bot, dict) or not bot.get("id"):
            continue
        line = base if index == 0 else random.choice(extra)
        context.peep_say(str(bot["id"]), line, "expression")


async def _run_bots(context, state: dict[str, Any], now: datetime) -> None:
    """Move active paintbots a little and let them take server-authoritative shots."""

    bots = _bot_participants(context, state)
    if not bots:
        return
    bot_config = _bot_config(_config(context))
    room_id = str(context.room.get("id", ""))
    users = await context.room_users(room_id)
    humans = [
        {
            "id": str(user.get("id", "")),
            "name": str(user.get("name", "") or "Peep"),
            "position": user.get("position"),
            "bot": False,
        }
        for user in users
        if isinstance(user.get("position"), (list, tuple))
    ]
    participants = [*humans, *bots]
    if len(participants) < 2:
        return
    config = _config(context)
    max_range = _config_float(config, "max_range", DEFAULT_MAX_RANGE)
    radius = _config_float(config, "peep_radius", DEFAULT_PEEP_RADIUS)
    colors = [entry["color"] for entry in _ammo(config)]
    scores = state.get("scores")
    if not isinstance(scores, dict):
        scores = {}
        state["scores"] = scores
    active_bots = state.get("bots") if isinstance(state.get("bots"), list) else []
    by_id = {str(bot.get("id")): bot for bot in active_bots if isinstance(bot, dict)}
    for bot in bots:
        if random.random() < 0.18:
            context.move_peep_sprite(str(bot["id"]), random=True)
        record = by_id.get(str(bot["id"]))
        next_shot = _parse_timestamp(record.get("next_shot_at")) if record else None
        if next_shot is not None and now < next_shot:
            continue
        targets = [entry for entry in participants if entry["id"] != bot["id"]]
        if not targets:
            continue
        human_targets = [entry for entry in targets if not entry["bot"]]
        target = random.choice(human_targets) if human_targets and random.random() < 0.75 else random.choice(targets)
        others = [entry for entry in participants if entry["id"] != bot["id"]]
        victim, impact, distance = _raycast(
            bot.get("position"),
            target.get("position"),
            others,
            max_range=max_range,
            radius=radius,
        )
        hit = victim is not None and _roll() < _hit_probability(
            distance,
            int(bot_config["dexterity"]),
            int(bot_config["quality"]),
            max_range,
        )
        _record_shot(
            context,
            state,
            shooter=bot,
            target=target,
            from_position=list(bot.get("position") or [50, 50]),
            to_position=list(target.get("position") or [50, 50]),
            impact_position=impact,
            color=random.choice(colors) if colors else "#ff4d6d",
            hit=hit,
            victim=victim if hit else None,
            distance=distance,
            max_range=max_range,
        )
        _add_splat(context, state, impact, str(state["shots"][-1]["color"]))
        entry = scores.setdefault(
            str(bot["id"]),
            {"name": bot.get("name", "Paintbot"), "hits": 0, "shots": 0, "bot": True},
        )
        entry["bot"] = True
        entry["shots"] = int(entry.get("shots", 0) or 0) + 1
        if hit and victim is not None:
            entry["hits"] = int(entry.get("hits", 0) or 0) + 1
            if not victim.get("bot"):
                victim_ref = PeepRef(kind="user", peep_id=None, account_id=str(victim.get("id")))
                context.apply_counter("health", -1, target=victim_ref)
                context.apply_counter("cleanliness", -10, target=victim_ref)
                context.apply_decal(
                    PAINT_DECAL_ID,
                    PAINT_DECAL_KIND,
                    count=_paint_decal_count(
                        float(victim.get("cleanliness", 100) or 0) - 10,
                        float(victim.get("max_cleanliness", 100) or 100),
                    ),
                    color=random.choice(colors) if colors else "#ff4d6d",
                    target=victim_ref,
                )
        if record is not None:
            low, high = bot_config["shot_seconds"]
            record["next_shot_at"] = (now + timedelta(seconds=random.uniform(low, high))).isoformat()


def _announce_standings(context, state: dict[str, Any], now: datetime) -> None:
    """Toast the top three when their order or hit counts change."""

    ranking = _ranking(state)
    top = ranking[:3]
    signature = [[row["id"], int(row["hits"])] for row in top]
    if signature == state.get("standings"):
        return
    last = _parse_timestamp(state.get("standings_at"))
    if last is not None and (now - last).total_seconds() < 4:
        return
    state["standings"] = signature
    state["standings_at"] = now.isoformat()
    if not top:
        return
    parts = [f"{index + 1}. {row['name']} ({row['hits']})" for index, row in enumerate(top)]
    context.room_feedback("Top 3: " + " | ".join(parts), "info")


def _announce_time(context, state: dict[str, Any], now: datetime) -> None:
    if state.get("phase") != "active":
        return
    announced = state.get("announced")
    if not isinstance(announced, list):
        announced = []
        state["announced"] = announced
    left = _seconds_left(state, now)
    for threshold in TIME_WARNINGS:
        if left <= threshold and threshold not in announced:
            announced.append(threshold)
            context.room_feedback(
                f"{_clock_label(left)} left in round {int(state.get('round', 0) or 0)}!",
                "info",
            )


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


def _record_shot(
    context,
    state: dict[str, Any],
    *,
    shooter: dict[str, object],
    target: dict[str, object],
    from_position: list[float],
    to_position: list[float],
    impact_position: list[float],
    color: str,
    hit: bool,
    victim: dict[str, object] | None,
    distance: float,
    max_range: float,
) -> None:
    state["shot_seq"] = int(state.get("shot_seq", 0) or 0) + 1
    shot = {
        "id": state["shot_seq"],
        "round": int(state.get("round", 0) or 0),
        "shooter_id": shooter.get("id"),
        "shooter_name": shooter.get("name"),
        "target_id": target.get("id"),
        "target_name": target.get("name"),
        "from": list(from_position),
        "to": list(to_position),
        "impact": list(impact_position),
        "color": color,
        "hit": bool(hit),
        "victim_id": victim.get("id") if victim else None,
        "victim_name": victim.get("name") if victim else None,
        "flight_ms": int(220 + 520 * min(1.0, max(0.0, distance / max_range))),
        "at": context.now.isoformat(),
    }
    shots = list(state.get("shots", []))
    shots.append(shot)
    state["shots"] = shots[-MAX_SHOTS:]


def _add_splat(context, state: dict[str, Any], position: list[float], color: str) -> None:
    splats = list(state.get("splats", []))
    splats.append(
        {
            "id": f"{state.get('shot_seq', 0)}:{len(splats)}",
            "x": float(position[0]),
            "y": float(position[1]),
            "color": color,
            "size": round(random.uniform(0.72, 1.12), 3),
            "rotation": round(random.uniform(0.0, math.tau), 3),
        }
    )
    state["splats"] = splats[-MAX_SPLATS:]


async def on_enter(context, event):
    """Initialize or refresh the arena when someone walks in."""

    del event
    state = _state_for(context)
    await _advance(context, state, context.now)
    if state.get("phase") == "active":
        context.feedback(
            f"Round {int(state.get('round', 0) or 0)} is live — "
            f"{_clock_label(_seconds_left(state, context.now))} left.",
            "info",
        )
    else:
        context.feedback(
            f"Next paintball round in {_clock_label(_seconds_left(state, context.now))}.",
            "info",
        )
    _publish(context, state)


async def on_tick(context, event):
    """Advance the round clock, run paintbots, and publish live standings."""

    del event
    state = _state_for(context)
    await _advance(context, state, context.now)
    if state.get("phase") == "active":
        await _run_bots(context, state, context.now)
        _announce_standings(context, state, context.now)
    _publish(context, state)


async def on_card_play(context, event):
    """Resolve a paintgun used on another user with a server-side raycast."""

    card = context.card
    if card is None or GUN_TAG not in card.tags:
        return
    target = event.target
    target_kind = getattr(target, "kind", "")
    target_id = getattr(target, "account_id", None) or getattr(target, "peep_id", None)
    shooter_id = getattr(context.actor, "account_id", None)
    if target_kind not in {"user", "npc"} or not target_id or target_id == shooter_id:
        context.feedback("Use your blaster on another peep.", "error")
        return
    state = _state_for(context)
    now = context.now
    await _advance(context, state, now)
    if state.get("phase") != "active":
        context.feedback("Wait for the next round to start shooting.", "info")
        return
    config = _config(context)
    max_range = _config_float(config, "max_range", DEFAULT_MAX_RANGE)
    radius = _config_float(config, "peep_radius", DEFAULT_PEEP_RADIUS)
    quality = int(card.quality or DEFAULT_QUALITY)
    room_id = event.room_id or ""
    users = await context.room_users(room_id)
    bots = _bot_participants(context, state)
    shooter = next((user for user in users if user.get("id") == shooter_id), None)
    aim = next((user for user in users if user.get("id") == target_id), None)
    if aim is None:
        aim = next((bot for bot in bots if bot.get("id") == target_id), None)
    if target_kind == "npc" and aim is None:
        context.feedback("That peep is not in this round.", "error")
        return
    if shooter is None or aim is None:
        context.feedback("That peep is no longer in the arena.", "error")
        return
    ammo = _ammo_for(context)
    if ammo is None:
        context.feedback("Equip a set of paintballs first.", "error")
        return
    shooter_position = shooter.get("position")
    aim_position = aim.get("position")
    if not isinstance(shooter_position, (list, tuple)) or not isinstance(aim_position, (list, tuple)):
        context.feedback("Hold still — the arena is still placing peeps.", "info")
        return
    others = [entry for entry in [*users, *bots] if entry.get("id") != shooter_id]
    others = [entry for entry in others if isinstance(entry.get("position"), (list, tuple))]
    victim, impact, distance = _raycast(
        shooter_position,
        aim_position,
        others,
        max_range=max_range,
        radius=radius,
    )
    dexterity = int(shooter.get("dexterity", 1) or 0)
    hit = victim is not None and _roll() < _hit_probability(distance, dexterity, quality, max_range)

    _record_shot(
        context,
        state,
        shooter=shooter,
        target=aim,
        from_position=list(shooter_position),
        to_position=list(aim_position),
        impact_position=impact,
        color=ammo["color"],
        hit=hit,
        victim=victim if hit else None,
        distance=distance,
        max_range=max_range,
    )
    context.remove_card(ammo["card"], 1)

    scores = state.get("scores")
    if not isinstance(scores, dict):
        scores = {}
        state["scores"] = scores
    entry = scores.setdefault(
        shooter_id,
        {"name": shooter.get("name", "Peep"), "hits": 0, "shots": 0},
    )
    entry["shots"] = int(entry.get("shots", 0) or 0) + 1

    if hit and victim is not None:
        entry["hits"] = int(entry.get("hits", 0) or 0) + 1
        if not victim.get("bot"):
            victim_ref = PeepRef(kind="user", peep_id=None, account_id=str(victim.get("id")))
            context.apply_counter("health", -1, target=victim_ref)
            context.apply_counter("cleanliness", -10, target=victim_ref)
            context.apply_decal(
                PAINT_DECAL_ID,
                PAINT_DECAL_KIND,
                count=_paint_decal_count(
                    float(victim.get("cleanliness", 100) or 0) - 10,
                    float(victim.get("max_cleanliness", 100) or 100),
                ),
                color=ammo["color"],
                target=victim_ref,
            )
        _add_splat(context, state, impact, ammo["color"])
        context.feedback(f"You splatted {victim.get('name', 'a peep')}!", "success")
    else:
        _add_splat(context, state, impact, ammo["color"])
        context.feedback("Your paintball missed.", "info")
    _announce_standings(context, state, now)
    _publish(context, state)


def on_quick_action(context, event):
    """Handle vending purchases and the staff round reset."""

    action = str(event.action or "").strip()
    if action == "reset":
        if not any(context.has_power(power) for power in _reset_powers(context)):
            context.feedback("Only an admin, moderator, or game master can reset the arena.", "error")
            return
        current = _state_for(context)
        _dismiss_bots(context, current)
        state = _new_state(context)
        context.state[STATE_KEY] = state
        _publish(context, state)
        context.feedback("Paintball arena reset. Next round starts shortly.", "success")
        context.room_feedback("Paintball arena reset. Next round starts shortly.", "info")
        return
    if not action.startswith("buy:"):
        return
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
    context.feedback(f"Purchased {card_id.replace('-', ' ')}.", "success")
