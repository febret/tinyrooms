"""Configuration tests for the mission-control server and world client."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from server.config import ConfigError, KNOWN_FEATURES, load_config
from server.mission_control.config import load_mc_config
from tests.common import REPO_ROOT


def _base_env(root: Path) -> dict[str, str]:
    return {
        "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "open",
        "TRSERVER_WORLD_PATH": str(REPO_ROOT / "worlds" / "tutorial"),
        "TRSERVER_WORLDSTATE_PATH": str(root / "worldstate.sqlite3"),
        "TRSERVER_USERS_PATH": str(root / "users"),
    }


class WorldClientConfigTests(unittest.TestCase):
    def test_mission_control_is_a_known_feature(self) -> None:
        self.assertIn("mission-control", KNOWN_FEATURES)

    def test_endpoint_without_token_is_rejected(self) -> None:
        with TemporaryDirectory() as temp:
            env = _base_env(Path(temp))
            env["TRSERVER_MC_ENDPOINT"] = "127.0.0.1:8001"
            with self.assertRaises(ConfigError):
                load_config(env=env, repo_root=REPO_ROOT)

    def test_endpoint_with_token_is_accepted(self) -> None:
        with TemporaryDirectory() as temp:
            env = _base_env(Path(temp))
            env["TRSERVER_MC_ENDPOINT"] = "127.0.0.1:8001"
            env["TRSERVER_MC_TOKEN"] = "shared"
            env["TRSERVER_MC_INSECURE_TLS"] = "1"
            config = load_config(env=env, repo_root=REPO_ROOT)
        self.assertEqual(config.mc_endpoint, "127.0.0.1:8001")
        self.assertEqual(config.mc_token, "shared")
        self.assertTrue(config.mc_insecure_tls)


class McConfigTests(unittest.TestCase):
    def _env(self, root: Path, **overrides: str) -> dict[str, str]:
        env = {
            "TRSERVER_FEATURES": "mission-control",
            "TRSERVER_MC_PASSPHRASE": "letmein",
            "TRSERVER_MC_TOKEN": "shared",
            "TRSERVER_MC_USERS_PATH": str(root / "users"),
            "TRSERVER_MC_INSTANCES_PATH": str(root / "instances"),
            "TRSERVER_MC_VERSIONS_PATH": str(root / "versions"),
        }
        env.update(overrides)
        return env

    def test_feature_is_required(self) -> None:
        with TemporaryDirectory() as temp:
            env = self._env(Path(temp), TRSERVER_FEATURES="world-editor")
            with self.assertRaises(ConfigError):
                load_mc_config(env=env, repo_root=REPO_ROOT)

    def test_passphrase_and_token_are_required(self) -> None:
        with TemporaryDirectory() as temp:
            env = self._env(Path(temp), TRSERVER_MC_PASSPHRASE="")
            with self.assertRaises(ConfigError):
                load_mc_config(env=env, repo_root=REPO_ROOT)
            env = self._env(Path(temp), TRSERVER_MC_TOKEN="")
            with self.assertRaises(ConfigError):
                load_mc_config(env=env, repo_root=REPO_ROOT)

    def test_valid_config_creates_paths(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            config = load_mc_config(env=self._env(root), repo_root=REPO_ROOT)
            self.assertEqual(config.port, 8001)
            self.assertEqual(config.host, "127.0.0.1")
            self.assertIn("https://127.0.0.1:8001", config.allowed_origins)
            self.assertTrue(config.users_path.is_dir())
            self.assertTrue(config.instances_path.is_dir())
            self.assertEqual(config.actor, "mission-control")
            self.assertTrue(config.new_account_passphrase)


if __name__ == "__main__":
    unittest.main()
