"""Shared instance policy, guest cap, and invitation tests."""

from __future__ import annotations

import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from server.instance_policy import (
    AccountLimitError,
    InstancePolicyError,
    InstancePolicyStore,
    WorldLimitError,
)
from server.mission_control.audit import McAuditLog
from server.mission_control.config import load_mc_config
from server.mission_control.entry import PlayerAuthService
from server.mission_control.registry import InstanceRegistry
from server.mission_control.supervisor import Supervisor
from server.profiles import ProfileRepository
from tests.common import REPO_ROOT, ServiceTestCase
from tests.mc_helpers import McHttpTestCase, mc_env


class PolicyStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.path = self.root / "instance-policy.json"

    def test_missing_file_returns_legacy_fallback(self) -> None:
        store = InstancePolicyStore(
            self.path,
            fallback_invitation="invite-123",
            fallback_max_guests=10,
            fallback_max_worlds=2,
        )
        policy = store.load()
        self.assertEqual(policy.invitation_code, "invite-123")
        self.assertEqual(policy.max_guests, 10)
        self.assertEqual(policy.max_worlds, 2)
        self.assertEqual(policy.updated_at, "")

    def test_update_is_atomic_private_and_cached(self) -> None:
        store = InstancePolicyStore(self.path, fallback_invitation="invite-123")
        updated = store.update(invitation_code="new-code", max_guests=25, max_worlds=3)
        self.assertEqual(updated.invitation_code, "new-code")
        self.assertEqual(updated.max_guests, 25)
        self.assertEqual(updated.max_worlds, 3)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["invitation_code"], "new-code")
        self.assertEqual(payload["version"], 1)
        self.assertTrue(self.path.exists())
        if os.name == "posix":
            mode = self.path.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)
        self.assertEqual(store.load(), updated)
        self.assertEqual(
            [item.name for item in self.root.iterdir()], ["instance-policy.json"]
        )

    def test_update_validates_fields(self) -> None:
        store = InstancePolicyStore(self.path, fallback_invitation="invite-123")
        with self.assertRaises(InstancePolicyError):
            store.update(invitation_code="short")
        with self.assertRaises(InstancePolicyError):
            store.update(max_guests=0)
        with self.assertRaises(InstancePolicyError):
            store.update(max_worlds=100)
        self.assertFalse(self.path.exists())

    def test_invitation_reads_current_value_without_restart(self) -> None:
        from server.state.migrations import DatabaseHub
        from tests.common import ensure_profile_database

        db_path = self.root / "profiles.sqlite3"
        ensure_profile_database(db_path)
        hub = DatabaseHub(db_path)
        self.addCleanup(hub.close)
        store = InstancePolicyStore(self.path, fallback_invitation="invite-123")
        profiles = ProfileRepository(hub, policy_store=store)
        auth = PlayerAuthService(profiles, "invite-123", policy_store=store)
        self.assertEqual(auth.invitation, "invite-123")
        store.update(invitation_code="changed-code")
        self.assertEqual(auth.invitation, "changed-code")


