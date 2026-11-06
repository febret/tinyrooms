"""Tests for Mission Control port selection in the multiworld launcher."""

from __future__ import annotations

from unittest.mock import patch
import socket
import unittest

from server.mission_control.supervisor import port_is_available
from start_multiworld import MultiworldConfigError, select_mc_port


class PortAvailabilityTests(unittest.TestCase):
    """Verify wildcard probes notice listeners on specific addresses."""

    def test_wildcard_probe_detects_a_loopback_listener(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        self.assertFalse(port_is_available("127.0.0.1", port))
        self.assertFalse(port_is_available("0.0.0.0", port))


class SelectMcPortTests(unittest.TestCase):
    """Verify Mission Control avoids ports already owned by another process."""

    @patch("start_multiworld.port_is_available", return_value=True)
    def test_default_port_is_used_when_free(self, port_is_available) -> None:
        self.assertEqual(select_mc_port({}, "127.0.0.1", set()), 8001)
        port_is_available.assert_called_once_with("127.0.0.1", 8001)

    @patch("start_multiworld.port_is_available")
    def test_default_port_falls_back_to_next_free_port(self, port_is_available) -> None:
        port_is_available.side_effect = lambda host, port: port >= 8003

        self.assertEqual(select_mc_port({}, "0.0.0.0", set()), 8003)
        self.assertEqual(
            [call.args[1] for call in port_is_available.call_args_list],
            [8001, 8002, 8003],
        )

    @patch("start_multiworld.port_is_available", return_value=True)
    def test_default_port_skips_ports_assigned_to_worlds(self, port_is_available) -> None:
        self.assertEqual(select_mc_port({}, "127.0.0.1", {8001}), 8002)
        port_is_available.assert_called_once_with("127.0.0.1", 8002)

    @patch("start_multiworld.port_is_available", return_value=True)
    def test_explicit_port_is_used_when_free(self, port_is_available) -> None:
        self.assertEqual(select_mc_port({"MC_PORT": "8123"}, "127.0.0.1", set()), 8123)
        port_is_available.assert_called_once_with("127.0.0.1", 8123)

    @patch("start_multiworld.port_is_available", return_value=False)
    def test_explicit_busy_port_is_a_configuration_error(self, port_is_available) -> None:
        with self.assertRaisesRegex(MultiworldConfigError, "already in use"):
            select_mc_port({"MC_PORT": "8123"}, "127.0.0.1", set())

    @patch("start_multiworld.port_is_available", return_value=True)
    def test_explicit_port_conflicting_with_world_is_a_configuration_error(
        self, port_is_available
    ) -> None:
        with self.assertRaisesRegex(MultiworldConfigError, "already in use"):
            select_mc_port({"MC_PORT": "8123"}, "127.0.0.1", {8123})


if __name__ == "__main__":
    unittest.main()
