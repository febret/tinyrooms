"""Persistence and lifecycle for Hacker Collective runs."""

from __future__ import annotations

import json
import logging
import random
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mods.tinytown.catalog import TRAITS_BY_ID
from mods.tinytown.hacker_engine import (
    CENTRAL_BOPS_MAX,
    CENTRAL_BOPS_MIN,
    CENTRAL_KUDOS,
    CENTRAL_PROPS,
    DEADLINE_SECONDS,
    FATIGUE_PER_NODE,
    NODE_BOPS_MAX,
    NODE_BOPS_MIN,
    VIBE_GATE,
    VIBE_PER_FLOOR,
    banter_pool,
    challenge_for,
    fit_for,
    payout_bops,
    score_result,
    screens_for,
    tip_pack,
)
from mods.tinytown.hacker_library import (
    CorpDefinition,
    HackerLibrary,
    load_hacker_library,
)
from mods.tinytown.hacker_map import available_ids, central_available, generate_map
from mods.tinytown.hacker_problems import (
    build_node_screens,
    build_screen,
    verify_screen,
)
from mods.tinytown.roommate_dialog import condition_label
from server.content.lighting import (
    DAY_NIGHT_CYCLE_SECONDS,
    cycle_index,
    cycle_phase,
    cycle_remaining,
    phase_to_environment,
)
from server.security import utc_now
from server.services.vibes import describe_vibe

MOD_ROOT = Path(__file__).resolve().parent
MAX_HELPERS = 1
CENTRAL_NODE = "central"
LOGGER = logging.getLogger("tinyrooms.mod.tinytown")

ACTIVE = "active"
COMPLETED = "completed"
ABANDONED = "abandoned"
EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class RunRow:
    """One persisted hack run."""

    run_id: str
    account_id: str
    cycle_key: str
    corp_id: str
    floor: int
    helper_id: str
    status: str
    state_json: str
    bops: int
    deadline_at: float
    created_at: str
    updated_at: str


