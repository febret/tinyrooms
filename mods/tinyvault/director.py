"""Guard direction, alarms, escapes, payouts, and supervision for Tiny Vault."""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import date
from typing import Any

from mods.tinyvault.guards import GuardState, advance_patrol, angle_to, can_see, move_toward, suspicion_rate
from mods.tinyvault.models import (
    BRIEFING_SECONDS,
    CATCH_DISTANCE,
    ESCAPE_DISTANCE,
    GUARD_BUBBLE_SECONDS,
    HANGAR_ROOM,
    HIDEOUT_ROOM,
    LOCKDOWN_SECONDS,
    RECOVERY_PEEPS,
    TARGET_ROOMS,
    VaultAttempt,
    iso_now,
    monotonic_now,
)
from server.broadcast import broadcast_room_event
from server.commands.outcomes import PendingRoomBroadcast
from server.protocol import room_snapshot_envelope


LOGGER = logging.getLogger("tinyrooms.tinyvault")


class HeistDirector:
    """Tick, alarm, payout, and recovery behavior mixed into HeistService."""

    runtime: Any
    job: Any
    content: Any
    _room_last_tick: dict[str, float]
    _move_budget: dict[str, Any]
    _guard_bubble_at: dict[str, float]
    _needs_recovery: bool

    async def tick_room(self, room_id: str, now: float) -> list[PendingRoomBroadcast]:
        """Advance one occupied target room and return its broadcasts."""

        assert self.job is not None
        last = self._room_last_tick.get(room_id, now)
        delta = min(5.0, max(0.05, now - last))
        self._room_last_tick[room_id] = now
        broadcasts: list[PendingRoomBroadcast] = []
        await self._move_guards(room_id, now, delta, broadcasts)
        await self._observe_room(room_id, now, delta, broadcasts)
        if self.job is None:
            return broadcasts
        await self._sync_security(room_id, now, broadcasts)
        if self.job is None:
            return broadcasts
        await self._check_vault_attempt(now, broadcasts)
        await self._check_auto_escape(room_id, broadcasts)
        if self.job is None:
            return broadcasts
        await self._check_alarm(now, room_id, broadcasts)
        await self._check_lockdown(now, broadcasts)
        return broadcasts

    async def supervise(self) -> None:
        """Reconcile disconnects, timeouts, and stale security once per second."""

        while True:
            await asyncio.sleep(1.0)
            try:
                if not self.available:
                    continue
                if self._needs_recovery:
                    await self._recover_stale_security()
                    self._needs_recovery = False
                if self.job is None:
                    await self._return_strays()
                    continue
                await self._supervise_job()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - supervision must not stop
                LOGGER.exception("tinyvault.supervise_failed")

    async def _move_guards(
        self, room_id: str, now: float, delta: float, broadcasts: list[PendingRoomBroadcast]
    ) -> None:
        assert self.job is not None
        for guard in self.job.guards.values():
            if guard.room_id != room_id:
                continue
            if guard.state == "investigate" and guard.last_seen is not None:
                move_toward(guard, guard.last_seen, guard.speed + 2.0, delta)
                if math.hypot(guard.last_seen[0] - guard.position[0], guard.last_seen[1] - guard.position[1]) < 2.0:
                    guard.pause_until = now + 2.5
                    if now >= guard.investigate_until:
                        guard.state = "patrol"
                        guard.last_seen = None
            elif guard.state == "alert" and self.job.decoy_position is not None and now < self.job.decoy_until:
                move_toward(guard, self.job.decoy_position, guard.speed + 3.0, delta)
            else:
                advance_patrol(guard, now, delta)
            try:
                position = self.runtime.rooms.sprites.set_npc_position(guard.peep_id, room_id, *guard.position)
            except ValueError:
                continue
            guard.position = position
            broadcasts.append(
                PendingRoomBroadcast(
                    room_id=room_id,
                    event={"type": "peep.sprite", "room_id": room_id, "peep_id": guard.peep_id, "position": list(position)},
                )
            )
            if guard.state in {"suspicious", "investigate", "alert"}:
                last = self._guard_bubble_at.get(guard.peep_id, 0.0)
                if now - last >= GUARD_BUBBLE_SECONDS:
                    self._guard_bubble_at[guard.peep_id] = now
                    text = {"suspicious": "Hm?", "investigate": "Who's there?", "alert": "Stop right there!"}[guard.state]
                    broadcasts.append(
                        PendingRoomBroadcast(
                            room_id=room_id,
                            event={
                                "type": "emote.bubble",
                                "room_id": room_id,
                                "source_id": guard.peep_id,
                                "speaker_id": guard.peep_id,
                                "source": self.runtime.world.peeps[guard.peep_id].label,
                                "bubble": {"kind": "expression", "text": f"{text} ({guard.suspicion:.0f})"},
                                "card_id": None,
                            },
                        )
                    )
        await self._move_bot(room_id, delta, broadcasts)

    async def _move_bot(self, room_id: str, delta: float, broadcasts: list[PendingRoomBroadcast]) -> None:
        assert self.job is not None
        if self.job.bot is None or not self.job.entered:
            return
        leader = self.job.crew.get(self.job.leader_id)
        if leader is None:
            return
        connection = await self.runtime.connections.get(leader.account_id)
        leader_room = connection.room_id if connection is not None else None
        if leader_room != room_id:
            return
        leader_position = self.runtime.rooms.sprites.position_of_user(leader.account_id)
        if leader_position is None or leader_position[0] != room_id:
            return
        target = (min(94.0, leader_position[1][0] + 6.0), min(94.0, leader_position[1][1] + 5.0))
        try:
            position = self.runtime.rooms.sprites.set_npc_position(self.job.bot.peep_id, room_id, *target)
        except ValueError:
            return
        broadcasts.append(
            PendingRoomBroadcast(
                room_id=room_id,
                event={"type": "peep.sprite", "room_id": room_id, "peep_id": self.job.bot.peep_id, "position": list(position)},
            )
        )

    async def _observe_room(
        self, room_id: str, now: float, delta: float, broadcasts: list[PendingRoomBroadcast]
    ) -> None:
        assert self.job is not None
        connections = await self.runtime.connections.list_room(room_id)
        crew_here = [
            self.job.crew[connection.account_id]
            for connection in connections
            if connection.account_id in self.job.crew and self.job.crew[connection.account_id].status == "active"
        ]
        if not crew_here:
            self._decay_guards(room_id, delta)
            return
        smoke = now < self.job.smoke_until.get(room_id, 0.0)
        look_factor = 0.75 if self.job.bot is not None and self.job.bot.role_id == "lookout" else 1.0
        for guard in self.job.guards.values():
            if guard.room_id != room_id:
                continue
            seen: tuple[float, float] | None = None
            seen_member = None
            for member in crew_here:
                position = self.runtime.rooms.sprites.position_of_user(member.account_id)
                if position is None or position[0] != room_id:
                    continue
                visibility = 0.65 if now < self.job.disguised_until.get(member.account_id, 0.0) else 1.0
                if can_see(guard.position, guard.facing, position[1], guard.vision_range, guard.vision_cone, obscured=smoke, visibility=visibility):
                    seen = position[1]
                    seen_member = member
                    break
            if seen is not None and seen_member is not None:
                distance = math.hypot(seen[0] - guard.position[0], seen[1] - guard.position[1])
                guard.suspicion = min(100.0, guard.suspicion + suspicion_rate(distance, guard.vision_range) * delta * look_factor)
                guard.last_seen = seen
                guard.investigate_until = now + 12.0
                guard.state = "alert" if guard.suspicion >= 100.0 else "investigate" if guard.suspicion >= 55.0 else "suspicious"
                self.job.alarm_score = min(120.0, self.job.alarm_score + (4.0 + distance / 10.0) * delta * look_factor)
                if guard.suspicion >= 100.0 and self.job.alarm_stage in {"calm", "suspicious"}:
                    await self._raise_alarm(now, room_id, broadcasts)
                if self.job.alarm_stage in {"alarm", "lockdown"} and distance <= CATCH_DISTANCE:
                    await self._catch(seen_member.account_id, room_id, broadcasts)
                    return
            else:
                guard.suspicion = max(0.0, guard.suspicion - 6.0 * delta)
                if guard.suspicion < 30.0 and guard.state == "suspicious":
                    guard.state = "patrol"
        for camera in self.job.generated.cameras:
            if camera.room_id != room_id or camera.prop_instance_id in self.job.cameras_permanent:
                continue
            if now < self.job.cameras_disabled_until.get(camera.prop_instance_id, 0.0) or smoke:
                continue
            for member in crew_here:
                position = self.runtime.rooms.sprites.position_of_user(member.account_id)
                if position is None or position[0] != room_id:
                    continue
                visibility = 0.65 if now < self.job.disguised_until.get(member.account_id, 0.0) else 1.0
                if can_see(camera.position, camera.facing, position[1], camera.vision_range, camera.vision_cone, visibility=visibility):
                    self.job.alarm_score = min(120.0, self.job.alarm_score + 9.0 * delta * look_factor)
                    break
        if any(laser.room_id == room_id and self._laser_active(laser, now) for laser in self.job.generated.lasers):
            self.job.alarm_score = min(120.0, self.job.alarm_score + 1.5 * delta)

    def _decay_guards(self, room_id: str, delta: float) -> None:
        assert self.job is not None
        for guard in self.job.guards.values():
            if guard.room_id == room_id and guard.state != "alert":
                guard.suspicion = max(0.0, guard.suspicion - 6.0 * delta)
                if guard.suspicion < 30.0:
                    guard.state = "patrol"

    def _laser_active(self, laser: object, now: float) -> bool:
        assert self.job is not None
        if laser.prop_instance_id in self.job.lasers_permanent:
            return False
        return now >= self.job.lasers_disabled_until.get(laser.prop_instance_id, 0.0)

    async def _sync_security(self, room_id: str, now: float, broadcasts: list[PendingRoomBroadcast]) -> None:
        """Re-arm expired EMP shutdowns so exits block and props look right again."""

        assert self.job is not None
        for camera in self.job.generated.cameras:
            if camera.room_id != room_id or camera.prop_instance_id in self.job.cameras_permanent:
                continue
            disabled = now < self.job.cameras_disabled_until.get(camera.prop_instance_id, 0.0)
            if self._security_visual.get(camera.prop_instance_id) != disabled:
                self._security_visual[camera.prop_instance_id] = disabled
                await self._set_prop_state(room_id, camera.prop_instance_id, "disabled" if disabled else "active")
        for laser in self.job.generated.lasers:
            if laser.room_id != room_id or laser.prop_instance_id in self.job.lasers_permanent:
                continue
            disabled = now < self.job.lasers_disabled_until.get(laser.prop_instance_id, 0.0)
            if self._security_visual.get(laser.prop_instance_id) != disabled:
                self._security_visual[laser.prop_instance_id] = disabled
                await self._set_prop_state(room_id, laser.prop_instance_id, "disabled" if disabled else "active")
            if laser.locked:
                want_block = not disabled
                enabled = self.runtime.environment.is_exit_enabled(room_id, laser.exit_id)
                if want_block == enabled:
                    if want_block:
                        await self._block_exit(room_id, laser.exit_id, "laser")
                    else:
                        await self._unblock_exit(room_id, laser.exit_id, "laser")

    async def _raise_alarm(self, now: float, room_id: str, broadcasts: list[PendingRoomBroadcast]) -> None:
        assert self.job is not None
        if self.job.alarm_stage in {"alarm", "lockdown"}:
            return
        if now < self.job.jammer_until and not self.job.jammer_used:
            self.job.jammer_used = True
            self.job.jammer_until = 0.0
            self.job.alarm_score = 70.0
            broadcasts.append(
                PendingRoomBroadcast(
                    room_id=room_id,
                    event={"type": "toast", "room_id": room_id, "tone": "info", "text": "The jammer eats the alarm call. Move now."},
                )
            )
            return
        self.job.alarm_stage = "alarm"
        self.job.alarm_at = now
        self.job.lockdown_at = now + LOCKDOWN_SECONDS
        for door in self.job.template.doors:
            if door.alarm_lock and door.prop_instance_id not in self.job.doors_unlocked:
                await self._block_exit(door.room_id, door.exit_id, "alarm")
        for peep_id in self.job.reinforcements:
            route = self.job.template.routes[peep_id]
            self.job.guards[peep_id] = GuardState(
                peep_id=peep_id,
                room_id=route.room_id,
                route=route.waypoints,
                position=route.waypoints[0],
                facing=angle_to(route.waypoints[0], route.waypoints[1]) if len(route.waypoints) > 1 else 0.0,
                speed=route.speed,
                vision_range=route.vision_range,
                vision_cone=route.vision_cone,
                state="alert",
                suspicion=80.0,
            )
            await self._summon_guard(peep_id, route.room_id)
            await self._place_guard(self.job.guards[peep_id])
        self.job.reinforcements.clear()
        self.job.alarm_raised = True
        broadcasts.extend(await self._cutscene_broadcasts("alarm-raised", room_id, "room"))
        for target in self.job.template.target_rooms:
            broadcasts.append(PendingRoomBroadcast(room_id=target, event={"type": "room.refresh", "room_id": target}))

    async def _check_alarm(self, now: float, room_id: str, broadcasts: list[PendingRoomBroadcast]) -> None:
        assert self.job is not None
        if self.job.alarm_stage in {"calm", "suspicious"} and self.job.alarm_score >= 100.0:
            await self._raise_alarm(now, room_id, broadcasts)
        elif self.job.alarm_stage == "calm" and self.job.alarm_score >= 40.0:
            self.job.alarm_stage = "suspicious"
            broadcasts.append(
                PendingRoomBroadcast(
                    room_id=room_id,
                    event={"type": "toast", "room_id": room_id, "tone": "warning", "text": "The guards are suspicious. Break sight lines."},
                )
            )
        if self.job.alarm_stage == "suspicious" and self.job.alarm_score < 25.0:
            self.job.alarm_stage = "calm"

    async def _check_lockdown(self, now: float, broadcasts: list[PendingRoomBroadcast]) -> None:
        assert self.job is not None
        expired = self.job.alarm_stage == "alarm" and now >= self.job.lockdown_at
        overtime = (
            self.job.infiltrated_at > 0.0
            and now - self.job.infiltrated_at >= self.job.template.time_limit_seconds
        )
        if not expired and not overtime:
            return
        self.job.alarm_stage = "lockdown"
        for member in list(self.job.crew.values()):
            if member.status != "active":
                continue
            connection = await self.runtime.connections.get(member.account_id)
            if connection is not None and connection.room_id in self.job.template.target_rooms:
                await self._catch(member.account_id, connection.room_id, broadcasts)
            if self.job is None:
                return
        if not self._anyone_inside():
            broadcasts.extend(await self._finalize())

    async def _check_vault_attempt(self, now: float, broadcasts: list[PendingRoomBroadcast]) -> None:
        assert self.job is not None
        vault = self.job.vault
        if vault.status != "cracking":
            return
        session = self.runtime.activities.get(vault.cracker_id)
        connection = await self.runtime.connections.get(vault.cracker_id)
        cracker = self.job.crew.get(vault.cracker_id)
        if (
            session is None
            or session.kind != "safecrack"
            or session.id != vault.session_id
            or connection is None
            or connection.room_id != self.job.template.vault_room_id
            or cracker is None
            or cracker.status != "active"
        ):
            self.job.vault = VaultAttempt(status="locked")
            broadcasts.append(
                PendingRoomBroadcast(
                    room_id=self.job.template.vault_room_id,
                    event={"type": "toast", "room_id": self.job.template.vault_room_id, "tone": "warning", "text": "The cracking attempt was interrupted."},
                )
            )

    async def _check_auto_escape(self, room_id: str, broadcasts: list[PendingRoomBroadcast]) -> None:
        assert self.job is not None
        if room_id not in self.job.template.escape_rooms:
            return
        getaway = next(
            (
                instance_id
                for instance_id, placed in self._instance_rooms.items()
                if placed == room_id
                and "heist-getaway" in self.runtime.world.props[self.runtime.world.rooms[room_id].props[instance_id].prop_id].tags
            ),
            None,
        )
        if getaway is None:
            return
        target = self.runtime.world.rooms[room_id].props[getaway].pos
        connections = await self.runtime.connections.list_room(room_id)
        for connection in connections:
            if self.job is None:
                return
            member = self.job.crew.get(connection.account_id)
            if member is None or member.status != "active":
                continue
            position = self.runtime.rooms.sprites.position_of_user(member.account_id)
            if position is None or position[0] != room_id:
                continue
            if math.hypot(position[1][0] - target[0], position[1][1] - target[1]) <= ESCAPE_DISTANCE:
                account = self.runtime.profiles.get_account_by_id(member.account_id)
                if account is None:
                    continue
                result = await self.escape_job(account, room_id)
                broadcasts.extend(result.room_broadcasts)
                if result.navigation is not None:
                    broadcasts.append(PendingRoomBroadcast(room_id=result.navigation.source_room_id, event=result.navigation.source_event))
                    broadcasts.append(PendingRoomBroadcast(room_id=result.navigation.destination_room_id, event=result.navigation.destination_event))
                    try:
                        await connection.send(room_snapshot_envelope(result.navigation.destination_snapshot))
                    except RuntimeError:
                        pass

    async def _catch(self, account_id: str, room_id: str, broadcasts: list[PendingRoomBroadcast]) -> None:
        assert self.job is not None
        member = self.job.crew.get(account_id)
        if member is None or member.status != "active":
            return
        account = self.runtime.profiles.get_account_by_id(account_id)
        member.status = "caught"
        member.provisional.clear()
        if account is not None:
            broadcasts.extend(await self._cutscene_private(account, "busted"))
            navigation = await self.runtime.rooms.enter_room(account, room_id, HIDEOUT_ROOM, direction="a guard's grip")
            broadcasts.append(PendingRoomBroadcast(room_id=navigation.source_room_id, event=navigation.source_event))
            broadcasts.append(PendingRoomBroadcast(room_id=navigation.destination_room_id, event=navigation.destination_event))
            connection = await self.runtime.connections.get(account_id)
            if connection is not None:
                await connection.send(room_snapshot_envelope(navigation.destination_snapshot))
        if not self._anyone_inside():
            broadcasts.extend(await self._finalize())

    def _anyone_inside(self) -> bool:
        assert self.job is not None
        return any(member.status == "active" for member in self.job.crew.values())

    async def _finalize(self) -> list[PendingRoomBroadcast]:
        assert self.job is not None
        broadcasts: list[PendingRoomBroadcast] = []
        escaped = [member for member in self.job.crew.values() if member.status == "escaped"]
        clean = bool(escaped) and not self.job.alarm_raised
        result = "clean" if clean else "completed" if escaped else "failed"
        elapsed = monotonic_now() - (self.job.infiltrated_at or self.job.started_at)
        speed_objective = next((item for item in self.job.template.objectives if item.kind == "speed"), None)
        if speed_objective is not None and speed_objective.seconds is not None and elapsed <= speed_objective.seconds and escaped:
            self.job.objectives_done.add("speedrun")
        bonus = self.job.template.rewards.bops // max(1, len(escaped)) if escaped else 0
        if clean:
            bonus += 15
        if "speedrun" in self.job.objectives_done:
            bonus += 10
        bonus += 5 * len(self.job.objectives_done)
        for member in escaped:
            ledger = f"heist:{self.job.run_id}:{member.account_id}:bonus"
            with self.runtime.hub.transaction() as connection:
                self.runtime.progression.grant_in_transaction(
                    connection,
                    member.account_id,
                    bops=bonus,
                    kudos=self.job.template.rewards.kudos,
                    ledger_key=ledger,
                    kind="heist-bonus",
                )
            first_ledger = f"heist-first:{self.job.template.id}:{member.account_id}"
            with self.runtime.hub.transaction() as connection:
                self.runtime.progression.grant_in_transaction(
                    connection, member.account_id, kudos=2, ledger_key=first_ledger, kind="heist-first"
                )
            changes = self.runtime.tasks.record(
                member.account_id,
                "signal",
                {
                    "event": "heist_job_complete",
                    "result": result,
                    "completed": "1" if result in {"clean", "completed"} else "0",
                    "clean": "1" if clean else "0",
                },
            )
            account = self.runtime.profiles.get_account_by_id(member.account_id)
            if account is not None:
                for event in self.runtime.tasks.feedback_events(member.account_id, changes, room_id=HIDEOUT_ROOM):
                    if event.get("type") == "cutscene.play":
                        event["account_id"] = member.account_id
                    broadcasts.append(PendingRoomBroadcast(room_id=HIDEOUT_ROOM, event=event))
        if escaped:
            with self.runtime.hub.transaction() as connection:
                self.runtime.progression.grant_in_transaction(
                    connection,
                    self.job.deposit_account_id,
                    bops=self.job.deposit,
                    ledger_key=f"heist:{self.job.run_id}:deposit",
                    kind="heist-deposit",
                )
        heat_gain = 0 if result == "failed" else 1 if clean else 2
        today = date.today().isoformat()

        def mutate(meta: dict[str, Any]) -> None:
            for member in escaped:
                entry = meta.setdefault("heat", {}).setdefault(member.account_id, {"value": 0, "day": today})
                entry["value"] = min(10, self._decayed_heat(meta, member.account_id) + heat_gain)
                entry["day"] = today
            history = meta.setdefault("history", [])
            history.append(
                {
                    "job_id": self.job.template.id if self.job else "unknown",
                    "run_id": self.job.run_id if self.job else "unknown",
                    "crew": sorted(member.account_id for member in escaped),
                    "result": result,
                    "loot": self.job.paid_total if self.job else 0,
                    "at": iso_now(),
                }
            )
            del history[:-25]

        with self.runtime.hub.transaction() as connection:
            self._write_meta(connection, mutate)
        await self._cleanup_security(broadcasts)
        self.job = None
        self._room_last_tick.clear()
        self._move_budget.clear()
        self._security_visual.clear()
        return broadcasts

    async def _abandon(self, *, refund: bool) -> None:
        assert self.job is not None
        if refund and self.job.deposit:
            with self.runtime.hub.transaction() as connection:
                self.runtime.progression.grant_in_transaction(
                    connection,
                    self.job.deposit_account_id,
                    bops=self.job.deposit,
                    ledger_key=f"heist:{self.job.run_id}:deposit",
                    kind="heist-deposit",
                )
        await self._cleanup_security([])
        self.job = None
        self._room_last_tick.clear()
        self._move_budget.clear()
        self._security_visual.clear()

    async def _cleanup_security(self, broadcasts: list[PendingRoomBroadcast]) -> None:
        assert self.job is not None
        for peep_id in (*self.job.guards, *(self.job.reinforcements or [])):
            await self._send_home(peep_id, broadcasts)
        if self.job.bot is not None:
            await self._send_home(self.job.bot.peep_id, broadcasts)
        for room_id in self.job.template.target_rooms:
            try:
                update = self.runtime.environment.set(room_id, {"disabled_exits": None, "hidden_props": None})
            except ValueError:
                continue
            event = PendingRoomBroadcast(room_id=room_id, event=update.event())
            broadcasts.append(event)
            await broadcast_room_event(self.runtime, room_id=room_id, event=update.event())
        for door in self.job.template.doors:
            await self._set_prop_state(door.room_id, door.prop_instance_id, "locked" if door.locked else "open")
        for camera in self.job.template.cameras:
            await self._set_prop_state(camera.room_id, camera.prop_instance_id, "active")
        for laser in self.job.template.lasers:
            await self._set_prop_state(laser.room_id, laser.prop_instance_id, "active")
        await self._set_prop_state(self.job.template.vault_room_id, "vault-door", "locked")

    async def _send_home(self, peep_id: str, broadcasts: list[PendingRoomBroadcast]) -> None:
        try:
            result = await self.runtime.rooms.summon_npc(peep_id, HANGAR_ROOM)
        except ValueError:
            return
        broadcasts.append(PendingRoomBroadcast(room_id=result.source_room_id, event=result.source_event))
        broadcasts.append(PendingRoomBroadcast(room_id=result.destination_room_id, event=result.destination_event))
        await broadcast_room_event(self.runtime, room_id=result.source_room_id, event=result.source_event)
        await broadcast_room_event(self.runtime, room_id=result.destination_room_id, event=result.destination_event)

    async def _supervise_job(self) -> None:
        assert self.job is not None
        if self.job.phase == "briefing" and monotonic_now() - self.job.started_at >= BRIEFING_SECONDS and not self.job.entered:
            await self._abandon(refund=True)
            return
        await self._prune_disconnected()
        if self.job is None:
            return
        for room_id in self.job.template.target_rooms:
            for connection in await self.runtime.connections.list_room(room_id):
                member = self.job.crew.get(connection.account_id)
                if member is None or member.status != "active":
                    account = self.runtime.profiles.get_account_by_id(connection.account_id)
                    if account is not None:
                        await self._move_account_home(account, room_id)

    async def _prune_disconnected(self) -> None:
        assert self.job is not None
        for member in list(self.job.crew.values()):
            if member.status != "active" or self.runtime.connections.is_online(member.account_id):
                continue
            member.status = "left"
            member.provisional.clear()
        actives = [item for item in self.job.crew.values() if item.status == "active"]
        if actives and self.job.leader_id not in {item.account_id for item in actives}:
            successor = sorted(actives, key=lambda item: item.joined_at)[0]
            successor.leader = True
            self.job.leader_id = successor.account_id
        if not actives and not self._anyone_inside():
            if self.job.entered:
                await self._finalize()
            else:
                await self._abandon(refund=True)

    async def _return_strays(self) -> None:
        for room_id in TARGET_ROOMS:
            for connection in await self.runtime.connections.list_room(room_id):
                account = self.runtime.profiles.get_account_by_id(connection.account_id)
                if account is not None:
                    await self._move_account_home(account, room_id)

    async def _recover_stale_security(self) -> None:
        for peep_id in RECOVERY_PEEPS:
            try:
                with self.runtime.hub.transaction() as connection:
                    self.runtime.peep_states.set_in_transaction(connection, peep_id, HANGAR_ROOM)
                    self.runtime.peep_states.record(peep_id, HANGAR_ROOM)
            except Exception:  # noqa: BLE001 - recovery must not stop startup
                LOGGER.exception("tinyvault.recover_peep_failed")
                continue
            self.runtime.rooms.sprites.forget_npc(peep_id)
        for room_id in TARGET_ROOMS:
            try:
                update = self.runtime.environment.set(room_id, {"disabled_exits": None, "hidden_props": None})
            except ValueError:
                continue
            await broadcast_room_event(self.runtime, room_id=room_id, event=update.event())

    async def _move_account_home(self, account: object, room_id: str) -> None:
        try:
            navigation = await self.runtime.rooms.enter_room(account, room_id, HIDEOUT_ROOM, direction="a service corridor")
        except ValueError:
            return
        await broadcast_room_event(self.runtime, room_id=navigation.source_room_id, event=navigation.source_event)
        await broadcast_room_event(self.runtime, room_id=navigation.destination_room_id, event=navigation.destination_event)
        connection = await self.runtime.connections.get(account.id)
        if connection is not None:
            try:
                await connection.send(room_snapshot_envelope(navigation.destination_snapshot))
            except RuntimeError:
                pass

    async def _cutscene_events(self, account: object, room_id: str, reference: str, audience: str) -> list[dict[str, object]]:
        try:
            definition = self.runtime.cutscenes.resolve(reference)
            launch = self.runtime.cutscenes.launch(
                definition=definition,
                account=account,
                room_id=room_id,
                audience=audience,
                origin="heist",
                occupants=await self._occupants(room_id),
            )
        except Exception:  # noqa: BLE001 - presentation must not break jobs
            LOGGER.exception("tinyvault.cutscene_failed")
            return []
        if launch.is_room_wide:
            return []
        return [launch.event]

    async def _cutscene_broadcasts(self, reference: str, room_id: str, audience: str) -> list[PendingRoomBroadcast]:
        connections = await self.runtime.connections.list_room(room_id)
        if not connections:
            return []
        account = self.runtime.profiles.get_account_by_id(connections[0].account_id)
        if account is None:
            return []
        try:
            definition = self.runtime.cutscenes.resolve(reference)
            launch = self.runtime.cutscenes.launch(
                definition=definition,
                account=account,
                room_id=room_id,
                audience=audience,
                origin="heist",
                occupants=[connection.account_id for connection in connections],
            )
        except Exception:  # noqa: BLE001 - presentation must not break jobs
            LOGGER.exception("tinyvault.cutscene_failed")
            return []
        if launch.is_room_wide:
            return [PendingRoomBroadcast(room_id=room_id, event=launch.event)]
        return []

    async def _cutscene_private(self, account: object, reference: str) -> list[PendingRoomBroadcast]:
        try:
            definition = self.runtime.cutscenes.resolve(reference)
            launch = self.runtime.cutscenes.launch(
                definition=definition, account=account, room_id=HIDEOUT_ROOM, audience="private", origin="heist"
            )
        except Exception:  # noqa: BLE001 - presentation must not break jobs
            LOGGER.exception("tinyvault.cutscene_failed")
            return []
        event = dict(launch.event)
        event["account_id"] = account.id
        return [PendingRoomBroadcast(room_id=HIDEOUT_ROOM, event=event)]

    async def _occupants(self, room_id: str) -> list[str]:
        return [connection.account_id for connection in await self.runtime.connections.list_room(room_id)]
