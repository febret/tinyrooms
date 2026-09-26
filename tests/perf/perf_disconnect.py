"""End-to-end checks that the WebSocket lifecycle does not leak work.

The unit-level tests in :mod:`tests.perf.perf_leaks` prove the pieces behave,
but the leak that mattered lived in the wiring: the ``websocket.disconnected``
branch in ``server/app.py`` unregistered a connection without closing it, so
the sender task survived even though ``close()`` itself was correct.

These tests drive real WebSocket connections through the real app so that a
regression in that wiring is caught rather than assumed away.

Account creation is rate limited per source IP, so the suite provisions a
handful of accounts and reconnects each of them several times. Reconnecting
also exercises the replaced-connection path, which is where a naive fix would
be tempted to skip ``close()``.
"""

from __future__ import annotations

import gc
import time

from tests.test_milestone1 import RuntimeTestCase, websocket_headers

ACCOUNTS = 3
CYCLES_PER_ACCOUNT = 3


class DisconnectLeakTests(RuntimeTestCase):
    """Repeated connect/disconnect cycles must not retain connections."""

    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.app.state.runtime
        self.credentials = [
            self.create_ready_account(f"leaky{index:02d}") for index in range(ACCOUNTS)
        ]

    def _connect_once(self, credentials: dict[str, str]):
        return self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(credentials["session_token"], credentials["csrf_token"]),
        )

    def test_registry_empties_after_every_disconnect(self) -> None:
        for round_index in range(CYCLES_PER_ACCOUNT):
            for credentials in self.credentials:
                with self._connect_once(credentials) as socket:
                    socket.receive_json()
                    self.assertEqual(
                        len(self.runtime.connections.list_all()),
                        1,
                        "the account should be registered while its socket is open",
                    )
                self.assertEqual(
                    self.runtime.connections.list_all(),
                    [],
                    f"a connection was still registered after its socket closed "
                    f"(round {round_index})",
                )

    def test_repeated_cycles_do_not_slow_teardown_down(self) -> None:
        """A leaked task per disconnect shows up as growing per-cycle cost."""

        samples: list[float] = []
        for credentials in self.credentials:
            for _ in range(CYCLES_PER_ACCOUNT):
                started = time.perf_counter()
                with self._connect_once(credentials) as socket:
                    socket.receive_json()
                gc.collect()
                samples.append((time.perf_counter() - started) * 1000.0)

        first_half = sum(samples[1 : len(samples) // 2]) / max(1, len(samples) // 2 - 1)
        second_half = sum(samples[len(samples) // 2 :]) / max(1, len(samples) // 2)
        self.assertLess(
            second_half,
            first_half * 6 + 250.0,
            f"reconnect cost grew from {first_half:.1f}ms to {second_half:.1f}ms across cycles, "
            "which suggests work is accumulating per disconnect",
        )

    def test_sender_tasks_are_retired_on_disconnect(self) -> None:
        """The connection's sender task must be finished once the socket closes."""

        for credentials in self.credentials:
            with self._connect_once(credentials) as socket:
                socket.receive_json()
                connection = self.runtime.connections.list_all()[0]
                self.assertIsNotNone(connection.sender_task, "the sender task was never started")
            self.assertTrue(
                connection.sender_task.done(),
                "the sender task was still running after the socket closed",
            )
