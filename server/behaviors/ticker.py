"""Per-room behavior tick loop with overlap protection."""

from __future__ import annotations

import asyncio
import logging

from server.behaviors.dispatcher import BehaviorDispatcher
from server.behaviors.events import BehaviorEvent, PeepRef
from server.content.worlds import WorldDefinition


SYSTEM_PEEP = PeepRef(kind="npc", peep_id=None, account_id=None)


class RoomTicker:
    """Owns one asyncio task per room and dispatches ``tick`` events."""

    def __init__(
        self,
        *,
        dispatcher: BehaviorDispatcher,
        world: WorldDefinition,
        interval: float = 1.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._world = world
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
        """Dispatch a single tick for *room_id*, skipping when one is running."""

        if room_id in self._running:
            return
        self._running.add(room_id)
        try:
            event = BehaviorEvent(
                type="tick",
                actor=SYSTEM_PEEP,
                target=None,
                room_id=room_id,
                action=None,
                data={},
            )
            await self._dispatcher.dispatch(event)
        finally:
            self._running.discard(room_id)