class GuestCapTests(ServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.policy_path = Path(self.temporary_directory.name) / "instance-policy.json"
        self.store = InstancePolicyStore(
            self.policy_path,
            fallback_invitation="invite-123",
            fallback_max_guests=2,
            fallback_max_worlds=4,
        )
        self.profiles = ProfileRepository(self.hub, policy_store=self.store)

    def test_guest_cap_is_enforced_in_account_creation(self) -> None:
        self.create_account("guest-one")
        self.create_account("guest-two")
        with self.assertRaises(AccountLimitError):
            self.create_account("guest-three")
        self.assertEqual(self.profiles.count_accounts(), 2)

    def test_lowering_cap_keeps_existing_accounts(self) -> None:
        first = self.create_account("guest-one")
        second = self.create_account("guest-two")
        self.store.update(max_guests=1)
        self.assertIsNotNone(self.profiles.get_account_by_id(first.id))
        self.assertIsNotNone(self.profiles.get_account_by_id(second.id))
        with self.assertRaises(AccountLimitError):
            self.create_account("guest-three")

    def test_concurrent_creation_does_not_exceed_cap(self) -> None:
        self.store.update(max_guests=2)

        def attempt(index: int) -> str:
            try:
                self.create_account(f"guest-{index}")
                return "created"
            except AccountLimitError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(attempt, range(5)))
        self.assertEqual(results.count("created"), 2)
        self.assertEqual(results.count("rejected"), 3)
        self.assertEqual(self.profiles.count_accounts(), 2)

    def test_latest_session_activity_is_nullable_and_tracked(self) -> None:
        self.assertEqual(self.profiles.latest_session_activity(), None)
        account = self.create_account("guest-one")
        self.profiles.issue_session(account.id)
        self.assertIsNotNone(self.profiles.latest_session_activity())


class WorldCapTests(unittest.TestCase):
    def test_supervisor_rejects_start_at_world_cap(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy_path = root / "instance-policy.json"
            config = load_mc_config(
                env=mc_env(root, TRSERVER_MC_INSTANCE_POLICY_PATH=str(policy_path)),
                repo_root=REPO_ROOT,
            )
            store = InstancePolicyStore(policy_path, fallback_invitation="invite-123")
            store.update(max_guests=10, max_worlds=1)
            registry = InstanceRegistry()
            registry.register_spawned(
                name="existing",
                endpoint="https://127.0.0.1:5999",
                instance_dir=str(root / "existing"),
                process_handle=None,
                spawn_config={
                    "world_path": str(REPO_ROOT / "worlds" / "tutorial"),
                    "worldstate_path": str(root / "worldstate.sqlite3"),
                    "users_path": str(root / "users"),
                    "host": "127.0.0.1",
                    "port": 5999,
                },
            )
            supervisor = Supervisor(
                config,
                registry,
                McAuditLog(),
                policy_store=store,
                spawn=lambda *args, **kwargs: None,
            )
            with self.assertRaises(WorldLimitError):
                supervisor.start(
                    name="second",
                    world_path=REPO_ROOT / "worlds" / "tutorial",
                    host="127.0.0.1",
                )


class PolicyHttpTests(McHttpTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.login()

    def test_policy_get_and_put(self) -> None:
        initial = self.client.get("/api/mission-control/instance-policy")
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.json()["ok"], True)
        response = self.client.put(
            "/api/mission-control/instance-policy",
            json={"invitation_code": "new-invite", "max_guests": 12, "max_worlds": 3},
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        policy = response.json()["policy"]
        self.assertEqual(policy["invitation_code"], "new-invite")
        self.assertEqual(policy["max_guests"], 12)
        self.assertEqual(policy["max_worlds"], 3)
        refreshed = self.client.get("/api/mission-control/instance-policy").json()[
            "policy"
        ]
        self.assertEqual(refreshed["invitation_code"], "new-invite")

    def test_policy_rejects_invalid_values(self) -> None:
        response = self.client.put(
            "/api/mission-control/instance-policy",
            json={"invitation_code": "x"},
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_policy")

    def test_usage_endpoint_reports_accounts_and_activity(self) -> None:
        runtime = self.app.state.mc
        runtime.policy_store.update(max_guests=10)
        account = runtime.profiles.create_account(
            "guest-one", "password123!", "tutorial", "hub"
        )
        runtime.profiles.issue_session(account.id)
        response = self.client.get("/api/mission-control/usage")
        self.assertEqual(response.status_code, 200)
        usage = response.json()["usage"]
        self.assertEqual(usage["account_count"], 1)
        self.assertEqual(usage["max_guests"], 10)
        self.assertGreaterEqual(usage["users_online"], 0)
        self.assertIsNotNone(usage["last_guest_activity_at"])
