"""Server-authoritative Tiny Vault heist commands and job setup."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from mods.tinyvault.content import HeistContent, load_heist_content
from mods.tinyvault.director import HeistDirector
from mods.tinyvault.guards import GuardState, angle_to
from mods.tinyvault.jobs import describe_generated, generate_job
from mods.tinyvault.models import (
    CONSOLE_COOLDOWN,
    HIDEOUT_ROOM,
    META_KEY,
    MOD_ID,
    MOVE_BURST,
    MOVE_SPEED_PER_SECOND,
    SAFECRACK_MIN_SECONDS,
    SAFECRACK_SECONDS,
    WORLD_ID,
    ActiveJob,
    BotCrew,
    CrewMember,
    HeistResult,
    LootAward,
    VaultAttempt,
    iso_now,
    monotonic_now,
)
from server.broadcast import broadcast_room_event
from server.commands.outcomes import PendingRoomBroadcast
from server.content.worlds import QuickAction
from server.services.cards import grant_card_to_inventory


LOGGER = logging.getLogger("tinyrooms.tinyvault")


def _now() -> float:
    return monotonic_now()


def _iso_now() -> str:
    return iso_now()


SAFECRACK_SYMBOLS = ("circle", "triangle", "square", "diamond", "star", "key")


def _hash_safecrack_seed(seed: object) -> int:
    """FNV-1a hash matching the safecrack client puzzle generator."""

    digest = 2166136261
    for character in str(seed or ""):
        digest ^= ord(character)
        digest = (digest * 16777619) & 0xFFFFFFFF
    return digest


def safecrack_sequence(seed: object, difficulty: object = 2) -> list[str]:
    """Generate the expected tumbler order for one cracking session."""

    try:
        level = int(difficulty or 2)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        level = 2
    length = min(6, max(3, 2 + level))
    state = _hash_safecrack_seed(seed) or 1
    sequence: list[str] = []
    while len(sequence) < length:
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        symbol = SAFECRACK_SYMBOLS[state % len(SAFECRACK_SYMBOLS)]
        if not sequence or sequence[-1] != symbol:
            sequence.append(symbol)
    return sequence


class HeistService(HeistDirector):
    """Owns Tiny Vault jobs, tools, loot, heat, and bot companions."""

    def __init__(self, runtime: object) -> None:
        self.runtime = runtime
        if getattr(getattr(runtime, "world", None), "id", "") == WORLD_ID:
            content_path = Path(__file__).resolve().parent / "content" / "jobs.yaml"
            self.content: HeistContent = load_heist_content(
                content_path, world=runtime.world, catalog=runtime.catalog
            )
        else:
            self.content = HeistContent(tools={}, bots={}, jobs={})
        self.job: ActiveJob | None = None
        self._task: asyncio.Task[None] | None = None
        self._move_budget: dict[str, tuple[tuple[float, float], float]] = {}
        self._room_last_tick: dict[str, float] = {}
        self._guard_bubble_at: dict[str, float] = {}
        self._security_visual: dict[str, bool] = {}
        self._needs_recovery = True
        self._instance_rooms: dict[str, str] = {}
        for room_id, room in runtime.world.rooms.items():
            for instance_id in room.props:
                self._instance_rooms[instance_id] = room_id

    @property
    def available(self) -> bool:
        """Return whether the loaded world is the Tiny Vault."""

        return getattr(getattr(self.runtime, "world", None), "id", "") == WORLD_ID

    def prepare(self) -> None:
        """Mark staged security for reconciliation on startup or reload."""

        self._needs_recovery = True

    def start(self) -> None:
        """Start the job supervisor used for timers, disconnects, and recovery."""

        if not self.available or (self._task is not None and not self._task.done()):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = loop.create_task(self.supervise())

    def stop(self) -> None:
        """Stop the job supervisor."""

        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def on_room_tick(self, room_id: str) -> list[object]:
        """Advance guards, vision, alarms, vault attempts, and escapes."""

        if not self.available or self.job is None or room_id not in self.job.template.target_rooms:
            return []
        try:
            return await self.tick_room(room_id, _now())
        except Exception:  # noqa: BLE001 - a heist tick must not break rooms
            LOGGER.exception("tinyvault.tick_failed")
            return []

    def validate_sprite_move(self, account: object, room_id: str, x: float, y: float) -> str | None:
        """Reject heist-room movement beyond a generous server-side speed budget."""

        if not self.available or self.job is None or room_id not in self.job.template.target_rooms:
            return None
        member = self.job.crew.get(getattr(account, "id", ""))
        if member is None or member.status != "active":
            return None
        try:
            target = (float(x), float(y))
        except (TypeError, ValueError):
            return "Those sprite coordinates are invalid."
        stored = self.runtime.rooms.sprites.position_of_user(account.id)
        now = _now()
        if stored is None or stored[0] != room_id:
            self._move_budget[account.id] = (target, now)
            return None
        previous, at = self._move_budget.get(account.id, (stored[1], now))
        elapsed = max(0.0, now - at)
        distance = math.hypot(target[0] - previous[0], target[1] - previous[1])
        if elapsed < 5.0 and distance > MOVE_SPEED_PER_SECOND * elapsed + MOVE_BURST:
            return "That move is too fast for a careful heist."
        self._move_budget[account.id] = (target, now)
        return None

    def room_quick_actions(self, account: object, room: object) -> tuple[QuickAction, ...]:
        """Return contextual room-wide heist actions for crew members."""

        try:
            if not self.available or self.job is None:
                return ()
            member = self.job.crew.get(account.id)
            if member is None or member.status != "active" or room.id not in self.job.template.target_rooms:
                return ()
            actions: list[QuickAction] = []
            if self._owns(account.id, "heist-disguise") and self._ready(member.account_id, "heist-disguise"):
                actions.append(QuickAction(label="Use disguise", command=".heist use heist-disguise"))
            if self._owns(account.id, "heist-smoke"):
                actions.append(QuickAction(label="Throw smoke", command=".heist use heist-smoke"))
            if self._owns(account.id, "heist-decoy"):
                actions.append(QuickAction(label="Plant decoy here", command=".heist use heist-decoy"))
            if self._owns(account.id, "heist-jammer") and not self.job.jammer_used:
                actions.append(QuickAction(label="Arm jammer", command=".heist use heist-jammer"))
            if room.id in self.job.template.escape_rooms:
                actions.append(QuickAction(label="Escape with loot", command=".heist escape", default=True))
            return tuple(actions)
        except Exception:  # noqa: BLE001 - action hooks must not break snapshots
            LOGGER.exception("tinyvault.room_actions_failed")
            return ()

    def personal_actions(self, account: object, prop: object) -> tuple[QuickAction, ...]:
        """Return contextual prop actions for heist tools and loot."""

        try:
            if not self.available or self.job is None:
                return ()
            member = self.job.crew.get(account.id)
            if member is None or member.status != "active":
                return ()
            room_id = self._instance_rooms.get(prop.id)
            if room_id is None or room_id not in self.job.template.target_rooms:
                return ()
            definition = self.runtime.world.props[prop.prop_id]
            tags = set(definition.tags)
            if "heist-door" in tags and self._owns(account.id, "heist-lockpick"):
                return (QuickAction(label="Pick lock", command=f".heist use heist-lockpick @prop:{prop.id}"),)
            if "heist-camera" in tags and self._owns(account.id, "heist-emp"):
                return (QuickAction(label="Disable camera", command=f".heist use heist-emp @prop:{prop.id}"),)
            if "heist-laser" in tags and self._owns(account.id, "heist-emp"):
                return (QuickAction(label="Disable lasers", command=f".heist use heist-emp @prop:{prop.id}"),)
            if "heist-console" in tags:
                return (QuickAction(label="Hack console", command=f".heist hack @prop:{prop.id}"),)
            if "heist-vault" in tags and self._owns(account.id, "heist-drill"):
                return (QuickAction(label="Start drill", command=f".heist use heist-drill @prop:{prop.id}"),)
            if "heist-loot" in tags and self.job.vault.status == "open" and prop.id in self.job.loot_active:
                return (QuickAction(label="Grab loot", command=f".heist loot @prop:{prop.id}"),)
            if "heist-grapple" in tags and self._owns(account.id, "heist-grapple"):
                return (QuickAction(label="Rig rappel line", command=f".heist use heist-grapple @prop:{prop.id}"),)
            return ()
        except Exception:  # noqa: BLE001 - action hooks must not break snapshots
            LOGGER.exception("tinyvault.prop_actions_failed")
            return ()

    async def board_payload(self, account_id: str) -> dict[str, object]:
        """Return jobs, heat, tools, crew, and status for the job board."""

        heat = self.heat_for(account_id)
        jobs: list[dict[str, object]] = []
        for template in self.content.jobs.values():
            preview = describe_generated(template, generate_job(template, "preview"))
            jobs.append({**preview, "locked": heat < template.heat_tier})
        jobs.sort(key=lambda entry: (entry["heat_tier"], entry["label"]))
        return {
            "heat": heat,
            "heat_tiers": [0, 1, 2, 3],
            "jobs": jobs,
            "tools": [self._tool_payload(tool_id, account_id) for tool_id in sorted(self.content.tools)],
            "bots": [
                {
                    "id": bot.id,
                    "label": bot.label,
                    "price": bot.price,
                    "description": bot.description,
                    "hired": self.job is not None and self.job.bot is not None and self.job.bot.role_id == bot.id,
                }
                for bot in self.content.bots.values()
            ],
            "active": await self.status_payload(),
        }

    async def status_payload(self) -> dict[str, object]:
        """Return the active job's public status."""

        if self.job is None:
            return {"active": False}
        crew = [
            {
                "account_id": member.account_id,
                "username": member.username,
                "leader": member.leader,
                "status": member.status,
                "loot": sum(award.value for award in member.provisional),
            }
            for member in sorted(self.job.crew.values(), key=lambda item: item.joined_at)
        ]
        return {
            "active": True,
            "run_id": self.job.run_id,
            "job_id": self.job.template.id,
            "label": self.job.template.label,
            "phase": self.job.phase,
            "alarm": self.job.alarm_stage,
            "alarm_score": round(self.job.alarm_score, 1),
            "leader_id": self.job.leader_id,
            "crew": crew,
            "bot": None if self.job.bot is None else {"role": self.job.bot.role_id, "label": self.job.bot.label},
            "vault": self.job.vault.status,
            "objectives": sorted(self.job.objectives_done),
            "elapsed_seconds": round(max(0.0, _now() - self.job.started_at), 1),
            "time_limit_seconds": self.job.template.time_limit_seconds,
        }

    def heat_for(self, account_id: str) -> int:
        """Return decayed heat for one account."""

        meta = self._read_meta()
        return self._decayed_heat(meta, account_id)

    async def start_job(self, account: object, room_id: str, template_id: str) -> HeistResult:
        """Create one active job and charge its deposit."""

        self._require_available()
        template = self.content.jobs.get(template_id)
        if template is None:
            raise ValueError("That job is not on the board.")
        if room_id != HIDEOUT_ROOM:
            raise ValueError("Start heists from the hideout.")
        if self.job is not None:
            raise ValueError("A heist is already active.")
        heat = self.heat_for(account.id)
        if heat < template.heat_tier:
            raise ValueError(f"That job needs heat {template.heat_tier}. Finish easier scores first.")
        run_id = uuid.uuid4().hex[:8]
        generated = generate_job(template, run_id)
        self._charge_deposit(account, template.deposit)
        now = _now()
        self.job = ActiveJob(
            run_id=run_id,
            seed=run_id,
            template=template,
            generated=generated,
            leader_id=account.id,
            started_at=now,
            deposit_account_id=account.id,
            deposit=template.deposit,
        )
        self.job.crew[account.id] = CrewMember(
            account_id=account.id, username=account.username_display, leader=True, joined_at=now
        )
        self._initialize_guards()
        result = HeistResult(
            message=f"{template.label} is on the board. The crew gathers in the hideout.",
            payload={"job": describe_generated(template, generated), "status": await self.status_payload()},
            refresh_user=True,
        )
        result.private_events.extend(await self._cutscene_events(account, room_id, "heist-briefing", "private"))
        return result

    async def join_job(self, account: object, room_id: str) -> HeistResult:
        """Add one hideout player to the briefing or active crew."""

        self._require_job()
        assert self.job is not None
        if room_id != HIDEOUT_ROOM:
            raise ValueError("Join from the hideout.")
        member = self.job.crew.get(account.id)
        if member is not None and member.status == "active":
            raise ValueError("You are already on this crew.")
        if member is not None and member.status in {"caught", "escaped"}:
            raise ValueError("Caught or escaped crew cannot rejoin this score.")
        humans = [item for item in self.job.crew.values() if item.status in {"active", "left"}]
        total = len([item for item in humans if item.status == "active"]) + (1 if self.job.bot else 0)
        if total >= self.job.template.max_crew:
            raise ValueError("That crew is full.")
        now = _now()
        if member is None:
            self.job.crew[account.id] = CrewMember(
                account_id=account.id, username=account.username_display, joined_at=now
            )
        else:
            member.status = "active"
            member.joined_at = now
        return HeistResult(
            message="You joined the crew.",
            payload={"status": await self.status_payload()},
        )

    async def leave_job(self, account: object) -> HeistResult:
        """Remove one player from the crew, promoting or aborting as needed."""

        self._require_job()
        assert self.job is not None
        member = self.job.crew.get(account.id)
        if member is None or member.status not in {"active", "left"}:
            raise ValueError("You are not on this crew.")
        member.status = "left"
        member.inside = False
        member.provisional.clear()
        actives = [item for item in self.job.crew.values() if item.status == "active"]
        if member.leader and actives:
            successor = sorted(actives, key=lambda item: item.joined_at)[0]
            successor.leader = True
            self.job.leader_id = successor.account_id
        if not actives and not self._anyone_inside():
            await self._abandon(refund=self.job.phase == "briefing")
            return HeistResult(message="The crew scattered and the job was abandoned.")
        return HeistResult(
            message="You left the crew.",
            payload={"status": await self.status_payload()},
        )

    async def abort_job(self, account: object) -> HeistResult:
        """Abort the job as its leader."""

        self._require_job()
        assert self.job is not None
        if account.id != self.job.leader_id:
            raise ValueError("Only the crew leader can abort this job.")
        refund = self.job.phase == "briefing"
        await self._abandon(refund=refund)
        if refund:
            return HeistResult(message="Job aborted before entry. The deposit was returned.", refresh_user=True)
        return HeistResult(message="Job aborted. The deposit is gone; the crew walks home.")

    async def enter_job(self, account: object, room_id: str) -> HeistResult:
        """Stage the bank once, then move one crew member into the target."""

        self._require_job()
        assert self.job is not None
        member = self.job.crew.get(account.id)
        if member is None or member.status != "active":
            raise ValueError("Only active crew can enter this bank.")
        if room_id != HIDEOUT_ROOM and room_id not in self.job.template.target_rooms:
            raise ValueError("Return to the hideout to enter the bank.")
        if self.job.phase == "briefing":
            crew_size = len(
                [item for item in self.job.crew.values() if item.status == "active"]
            ) + (1 if self.job.bot else 0)
            if crew_size < self.job.template.min_crew:
                raise ValueError(
                    f"This score needs at least {self.job.template.min_crew} crew."
                )
            await self._stage_job()
        if self.job.phase not in {"infiltration", "vault", "escape"}:
            raise ValueError("This job is no longer enterable.")
        navigation = await self.runtime.rooms.enter_room(
            account, room_id, self.job.template.entry_room_id, direction="a service entrance"
        )
        self.job.entered = True
        member.inside = True
        return HeistResult(
            message="You slip into the bank.",
            navigation=navigation,
            payload={"status": await self.status_payload()},
        )

    async def buy_tool(self, account: object, room_id: str, tool_id: str) -> HeistResult:
        """Sell one tool card from the hideout locker."""

        self._require_available()
        if room_id != HIDEOUT_ROOM:
            raise ValueError("Buy tools from the hideout locker.")
        tool = self.content.tools.get(tool_id)
        if tool is None:
            raise ValueError("That tool is not stocked.")
        if tool.kind == "reusable" and self._owns(account.id, tool_id):
            raise ValueError("You already own that reusable tool.")
        self._spend(account, tool.price, f"the {tool.label}")
        definition = self.runtime.catalog.cards[tool_id]
        with self.runtime.hub.transaction() as connection:
            current = self.runtime.profiles.get_account_by_id(account.id)
            if current is None:
                raise ValueError("That account no longer exists.")
            self.runtime.profiles.update_progress(connection, current, bops=current.bops - tool.price)
            grant_card_to_inventory(
                self.runtime.profiles, connection, account_id=account.id, definition=definition, world_id=WORLD_ID
            )
        return HeistResult(
            message=f"{tool.label} added to your loadout.",
            payload={"tools": [self._tool_payload(item, account.id) for item in sorted(self.content.tools)]},
            refresh_user=True,
        )

    async def hire_bot(self, account: object, room_id: str, role_id: str) -> HeistResult:
        """Hire one passive bot companion for the active job."""

        self._require_job()
        assert self.job is not None
        bot = self.content.bots.get(role_id)
        if bot is None:
            raise ValueError("That bot is not available.")
        if room_id != HIDEOUT_ROOM:
            raise ValueError("Hire bots in the hideout.")
        if self.job.bot is not None:
            raise ValueError("This crew already hired a bot.")
        total = len([item for item in self.job.crew.values() if item.status == "active"]) + 1
        if total > self.job.template.max_crew:
            raise ValueError("There is no crew slot left for a bot.")
        self._spend(account, bot.price, bot.label)
        with self.runtime.hub.transaction() as connection:
            current = self.runtime.profiles.get_account_by_id(account.id)
            if current is None:
                raise ValueError("That account no longer exists.")
            self.runtime.profiles.update_progress(connection, current, bops=current.bops - bot.price)
        self.job.bot = BotCrew(role_id=bot.id, peep_id=bot.peep_id, label=bot.label)
        if self.job.staged:
            await self._summon_bot()
        return HeistResult(
            message=f"{bot.label} joined as crew support.",
            payload={"status": await self.status_payload()},
            refresh_user=True,
        )

    async def use_tool(self, account: object, room_id: str, tool_id: str, prop_id: str | None) -> HeistResult:
        """Validate and apply one tool use."""

        self._require_job()
        assert self.job is not None
        member = self._require_active(account.id)
        if room_id not in self.job.template.target_rooms:
            raise ValueError("Tools only work inside the bank.")
        tool = self.content.tools.get(tool_id)
        if tool is None:
            raise ValueError("That tool is not stocked.")
        if not self._owns(account.id, tool_id):
            raise ValueError(f"You do not own {tool.label}.")
        now = _now()
        ready_at = self.job.cooldowns.get((account.id, tool_id), 0.0)
        if now < ready_at:
            raise ValueError(f"{tool.label} needs {ready_at - now:.0f} more seconds.")
        handler = {
            "heist-lockpick": self._use_lockpick,
            "heist-disguise": self._use_disguise,
            "heist-smoke": self._use_smoke,
            "heist-emp": self._use_emp,
            "heist-decoy": self._use_decoy,
            "heist-jammer": self._use_jammer,
            "heist-drill": self._use_drill,
            "heist-grapple": self._use_grapple,
        }[tool_id]
        result = await handler(account, member, room_id, prop_id, now)
        if tool.kind == "reusable" and tool.cooldown_seconds:
            self.job.cooldowns[(account.id, tool_id)] = now + tool.cooldown_seconds
        if tool.kind == "consumable":
            self._consume_tool(account.id, tool_id)
        result.refresh_user = True
        return result

    async def hack_console(self, account: object, room_id: str, prop_id: str) -> HeistResult:
        """Permanently disable one room's cameras and lasers, loudly."""

        self._require_job()
        assert self.job is not None
        member = self._require_active(account.id)
        if room_id not in self.job.template.target_rooms:
            raise ValueError("That console is not part of this job.")
        instance_room = self._instance_rooms.get(prop_id)
        if instance_room != room_id:
            raise ValueError("That console is not here.")
        definition = self.runtime.world.props[self.runtime.world.rooms[room_id].props[prop_id].prop_id]
        if "heist-console" not in definition.tags:
            raise ValueError("That prop is not a security console.")
        now = _now()
        if now < self.job.console_ready_at:
            raise ValueError("The console is still tracing the last hack.")
        self.job.console_ready_at = now + CONSOLE_COOLDOWN
        for camera in self.job.generated.cameras:
            if camera.room_id == room_id:
                self.job.cameras_permanent.add(camera.prop_instance_id)
                await self._set_prop_state(camera.room_id, camera.prop_instance_id, "disabled")
        for laser in self.job.generated.lasers:
            if laser.room_id == room_id:
                self.job.lasers_permanent.add(laser.prop_instance_id)
                await self._unblock_exit(laser.room_id, laser.exit_id, "laser")
                await self._set_prop_state(laser.room_id, laser.prop_instance_id, "disabled")
        self.job.alarm_score = min(120.0, self.job.alarm_score + 15.0)
        result = HeistResult(message="Console hacked. This room's security is dark, but someone heard the typing.")
        result.room_broadcasts.append(PendingRoomBroadcast(room_id=room_id, event={"type": "room.refresh", "room_id": room_id}))
        result.payload = {"status": await self.status_payload()}
        return result

    async def loot_prop(self, account: object, room_id: str, prop_id: str) -> HeistResult:
        """Take provisional loot from an opened vault."""

        self._require_job()
        assert self.job is not None
        member = self._require_active(account.id)
        if room_id != self.job.template.vault_room_id or self.job.vault.status != "open":
            raise ValueError("The vault loot is not available yet.")
        spot = self.job.loot_active.get(prop_id)
        if spot is None or self._instance_rooms.get(prop_id) != room_id:
            raise ValueError("That loot is not part of this score.")
        if prop_id in self.job.loot_taken:
            raise ValueError("That loot is already gone.")
        value = int(spot["value"])
        if self.job.bot is not None and self.job.bot.role_id == "muscle":
            value = int(round(value * 1.2))
        member.provisional.append(LootAward(prop_instance_id=prop_id, card_id=str(spot["card"]), value=value))
        self.job.loot_taken.add(prop_id)
        self.job.cards_stolen.add(str(spot["card"]))
        self.job.props_stolen.add(prop_id)
        await self._set_hidden(room_id, prop_id, True, "looted")
        result = HeistResult(message=f"Provisional loot secured: {value} Bops if you escape.")
        result.room_broadcasts.append(PendingRoomBroadcast(room_id=room_id, event={"type": "room.refresh", "room_id": room_id}))
        result.payload = {"status": await self.status_payload()}
        return result

    async def open_safecrack(self, account: object, room_id: str) -> HeistResult:
        """Open the safe-cracking activity for the crew's driller."""

        self._require_job()
        assert self.job is not None
        member = self._require_active(account.id)
        if room_id != self.job.template.vault_room_id:
            raise ValueError("The safe is in the vault room.")
        if not self._owns(account.id, "heist-drill"):
            raise ValueError("You need the vault drill.")
        if self.job.vault.status != "cracking" or self.job.vault.cracker_id != account.id:
            raise ValueError("Start the drill on the vault prop first.")
        definition = self.runtime.world.activities.get("safecrack")
        if definition is None:
            raise ValueError("Safecracking is unavailable.")
        difficulty = 2 + self.job.template.heat_tier
        session, replaced = self.runtime.activities.start(
            account_id=account.id,
            kind="safecrack",
            title="Safecrack",
            room_id=room_id,
            replace_existing=True,
            config={
                "seed": f"{self.job.seed}:{self.job.vault.attempts}",
                "difficulty": difficulty,
                "time_limit_seconds": self._crack_time_limit(),
            },
        )
        self.job.vault.session_id = session.id
        result = HeistResult(message="The drill bites. Keep the room quiet.")
        if replaced is not None:
            result.private_events.append({"type": "activity.closed", "activity": self.runtime.activities.serialize(replaced), "reason": "replaced"})
        result.private_events.append({"type": "activity.started", "activity": self.runtime.activities.serialize(session)})
        result.payload = {"status": await self.status_payload()}
        return result

    async def safecrack_result(
        self, account: object, room_id: str, symbols: list[str], seconds: float
    ) -> HeistResult:
        """Resolve one safe-cracking attempt from the activity bridge command."""

        self._require_job()
        assert self.job is not None
        member = self._require_active(account.id)
        if room_id != self.job.template.vault_room_id or self.job.vault.status != "cracking":
            raise ValueError("There is no live cracking attempt.")
        if self.job.vault.cracker_id != account.id:
            raise ValueError("Only the driller can report this attempt.")
        if not self._owns(account.id, "heist-drill"):
            raise ValueError("You need the vault drill.")
        attempts = self.job.vault.attempts
        session = self.runtime.activities.get(account.id)
        if session is None or session.kind != "safecrack" or session.id != self.job.vault.session_id:
            self.job.vault = VaultAttempt(status="locked", attempts=attempts)
            raise ValueError("The cracking session is no longer active.")
        elapsed = float(seconds)
        if not math.isfinite(elapsed) or elapsed < SAFECRACK_MIN_SECONDS or elapsed > self._crack_time_limit():
            self.job.vault = VaultAttempt(status="locked", attempts=attempts)
            raise ValueError("That cracking report looks tampered with.")
        expected = safecrack_sequence(
            f"{self.job.seed}:{attempts}", 2 + self.job.template.heat_tier
        )
        attempt = [str(symbol).strip().lower() for symbol in symbols or []]
        if attempt != expected:
            self.job.vault = VaultAttempt(status="locked", attempts=attempts)
            self.job.cooldowns[(account.id, "heist-drill")] = _now() + 10.0
            self.job.alarm_score = min(120.0, self.job.alarm_score + 10.0)
            result = HeistResult(message="The drill slips. The vault stays shut and the noise carries.")
            result.payload = {"status": await self.status_payload()}
            return result
        self.job.vault = VaultAttempt(status="open", attempts=attempts)
        self.job.phase = "vault"
        await self._set_prop_state(room_id, "vault-door", "open")
        result = HeistResult(message="The vault sighs open. Close the safecrack window and grab the loot.")
        result.room_broadcasts.extend(await self._cutscene_broadcasts("vault-open", room_id, "room"))
        result.room_broadcasts.append(PendingRoomBroadcast(room_id=room_id, event={"type": "room.refresh", "room_id": room_id}))
        result.payload = {"status": await self.status_payload()}
        return result

    async def escape_job(self, account: object, room_id: str) -> HeistResult:
        """Pay provisional loot and move one crew member to the hideout."""

        self._require_job()
        assert self.job is not None
        member = self._require_active(account.id)
        if room_id not in self.job.template.escape_rooms:
            raise ValueError("Escape from the alley or the roof.")
        if room_id == "bank-roof" and self.job.exit_blocks.get(("bank-roof", "alley")):
            raise ValueError("Rig the rappel line before escaping from the roof.")
        payout = sum(award.value for award in member.provisional)
        cards = [award.card_id for award in member.provisional]
        ledger = f"heist:{self.job.run_id}:{account.id}:loot"
        with self.runtime.hub.transaction() as connection:
            self.runtime.progression.grant_in_transaction(
                connection, account.id, bops=payout, cards=tuple(cards), ledger_key=ledger, kind="heist-loot"
            )
        member.provisional.clear()
        member.status = "escaped"
        member.inside = False
        self.job.paid_total += payout
        navigation = await self.runtime.rooms.enter_room(account, room_id, HIDEOUT_ROOM, direction="a getaway")
        result = HeistResult(
            message=f"Clean hands, {payout} Bops. The fence will remember this.",
            navigation=navigation,
            refresh_user=True,
        )
        account_record = self.runtime.profiles.get_account_by_id(account.id)
        if account_record is not None:
            result.private_events.extend(await self._cutscene_events(account_record, HIDEOUT_ROOM, "clean-escape", "private"))
        if not self._anyone_inside():
            result.room_broadcasts.extend(await self._finalize())
        else:
            result.payload = {"status": await self.status_payload()}
        return result

    async def heat_payload(self, account_id: str) -> dict[str, object]:
        """Return heat and recent history for one account."""

        meta = self._read_meta()
        return {
            "heat": self._decayed_heat(meta, account_id),
            "history": meta.get("history", [])[-10:],
            "laylow_price": 25,
        }

    async def lay_low(self, account: object) -> HeistResult:
        """Pay the fence to reduce heat by one."""

        self._require_available()
        price = 25
        heat = self.heat_for(account.id)
        if heat <= 0:
            raise ValueError("You have no heat to lose.")
        self._spend(account, price, "laying low")
        today = date.today().isoformat()

        def mutate(meta: dict[str, Any]) -> None:
            entry = meta.setdefault("heat", {}).setdefault(account.id, {"value": 0, "day": today})
            entry["value"] = max(0, self._decayed_heat(meta, account.id) - 1)
            entry["day"] = today

        with self.runtime.hub.transaction() as connection:
            current = self.runtime.profiles.get_account_by_id(account.id)
            if current is None:
                raise ValueError("That account no longer exists.")
            self.runtime.profiles.update_progress(connection, current, bops=current.bops - price)
            self._write_meta(connection, mutate)
        return HeistResult(message="Mara loses your paperwork. Heat down by one.", refresh_user=True)

    def _require_available(self) -> None:
        if not self.available:
            raise ValueError("Tiny Vault heists are not available here.")

    def _require_job(self) -> None:
        self._require_available()
        if self.job is None:
            raise ValueError("There is no active heist.")

    def _require_active(self, account_id: str) -> CrewMember:
        assert self.job is not None
        member = self.job.crew.get(account_id)
        if member is None or member.status != "active":
            raise ValueError("Only active crew can do that.")
        return member

    def _owns(self, account_id: str, card_id: str) -> bool:
        return any(
            stack.card_def_id == card_id
            for stack in self.runtime.profiles.list_inventory(account_id, WORLD_ID)
        )

    def _ready(self, account_id: str, tool_id: str) -> bool:
        """Return whether a reusable tool's cooldown has elapsed."""

        if self.job is None:
            return True
        return _now() >= self.job.cooldowns.get((account_id, tool_id), 0.0)

    def _consume_tool(self, account_id: str, card_id: str) -> None:
        stacks = [
            stack
            for stack in self.runtime.profiles.list_inventory(account_id, WORLD_ID)
            if stack.card_def_id == card_id
        ]
        if not stacks:
            raise ValueError("That consumable is already gone.")
        stack = sorted(stacks, key=lambda item: item.quantity)[0]
        with self.runtime.hub.transaction() as connection:
            self.runtime.profiles.remove_inventory_quantity(
                connection, account_id=account_id, world_id=WORLD_ID, stack_id=stack.stack_id, quantity=1
            )

    def _spend(self, account: object, price: int, label: str) -> None:
        current = self.runtime.profiles.get_account_by_id(account.id)
        if current is None or current.bops < price:
            raise ValueError(f"You need {price} Bops for {label}.")

    def _charge_deposit(self, account: object, deposit: int) -> None:
        current = self.runtime.profiles.get_account_by_id(account.id)
        if current is None:
            raise ValueError("That account no longer exists.")
        if current.bops < deposit:
            raise ValueError(f"You need a {deposit} Bop deposit to start this job.")
        with self.runtime.hub.transaction() as connection:
            fresh = self.runtime.profiles.get_account_by_id(account.id)
            if fresh is None or fresh.bops < deposit:
                raise ValueError(f"You need a {deposit} Bop deposit to start this job.")
            self.runtime.profiles.update_progress(connection, fresh, bops=fresh.bops - deposit)

    def _tool_payload(self, tool_id: str, account_id: str) -> dict[str, object]:
        tool = self.content.tools[tool_id]
        ready_at = 0.0 if self.job is None else self.job.cooldowns.get((account_id, tool_id), 0.0)
        return {
            "id": tool.id,
            "label": tool.label,
            "price": tool.price,
            "kind": tool.kind,
            "owned": self._owns(account_id, tool_id),
            "cooldown_seconds": tool.cooldown_seconds,
            "ready_in_seconds": round(max(0.0, ready_at - _now()), 1),
            "duration_seconds": tool.duration_seconds,
        }

    def _read_meta(self) -> dict[str, Any]:
        raw = self.runtime.world_state.read_world_meta(META_KEY)
        if not raw:
            return {"heat": {}, "history": []}
        try:
            meta = json.loads(raw)
        except ValueError:
            return {"heat": {}, "history": []}
        if not isinstance(meta, dict):
            return {"heat": {}, "history": []}
        meta.setdefault("heat", {})
        meta.setdefault("history", [])
        return meta

    def _write_meta(self, connection: object, mutate: Any) -> dict[str, Any]:
        row = connection.execute("SELECT value FROM world.world_meta WHERE key = ?", (META_KEY,)).fetchone()
        try:
            meta = json.loads(row["value"]) if row is not None else {"heat": {}, "history": []}
        except ValueError:
            meta = {"heat": {}, "history": []}
        if not isinstance(meta, dict):
            meta = {"heat": {}, "history": []}
        meta.setdefault("heat", {})
        meta.setdefault("history", [])
        mutate(meta)
        self.runtime.world_state.write_world_meta(connection, META_KEY, json.dumps(meta))
        return meta

    def _decayed_heat(self, meta: dict[str, Any], account_id: str) -> int:
        entry = meta.get("heat", {}).get(account_id)
        if not isinstance(entry, dict):
            return 0
        try:
            last = date.fromisoformat(str(entry.get("day", date.today().isoformat())))
        except ValueError:
            last = date.today()
        days = max(0, (date.today() - last).days)
        return max(0, int(entry.get("value", 0)) - days)

    def _initialize_guards(self) -> None:
        assert self.job is not None
        guards: dict[str, GuardState] = {}
        for setup in self.job.generated.guards:
            route = setup.route
            guards[setup.peep_id] = GuardState(
                peep_id=setup.peep_id,
                room_id=route.room_id,
                route=route.waypoints,
                position=route.waypoints[0],
                facing=angle_to(route.waypoints[0], route.waypoints[1]) if len(route.waypoints) > 1 else 0.0,
                speed=route.speed,
                vision_range=route.vision_range,
                vision_cone=route.vision_cone,
            )
        self.job.guards = guards
        self.job.reinforcements = [setup.peep_id for setup in self.job.generated.reinforcements]

    async def _stage_job(self) -> None:
        assert self.job is not None
        if self.job.staged:
            return
        self.job.staged = True
        self.job.phase = "infiltration"
        self.job.infiltrated_at = _now()
        self.job.loot_active = {
            spot.prop_instance_id: {"card": spot.card_id, "value": spot.value, "room": spot.room_id}
            for spot in self.job.generated.loot
        }
        for guard in self.job.guards.values():
            await self._summon_guard(guard.peep_id, guard.room_id)
            await self._place_guard(guard)
        if self.job.bot is not None:
            await self._summon_bot()
        for door in self.job.template.doors:
            if door.locked:
                reason = "grapple" if door.prop_instance_id == "roof-drop" else "locked"
                await self._block_exit(door.room_id, door.exit_id, reason)
            await self._set_prop_state(door.room_id, door.prop_instance_id, "open" if not door.locked else "locked")
        for laser in self.job.generated.lasers:
            if laser.locked:
                await self._block_exit(laser.room_id, laser.exit_id, "laser")
            await self._set_prop_state(laser.room_id, laser.prop_instance_id, "active")
            self._security_visual[laser.prop_instance_id] = False
        for camera in self.job.generated.cameras:
            await self._set_prop_state(camera.room_id, camera.prop_instance_id, "active")
            self._security_visual[camera.prop_instance_id] = False
        await self._set_prop_state(self.job.template.vault_room_id, "vault-door", "locked")
        hidden: dict[str, dict[str, object]] = {}
        for spot in self.job.template.loot:
            if spot.prop_instance_id not in self.job.loot_active:
                hidden.setdefault(spot.room_id, {})[spot.prop_instance_id] = {"reason": "not-on-this-job"}
        for room_id, props in hidden.items():
            await self._merge_environment(room_id, {"hidden_props": props})
        for room_id in self.job.template.target_rooms:
            await broadcast_room_event(self.runtime, room_id=room_id, event={"type": "room.refresh", "room_id": room_id})

    async def _summon_guard(self, peep_id: str, room_id: str) -> None:
        try:
            result = await self.runtime.rooms.summon_npc(peep_id, room_id)
        except ValueError as exc:
            if "already" not in str(exc).lower():
                raise
            return
        await broadcast_room_event(self.runtime, room_id=result.source_room_id, event=result.source_event)
        await broadcast_room_event(self.runtime, room_id=result.destination_room_id, event=result.destination_event)

    async def _place_guard(self, guard: GuardState) -> None:
        try:
            position = self.runtime.rooms.sprites.set_npc_position(guard.peep_id, guard.room_id, *guard.position)
        except ValueError:
            position = self.runtime.rooms.sprites.ensure_npc(guard.peep_id, guard.room_id)
            if position is None:
                return
            guard.position = position
            return
        guard.position = position
        await broadcast_room_event(
            self.runtime,
            room_id=guard.room_id,
            event={"type": "peep.sprite", "room_id": guard.room_id, "peep_id": guard.peep_id, "position": list(position)},
        )

    async def _summon_bot(self) -> None:
        assert self.job is not None and self.job.bot is not None
        await self._summon_guard(self.job.bot.peep_id, self.job.template.entry_room_id)

    async def _block_exit(self, room_id: str, exit_id: str, reason: str) -> None:
        """Add one block reason to an exit and apply the combined state."""

        assert self.job is not None
        self.job.exit_blocks.setdefault((room_id, exit_id), set()).add(reason)
        await self._apply_exit_block(room_id, exit_id)

    async def _unblock_exit(self, room_id: str, exit_id: str, reason: str) -> None:
        """Remove one block reason from an exit and apply the combined state."""

        assert self.job is not None
        reasons = self.job.exit_blocks.setdefault((room_id, exit_id), set())
        reasons.discard(reason)
        await self._apply_exit_block(room_id, exit_id)

    async def _apply_exit_block(self, room_id: str, exit_id: str) -> None:
        assert self.job is not None
        reasons = sorted(self.job.exit_blocks.get((room_id, exit_id), ()))
        environment = self.runtime.environment.get(room_id)
        disabled = dict(environment.get("disabled_exits") or {})
        if reasons:
            disabled[exit_id] = {"reason": reasons[0]}
        else:
            disabled.pop(exit_id, None)
        update = self.runtime.environment.set(room_id, {"disabled_exits": disabled or None})
        await broadcast_room_event(self.runtime, room_id=room_id, event=update.event())

    async def _merge_environment(self, room_id: str, patch: dict[str, object]) -> None:
        environment = self.runtime.environment.get(room_id)
        merged: dict[str, object] = {}
        for key, value in patch.items():
            if isinstance(value, dict):
                merged[key] = {**(environment.get(key) or {}), **value}
            else:
                merged[key] = value
        update = self.runtime.environment.set(room_id, merged)
        await broadcast_room_event(self.runtime, room_id=room_id, event=update.event())

    async def _set_hidden(self, room_id: str, prop_id: str, hidden: bool, reason: str) -> None:
        environment = self.runtime.environment.get(room_id)
        props = dict(environment.get("hidden_props") or {})
        if hidden:
            props[prop_id] = {"reason": reason}
        else:
            props.pop(prop_id, None)
        update = self.runtime.environment.set(room_id, {"hidden_props": props or None})
        await broadcast_room_event(self.runtime, room_id=room_id, event=update.event())

    async def _set_prop_state(self, room_id: str, prop_id: str, state: str) -> None:
        try:
            event = self.runtime.rooms.set_prop_state(room_id, prop_id, state)
        except ValueError:
            return
        await broadcast_room_event(self.runtime, room_id=room_id, event=event)

    async def _use_lockpick(
        self, account: object, member: CrewMember, room_id: str, prop_id: str | None, now: float
    ) -> HeistResult:
        assert self.job is not None
        door = self._door_for_prop(room_id, prop_id)
        if door is None:
            raise ValueError("Pick a locked heist door.")
        if door.prop_instance_id in self.job.doors_unlocked:
            raise ValueError("That door is already open.")
        self.job.doors_unlocked.add(door.prop_instance_id)
        await self._unblock_exit(door.room_id, door.exit_id, "locked")
        await self._set_prop_state(door.room_id, door.prop_instance_id, "open")
        result = HeistResult(message="The lock gives up quietly.")
        result.room_broadcasts.append(PendingRoomBroadcast(room_id=room_id, event={"type": "room.refresh", "room_id": room_id}))
        return result

    async def _use_disguise(
        self, account: object, member: CrewMember, room_id: str, prop_id: str | None, now: float
    ) -> HeistResult:
        assert self.job is not None
        duration = self.content.tools["heist-disguise"].duration_seconds or 30.0
        self.job.disguised_until[account.id] = now + duration
        self.job.alarm_score = max(0.0, self.job.alarm_score - 12.0)
        return HeistResult(message=f"Disguise on. You look almost honest for {duration:.0f} seconds.")

    async def _use_smoke(
        self, account: object, member: CrewMember, room_id: str, prop_id: str | None, now: float
    ) -> HeistResult:
        assert self.job is not None
        duration = self.content.tools["heist-smoke"].duration_seconds or 20.0
        self.job.smoke_until[room_id] = now + duration
        result = HeistResult(message="Smoke blooms. Cameras see weather, not crime.")
        result.room_broadcasts.append(PendingRoomBroadcast(room_id=room_id, event={"type": "room.refresh", "room_id": room_id}))
        return result

    async def _use_emp(
        self, account: object, member: CrewMember, room_id: str, prop_id: str | None, now: float
    ) -> HeistResult:
        assert self.job is not None
        if prop_id is None or self._instance_rooms.get(prop_id) != room_id:
            raise ValueError("Aim the EMP at a camera, laser, or console in this room.")
        prop = self.runtime.world.rooms[room_id].props.get(prop_id)
        if prop is None:
            raise ValueError("Aim the EMP at a camera, laser, or console in this room.")
        definition = self.runtime.world.props.get(prop.prop_id)
        if definition is None:
            raise ValueError("Aim the EMP at a camera, laser, or console in this room.")
        tags = set(definition.tags)
        duration = self.content.tools["heist-emp"].duration_seconds or 30.0
        if self.job.bot is not None and self.job.bot.role_id == "slicer":
            duration *= 1.5
        if "heist-camera" in tags:
            self.job.cameras_disabled_until[prop_id] = now + duration
            await self._set_prop_state(room_id, prop_id, "disabled")
        elif "heist-laser" in tags:
            laser = next((item for item in self.job.generated.lasers if item.prop_instance_id == prop_id), None)
            if laser is None:
                raise ValueError("That laser is not armed on this job.")
            self.job.lasers_disabled_until[prop_id] = now + duration
            await self._unblock_exit(laser.room_id, laser.exit_id, "laser")
            await self._set_prop_state(room_id, prop_id, "disabled")
        elif "heist-console" in tags:
            return await self.hack_console(account, room_id, prop_id)
        else:
            raise ValueError("The EMP only understands cameras and lasers.")
        self.job.alarm_score = min(120.0, self.job.alarm_score + 6.0)
        result = HeistResult(message="EMP pop. One electronic witness takes a nap.")
        result.room_broadcasts.append(PendingRoomBroadcast(room_id=room_id, event={"type": "room.refresh", "room_id": room_id}))
        return result

    async def _use_decoy(
        self, account: object, member: CrewMember, room_id: str, prop_id: str | None, now: float
    ) -> HeistResult:
        assert self.job is not None
        position = self.runtime.rooms.sprites.position_of_user(account.id)
        if position is None or position[0] != room_id:
            raise ValueError("Plant the decoy where you are standing.")
        duration = self.content.tools["heist-decoy"].duration_seconds or 18.0
        self.job.decoy_position = position[1]
        self.job.decoy_until = now + duration
        for guard in self.job.guards.values():
            if guard.room_id == room_id and guard.state != "alert":
                guard.state = "investigate"
                guard.last_seen = position[1]
                guard.investigate_until = now + duration
        self.job.alarm_score = min(120.0, self.job.alarm_score + 8.0)
        return HeistResult(message="The decoy chirps. Every nearby guard suddenly has somewhere to be.")

    async def _use_jammer(
        self, account: object, member: CrewMember, room_id: str, prop_id: str | None, now: float
    ) -> HeistResult:
        assert self.job is not None
        if self.job.jammer_used:
            raise ValueError("The crew already spent its one jammed alarm call.")
        duration = self.content.tools["heist-jammer"].duration_seconds or 60.0
        self.job.jammer_until = now + duration
        return HeistResult(message="Jammer armed. The next alarm call will die quietly.")

    async def _use_drill(
        self, account: object, member: CrewMember, room_id: str, prop_id: str | None, now: float
    ) -> HeistResult:
        assert self.job is not None
        if room_id != self.job.template.vault_room_id or prop_id != "vault-door":
            raise ValueError("Drill the vault door in the vault room.")
        if self.job.vault.status != "locked":
            raise ValueError("The vault is already being cracked or open.")
        self.job.vault = VaultAttempt(status="cracking", cracker_id=account.id, started_at=now, attempts=self.job.vault.attempts + 1)
        self.job.phase = "vault"
        self.job.alarm_score = min(120.0, self.job.alarm_score + 10.0)
        result = await self.open_safecrack(account, room_id)
        result.message = "The drill bites into the vault. Solve it before the room notices."
        return result

    async def _use_grapple(
        self, account: object, member: CrewMember, room_id: str, prop_id: str | None, now: float
    ) -> HeistResult:
        assert self.job is not None
        if room_id != "bank-roof" or prop_id != "roof-winch":
            raise ValueError("Rig the rappel line from the roof winch.")
        await self._unblock_exit("bank-roof", "alley", "grapple")
        result = HeistResult(message="The rappel line is rigged. The roof is now an escape.")
        result.room_broadcasts.append(PendingRoomBroadcast(room_id=room_id, event={"type": "room.refresh", "room_id": room_id}))
        return result

    def _door_for_prop(self, room_id: str, prop_id: str | None) -> Any | None:
        assert self.job is not None
        if prop_id is None or self._instance_rooms.get(prop_id) != room_id:
            return None
        return next((door for door in self.job.template.doors if door.room_id == room_id and door.prop_instance_id == prop_id), None)

    def _crack_time_limit(self) -> float:
        assert self.job is not None
        limit = SAFECRACK_SECONDS
        if self.job.bot is not None and self.job.bot.role_id == "muscle":
            limit *= 0.7
        return limit

