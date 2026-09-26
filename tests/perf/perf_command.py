"""Per-message WebSocket overhead as a world fills up.

Everything in this module runs at least once per inbound frame, so its cost is
multiplied by every connected player. Two things were unconditional work that
did not need to be:

* ``build_command_context`` called ``AccountService.list_stickers()``, which
  did a sorted ``iterdir()`` plus a ``stat()`` per asset, on *every command*.
  The sticker set is static for the lifetime of a runtime.
* ``_log_event`` ran ``json.dumps`` on every request, command and connect
  before checking whether the record would be emitted at all.

These are asserted as call counts rather than timings, so they cannot flake.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import server.app as app_module
from server.accounts import AccountService
from server.commands.context import build_command_context
from server.config import load_config
from server.profiles import ProfileRepository
from tests.common import REPO_ROOT
from tests.perf.perfkit import PerfCase
from tests.perf.synthetic import temp_world

COMMANDS = 200

#: Every attribute ``build_command_context`` reads off the runtime.
RUNTIME_SLOTS = (
    "profiles", "world_state", "rooms", "cards", "activities", "activity_results",
    "registry", "stats", "inventory", "progression", "actions", "friends", "shop",
    "prop_shop", "pricing", "content", "behaviors", "dialogs", "tasks", "memories",
    "powers", "ownership", "environment", "audit", "connections", "mods",
    "dispensers", "crafting",
)


def _account_service(root: Path, profiles) -> AccountService:
    config = load_config(
        env={
            "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "open-sesame",
            "TRSERVER_USERS_PATH": str(root / "users"),
            "TRSERVER_WORLDSTATE_PATH": str(root / "worldstate.sqlite3"),
        },
        repo_root=REPO_ROOT,
    )
    return AccountService(config, profiles, world_id="tutorial", entry_room_id="hub")


def _runtime_stub(world, accounts: AccountService):
    """A minimal object exposing the runtime surface ``build_command_context`` reads."""

    class _Stub:
        pass

    stub = _Stub()
    stub.world = world
    stub.accounts = accounts
    stub.reload_world = lambda: None
    for name in RUNTIME_SLOTS:
        setattr(stub, name, object())
    return stub


class _DirectoryScanCounter:
    """Count ``iterdir`` calls on sticker directories across a block."""

    def __init__(self) -> None:
        self.scans = 0
        self._original = None
        self._path_type = None

    def __enter__(self) -> "_DirectoryScanCounter":
        from pathlib import Path as _Path

        self._path_type = _Path
        self._original = _Path.iterdir

        def counting_iterdir(self_path, _counter=self):
            _counter.scans += 1
            return self._original(self_path)

        _Path.iterdir = counting_iterdir  # type: ignore[method-assign]
        return self

    def __exit__(self, *exc: object) -> None:
        if self._original is not None:
            self._path_type.iterdir = self._original  # type: ignore[method-assign]


class StickerScanTests(PerfCase):
    """The sticker set must be resolved once, not once per command."""

    def test_sticker_listing_is_cached(self) -> None:
        with temp_world(rooms=1) as (_root, _runtime, hub):
            service = _account_service(_root, ProfileRepository(hub))
            service.list_stickers()
            with _DirectoryScanCounter() as counter:
                for _ in range(COMMANDS):
                    service.list_stickers()
            self.measure(
                "server/accounts/sticker-scans",
                counter.scans,
                unit="scans",
                ceiling=1,
                note=(
                    f"Directory walks for {COMMANDS} repeated sticker listings. The asset set is "
                    "static for the lifetime of a runtime."
                ),
            )

    def test_cached_stickers_stay_consistent(self) -> None:
        with temp_world(rooms=1) as (root, _runtime, hub):
            service = _account_service(root, ProfileRepository(hub))
            first = service.list_stickers()
            self.assertEqual(service.list_stickers(), first)
            self.assertTrue(first, "the tutorial world should expose sticker assets")


class LogEventTests(PerfCase):
    """Log records must not be serialised unless they will be emitted."""

    def _count_dumps(self, *, level: int, calls: int):
        original = json.dumps
        counter: list[int] = []

        def counting_dumps(*args, **kwargs):
            counter.append(1)
            return original(*args, **kwargs)

        previous = app_module.LOGGER.level
        app_module.LOGGER.setLevel(level)
        json.dumps = counting_dumps  # type: ignore[assignment]
        try:
            for index in range(calls):
                app_module._log_event("perf.probe", index=index)
        finally:
            json.dumps = original  # type: ignore[assignment]
            app_module.LOGGER.setLevel(previous)
        return len(counter)

    def test_json_is_not_built_when_the_level_is_disabled(self) -> None:
        count = self._count_dumps(level=logging.WARNING, calls=COMMANDS)
        self.measure(
            "server/logging/dumps-when-disabled",
            count,
            unit="dumps",
            ceiling=0,
            note=f"Serialisations for {COMMANDS} log records that were then discarded.",
        )
        self.assertEqual(
            count,
            0,
            f"ran {count} serialisations for {COMMANDS} log records that were then discarded",
        )

    def test_json_is_built_once_when_the_level_is_enabled(self) -> None:
        count = self._count_dumps(level=logging.INFO, calls=1)
        self.assertEqual(count, 1, "an enabled log record should be serialised exactly once")


class CommandContextCostTests(PerfCase):
    """Command context construction must not touch the filesystem or the world."""

    def _bind(self, *, rooms: int = 1, props: int = 0):
        holder = temp_world(rooms=rooms, props_per_room=props)
        root, runtime, hub = holder.__enter__()
        self.addCleanup(lambda: holder.__exit__(None, None, None))
        runtime.bind(hub)
        account = runtime.create_account("ctx")
        stub = _runtime_stub(runtime.world, _account_service(root, runtime.profiles))
        return account, stub

    def _build(self, account, stub) -> None:
        build_command_context(
            stub,  # type: ignore[arg-type]
            account=account,
            connection=object(),
            serialize_user=lambda _a: {},
        )

    def test_building_contexts_does_not_rescan_the_sticker_directory(self) -> None:
        account, stub = self._bind()
        self._build(account, stub)
        with _DirectoryScanCounter() as counter:
            for _ in range(50):
                self._build(account, stub)
        self.measure(
            "server/commands/sticker-dir-scans",
            counter.scans,
            unit="scans",
            ceiling=1,
            note="Directory walks while building 50 command contexts.",
        )
        self.assertLessEqual(
            counter.scans,
            1,
            f"building 50 command contexts walked the sticker directory {counter.scans} times",
        )

    def test_context_construction_cost_does_not_grow_with_the_world(self) -> None:
        small_account, small_stub = self._bind(rooms=1, props=5)
        large_account, large_stub = self._bind(rooms=200, props=20)

        def mean_ms(account, stub) -> float:
            for _ in range(5):
                self._build(account, stub)
            started = time.perf_counter()
            for _ in range(100):
                self._build(account, stub)
            return (time.perf_counter() - started) * 1000.0 / 100

        small = mean_ms(small_account, small_stub)
        large = mean_ms(large_account, large_stub)
        self.measure(
            "server/commands/context-ms/small-world",
            small,
            unit="ms",
            ceiling=5.0,
            note="Context construction in a 1-room world.",
        )
        self.measure(
            "server/commands/context-ms/large-world",
            large,
            unit="ms",
            ceiling=5.0,
            note="Context construction in a 200-room world.",
        )
        self.assert_scales(
            "commands/context-vs-world-size",
            small,
            large,
            factor=200,
            max_factor=1.2,
            small_n=1,
            large_n=200,
        )
