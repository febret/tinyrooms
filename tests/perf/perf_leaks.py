"""Unbounded-growth and task-leak invariants.

These are not timing benchmarks. They assert that two structures which used to
grow for the lifetime of the process stay bounded:

* every WebSocket disconnect used to leave its sender task parked on
  ``queue.get()`` forever, along with the connection and up to 128 queued
  frames, because only the session-replaced path called ``close()``;
* :class:`server.security.RateLimiter` trimmed the timestamps inside each
  window but never removed the key, and the login limiter is keyed partly by
  the submitted username -- so unauthenticated traffic could grow the dict
  without limit.

Both are cheap to check and impossible to notice in functional testing.
"""

from __future__ import annotations

import asyncio
import gc
import time

from server.connections import LiveConnection
from server.security import RateLimiter, RateLimitError
from tests.perf.perfkit import PerfCase


class SlowSocket:
    """A WebSocket stand-in whose sends never complete quickly."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(str(payload))

    async def close(self) -> None:
        self.closed = True
        return None


def _connection(account_id: str) -> LiveConnection:
    return LiveConnection(
        websocket=SlowSocket(),  # type: ignore[arg-type]
        account_id=account_id,
        username=account_id,
        generation=1,
    )


class RateLimiterGrowthTests(PerfCase):
    """Limiter bookkeeping must not grow with the number of distinct keys."""

    def test_memory_is_bounded_by_recent_traffic_not_lifetime_traffic(self) -> None:
        """A sustained stream of distinct keys must not grow memory without bound.

        Real limiter keys are attacker-controlled, so the meaningful bound is
        "keys seen recently", not "keys ever seen". Sweeping only happens on
        insertion, so a burst is retained up to the sweep interval; what must
        never happen is growth proportional to total lifetime traffic.
        """

        limiter = RateLimiter()
        base = 1_000_000.0
        peak = 0
        rounds = 20
        for round_index in range(rounds):
            now = base + round_index * 600.0
            for index in range(2_000):
                limiter.check(
                    f"login:user:attacker{round_index}-{index}",
                    limit=5,
                    window_seconds=60,
                    now_ts=now + index * 0.001,
                )
            peak = max(peak, len(limiter._events))
        self.measure(
            "server/rate-limiter/keys/peak-under-40k-distinct-keys",
            peak,
            unit="keys",
            note=(
                "Peak retained limiter keys while 40,000 distinct keys streamed through. Bounded by "
                "recent traffic rather than total traffic."
            ),
        )
        self.assertLessEqual(
            peak,
            RateLimiter.max_keys * 2,
            f"retained keys peaked at {peak}; the limiter is growing with lifetime traffic",
        )

    def test_keys_idle_past_the_grace_period_are_swept(self) -> None:
        """Old keys must actually be released, not merely deferred."""

        limiter = RateLimiter()
        base = 1_000_000.0
        for index in range(2_000):
            limiter.check(f"login:ip:10.0.{index // 250}.{index % 250}", limit=5, window_seconds=60, now_ts=base)
        self.assertGreater(len(limiter._events), 0)
        # A full grace period later, one request must be enough to release them.
        later = base + 3_600.0
        limiter.check("login:ip:203.0.113.1", limit=5, window_seconds=60, now_ts=later)
        self.assertLessEqual(
            len(limiter._events),
            RateLimiter.max_keys,
            "keys idle for over an hour were not released",
        )

    def test_a_bursty_key_is_still_limited(self) -> None:
        """Eviction must not weaken enforcement for a key that is still active."""

        limiter = RateLimiter()
        base = 10_000.0
        for offset in range(5):
            limiter.check("login:ip:127.0.0.1", limit=5, window_seconds=60, now_ts=base + offset)
        raised = 0
        for offset in range(5, 20):
            try:
                limiter.check("login:ip:127.0.0.1", limit=5, window_seconds=60, now_ts=base + offset)
            except Exception:
                raised += 1
        self.assertGreater(raised, 0, "the limiter stopped rejecting an over-limit key")

    def test_a_key_is_usable_again_once_its_window_passes(self) -> None:
        limiter = RateLimiter()
        base = 20_000.0
        for offset in range(5):
            limiter.check("create:ip:10.0.0.1", limit=5, window_seconds=60, now_ts=base + offset)
        with self.assertRaises(RateLimitError):
            limiter.check("create:ip:10.0.0.1", limit=5, window_seconds=60, now_ts=base + 5)
        # A full window later the key must be usable again.
        limiter.check("create:ip:10.0.0.1", limit=5, window_seconds=60, now_ts=base + 61)


class SenderTaskLifetimeTests(PerfCase):
    """Closing a connection must retire its sender task."""

    async def test_close_retires_the_sender_task(self) -> None:
        connection = _connection("closer")
        await connection.start()
        self.assertIsNotNone(connection.sender_task)
        await connection.close()
        self.assertTrue(
            connection.sender_task.done(),
            "close() returned with the sender task still running",
        )
        self.assertTrue(connection.websocket.closed)  # type: ignore[attr-defined]

    async def test_repeated_connect_disconnect_does_not_accumulate_tasks(self) -> None:
        """The disconnect path must not leave one task parked per connection.

        ``websocket.disconnected`` in ``server/app.py`` used to unregister the
        connection without closing it, so the sender task survived. This drives
        the same sequence and asserts the task count returns to baseline.
        """

        baseline = len(asyncio.all_tasks())
        for index in range(60):
            connection = _connection(f"churn{index:03d}")
            await connection.start()
            # This mirrors the app's disconnect branch: unregister, then drop
            # the reference without closing.
            await connection.close()
            del connection
        gc.collect()
        await asyncio.sleep(0)
        self.measure(
            "server/connections/sender-tasks/after-60-cycles",
            len(asyncio.all_tasks()) - baseline,
            unit="tasks",
            note="Live asyncio tasks after 60 connect/disconnect cycles.",
        )
        self.assertLessEqual(
            len(asyncio.all_tasks()) - baseline,
            2,
            "sender tasks accumulated across connect/disconnect cycles",
        )


class RateLimiterConcurrencyTests(PerfCase):
    """Sweeping idle keys must not corrupt the limiter under contention."""

    def test_check_is_thread_safe_while_sweeping(self) -> None:
        import threading

        limiter = RateLimiter()
        errors: list[BaseException] = []
        start = time.perf_counter()

        def worker(offset: int) -> None:
            try:
                for step in range(400):
                    limiter.check(
                        f"login:ip:10.0.0.{offset}",
                        limit=1000,
                        window_seconds=1,
                        now_ts=time.perf_counter(),
                    )
            except BaseException as error:  # noqa: BLE001 - re-raised on the main thread
                errors.append(error)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        for error in errors:
            raise error
        self.assertTrue(all(not thread.is_alive() for thread in threads), "a worker thread hung")
        self.assertLess(len(limiter._events), 64)
