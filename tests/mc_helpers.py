"""Shared helpers for mission-control tests (not collected as a test module)."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from starlette.testclient import TestClient

from server.mission_control.app import create_mc_app
from server.mission_control.config import load_mc_config
from tests.common import REPO_ROOT


MC_BASE_URL = "https://127.0.0.1:8001"


def mc_env(root: Path, **overrides: str) -> dict[str, str]:
    """Build a valid mission-control environment for a temp directory."""

    env = {
        "TRSERVER_FEATURES": "mission-control",
        "TRSERVER_MC_PASSPHRASE": "letmein",
        "TRSERVER_MC_TOKEN": "shared",
        "TRSERVER_MC_HOST": "127.0.0.1",
        "TRSERVER_MC_PORT": "8001",
        "TRSERVER_MC_USERS_PATH": str(root / "users"),
        "TRSERVER_MC_INSTANCES_PATH": str(root / "instances"),
        "TRSERVER_MC_VERSIONS_PATH": str(root / "versions"),
        "TRSERVER_MC_HEARTBEAT_SECONDS": "5",
    }
    env.update(overrides)
    return env


class McHttpTestCase(unittest.TestCase):
    """Boot an in-process mission-control app with isolated paths."""

    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.config = load_mc_config(env=mc_env(root), repo_root=REPO_ROOT)
        self.app = create_mc_app(self.config)
        self.client_context = TestClient(self.app, base_url=MC_BASE_URL)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)

    @property
    def origin(self) -> str:
        return MC_BASE_URL

    def login(self, passphrase: str = "letmein"):
        """Log in and return the response."""

        return self.client.post(
            "/api/mission-control/auth/login",
            json={"passphrase": passphrase},
            headers={"origin": self.origin},
        )

    def csrf_headers(self) -> dict[str, str]:
        """Return Origin + CSRF headers for a state-changing request."""

        return {"origin": self.origin, "x-csrf-token": self.client.cookies.get("tr_mc_csrf", "")}
