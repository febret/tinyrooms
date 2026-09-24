"""Milestone 3 Phase G activity result hook, bridge, and record tests."""

from __future__ import annotations

import unittest
from zoneinfo import ZoneInfo

from server.content.activities import ActivityDefinition
from server.services.activity_results import ActivityResultService
from server.services.progression import ProgressionService
from server.services.stats import StatsService
from server.services.tasks import TaskService
from tests.common import WORLD_ID, ServiceTestCase
from tests.test_milestone1 import auth_cookies, auth_headers, websocket_headers
from tests.test_milestone2_integration import Milestone2IntegrationTestCase
from tests.test_milestone3_tasks import make_step, make_task


UTC = ZoneInfo("UTC")


def definition(
    kind: str,
    *,
    start_cost: int = 1,
    record: bool = True,
    min_completed_round: float = 0.0,
) -> ActivityDefinition:
    """Build a test activity definition with sensible result-hook defaults."""

    return ActivityDefinition(
        id=kind,
        title=kind.replace("-", " ").title(),
        room_bound=True,
        aliases=(),
        rooms=(),
        required_feature=None,
        source="test",
        start_cost=start_cost,
        record=record,
        min_completed_round=min_completed_round,
    )


class ActivityResultServiceTestCase(ServiceTestCase):
    """Shared fixtures for the result service tests."""

    def setUp(self) -> None:
        super().setUp()
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.progression = ProgressionService(
            self.hub, self.profiles, self.stats, self.catalog, self.content, WORLD_ID
        )

    def build(self, definitions=None, task_definitions=None):
        """Construct a result service with optional custom definitions and tasks."""

        tasks = TaskService(
            self.hub,
            self.profiles,
            self.stats,
            self.progression,
            self.content,
            WORLD_ID,
            task_definitions or {},
            UTC,
        )
        service = ActivityResultService(
            self.hub,
            self.profiles,
            self.stats,
            self.progression,
            tasks,
            WORLD_ID,
            definitions or {"lazor-rush": definition("lazor-rush")},
        )
        return service, tasks


class StartCostTests(ActivityResultServiceTestCase):
    """Start costs are charged, and affordability follows Energy rules."""

    def test_start_charges_the_cost(self) -> None:
        service, _ = self.build()
        account = self.create_account("ann")
        first = service.start(account, "lazor-rush")
        self.assertEqual(first.charged, 1)
        self.assertEqual(self.reload_account(account).shared_energy, 79)
        second = service.start(account, "lazor-rush")
        self.assertEqual(second.charged, 1)
        self.assertEqual(self.reload_account(account).shared_energy, 78)

    def test_start_without_energy_is_rejected_without_charge(self) -> None:
        service, _ = self.build(
            {
                "lazor-rush": definition("lazor-rush"),
                "pricey": definition("pricey", start_cost=5),
            }
        )
        account = self.create_account("bea")
        self.set_energy(account, 1)
        with self.assertRaises(ValueError):
            service.start(account, "pricey")
        self.assertEqual(self.reload_account(account).shared_energy, 1)
        service.start(account, "lazor-rush")
        self.assertEqual(self.reload_account(account).shared_energy, 0)
        with self.assertRaises(ValueError):
            service.start(account, "lazor-rush")
        done = service.complete(account, "lazor-rush", {"seconds": 5.0, "captured": True})
        self.assertTrue(done.recorded)


