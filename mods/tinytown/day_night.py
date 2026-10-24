"""Server-authoritative day-night cycle for TinyTown rooms."""

from __future__ import annotations

import asyncio
import logging


LOGGER = logging.getLogger("tinyrooms.mod.tinytown")


class DayNightCycle:
    """Drive every inheriting tinytown room through the town's day-night cycle.

    The shared phase uses the same wall-clock epoch as the town diorama
    board, so basic home rooms transition in step with the town view.
    Only occupied rooms receive a broadcast, and only when the resolved
    environment band actually changes. The refresh prompts clients to
    re-snapshot, which carries the fresh lighting preset.
    """

    INTERVAL_SECONDS = 10.0

    def __init__(self, runtime: object) -> None:
        self._runtime = runtime
        self._task: object | None = None

    def start(self) -> None:
        """Pin the current cycle and begin the background band watcher."""

        if self._task is not None and not getattr(self._task, "done", lambda: True)():
            return
        if getattr(getattr(self._runtime, "world", None), "id", None) != "tinytown":
            return
        if getattr(self._runtime, "lighting", None) is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._apply()
        self._task = loop.create_task(self._loop())

    def stop(self) -> None:
        """Cancel the background watcher."""

        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.INTERVAL_SECONDS)
            try:
                self._apply()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - day-night must never stop the world loop
                LOGGER.exception("tinytown.day_night_failed")

    def _apply(self) -> None:
        lighting = getattr(self._runtime, "lighting", None)
        if lighting is None:
            return
        changed = lighting.apply_cycle()
        if not changed:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._broadcast(changed))

    async def _broadcast(self, changed: dict[str, str]) -> None:
        from server.broadcast import broadcast_room_event

        connections = getattr(self._runtime, "connections", None)
        for room_id in changed:
            try:
                occupied = await connections.list_room(room_id) if connections is not None else []
            except Exception:  # noqa: BLE001 - presence checks must not break the cycle
                continue
            if not occupied:
                continue
            try:
                await broadcast_room_event(
                    self._runtime,
                    room_id=room_id,
                    event={"type": "room.refresh", "room_id": room_id},
                )
            except Exception:  # noqa: BLE001 - broadcast failures must not break the cycle
                LOGGER.exception("tinytown.day_night_broadcast_failed")
