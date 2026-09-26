"""Idle behavior-tick cost as a world gains rooms and connected players.

The ticker runs forever at a fixed interval, so its per-tick cost is multiplied
by both the number of connected players and the number of rooms in the world.
Two properties were unguarded:

* ``AuraService.enter`` read the user profile to ask whether a room aura was
  already applied -- one query per occupant per second, forever, to establish
  that nothing had changed.
* ``RoomTicker.start`` created one asyncio task per room in the world, all of
  them waking every second, including every player bedroom ever created and
  almost all of them permanently empty.
"""

from __future__ import annotations

import asyncio

from server.behaviors.ticker import RoomTicker
from server.connections import SyntheticConnection
from server.services.auras import AuraService
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


class _StubStats:
    """Records aura source writes without touching a database."""

    def __init__(self) -> None:
        self.applied: list[tuple[str, str]] = []
        self.removed: list[tuple[str, str]] = []
        self.buffs: list[tuple[str, object]] = []

    def has_source(self, account_id: str, source: str) -> bool:
        return (account_id, source) in self.applied

    def apply_source(self, account_id: str, source: str, modifiers) -> None:
        self.applied.append((account_id, source))

    def remove_source(self, account_id: str, source: str) -> None:
        self.applied = [entry for entry in self.applied if entry != (account_id, source)]
        self.removed.append((account_id, source))

    def add_buff(self, account_id: str, instance: object) -> None:
        self.buffs.append((account_id, instance))


class AuraProbeTests(PerfCase):
    """Repeated aura probes for an already-applied aura must not read the database."""

    def test_reapplying_an_aura_is_free_after_the_first_time(self) -> None:
        with temp_world(rooms=1, aura_rooms=1) as (_root, runtime, hub):
            stats = _StubStats()
            auras = AuraService(hub, stats, runtime.world)  # type: ignore[arg-type]
            account_ids = [f"acct{index:03d}" for index in range(OCCUPANTS)]
            room = next(
                (room for room in runtime.world.rooms.values() if room.aura),
                None,
            )
            self.assertIsNotNone(room, "the generated world should define a room aura")
            for account_id in account_ids:
                auras.enter(account_id, room.id)
            applied_after_first = len(stats.applied)
            self.assertGreater(applied_after_first, 0, "no aura was applied at all")

            with sql_counter(hub.connection) as statements:
                for _ in range(10):
                    for account_id in account_ids:
                        auras.enter(account_id, room.id)

            self.assertEqual(
                len(stats.applied),
                applied_after_first,
                "re-applying an aura duplicated the source",
            )
            self.measure(
                "server/tick/aura-queries/10-ticks",
                len(statements),
                unit="queries",
                ceiling=0,
                note=(
                    f"SQL statements for 10 repeat probes across {OCCUPANTS} occupants in a room "
                    "with an aura already applied. All of them answered 'already applied'."
                ),
            )
            self.assertEqual(
                len(statements),
                0,
                f"repeat aura probes issued {len(statements)} queries; applied state should be "
                "tracked in memory",
            )

    def test_leaving_clears_the_cached_state(self) -> None:
        with temp_world(rooms=1, aura_rooms=1) as (_root, runtime, hub):
            stats = _StubStats()
            auras = AuraService(hub, stats, runtime.world)  # type: ignore[arg-type]
            room = next((room for room in runtime.world.rooms.values() if room.aura), None)
            self.assertIsNotNone(room, "the generated world should define a room aura")
            auras.enter("acct001", room.id)
            auras.leave("acct001", room.id)
            self.assertEqual(stats.removed, [("acct001", auras.source_for(room.id))])
            # Re-entering after leaving must apply again.
            auras.enter("acct001", room.id)
            self.assertIn(("acct001", auras.source_for(room.id)), stats.applied)


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
        with temp_world(rooms=1, aura_rooms=1) as (_root, runtime, hub):
            dispatcher = _StubDispatcher()
            auras = AuraService(hub, _StubStats(), runtime.world)
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
                auras=auras,
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
