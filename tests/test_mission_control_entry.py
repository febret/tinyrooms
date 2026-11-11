"""Player entry recovery and diagnostic tests."""

from __future__ import annotations

from pathlib import Path
import unittest

import httpx

from server.mission_control.registry import STATUS_RUNNING, STATUS_STOPPED
from server.security import CSRF_COOKIE, SESSION_COOKIE, utc_now
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

    def add_running_instance(
        self,
        instance_id: str = "mc-live",
        *,
        world_id: str = "tutorial",
        port: int = 10000,
    ) -> object:
        instance_dir = Path(self.temporary_directory.name) / "instances" / instance_id
        instance_dir.mkdir(parents=True)
        runtime = self.app.state.mc
        record = runtime.registry.register_spawned(
            instance_id=instance_id,
            name=instance_id,
            endpoint=f"https://127.0.0.1:{port}",
            instance_dir=str(instance_dir),
            process_handle=None,
            spawn_config={
                "instance_id": instance_id,
                "name": instance_id,
                "world_path": str(Path(self.temporary_directory.name) / "world"),
                "worldstate_path": str(instance_dir / "worldstate.sqlite3"),
                "users_path": str(runtime.config.users_path),
                "host": "127.0.0.1",
                "port": port,
                "features": "",
                "admins": "",
                "mods": "*",
                "base_path": "",
            },
        )
        record.world_id = world_id
        record.entry_room_id = "hub"
        record.client_url = f"https://127.0.0.1:{port}"
        record.registered_at = utc_now().isoformat()
        runtime.registry.set_status(instance_id, STATUS_RUNNING)
        return record

    def sign_in(self, saved_instance_id: str) -> tuple[object, object]:
        runtime = self.app.state.mc
        account = runtime.profiles.create_account("player", "password123!", "tutorial", "hub")
        runtime.profiles.remember_instance(account.id, saved_instance_id)
        issued, _ = runtime.profiles.issue_session(account.id)
        self.client.cookies.set(SESSION_COOKIE, issued.token)
        self.client.cookies.set(CSRF_COOKIE, issued.csrf_token)
        return account, issued

    def mock_health(self, record: object) -> None:
        runtime = self.app.state.mc
        original = runtime.http
        runtime.http = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"ok": True, "world_id": record.world_id, "instance_id": record.instance_id},
                )
            )
        )
        self.addCleanup(lambda: __import__("asyncio").run(runtime.http.aclose()))
        self.addCleanup(lambda: __import__("asyncio").run(original.aclose()))

    def test_resolve_offers_same_world_candidates_for_missing_instance(self) -> None:
        live = self.add_running_instance()
        self.sign_in("mc-missing")

        response = self.client.get("/api/entry/resolve")

        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data["code"], "entry_instance_missing")
        self.assertTrue(data["can_repair"])
        self.assertEqual([candidate["instance_id"] for candidate in data["candidates"]], [live.instance_id])

    def test_resolve_without_candidates_keeps_operator_message(self) -> None:
        self.sign_in("mc-missing")

        response = self.client.get("/api/entry/resolve")

        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertFalse(data["can_repair"])
        self.assertEqual(data["candidates"], [])
        self.assertIn("operator", data["message"])

    def test_resolve_offers_candidates_for_ambiguous_legacy_profile(self) -> None:
        first = self.add_running_instance("mc-first", port=10001)
        second = self.add_running_instance("mc-second", port=10002)
        self.sign_in(None)

        response = self.client.get("/api/entry/resolve")

        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data["code"], "entry_instance_ambiguous")
        self.assertTrue(data["can_repair"])
        self.assertEqual(
            {candidate["instance_id"] for candidate in data["candidates"]},
            {first.instance_id, second.instance_id},
        )

    def test_repair_rebinds_player_to_confirmed_candidate(self) -> None:
        live = self.add_running_instance()
        self.mock_health(live)
        account, issued = self.sign_in("mc-missing")

        response = self.client.post(
            "/api/entry/repair",
            headers={"origin": self.origin, "x-csrf-token": issued.csrf_token},
            json={"instance_id": live.instance_id, "world_id": "tutorial"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["instance_id"], live.instance_id)
        profile = self.app.state.mc.profiles.get_user_profile(account.id)
        self.assertEqual(profile.last_instance_id, live.instance_id)
        resolved = self.client.get("/api/entry/resolve")
        self.assertEqual(resolved.status_code, 200)

    def test_repair_rejects_healthy_saved_instance(self) -> None:
        saved = self.add_running_instance("mc-saved", port=10001)
        self.add_running_instance("mc-live", port=10002)
        self.mock_health(saved)
        _, issued = self.sign_in(saved.instance_id)

        response = self.client.post(
            "/api/entry/repair",
            headers={"origin": self.origin, "x-csrf-token": issued.csrf_token},
            json={"instance_id": "mc-live", "world_id": "tutorial"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "entry_instance_healthy")

    def test_repair_allows_stopped_saved_instance(self) -> None:
        saved = self.add_running_instance("mc-saved", port=10001)
        live = self.add_running_instance("mc-live", port=10002)
        self.app.state.mc.registry.set_status(saved.instance_id, STATUS_STOPPED)
        self.mock_health(live)
        account, issued = self.sign_in(saved.instance_id)

        response = self.client.post(
            "/api/entry/repair",
            headers={"origin": self.origin, "x-csrf-token": issued.csrf_token},
            json={"instance_id": live.instance_id, "world_id": "tutorial"},
        )

        self.assertEqual(response.status_code, 200)
        profile = self.app.state.mc.profiles.get_user_profile(account.id)
        self.assertEqual(profile.last_instance_id, live.instance_id)

    def test_repair_rejects_different_world(self) -> None:
        other = self.add_running_instance("mc-other", world_id="other-world")
        self.mock_health(other)
        _, issued = self.sign_in("mc-missing")

        response = self.client.post(
            "/api/entry/repair",
            headers={"origin": self.origin, "x-csrf-token": issued.csrf_token},
            json={"instance_id": other.instance_id, "world_id": "tutorial"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "entry_instance_world_mismatch")

    def mock_fleet_health(self, *records: object) -> None:
        runtime = self.app.state.mc
        original = runtime.http
        by_port = {int(record.endpoint.rsplit(":", 1)[1]): record for record in records}

        def handler(request: httpx.Request) -> httpx.Response:
            record = by_port.get(request.url.port)
            if record is None:
                return httpx.Response(503)
            return httpx.Response(
                200,
                json={"ok": True, "world_id": record.world_id, "instance_id": record.instance_id},
            )

        runtime.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addCleanup(lambda: __import__("asyncio").run(runtime.http.aclose()))
        self.addCleanup(lambda: __import__("asyncio").run(original.aclose()))

    def test_resolve_world_mismatch_offers_same_world_candidates(self) -> None:
        saved = self.add_running_instance("mc-saved", world_id="other-world", port=10001)
        live = self.add_running_instance("mc-live", port=10002)
        self.mock_fleet_health(saved, live)
        self.sign_in(saved.instance_id)

        response = self.client.get("/api/entry/resolve")

        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data["code"], "entry_instance_world_mismatch")
        self.assertTrue(data["can_repair"])
        self.assertEqual([candidate["instance_id"] for candidate in data["candidates"]], [live.instance_id])
        self.assertNotIn("current_world", data)

    def test_resolve_world_mismatch_without_candidates_offers_current_world(self) -> None:
        saved = self.add_running_instance("mc-saved", world_id="other-world", port=10001)
        self.mock_health(saved)
        self.sign_in(saved.instance_id)

        response = self.client.get("/api/entry/resolve")

        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data["code"], "entry_instance_world_mismatch")
        self.assertTrue(data["can_repair"])
        self.assertEqual(data["candidates"], [])
        self.assertEqual(data["current_world"]["instance_id"], saved.instance_id)
        self.assertEqual(data["current_world"]["world_id"], "other-world")

    def test_repair_rebinds_from_world_mismatch_to_same_world_instance(self) -> None:
        saved = self.add_running_instance("mc-saved", world_id="other-world", port=10001)
        live = self.add_running_instance("mc-live", port=10002)
        self.mock_fleet_health(saved, live)
        account, issued = self.sign_in(saved.instance_id)

        response = self.client.post(
            "/api/entry/repair",
            headers={"origin": self.origin, "x-csrf-token": issued.csrf_token},
            json={"instance_id": live.instance_id, "world_id": "tutorial"},
        )

        self.assertEqual(response.status_code, 200)
        profile = self.app.state.mc.profiles.get_user_profile(account.id)
        self.assertEqual(profile.last_instance_id, live.instance_id)
        self.assertEqual(profile.last_world_id, "tutorial")

    def test_switch_world_moves_player_to_saved_instance_world(self) -> None:
        saved = self.add_running_instance("mc-saved", world_id="other-world", port=10001)
        self.mock_health(saved)
        account, issued = self.sign_in(saved.instance_id)

        response = self.client.post(
            "/api/entry/repair",
            headers={"origin": self.origin, "x-csrf-token": issued.csrf_token},
            json={"instance_id": saved.instance_id, "switch_world": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["world_id"], "other-world")
        profile = self.app.state.mc.profiles.get_user_profile(account.id)
        self.assertEqual(profile.last_world_id, "other-world")
        self.assertEqual(profile.remembered_room, "hub")
        self.assertEqual(profile.last_instance_id, saved.instance_id)
        self.assertEqual(self.client.get("/api/entry/resolve").status_code, 200)

    def test_switch_world_rejected_when_same_world_candidate_exists(self) -> None:
        saved = self.add_running_instance("mc-saved", world_id="other-world", port=10001)
        live = self.add_running_instance("mc-live", port=10002)
        self.mock_fleet_health(saved, live)
        account, issued = self.sign_in(saved.instance_id)

        response = self.client.post(
            "/api/entry/repair",
            headers={"origin": self.origin, "x-csrf-token": issued.csrf_token},
            json={"instance_id": saved.instance_id, "switch_world": True},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "entry_world_switch_unavailable")
        self.assertEqual(self.app.state.mc.profiles.get_user_profile(account.id).last_world_id, "tutorial")

    def test_switch_world_rejected_when_saved_instance_is_not_mismatched(self) -> None:
        other = self.add_running_instance("mc-other", world_id="other-world", port=10002)
        self.mock_health(other)
        account, issued = self.sign_in("mc-missing")

        response = self.client.post(
            "/api/entry/repair",
            headers={"origin": self.origin, "x-csrf-token": issued.csrf_token},
            json={"instance_id": other.instance_id, "switch_world": True},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "entry_world_switch_unavailable")
        self.assertEqual(self.app.state.mc.profiles.get_user_profile(account.id).last_world_id, "tutorial")

    def test_retired_instance_successor_is_ranked_first(self) -> None:
        retired = self.add_running_instance("mc-retired", port=10001)
        replacement = self.add_running_instance("mc-replacement", port=10002)
        self.add_running_instance("mc-other", port=10003)
        runtime = self.app.state.mc
        runtime.registry.remove(retired.instance_id)
        runtime.retired.record(retired, successor_instance_id=replacement.instance_id)
        self.sign_in(retired.instance_id)

        response = self.client.get("/api/entry/resolve")

        self.assertEqual(response.status_code, 409)
        candidates = response.json()["candidates"]
        self.assertEqual(candidates[0]["instance_id"], replacement.instance_id)
        self.assertTrue(candidates[0]["replacement"])

    def test_missing_saved_instance_auto_switches_to_default(self) -> None:
        default = self.add_running_instance("mc-default", world_id="other-world", port=10003)
        self.mock_health(default)
        runtime = self.app.state.mc
        runtime.entry_settings.set_default(default.instance_id)
        account, _ = self.sign_in("mc-missing")

        response = self.client.get("/api/entry/resolve")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["instance_id"], default.instance_id)
        self.assertEqual(data["world_id"], "other-world")
        self.assertTrue(data["auto_switched"])
        self.assertEqual(data["previous_instance_id"], "mc-missing")
        profile = runtime.profiles.get_user_profile(account.id)
        self.assertEqual(profile.last_instance_id, default.instance_id)
        self.assertEqual(profile.last_world_id, "other-world")
        entries = runtime.audit.entries()
        self.assertTrue(
            any(
                entry["action"] == "player.destination.auto_switch"
                and entry["target"] == default.instance_id
                for entry in entries
            )
        )
        self.assertEqual(self.client.get("/api/entry/resolve").status_code, 200)

    def test_missing_saved_instance_keeps_repair_when_default_unusable(self) -> None:
        default = self.add_running_instance("mc-default", port=10003)
        runtime = self.app.state.mc
        runtime.entry_settings.set_default(default.instance_id)
        runtime.registry.set_status(default.instance_id, STATUS_STOPPED)
        self.sign_in("mc-missing")

        response = self.client.get("/api/entry/resolve")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "entry_instance_missing")


if __name__ == "__main__":
    unittest.main()
