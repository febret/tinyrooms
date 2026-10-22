"""Player entry recovery and diagnostic tests."""

from __future__ import annotations

from pathlib import Path
import unittest

import httpx

from server.mission_control.registry import STATUS_RUNNING
from server.security import utc_now
from tests.mc_helpers import McHttpTestCase


class EntryRecoveryTests(McHttpTestCase):
    def add_restored_instance(self, instance_id: str = "mc-test") -> object:
        instance_dir = Path(self.temporary_directory.name) / "instances" / instance_id
        instance_dir.mkdir(parents=True)
        runtime = self.app.state.mc
        record = runtime.registry.register_spawned(
            instance_id=instance_id,
            name="tutorial",
            endpoint="https://127.0.0.1:10000",
            instance_dir=str(instance_dir),
            process_handle=None,
            spawn_config={
                "instance_id": instance_id,
                "name": "tutorial",
                "world_path": str(Path(self.temporary_directory.name) / "world"),
                "worldstate_path": str(instance_dir / "worldstate.sqlite3"),
                "users_path": str(runtime.config.users_path),
                "host": "127.0.0.1",
                "port": 10000,
                "features": "",
                "admins": "",
                "mods": "*",
                "base_path": "",
            },
        )
        runtime.registry.set_status(instance_id, STATUS_RUNNING)
        return record

    def test_heartbeat_requests_reregistration_for_restored_instance(self) -> None:
        record = self.add_restored_instance()
        runtime = self.app.state.mc
        response = self.client.post(
            "/api/mc/heartbeat",
            headers={"x-mc-token": self.config.token},
            json={
                "instance_id": record.instance_id,
                "uptime_seconds": 10,
                "users_online": 0,
                "world_id": "tutorial",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(response.json()["code"], "reregister_required")
        self.assertIsNone(record.registered_at)

        registered = self.client.post(
            "/api/mc/register",
            headers={"x-mc-token": self.config.token},
            json={
                "instance_id": record.instance_id,
                "instance_name": "tutorial",
                "endpoint": "https://127.0.0.1:10000",
                "client_url": "https://127.0.0.1:10000",
                "world": {"id": "tutorial", "entry_room_id": "hub"},
            },
        )
        self.assertEqual(registered.status_code, 200)
        self.assertIsNotNone(record.registered_at)
        self.assertEqual(record.entry_room_id, "hub")

        heartbeat = self.client.post(
            "/api/mc/heartbeat",
            headers={"x-mc-token": self.config.token},
            json={"instance_id": record.instance_id, "uptime_seconds": 11, "users_online": 0,
                  "world_id": "tutorial"},
        )
        self.assertTrue(heartbeat.json()["ok"])

    def test_create_names_restored_instance_and_explains_recovery(self) -> None:
        record = self.add_restored_instance()
        runtime = self.app.state.mc
        record.world_id = "tutorial"
        record.entry_room_id = "hub"
        record.client_url = "https://127.0.0.1:10000"
        runtime.entry_settings.set_default(record.instance_id)

        response = self.client.post(
            "/api/entry/create",
            headers={"origin": self.origin},
            json={
                "username": "sunbeam",
                "password": "password123!",
                "passphrase": self.config.new_account_passphrase,
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "entry_instance_not_registered")
        self.assertIn("tutorial", response.json()["message"])
        self.assertIn(record.instance_id, response.json()["message"])

    def test_create_succeeds_after_registration_is_restored(self) -> None:
        record = self.add_restored_instance()
        runtime = self.app.state.mc
        record.world_id = "tutorial"
        record.entry_room_id = "hub"
        record.client_url = "https://127.0.0.1:10000"
        record.registered_at = utc_now().isoformat()
        runtime.entry_settings.set_default(record.instance_id)

        original = runtime.http
        runtime.http = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"ok": True, "world_id": "tutorial", "instance_id": record.instance_id},
                )
            )
        )
        self.addCleanup(lambda: __import__("asyncio").run(runtime.http.aclose()))
        self.addCleanup(lambda: __import__("asyncio").run(original.aclose()))

        response = self.client.post(
            "/api/entry/create",
            headers={"origin": self.origin},
            json={
                "username": "sunbeam",
                "password": "password123!",
                "passphrase": self.config.new_account_passphrase,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])


if __name__ == "__main__":
    unittest.main()
