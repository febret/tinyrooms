"""Room snapshot cost as a room fills with occupants, props, peeps and cards.

``RoomService.build_snapshot`` is the single most expensive routine in the
server: it runs on connect, on every ``snapshot.request``, on every ``.go`` and
on every ``.reset_room``. It is also the routine whose cost has the most
awkward shape, because it assembles data for *every* occupant but is invoked
separately for *each* occupant. That combination is what turns a busy room
quadratic.

The counters here therefore focus on the number of SQL statements issued rather
than on wall-clock time. Statement counts are exactly reproducible, they point
directly at the responsible code, and a change that removes a per-occupant
query shows up immediately.
"""

from __future__ import annotations

import json
import time

from server.connections import SyntheticConnection
from server.profiles import AccountRecord
from tests.perf.perfkit import PerfCase, sql_counter
from tests.perf.synthetic import ENTRY_ROOM, entity_counts, temp_world

PROPS = 60
PEEPS = 12
CARDS = 20
ROOMS = 4

#: Occupant counts swept by the scaling assertion. A batched snapshot costs
#: roughly the same at either end; a per-occupant snapshot costs 8x.
OCCUPANT_SCALE = (5, 40)


async def _occupy(runtime: SyntheticRuntime, accounts: list[AccountRecord], room_id: str) -> None:
    for account in accounts:
        connection = SyntheticConnection(
            account_id=account.id,
            username=account.username_display,
        )
        await runtime.connections.register(connection)
        await runtime.connections.set_room(account.id, room_id)


async def _count_sql(hub, coroutine_factory) -> tuple[object, int]:
    """Run a coroutine and return ``(result, statements_issued)``."""

    with sql_counter(hub.connection) as statements:
        result = await coroutine_factory()
    return result, len(statements)