class RecordTests(ActivityResultServiceTestCase):
    """Only captured completed rounds count, and records are personal and shared."""

    def test_only_captured_rounds_record(self) -> None:
        service, _ = self.build()
        account = self.create_account("dee")
        missed = service.complete(account, "lazor-rush", {"seconds": 30.0, "captured": False})
        self.assertFalse(missed.recorded)
        self.assertIsNone(service.records(account.id, "lazor-rush").personal_best)

    def test_personal_and_world_records(self) -> None:
        service, _ = self.build()
        alice = self.create_account("fay")
        bob = self.create_account("gil")
        service.complete(alice, "lazor-rush", {"seconds": 12.5, "captured": True})
        service.complete(alice, "lazor-rush", {"seconds": 8.0, "captured": True})
        self.assertEqual(service.records(alice.id, "lazor-rush").personal_best, 12.5)
        service.complete(bob, "lazor-rush", {"seconds": 20.0, "captured": True})
        self.assertEqual(service.records(alice.id, "lazor-rush").personal_best, 12.5)
        self.assertEqual(service.records(bob.id, "lazor-rush").personal_best, 20.0)
        self.assertEqual(service.records(alice.id, "lazor-rush").world_best, 20.0)
        self.assertEqual(service.records(bob.id, "lazor-rush").world_best, 20.0)

    def test_malformed_results_are_rejected(self) -> None:
        service, _ = self.build()
        account = self.create_account("iva")
        with self.assertRaises(ValueError):
            service.complete(account, "lazor-rush", {"seconds": -1, "captured": True})
        self.assertIsNone(service.records(account.id, "lazor-rush").personal_best)

    def test_completion_fires_the_activity_result_trigger(self) -> None:
        tasks_definitions = {
            "lazor-round": make_task(
                "lazor-round",
                [make_step("play", "activity_result", match={"activity": "lazor-rush"})],
                kudos=1,
            )
        }
        service, tasks = self.build(task_definitions=tasks_definitions)
        account = self.create_account("joe")
        service.start(account, "lazor-rush")
        service.complete(account, "lazor-rush", {"seconds": 21.0, "captured": True})
        view = tasks.view(account.id, "lazor-round")
        self.assertIsNotNone(view)
        self.assertEqual(view["status"], "completed")
        self.assertEqual(self.reload_account(account).kudos, 1)


class ActivityResultIntegrationTests(Milestone2IntegrationTestCase):
    """Signed bridge results work end to end over HTTP and the WebSocket."""

    def _bridge(self, credentials, activity, payload):
        return self.client.post(
            f"/api/activities/{activity['id']}/bridge",
            json={"type": "activity.result", "payload": payload},
            headers=auth_headers(credentials["csrf_token"]),
            cookies=auth_cookies(credentials["session_token"], credentials["csrf_token"]),
        )

    def _open_and_start(self, socket):
        opened = self.command(socket, "play-1", ".play lazor-rush")
        self.assertTrue(opened["ok"], opened)
        activity = opened["payload"]["activity"]
        started = self.command(socket, "start-1", ".activity_start")
        self.assertTrue(started["ok"], started)
        return activity, started

    def test_signed_result_records(self) -> None:
        credentials = self.create_ready_account("gwen")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            activity, started = self._open_and_start(socket)
            self.assertEqual(started["payload"]["round"]["charged"], 1)
            response = self._bridge(
                credentials,
                activity,
                {"result": {"seconds": 12.5, "captured": True}, "token": activity["token"]},
            )
            body = response.json()
            self.assertTrue(body["ok"], body)
            self.assertTrue(body["recorded"])
            self.assertEqual(body["records"]["personal_best"], 12.5)
            records = self.command(socket, "records-1", ".activity_records lazor-rush")
            self.assertEqual(records["payload"]["records"]["personal_best"], 12.5)

    def test_tampered_result_changes_nothing(self) -> None:
        credentials = self.create_ready_account("hana")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            activity, _ = self._open_and_start(socket)
            tampered = self._bridge(
                credentials,
                activity,
                {"result": {"seconds": 99.0, "captured": True}, "token": "not-a-signature"},
            )
            self.assertEqual(tampered.status_code, 400)
            records = self.command(socket, "records-1", ".activity_records lazor-rush")
            self.assertIsNone(records["payload"]["records"]["personal_best"])

    def test_close_does_not_refund(self) -> None:
        credentials = self.create_ready_account("ivy")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            self._open_and_start(socket)
            self.command(socket, "cancel-1", ".cancel")
            records = self.command(socket, "records-1", ".activity_records lazor-rush")
            self.assertIsNone(records["payload"]["records"]["personal_best"])
        self.assertEqual(self.bootstrap(credentials)["counters"]["energy"], 79)

    def test_room_change_does_not_refund(self) -> None:
        credentials = self.create_ready_account("jax")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            self._open_and_start(socket)
            moved = self.command(socket, "go-1", ".go @way:exit0")
            self.assertTrue(moved["ok"], moved)
            socket.receive_json()
            records = self.command(socket, "records-1", ".activity_records lazor-rush")
            self.assertIsNone(records["payload"]["records"]["personal_best"])
        self.assertEqual(self.bootstrap(credentials)["counters"]["energy"], 78)


if __name__ == "__main__":
    unittest.main()
