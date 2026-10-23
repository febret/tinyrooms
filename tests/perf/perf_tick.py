"""Idle behavior-tick cost as a world gains rooms and connected players.

The ticker runs forever at a fixed interval, so its per-tick cost is multiplied
by both the number of connected players and the number of rooms in the world.
``RoomTicker.start`` used to create one asyncio task per room in the world, all
of them waking every second, including every player classroom ever created and
almost all of them permanently empty.
"""

from __future__ import annotations

import asyncio

from server.behaviors.ticker import RoomTicker
from server.connections import SyntheticConnection
from tests.perf.perfkit import PerfCase, sql_counter
from tests.perf.synthetic import ENTRY_ROOM, temp_world

OCCUPANTS = 25
WORLD_ROOMS = 40


class _StubDispatcher:
    """A dispatcher that records dispatches and does no work."""

    def __init__(self) -> None:
        self.events: list[str] = []

    async def dispatch(self, event: object) -> None:
        self.events.append(getattr(event, "type", "?"))


class TickerSchedulingTests(PerfCase):
    """The scheduler must not scale its task count with the size of the world."""

    async def test_task_count_does_not_grow_with_the_world(self) -> None:
        with temp_world(rooms=WORLD_ROOMS) as (_root, runtime, _hub):
            ticker = RoomTicker(
                dispatcher=_StubDispatcher(),  # type: ignore[arg-type]
                world=runtime.world,
                interval=3600.0,
            )
            baseline = len(asyncio.all_tasks())
            ticker.start()
            await asyncio.sleep(0)
            scheduled = len(asyncio.all_tasks()) - baseline
            ticker.stop()
            await asyncio.sleep(0)

            self.measure(
                "server/tick/scheduled-tasks",
                scheduled,
                unit="tasks",
                ceiling=2,
                note=(
                    f"asyncio tasks created to tick a {WORLD_ROOMS}-room world. One task per room "
                    f"would be {WORLD_ROOMS}."
                ),
            )
            self.assertLessEqual(
                scheduled,
                2,
                f"ticking a {WORLD_ROOMS}-room world created {scheduled} tasks; the scheduler "
                "should use a single task",
            )

    async def test_stop_clears_the_overlap_guard(self) -> None:
        with temp_world(rooms=1) as (_root, runtime, _hub):
            dispatcher = _StubDispatcher()
            ticker = RoomTicker(
                dispatcher=dispatcher,  # type: ignore[arg-type]
                world=runtime.world,
                interval=3600.0,
            )
            await ticker.run_once(ENTRY_ROOM)
            self.assertEqual(dispatcher.events, ["tick"], "a lone room should still tick")
            ticker.stop()
            self.assertEqual(ticker._running, set(), "stop() left rooms marked as running")


class OccupiedRoomTickTests(PerfCase):
    """Per-tick work must be proportional to the room's occupants, not the world."""

    async def test_repeat_ticks_in_one_room_are_cheap(self) -> None:
        with temp_world(rooms=1) as (_root, runtime, hub):
            dispatcher = _StubDispatcher()
            runtime.bind(hub)  # type: ignore[arg-type]
            connections = runtime.connections
            accounts = [runtime.create_account(f"tick{index:03d}") for index in range(OCCUPANTS)]
            for account in accounts:
                await connections.register(
                    SyntheticConnection(account.id, account.username_display)
                )
                await connections.set_room(account.id, ENTRY_ROOM)

            ticker = RoomTicker(
                dispatcher=dispatcher,  # type: ignore[arg-type]
                world=runtime.world,
                connections=connections,
                interval=3600.0,
            )
            await ticker.run_once(ENTRY_ROOM)
            with sql_counter(hub.connection) as statements:
                for _ in range(5):
                    await ticker.run_once(ENTRY_ROOM)

            self.measure(
                "server/tick/queries/5-ticks-25-occupants",
                len(statements),
                unit="queries",
                ceiling=0,
                note=(
                    f"SQL statements for 5 ticks in a room with {OCCUPANTS} occupants. A tick with "
                    "no expiring effects and no scripted behaviour should not touch the database."
                ),
            )
            self.assertEqual(
                len(statements),
                0,
                f"5 idle ticks issued {len(statements)} statements; steady-state ticking should be "
                "in-memory only",
            )
            self.assertEqual(len(dispatcher.events), 6, "not every tick was dispatched")