class SnapshotCostTests(PerfCase):
    """``build_snapshot`` must not scale with the number of occupants in the room."""

    async def asyncSetUp(self) -> None:
        self._world = temp_world(
            rooms=ROOMS, props_per_room=PROPS, peeps_per_room=PEEPS, cards_per_room=CARDS
        )
        self.addCleanup(self._world.__exit__, None, None, None)
        _root, self.runtime, self.hub = self._world.__enter__()
        self.rooms = self.runtime.bind(self.hub)
        self.account = self.runtime.create_account("owner")

    async def _snapshot(self, account: AccountRecord, room_id: str = ENTRY_ROOM) -> dict[str, object]:
        return await self.rooms.build_snapshot(account, room_id)

    async def test_snapshot_cost_is_flat_across_occupant_count(self) -> None:
        """A full-room snapshot must issue roughly a constant number of queries.

        This is the regression guard for the per-occupant ``stats.view`` fanout.
        """

        small_n, large_n = OCCUPANT_SCALE
        samples: dict[int, tuple[int, float]] = {}
        for count in (small_n, large_n):
            registry = self.runtime.connections
            for stale in list(registry.list_all()):
                await registry.unregister(stale.account_id)
            accounts = [self.runtime.create_account(f"occ{count}x{index:03d}") for index in range(count)]
            await _occupy(self.runtime, accounts, ENTRY_ROOM)
            snapshot, statements = await _count_sql(
                self.hub, lambda: self._snapshot(self.account)
            )
            # One extra statement group is fine: the trace hook itself is free,
            # but the first snapshot after registration warms page caches.
            self.measure(
                f"server/snapshot/queries/occupants={count}",
                statements,
                unit="queries",
                note=f"SQL statements for one snapshot in a room with {count} occupants.",
            )
            self.measure(
                f"server/snapshot/occupants={count}/entities",
                sum(entity_counts(snapshot).values()),
                unit="entities",
                lower_is_better=False,
                note="Entity count carried by the snapshot, for context.",
            )
            samples[count] = (statements, 0.0)

        small, large = samples[small_n][0], samples[large_n][0]
        if large > small * 1.4 + 2:
            self.fail(
                f"build_snapshot issued {large} SQL statements with {large_n} occupants but only "
                f"{small} with {small_n}. Snapshot cost is growing with occupancy, which means a "
                "per-occupant query has been reintroduced. Occupant state should be fetched in one "
                "batched read, not once per occupant."
            )

    async def test_snapshot_query_count_has_a_ceiling(self) -> None:
        """The statement budget catches regressions the ratio check would smooth over."""

        accounts = [self.runtime.create_account(f"full{index:03d}") for index in range(40)]
        await _occupy(self.runtime, accounts, ENTRY_ROOM)
        _, statements = await _count_sql(self.hub, lambda: self._snapshot(self.account))
        self.measure(
            "server/snapshot/queries/room-max",
            statements,
            unit="queries",
            ceiling=90,
            note=(
                "A fully populated room (40 occupants, 60 props, 12 peeps, 20 cards) must build a "
                "snapshot in a bounded number of statements. Per-occupant profile reads push this "
                "past 200."
            ),
        )

    async def test_snapshot_serialised_size_stays_bounded(self) -> None:
        """Snapshot payload growth is a client-visible cost on every join and resync."""

        accounts = [self.runtime.create_account(f"size{index:03d}") for index in range(20)]
        await _occupy(self.runtime, accounts, ENTRY_ROOM)
        snapshot = await self._snapshot(self.account)
        encoded = json.dumps(snapshot, separators=(",", ":"))
        self.measure(
            "server/snapshot/bytes/room-max",
            len(encoded),
            unit="bytes",
            ceiling=200_000,
            note=(
                "Serialised snapshot size for a 20-occupant room. Encoded once per recipient, so "
                "this is multiplied by the occupant count on the wire."
            ),
        )

    async def test_snapshot_wall_clock_budget(self) -> None:
        """A generous absolute bound so a pathological regression fails loudly."""

        accounts = [self.runtime.create_account(f"clock{index:03d}") for index in range(30)]
        await _occupy(self.runtime, accounts, ENTRY_ROOM)
        await self._snapshot(self.account)
        iterations = 10
        started = time.perf_counter()
        for _ in range(iterations):
            await self._snapshot(self.account)
        elapsed = (time.perf_counter() - started) * 1000.0 / iterations
        self.measure(
            "server/snapshot/ms/room-max",
            elapsed,
            unit="ms",
            ceiling=250.0,
            note="Mean wall clock for one snapshot in a 30-occupant room.",
        )


