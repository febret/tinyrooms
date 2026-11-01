"""Dedicated realtime ticker for room activity controllers."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from server.behaviors.events import BehaviorEvent, PropRef
from server.behaviors.ticker import SYSTEM_PEEP


class ActivityTicker:
    """Dispatch ``activity_tick`` to realtime room activities at their own rate.

    Unlike the global 1 Hz room ticker, this loop only targets rooms with an
    authored ``tick_hz`` activity config and an open activity session, so the
    paintball arena can simulate at 15 Hz without waking every room script in
    the process. Activity state is memory-only and resets on restart.
    """

    def __init__(
        self,
        *,
        dispatcher,
        world,
        connections=None,
        activities=None,
        on_result: Callable[[object], Awaitable[None]] | None = None,
        default_interval: float = 0.05,
        logger: logging.Logger | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._world = world
        self._connections = connections
        self._activities = activities
        self._on_result = on_result
        self._default_interval = max(0.01, float(default_interval))
        self._logger = logger or logging.getLogger("tinyrooms.activities")
        self._task: asyncio.Task[None] | None = None
        self._next_due: dict[tuple[str, str], float] = {}

    def start(self) -> None:
        """Start the scheduler task; a no-op when already started."""

        if self._task is not None and not self._task.done():
            return
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._loop())

    def stop(self) -> None:
        """Cancel the scheduler task."""

        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._next_due.clear()

    def _tick_hz(self, config: object) -> float:
        if not isinstance(config, dict):
            return 0.0
        try:
            value = float(config.get("tick_hz", 0.0))
        except (TypeError, ValueError):
            return 0.0
        return min(60.0, max(0.0, value))

    async def _has_watchers(self, room_id: str, kind: str) -> bool:
        if self._activities is not None and hasattr(self._activities, "has_sessions"):
            return bool(self._activities.has_sessions(room_id, kind))
        return True

    async def _room_occupied(self, room_id: str) -> bool:
        if self._connections is None:
            return False
        occupants = await self._connections.list_room(room_id)
        return bool(occupants)

    async def run_once(self, room_id: str, kind: str) -> None:
        """Dispatch one activity tick to a room activity's controller prop."""

        room = self._world.rooms.get(room_id)
        if room is None:
            return
        activity = room.activities.get(kind)
        if activity is None:
            return
        if not await self._room_occupied(room_id):
            return
        if not await self._has_watchers(room_id, kind):
            return
        instance = room.props.get(activity.controller)
        if instance is None:
            return
        event = BehaviorEvent(
            type="activity_tick",
            actor=SYSTEM_PEEP,
            target=PropRef(instance_id=instance.id, prop_id=instance.prop_id, room_id=room_id),
            room_id=room_id,
            action=kind,
            data={"kind": kind},
        )
        result = await self._dispatcher.dispatch(event)
        if self._on_result is not None and result is not None:
            await self._on_result(result)

    async def _loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._default_interval)
                now = time.monotonic()
                for room in tuple(self._world.rooms.values()):
                    for kind, activity in room.activities.items():
                        hertz = self._tick_hz(activity.config)
                        if hertz <= 0:
                            continue
                        key = (room.id, kind)
                        if now < self._next_due.get(key, 0.0):
                            continue
                        self._next_due[key] = now + 1.0 / hertz
                        await self.run_once(room.id, kind)
        except asyncio.CancelledError:
            raise
