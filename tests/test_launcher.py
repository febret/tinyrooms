"""Tests for the HTTPS launcher."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import signal
import unittest

from cryptography import x509
import uvicorn

from run import (
    BoundedShutdownServer,
    FORCED_EXIT_TIMEOUT_SECONDS,
    GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
    ensure_self_signed_certificate,
    is_mission_control,
)


class LaunchModeTests(unittest.TestCase):
    """Verify the single launcher selects the mission-control server."""

    def test_mission_control_feature_selects_mc(self) -> None:
        self.assertTrue(is_mission_control({"TRSERVER_FEATURES": "mission-control"}))
        self.assertTrue(is_mission_control({"TRSERVER_FEATURES": "dev_sample_activity,mission_control"}))
        self.assertTrue(is_mission_control({"TRSERVER_FEATURES": "MISSION-CONTROL"}))

    def test_world_features_do_not_select_mc(self) -> None:
        self.assertFalse(is_mission_control({"TRSERVER_FEATURES": "dev_sample_activity,world-editor"}))
        self.assertFalse(is_mission_control({"TRSERVER_FEATURES": ""}))
        self.assertFalse(is_mission_control({}))


class LauncherTests(unittest.TestCase):
    """Verify local certificate generation and reuse."""

    def test_certificate_is_valid_and_reused(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            local_path = Path(temporary_directory)
            cert_path, key_path = ensure_self_signed_certificate(
                local_path,
                "127.0.0.1",
            )
            first_cert = cert_path.read_bytes()
            first_key = key_path.read_bytes()
            certificate = x509.load_pem_x509_certificate(first_cert)
            self.assertGreater(
                certificate.not_valid_after_utc,
                datetime.now(tz=UTC),
            )
            reused_cert, reused_key = ensure_self_signed_certificate(
                local_path,
                "127.0.0.1",
            )
            self.assertEqual(reused_cert.read_bytes(), first_cert)
            self.assertEqual(reused_key.read_bytes(), first_key)

    @patch("run.threading.Thread")
    def test_first_signal_starts_one_shutdown_watchdog(self, thread_type: Mock) -> None:
        server = BoundedShutdownServer(uvicorn.Config("server.app:create_app"))

        server.handle_exit(signal.SIGINT, None)
        server.handle_exit(signal.SIGINT, None)

        thread_type.assert_called_once_with(
            target=server._force_exit_after_timeout,
            args=(signal.SIGINT,),
            name="tinyrooms-shutdown-watchdog",
            daemon=True,
        )
        thread_type.return_value.start.assert_called_once_with()
        self.assertTrue(server.should_exit)
        self.assertTrue(server.force_exit)

    @patch("run.os._exit")
    def test_watchdog_forces_exit_when_shutdown_exceeds_deadline(self, force_exit: Mock) -> None:
        server = BoundedShutdownServer(uvicorn.Config("server.app:create_app"))
        server._shutdown_complete = Mock()
        server._shutdown_complete.wait.return_value = False

        server._force_exit_after_timeout(signal.SIGINT)

        server._shutdown_complete.wait.assert_called_once_with(FORCED_EXIT_TIMEOUT_SECONDS)
        force_exit.assert_called_once_with(128 + signal.SIGINT)

    @patch("run.os._exit")
    def test_watchdog_does_not_exit_after_clean_shutdown(self, force_exit: Mock) -> None:
        server = BoundedShutdownServer(uvicorn.Config("server.app:create_app"))
        server._shutdown_complete.set()

        server._force_exit_after_timeout(signal.SIGINT)

        force_exit.assert_not_called()

    def test_graceful_timeout_leaves_time_for_hard_stop(self) -> None:
        self.assertLess(GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS, FORCED_EXIT_TIMEOUT_SECONDS)
        self.assertLess(FORCED_EXIT_TIMEOUT_SECONDS, 2)


if __name__ == "__main__":
    unittest.main()
