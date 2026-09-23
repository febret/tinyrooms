"""Per-room behavior tick loop with overlap protection."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
import sqlite3

from server.behaviors.dispatcher import BehaviorDispatcher
from server.behaviors.events import BehaviorEvent, PeepRef
from server.commands.outcomes import PendingRoomBroadcast
from server.content.worlds import WorldDefinition


SYSTEM_PEEP = PeepRef(kind="npc", peep_id=None, account_id=None)


class RoomTicker:
    """Owns one asyncio task per room and dispatches ``tick`` events."""

    def __init__(
        self,
        *,
        dispatcher: BehaviorDispatcher,
        world: WorldDefinition,
        connections: object | None = None,
        environment: object | None = None,
        auras: object | None = None,
        on_result: Callable[[object], Awaitable[None]] | None = None,
        interval: float = 1.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._world = world
        self._connections = connections
        self._environment = environment
        self._auras = auras
        self._on_result = on_result
        self._interval = float(interval)
        self._logger = logger or logging.getLogger("tinyrooms.behaviors")
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._running: set[str] = set()

    def start(self) -> None:
        """Start one tick task per room; a no-op when already started."""

        if self._tasks:
            return
        loop = asyncio.get_running_loop()
        for room_id in self._world.rooms:
            self._tasks[room_id] = loop.create_task(self._loop(room_id))

    def stop(self) -> None:
        """Cancel all tick tasks."""

        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    async def _loop(self, room_id: str) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval)
                await self.run_once(room_id)
        except asyncio.CancelledError:
            raise

    async def run_once(self, room_id: str) -> None:
        """Dispatch a single tick for *room_id*, skipping empty or busy rooms."""

        if room_id in self._running:
            return
        occupants: list[object] = []
        if self._connections is not None:
            occupants = await self._connections.list_room(room_id)
            if not occupants:
                return
        self._running.add(room_id)
        try:
            self._apply_auras(room_id, occupants)
            event = BehaviorEvent(
                type="tick",
                actor=SYSTEM_PEEP,
                target=None,
                room_id=room_id,
                action=None,
                data={},
            )
            result = await self._dispatcher.dispatch(event)
            self._expire_environment(room_id, result)
            if self._on_result is not None and result is not None:
                await self._on_result(result)
        finally:
            self._running.discard(room_id)

    def _apply_auras(self, room_id: str, occupants: list[object]) -> None:
        if self._auras is None:
            return
        for occupant in occupants:
            account_id = getattr(occupant, "account_id", None)
            if not isinstance(account_id, str):
                continue
            try:
                self._auras.enter(account_id, room_id)
            except (ValueError, sqlite3.Error) as exc:
                self._logger.warning("aura.enter failed for %s: %s", account_id, exc)

    def _expire_environment(self, room_id: str, result: object) -> None:
        if self._environment is None or result is None:
            return
        update = self._environment.expire(room_id)
        if update is not None:
            result.room_broadcasts.append(PendingRoomBroadcast(room_id=room_id, event=update.event()))