def _row_to_run(row: sqlite3.Row) -> RunRow:
    return RunRow(
        run_id=str(row["run_id"]),
        account_id=str(row["account_id"]),
        cycle_key=str(row["cycle_key"]),
        corp_id=str(row["corp_id"]),
        floor=int(row["floor"]),
        helper_id=str(row["helper_id"] or ""),
        status=str(row["status"]),
        state_json=str(row["state_json"]),
        bops=int(row["bops"]),
        deadline_at=float(row["deadline_at"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class HackerRuns:
    """Own the megacorp board and every node, screen, and reward in a hack."""

    def __init__(self, service: object) -> None:
        self.service = service
        self.runtime = service.runtime
        self.hub = self.runtime.hub
        self.profiles = self.runtime.profiles
        self.stats = self.runtime.stats
        self.progression = self.runtime.progression
        self.npcs = service.npcs
        self.vibes = getattr(self.npcs, "vibes", None)
        self._library: HackerLibrary | None = None
        self._clock = time.time

    @property
    def available(self) -> bool:
        return bool(getattr(self.service, "available", False))

    @property
    def library(self) -> HackerLibrary:
        if self._library is None:
            self._library = load_hacker_library()
        return self._library

    # -- setup ---------------------------------------------------------------

    def prepare(self) -> None:
        if not self.available:
            return
        self._ensure_schema()
        _ = self.library

    def _ensure_schema(self) -> None:
        with self.hub.transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS world.tinytown_hacker_runs (
                    run_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    cycle_key TEXT NOT NULL,
                    corp_id TEXT NOT NULL,
                    floor INTEGER NOT NULL,
                    helper_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    bops INTEGER NOT NULL DEFAULT 0,
                    deadline_at REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS world.idx_tinytown_hacker_active "
                "ON tinytown_hacker_runs(account_id) WHERE status = 'active'"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS world.idx_tinytown_hacker_account "
                "ON tinytown_hacker_runs(account_id, cycle_key)"
            )

    # -- account payloads ----------------------------------------------------

    def _player_payload(self, account: object) -> dict[str, Any]:
        snapshot = self.stats.snapshot(account.id)
        return {
            "name": account.username_display,
            "traits": (),
            "energy": snapshot.energy,
            "health": snapshot.health,
            "cleanliness": snapshot.cleanliness,
            "vibe": 0.0,
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
                LOGGER.debug("tinytown.hacker_vibe_read_failed", exc_info=True)
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
            "is_player": False,
        }

    def _helper_cards(self, helpers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for helper in helpers:
            vibe = int(helper.get("vibe", 0))
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
                    "vibe": {"label": describe_vibe(vibe), "willing": vibe > VIBE_GATE},
                    "fatigue": round(max(0.0, min(1.0, (55.0 - float(helper.get("energy", 70.0))) / 55.0)), 2),
                }
            )
        cards.sort(key=lambda card: (not card["vibe"]["willing"], card["name"].casefold()))
        return cards

    def _helper_record(self, account: object, helper_id: str) -> tuple[object, dict[str, Any]]:
        record = self.npcs.record_for(helper_id)
        if record is None or getattr(record, "owner_account_id", None) != account.id:
            raise ValueError("That roommate is not part of your household.")
        payload = self._helper_payload(account, record)
        if int(payload["vibe"]) <= VIBE_GATE:
            raise ValueError(f"{record.name} would rather not hack with you right now.")
        return record, payload

    def _condition(self, energy: float) -> str:
        return condition_label(energy)

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

    def _cycle_key(self) -> str:
        return f"cycle-{cycle_index(self._clock())}"

    # -- rows ----------------------------------------------------------------

    def _active_row(self, account_id: str) -> RunRow | None:
        with self.hub.locked() as connection:
            row = connection.execute(
                "SELECT * FROM world.tinytown_hacker_runs WHERE account_id = ? "
                "AND status = 'active' LIMIT 1",
                (account_id,),
            ).fetchone()
        return _row_to_run(row) if row is not None else None

    def _expire_if_due(self, row: RunRow) -> bool:
        if self._clock() < row.deadline_at:
            return False
        state = json.loads(row.state_json)
        self._close(row, state, EXPIRED)
        return True

    def _remaining_ms(self, row: RunRow) -> int:
        return max(0, int((row.deadline_at - self._clock()) * 1000))

    # -- board ---------------------------------------------------------------

    def _corp_payload(self, corp: CorpDefinition) -> dict[str, Any]:
        return {
            "id": corp.id,
            "title": corp.title,
            "tagline": corp.tagline,
            "blurb": corp.blurb,
            "grade": corp.grade,
            "topic": corp.topic,
            "motif": corp.motif,
            "palette": dict(corp.palette),
            "logo_url": f"/activities/hacker/art/{corp.logo}",
            "background_url": f"/activities/hacker/art/{corp.background}",
            "arena_url": f"/activities/hacker/art/{corp.arena}",
            "playable": corp.playable,
            "open_floor": (
                {
                    "level": corp.open_floor.level,
                    "title": corp.open_floor.title,
                    "topic": corp.open_floor.topic,
                    "nodes": corp.open_floor.nodes,
                }
                if corp.open_floor
                else None
            ),
            "floors": [
                {
                    "level": floor.level,
                    "title": floor.title,
                    "topic": floor.topic,
                    "nodes": floor.nodes,
                    "available": floor.available,
                    "locked": not (corp.playable and floor.available),
                }
                for floor in corp.floors
            ],
        }

    def board(self, account: object) -> dict[str, Any]:
        self._require_available()
        active = self._active_row(account.id)
        active_payload = None
        if active is not None and self._expire_if_due(active):
            active = None
        if active is not None:
            state = json.loads(active.state_json)
            active_payload = {
                "run_id": active.run_id,
                "corp_id": active.corp_id,
                "floor": active.floor,
                "cleared": len(state.get("cleared", [])),
                "remaining_ms": self._remaining_ms(active),
                "bops": active.bops,
            }
        snapshot = self.stats.snapshot(account.id)
        return {
            "cycle": self._cycle_payload(),
            "corps": [self._corp_payload(corp) for corp in self.library.corps.values()],
            "helpers": self._helper_cards(
                [self._helper_payload(account, record) for record in self.npcs.records_for_owner(account.id)]
            ),
            "max_helpers": MAX_HELPERS,
            "player": {
                "name": account.username_display,
                "condition": self._condition(snapshot.energy),
            },
            "active_run": active_payload,
        }

    # -- payloads ------------------------------------------------------------

    def _lead(self, run: dict[str, Any]) -> dict[str, Any]:
        helper = run.get("helper")
        return helper if helper else run["player"]

    def _node_state(self, run: dict[str, Any], node_id: str) -> dict[str, Any]:
        if node_id == CENTRAL_NODE:
            return run["central"]
        return run["nodes"].setdefault(
            node_id,
            {"screens": [], "challenge": None, "attempts": 0},
        )

    def _fit(self, run: dict[str, Any], layer: int, approach: str, *, central: bool) -> dict[str, Any]:
        return fit_for(
            run["grade"],
            layer,
            central=central,
            player=run["player"],
            lead=self._lead(run),
            approach=approach,
        )

    def _payout_payload(self, node_id: str) -> dict[str, int]:
        if node_id == CENTRAL_NODE:
            return {
                "min": CENTRAL_BOPS_MIN,
                "max": CENTRAL_BOPS_MAX,
                "kudos": CENTRAL_KUDOS,
                "props": CENTRAL_PROPS,
            }
        return {"min": NODE_BOPS_MIN, "max": NODE_BOPS_MAX}

    def _earned_bops(self, run: dict[str, Any], node_id: str) -> int:
        return int(run.get("node_bops", {}).get(node_id, 0))

    def _run_payload(self, row: RunRow, run: dict[str, Any]) -> dict[str, Any]:
        corp = self.library.corp(row.corp_id)
        generated = generate_map(run["map_seed"], int(run.get("node_count", 10)))
        cleared = list(run.get("cleared", []))
        open_ids = set(available_ids(cleared, generated))
        done = set(cleared)
        nodes = []
        for node in generated["nodes"]:
            status = "cleared" if node["id"] in done else "open" if node["id"] in open_ids else "locked"
            nodes.append(
                {
                    **{key: node[key] for key in ("id", "label", "name", "kind", "approach", "layer", "x", "y", "depends_on")},
                    "status": status,
                    "fit": self._fit(run, node["layer"], node["approach"], central=False),
                    "payout": self._payout_payload(node["id"]),
                    "earned_bops": self._earned_bops(run, node["id"]),
                }
            )
        core_status = (
            "cleared"
            if CENTRAL_NODE in done
            else "open"
            if central_available(cleared, generated)
            else "locked"
        )
        active_id = run.get("active_node")
        active = None
        if active_id is not None:
            target = self._node_state(run, active_id)
            active = {
                "id": active_id,
                "screens": target.get("screens", []),
                "tips": target.get("tips", []),
                "payout": self._payout_payload(active_id),
                "earned_bops": self._earned_bops(run, active_id),
                "challenge": target.get("challenge"),
                "ready": all(screen.get("passed") for screen in target.get("screens", []))
                and bool(target.get("screens")),
            }
        helper = run.get("helper")
        return {
            "run_id": row.run_id,
            "corp": self._corp_payload(corp),
            "floor": {
                "level": row.floor,
                "title": corp.floor(row.floor).title if corp.floor(row.floor) else "",
                "topic": corp.floor(row.floor).topic if corp.floor(row.floor) else "",
                "nodes": int(run.get("node_count", 10)),
            },
            "remaining_ms": self._remaining_ms(row),
            "deadline_at": row.deadline_at,
            "bops": row.bops,
            "cleared": cleared,
            "nodes": nodes,
            "central": {
                **generated["central"],
                "status": core_status,
                "fit": self._fit(run, generated["central"]["layer"], generated["central"]["approach"], central=True),
                "payout": self._payout_payload(CENTRAL_NODE),
                "earned_bops": self._earned_bops(run, CENTRAL_NODE),
            },
            "edges": generated["edges"],
            "helper": (
                self._helper_cards([helper])[0] if helper else None
            ),
            "player": {"name": run["player"].get("name", "You"), "condition": self._condition(run["player"].get("energy", 70.0))},
            "active": active,
            "banter": banter_pool(self.library.banter, helper, f"{run['banter_seed']}:{active_id}"),
            "completed": False,
        }

    # -- start ---------------------------------------------------------------

    def start(
        self,
        account: object,
        corp_id: str,
        helper_id: str | None,
        floor_level: int | None = None,
    ) -> dict[str, Any]:
        self._require_available()
        corp = self.library.corps.get(corp_id)
        if corp is None:
            raise ValueError("That megacorp is not on the network.")
        if not corp.playable or corp.open_floor is None:
            raise ValueError(f"{corp.title} is sealed until its grade opens.")
        floor = corp.floor(floor_level) if floor_level is not None else corp.open_floor
        if floor is None or not floor.available:
            raise ValueError("That floor is not open yet.")
        if self._active_row(account.id) is not None:
            raise ValueError("Finish or abandon your current hack first.")
        helpers = [helper_id] if helper_id else []
        unique = list(dict.fromkeys(str(value) for value in helpers if str(value)))
        if len(unique) > MAX_HELPERS:
            raise ValueError("Bring at most one roommate.")
        helper = None
        if unique:
            _record, helper = self._helper_record(account, unique[0])
        run_id = f"tthack:{secrets.token_hex(16)}"
        map_seed = secrets.token_hex(12)
        run = {
            "corp_id": corp.id,
            "grade": corp.grade,
            "floor": floor.level,
            "node_count": floor.nodes,
            "map_seed": map_seed,
            "player": self._player_payload(account),
            "helper": helper,
            "helper_id": helper["npc_id"] if helper else "",
            "banter_seed": secrets.token_hex(8),
            "cleared": [],
            "node_bops": {},
            "nodes": {},
            "central": {"screens": [], "challenge": None, "attempts": 0},
            "active_node": None,
            "screen_seq": 0,
            "bops_awarded": 0,
        }
        now = self._clock()
        timestamp = utc_now().isoformat()
        try:
            with self.hub.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO world.tinytown_hacker_runs (
                        run_id, account_id, cycle_key, corp_id, floor, helper_id,
                        status, state_json, bops, deadline_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, 0, ?, ?, ?)
                    """,
                    (
                        run_id,
                        account.id,
                        self._cycle_key(),
                        corp.id,
                        floor.level,
                        run["helper_id"],
                        json.dumps(run, separators=(",", ":")),
                        now + DEADLINE_SECONDS,
                        timestamp,
                        timestamp,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("That hack could not start. Open the tower again.") from exc
        return self._run_payload(self._row(run_id), run)

    def _row(self, run_id: str) -> RunRow:
        with self.hub.locked() as connection:
            row = connection.execute(
                "SELECT * FROM world.tinytown_hacker_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise ValueError("That hack no longer exists.")
        return _row_to_run(row)

    # -- lifecycle -----------------------------------------------------------

    def _load_active(self, account: object) -> tuple[RunRow, dict[str, Any]]:
        self._require_available()
        row = self._active_row(account.id)
        if row is None:
            raise ValueError("You do not have a hack in progress.")
        if self._expire_if_due(row):
            raise ValueError("The connection timed out. That hack is over.")
        try:
            run = json.loads(row.state_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("Your hack state could not be read. Abandon it and try again.") from exc
        return row, run

    def _save(self, row: RunRow, run: dict[str, Any], *, bops: int | None = None) -> None:
        with self.hub.transaction() as connection:
            fields = "state_json = ?, updated_at = ?"
            values: list[Any] = [json.dumps(run, separators=(",", ":")), utc_now().isoformat()]
            if bops is not None:
                fields += ", bops = ?"
                values.append(bops)
            connection.execute(
                f"UPDATE world.tinytown_hacker_runs SET {fields} WHERE run_id = ? AND status = 'active'",
                (*values, row.run_id),
            )

    def resume(self, account: object) -> dict[str, Any]:
        row, run = self._load_active(account)
        return self._run_payload(row, run)

    def quit(self, account: object) -> dict[str, Any]:
        row, run = self._load_active(account)
        self._close(row, run, ABANDONED)
        return {
            "run": None,
            "outcome": {
                "abandoned": True,
                "cleared": len(run.get("cleared", [])),
                "bops": row.bops,
            },
        }

    def _close(self, row: RunRow, run: dict[str, Any], status: str) -> None:
        with self.hub.transaction() as connection:
            connection.execute(
                "UPDATE world.tinytown_hacker_runs SET status = ?, state_json = ?, updated_at = ? "
                "WHERE run_id = ? AND status = 'active'",
                (status, json.dumps(run, separators=(",", ":")), utc_now().isoformat(), row.run_id),
            )

    # -- nodes ---------------------------------------------------------------

    def _next_screen_id(self, run: dict[str, Any], node_id: str) -> str:
        run["screen_seq"] = int(run.get("screen_seq", 0)) + 1
        return f"hs{run['screen_seq']}"

    def _screen_ids(self, run: dict[str, Any], node_id: str, count: int) -> list[str]:
        return [f"{node_id}-{self._next_screen_id(run, node_id)}" for _ in range(count)]

    def _ensure_screens(self, run: dict[str, Any], node_id: str, layer: int, *, central: bool) -> None:
        target = self._node_state(run, node_id)
        if target.get("screens"):
            if not target.get("tips"):
                target["tips"] = tip_pack(
                    run["grade"],
                    target["screens"],
                    self.library.lines_for("tip"),
                    f"{run['map_seed']}:{node_id}:tips",
                )
            return
        count = screens_for(layer, central=central)
        rng = random.Random(f"tinytown-hacker-screens:{run['map_seed']}:{node_id}:{target.get('attempts', 0)}")
        ids = self._screen_ids(run, node_id, count)
        target["screens"] = build_node_screens(run["grade"], ids, rng)
        target["tips"] = tip_pack(
            run["grade"],
            target["screens"],
            self.library.lines_for("tip"),
            f"{run['map_seed']}:{node_id}:tips",
        )
        target["attempts"] = int(target.get("attempts", 0))

    def enter(self, account: object, node_id: str) -> dict[str, Any]:
        row, run = self._load_active(account)
        generated = generate_map(run["map_seed"], int(run.get("node_count", 10)))
        central = node_id == CENTRAL_NODE
        if central:
            if not central_available(run.get("cleared", []), generated):
                raise ValueError("The central server is still behind a locked node.")
            if CENTRAL_NODE in run.get("cleared", []):
                raise ValueError("The central server is already ours.")
            layer = generated["central"]["layer"]
        else:
            node = next((entry for entry in generated["nodes"] if entry["id"] == node_id), None)
            if node is None:
                raise ValueError("That node is not on this network map.")
            if node_id in run.get("cleared", []):
                raise ValueError("That node is already clean.")
            if node_id not in available_ids(run.get("cleared", []), generated):
                raise ValueError("That node is still locked behind its dependencies.")
            layer = int(node["layer"])
        run["active_node"] = node_id
        self._ensure_screens(run, node_id, layer, central=central)
        self._save(row, run)
        return self._run_payload(row, run)

    def _active_target(self, run: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        node_id = run.get("active_node")
        if not node_id:
            raise ValueError("Open a node before answering.")
        return node_id, self._node_state(run, node_id)

    def _screens_complete(self, target: dict[str, Any]) -> bool:
        screens = target.get("screens", [])
        return bool(screens) and all(screen.get("passed") for screen in screens)

    def leave(self, account: object) -> dict[str, Any]:
        """Leave the open node and reset its screens for the next attempt."""

        row, run = self._load_active(account)
        node_id = run.get("active_node")
        if node_id:
            target = self._node_state(run, node_id)
            target["screens"] = []
            target["tips"] = []
            target["challenge"] = None
            target["attempts"] = 0
            run["active_node"] = None
        self._save(row, run)
        return self._run_payload(row, run)

    def answer(
        self,
        account: object,
        screen_id: str,
        elapsed_ms: int,
        answers: dict[str, Any],
    ) -> dict[str, Any]:
        row, run = self._load_active(account)
        node_id, target = self._active_target(run)
        screen = next((entry for entry in target.get("screens", []) if entry.get("id") == screen_id), None)
        if screen is None:
            raise ValueError("That screen is not part of the open node.")
        if screen.get("passed"):
            raise ValueError("That screen is already decrypting.")
        limit = int(screen.get("payload", {}).get("time_limit_ms", 0) or 0)
        if limit and int(elapsed_ms) > limit:
            replacement = build_screen(
                run["grade"],
                screen["type"],
                f"{node_id}-{self._next_screen_id(run, node_id)}",
                random.Random(f"tinytown-hacker-reset:{run['map_seed']}:{screen_id}:{elapsed_ms}"),
            )
            target["screens"] = [replacement if entry.get("id") == screen_id else entry for entry in target["screens"]]
            target["tips"] = tip_pack(
                run["grade"],
                target["screens"],
                self.library.lines_for("tip"),
                f"{run['map_seed']}:{node_id}:tips:{elapsed_ms}",
            )
            self._save(row, run)
            return {
                "result": {"passed": False, "timeout": True, "correct": {}, "elapsed_ms": int(elapsed_ms)},
                "run": self._run_payload(row, run),
            }
        verification = verify_screen(screen, answers)
        if verification["passed"]:
            screen["passed"] = True
        self._save(row, run)
        return {
            "result": {
                "passed": bool(verification["passed"]),
                "timeout": False,
                "correct": verification["correct"],
                "elapsed_ms": int(elapsed_ms),
            },
            "run": self._run_payload(row, run),
        }

    # -- minigames -----------------------------------------------------------

    def challenge(self, account: object, node_id: str | None = None) -> dict[str, Any]:
        row, run = self._load_active(account)
        target_id = node_id or run.get("active_node")
        if not target_id:
            raise ValueError("Open a node before starting its reflex challenge.")
        if target_id != run.get("active_node"):
            raise ValueError("That node is not the one you have open.")
        target = self._node_state(run, target_id)
        if not self._screens_complete(target):
            raise ValueError("Decrypt every maths screen on this node first.")
        central = target_id == CENTRAL_NODE
        generated = generate_map(run["map_seed"], int(run.get("node_count", 10)))
        layer = (
            generated["central"]["layer"]
            if central
            else int(next(node for node in generated["nodes"] if node["id"] == target_id)["layer"])
        )
        approach = (
            generated["central"]["approach"]
            if central
            else str(next(node for node in generated["nodes"] if node["id"] == target_id)["approach"])
        )
        attempt = int(target.get("attempts", 0)) + 1
        target["attempts"] = attempt
        built = challenge_for(
            seed=run["map_seed"],
            node_id=target_id,
            grade=run["grade"],
            layer=layer,
            central=central,
            player=run["player"],
            lead=self._lead(run),
            approach=approach,
            attempt=attempt,
        )
        challenge_id = f"ttch:{secrets.token_hex(8)}"
        target["challenge"] = {**built, "id": challenge_id}
        self._save(row, run)
        return {
            "challenge": {
                "id": challenge_id,
                "node_id": target_id,
                "central": central,
                "game": built["game"],
                "params": built["params"],
                "difficulty": built["difficulty"],
                "arena_url": f"/activities/hacker/art/{self.library.corp(run['corp_id']).arena}",
            },
            "run": self._run_payload(row, run),
        }

    def resolve(
        self,
        account: object,
        node_id: str,
        challenge_id: str,
        score: int,
        elapsed_ms: int,
    ) -> dict[str, Any]:
        row, run = self._load_active(account)
        target = self._node_state(run, node_id)
        challenge = target.get("challenge")
        if not challenge or challenge.get("id") != challenge_id:
            raise ValueError("That challenge is not the one in progress.")
        _passed, counted, note = score_result(challenge["params"], score, elapsed_ms)
        target["challenge"] = None
        run["active_node"] = None
        maximum = int(challenge["params"].get("max_score", 0))
        if node_id == CENTRAL_NODE:
            bops = payout_bops(counted, maximum, CENTRAL_BOPS_MIN, CENTRAL_BOPS_MAX)
            outcome = self._finish_floor(account, row, run, challenge, bops)
            return {
                "result": {
                    "passed": True,
                    "score": counted,
                    "required": 0,
                    "total": maximum,
                    "bops": outcome["bops"],
                    "text": note or "The core is ours.",
                    "central": True,
                },
                "run": None,
                "outcome": outcome,
            }
        bops = payout_bops(counted, maximum, NODE_BOPS_MIN, NODE_BOPS_MAX)
        reward = self._clear_node(account, row, run, node_id, bops)
        fresh = self._row(row.run_id)
        return {
            "result": {
                "passed": True,
                "score": counted,
                "required": 0,
                "total": maximum,
                "text": note or "Node clean. The packet path is open.",
                "central": False,
                **reward,
            },
            "run": self._run_payload(fresh, run),
            "outcome": None,
        }

    # -- rewards -------------------------------------------------------------

    def _clear_node(
        self,
        account: object,
        row: RunRow,
        run: dict[str, Any],
        node_id: str,
        bops: int,
    ) -> dict[str, Any]:
        run.setdefault("cleared", []).append(node_id)
        paid = False
        ledger_key = f"tinytown-hacker:{account.id}:{row.cycle_key}:{row.corp_id}:{row.floor}:{node_id}"
        with self.hub.transaction() as connection:
            paid = self.progression.grant_in_transaction(
                connection,
                account.id,
                bops=bops,
                ledger_key=ledger_key,
                kind="tinytown-hacker-node",
            )
            run.setdefault("node_bops", {})[node_id] = bops if paid else 0
            connection.execute(
                "UPDATE world.tinytown_hacker_runs SET state_json = ?, bops = bops + ?, updated_at = ? "
                "WHERE run_id = ? AND status = 'active'",
                (
                    json.dumps(run, separators=(",", ":")),
                    bops if paid else 0,
                    utc_now().isoformat(),
                    row.run_id,
                ),
            )
        if paid:
            run["bops_awarded"] = int(run.get("bops_awarded", 0)) + bops
        self._apply_node_fatigue(run)
        if paid:
            self._save(row, run)
        return {"bops": bops if paid else 0, "potential": bops, "paid": paid}

    def _apply_node_fatigue(self, run: dict[str, Any]) -> None:
        helper = run.get("helper")
        if not helper:
            return
        npc_id = str(helper.get("npc_id", ""))
        record = self.npcs.record_for(npc_id) if npc_id else None
        if record is None:
            return
        stats = dict(record.stats)
        stats["energy"] = self.npcs._clamp(stats.get("energy", 70.0) - FATIGUE_PER_NODE)
        try:
            self.npcs._write(self.npcs._with(record, stats=stats), created=False)
        except Exception:
            LOGGER.warning("tinytown.hacker_fatigue_failed npc_id=%s", npc_id, exc_info=True)

    def _prop_choices(self, account: object, row: RunRow) -> list[str]:
        world = self.runtime.world
        profile = self.profiles.get_user_profile(account.id)
        owned = set(profile.unlocked_props) if profile is not None else set()
        candidates = [
            definition.id
            for definition in world.props.values()
            if definition.source_kind == "propset"
            and definition.decorative
            and not definition.hidden
            and definition.locked
            and definition.id not in owned
        ]
        if not candidates:
            return []
        rng = random.Random(f"tinytown-hacker-props:{account.id}:{row.cycle_key}:{row.corp_id}:{row.floor}")
        rng.shuffle(candidates)
        chosen: list[str] = []
        for prop_id in candidates:
            chosen.append(prop_id)
            if len(chosen) >= CENTRAL_PROPS:
                break
        return chosen

    def _finish_floor(
        self,
        account: object,
        row: RunRow,
        run: dict[str, Any],
        challenge: dict[str, Any],
        bops: int,
    ) -> dict[str, Any]:
        run.setdefault("cleared", []).append(CENTRAL_NODE)
        props = self._prop_choices(account, row)
        run.setdefault("node_bops", {})[CENTRAL_NODE] = bops
        ledger_key = f"tinytown-hacker:{account.id}:{row.cycle_key}:{row.corp_id}:{row.floor}:{CENTRAL_NODE}"
        updated_vibes: dict[str, int] = {}
        granted = False
        with self.hub.transaction() as connection:
            granted = self.progression.grant_in_transaction(
                connection,
                account.id,
                kudos=CENTRAL_KUDOS,
                bops=bops,
                props=props,
                ledger_key=ledger_key,
                kind="tinytown-hacker-core",
            )
            connection.execute(
                "UPDATE world.tinytown_hacker_runs SET status = 'completed', state_json = ?, "
                "bops = bops + ?, updated_at = ? WHERE run_id = ? AND status = 'active'",
                (
                    json.dumps(run, separators=(",", ":")),
                    bops if granted else 0,
                    utc_now().isoformat(),
                    row.run_id,
                ),
            )
            helper = run.get("helper")
            if granted and helper and self.vibes is not None:
                updated_vibes = {
                    source: value
                    for (source, _target), value in self.vibes.adjust_many_in_transaction(
                        connection,
                        [(str(helper["npc_id"]), account.id, VIBE_PER_FLOOR)],
                    ).items()
                }
        helper = run.get("helper")
        names = {}
        if helper:
            for prop_id in props:
                definition = self.runtime.world.props.get(prop_id)
                names[prop_id] = definition.label if definition is not None else prop_id
        return {
            "completed": True,
            "corp_id": row.corp_id,
            "floor": row.floor,
            "cleared": len(run.get("cleared", [])),
            "kudos": CENTRAL_KUDOS if granted else 0,
            "bops": bops if granted else 0,
            "props": [{"id": prop_id, "label": names.get(prop_id, prop_id)} for prop_id in (props if granted else [])],
            "helper": (
                {
                    "id": helper.get("npc_id", ""),
                    "name": helper.get("name", ""),
                    "avatar_url": helper.get("avatar_url", ""),
                    "vibe_delta": VIBE_PER_FLOOR if granted else 0,
                    "vibe_label": describe_vibe(updated_vibes.get(str(helper.get("npc_id")), int(helper.get("vibe", 0)))),
                }
                if helper
                else None
            ),
            "score": int(challenge["params"].get("max_score", 0)),
        }

    def _require_available(self) -> None:
        if not self.available:
            raise ValueError("The Hacker Collective is not available here.")


__all__ = ["CENTRAL_NODE", "MAX_HELPERS", "HackerRuns"]