class SnapshotContentTests(PerfCase):
    """Caching must not be allowed to win by returning less data.

    Every performance assertion in this module counts queries, allocations or
    bytes. A cache that quietly dropped props or occupants would make all of
    them look better, so correctness is pinned here against the authored world
    definition rather than against a previous snapshot.
    """

    async def asyncSetUp(self) -> None:
        self._world = temp_world(
            rooms=2, props_per_room=PROPS, peeps_per_room=PEEPS, cards_per_room=CARDS
        )
        self.addCleanup(self._world.__exit__, None, None, None)
        _root, self.runtime, self.hub = self._world.__enter__()
        self.rooms = self.runtime.bind(self.hub)
        self.account = self.runtime.create_account("owner")

    async def test_snapshot_carries_every_authored_entity(self) -> None:
        definition = self.runtime.world.rooms[ENTRY_ROOM]
        expected_npcs = sum(
            1 for peep in self.runtime.world.peeps.values() if peep.room_id == ENTRY_ROOM
        )
        accounts = [self.runtime.create_account(f"body{index:03d}") for index in range(6)]
        await _occupy(self.runtime, accounts, ENTRY_ROOM)
        snapshot = await self.rooms.build_snapshot(self.account, ENTRY_ROOM)
        counts = entity_counts(snapshot)

        self.assertEqual(counts["occupants"], 6, "occupants were dropped from the snapshot")
        self.assertEqual(
            counts["npcs"],
            expected_npcs,
            "NPC peeps were dropped from the snapshot",
        )
        self.assertEqual(
            counts["props"],
            len(definition.props),
            "prop instances were dropped from the snapshot",
        )
        self.assertGreaterEqual(counts["room_cards"], CARDS, "room cards were dropped")

    async def test_repeat_snapshots_are_identical(self) -> None:
        """The environment cache must return the same data as a cold read."""

        definition = self.runtime.world.rooms[ENTRY_ROOM]
        first = await self.rooms.build_snapshot(self.account, ENTRY_ROOM)
        self.runtime.world_state.invalidate_room_environment()
        self.runtime.rooms._layout = None  # bypass the layout cache for a true cold read
        second = await self.rooms.build_snapshot(self.account, ENTRY_ROOM)
        for field in ("props", "exits", "npcs", "environment", "environment_revision"):
            self.assertEqual(
                first[field],
                second[field],
                f"snapshot field '{field}' differs between a cached and an uncached read",
            )
        self.assertEqual(len(definition.props), len(second["props"]))

    async def test_environment_writes_are_visible_to_later_reads(self) -> None:
        """A cached environment must not mask a write."""

        from server.services.environment import ENVIRONMENT_KEYS

        expiry = {"expires_at": "2999-01-01T00:00:00+00:00"}
        values = {
            "lighting": "dark",
            "hidden_props": {"bulk-prop-0": expiry},
            "disabled_exits": {"exit0": expiry},
            "disabled_actions": {"inspect": expiry},
        }
        for key in ENVIRONMENT_KEYS:
            self.runtime.world_state.invalidate_room_environment()
            value = values[key]
            update = self.runtime.environment.set(ENTRY_ROOM, {key: value})
            read_back = self.runtime.environment.get(ENTRY_ROOM)
            self.assertEqual(
                read_back.get(key),
                value,
                f"environment key '{key}' was not visible after being written through the cache",
            )
            self.assertEqual(update.environment.get(key), value)


class SnapshotAxisScalingTests(PerfCase):
    """Snapshot cost must grow linearly with each entity axis, never quadratically."""

    def _world_for(self, axis: str, count: int):
        return temp_world(
            rooms=1,
            props_per_room=count if axis == "props" else 0,
            peeps_per_room=count if axis == "peeps" else 0,
            cards_per_room=count if axis == "cards" else 0,
        )

    async def _measure_axis(self, axis: str, small: int, large: int, *, query_ceiling: int) -> None:
        timings: dict[int, float] = {}
        counts: dict[int, int] = {}
        for count in (small, large):
            world = self._world_for(axis, count)
            root, runtime, hub = world.__enter__()
            try:
                rooms = runtime.bind(hub)
                account = runtime.create_account("owner")
                await rooms.build_snapshot(account, ENTRY_ROOM)
                iterations = 8
                started = time.perf_counter()
                for _ in range(iterations):
                    await rooms.build_snapshot(account, ENTRY_ROOM)
                timings[count] = (time.perf_counter() - started) * 1000.0 / iterations
                _, statements = await _count_sql(hub, lambda: rooms.build_snapshot(account, ENTRY_ROOM))
                counts[count] = statements
            finally:
                world.__exit__(None, None, None)

        self.measure(
            f"server/snapshot/queries/axis-{axis}-{large}",
            counts[large],
            unit="queries",
            ceiling=query_ceiling,
            note=(
                f"SQL statements for one snapshot at {large} {axis}. Room environment and authored "
                "action data are static per room, so this must not grow one statement per entity."
            ),
        )
        self.assert_scales(
            f"snapshot/axis-{axis}",
            timings[small],
            timings[large],
            factor=large / small,
            max_factor=2.6,
            small_n=small,
            large_n=large,
        )

    async def test_props_axis_is_linear(self) -> None:
        await self._measure_axis("props", small=8, large=64, query_ceiling=25)

    async def test_peeps_axis_is_linear(self) -> None:
        await self._measure_axis("peeps", small=4, large=32, query_ceiling=18)

    async def test_cards_axis_is_linear(self) -> None:
        await self._measure_axis("cards", small=4, large=32, query_ceiling=14)
