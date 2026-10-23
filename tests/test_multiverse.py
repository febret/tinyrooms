"""Multiverse activity discovery, travel, and presentation contracts."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from server.commands.activity_launch import ResolvedActivity, start_activity
from server.commands.outcomes import CommandError
from server.content.activities import ActivityDefinition, load_activity_definitions
from server.content.common import ContentError
from server.services.cross_world import CrossWorldService
from tests.common import (
    REPO_ROOT,
    Milestone2IntegrationTestCase,
    RuntimeTestCase,
    load_test_world,
    websocket_headers,
)
from tests.mc_helpers import McHttpTestCase


MC_TOKEN = "shared"


def _activity_definition(skill: str | None = "multiverse-map") -> ActivityDefinition:
    return ActivityDefinition(
        id="multiverse",
        title="Multiverse",
        aliases=(),
        rooms=(),
        required_feature=None,
        source="test",
        required_skill=skill,
    )


class ActivitySkillGateTests(unittest.TestCase):
    def _context(self, *, admin: bool, slotted: bool):
        context = SimpleNamespace(
            account=SimpleNamespace(id="account-1"),
            powers=Mock(),
            progression=Mock(),
            activities=Mock(),
        )
        context.powers.has_power.return_value = admin
        context.progression.has_slotted_skill.return_value = slotted
        session = SimpleNamespace(id="session-1")
        context.activities.start.return_value = (session, None)
        context.activities.serialize.return_value = {"id": "session-1"}
        return context

    def test_launch_requires_slotted_map(self) -> None:
        context = self._context(admin=False, slotted=False)
        with self.assertRaises(CommandError) as caught:
            start_activity(
                context,
                ResolvedActivity(_activity_definition()),
                room_id="hub",
                replace_existing=False,
            )
        self.assertIn("Multiverse Map", str(caught.exception))
        context.activities.start.assert_not_called()

    def test_launch_allows_slotted_map(self) -> None:
        context = self._context(admin=False, slotted=True)
        outcome = start_activity(
            context,
            ResolvedActivity(_activity_definition()),
            room_id="hub",
            replace_existing=False,
        )
        self.assertEqual(outcome.payload["activity"], {"id": "session-1"})
        context.activities.start.assert_called_once()


class MultiverseContentTests(unittest.TestCase):
    def test_core_activity_requires_multiverse_map(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        definition = world.activities["multiverse"]
        self.assertEqual(definition.required_skill, "multiverse-map")

    def test_activity_skill_must_be_non_empty(self) -> None:
        with TemporaryDirectory() as root:
            path = Path(root) / "activities.yaml"
            path.write_text("test:\n  title: Test\n  skill: '   '\n", encoding="utf-8")
            with self.assertRaisesRegex(ContentError, "skill must be a non-empty string"):
                load_activity_definitions(path, source="test")

    def test_world_images_are_loaded_from_world_yaml(self) -> None:
        tutorial = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        scammon = load_test_world(REPO_ROOT / "worlds" / "scammon-academia")
        self.assertEqual(tutorial.image_name, "rooms/hub.jpg")
        self.assertTrue(tutorial.image_path is not None and tutorial.image_path.is_file())
        self.assertEqual(scammon.image_name, "rooms/hall.png")
        self.assertTrue(scammon.image_path is not None and scammon.image_path.is_file())


class WorldImageRouteTests(RuntimeTestCase):
    def test_world_image_is_served(self) -> None:
        response = self.client.get("/assets/world-image")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.content)
        self.assertIn(response.headers.get("content-type", ""), {"image/jpeg", "image/png"})


class MultiverseActivityAssetsTests(RuntimeTestCase):
    def test_activity_document_and_assets_are_served(self) -> None:
        index = self.client.get("/activities/multiverse/")
        self.assertEqual(index.status_code, 200, index.text)
        self.assertIn("multiverse.js", index.text)
        for path in (
            "/activities/multiverse/multiverse.js",
            "/activities/multiverse/multiverse.css",
            "/activities/multiverse/world-placeholder.svg",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertTrue(response.content, path)


class MultiverseCommandIntegrationTests(Milestone2IntegrationTestCase):
    def _client_for(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/mc/worlds":
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "worlds": [
                            {
                                "id": "tutorial",
                                "label": "The Little House",
                                "description": "A pocket-sized home.",
                                "image": "rooms/hub.jpg",
                                "users_online": 1,
                                "online_account_ids": [],
                                "instances": [
                                    {
                                        "instance_id": "tutorial-1",
                                        "client_url": "https://testserver:5100",
                                        "image_url": "https://testserver:5100/assets/world-image",
                                    }
                                ],
                            },
                            {
                                "id": "scammon-academia",
                                "label": "Scammon Academia",
                                "description": "A cheery little school.",
                                "image": "",
                                "users_online": 0,
                                "online_account_ids": [],
                                "instances": [
                                    {
                                        "instance_id": "scammon-1",
                                        "client_url": "https://testserver:5101",
                                        "image_url": "",
                                    }
                                ],
                            },
                        ],
                    },
                )
            if request.url.path == "/api/mc/instances/scammon-academia/destination":
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "instance_id": "scammon-1",
                        "world_id": "scammon-academia",
                        "client_url": "https://testserver:5101",
                        "entry_room_id": "hall",
                    },
                )
            raise AssertionError(f"unexpected mission-control request: {request.url.path}")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addCleanup(lambda: asyncio.run(client.aclose()))
        return client

    def test_play_list_and_travel_commands(self) -> None:
        credentials = self.create_ready_account("multiverse-explorer")
        account_id = self.account_id(credentials)
        stack_id = self.grant_card(account_id, "multiverse-map")
        runtime = self.runtime()
        account = runtime.profiles.get_account_by_id(account_id)
        with runtime.hub.transaction() as connection:
            account = runtime.profiles.update_progress(connection, account, level=1)
        runtime.progression.slot_skill(account, 0, stack_id)
        runtime.config = replace(runtime.config, mc_endpoint="mc.example:8001", mc_token=MC_TOKEN)
        runtime.cross_world._config = runtime.config  # noqa: SLF001
        runtime.cross_world._client = self._client_for()  # noqa: SLF001

        with self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(credentials["session_token"], credentials["csrf_token"]),
        ) as socket:
            socket.receive_json()
            opened = self.command(socket, "multiverse-open", ".play multiverse")
            self.assertTrue(opened["ok"], opened)
            self.assertIn("/activities/multiverse/", opened["payload"]["activity"]["iframe_url"])

            listing = self.command(socket, "multiverse-list", ".multiverse_worlds")
            self.assertTrue(listing["ok"], listing)
            worlds = listing["payload"]["worlds"]
            self.assertEqual([world["id"] for world in worlds], ["tutorial", "scammon-academia"])
            self.assertTrue(worlds[0]["current"])
            self.assertEqual(worlds[0]["friends"], [])

            travel = self.command(socket, "multiverse-travel", ".multiverse_travel scammon-academia")
            self.assertTrue(travel["ok"], travel)
            self.assertEqual(travel["payload"]["travel"]["url"], "https://testserver:5101")
            self.assertEqual(travel["payload"]["travel"]["room_id"], "hall")


class FleetWorldsTests(McHttpTestCase):
    def _register(self, *, instance_id: str, world_id: str, label: str, description: str, image: str, client_url: str) -> None:
        response = self.client.post(
            "/api/mc/register",
            headers={"X-MC-Token": MC_TOKEN},
            json={
                "instance_name": instance_id,
                "instance_id": instance_id,
                "endpoint": client_url,
                "client_url": client_url,
                "version": "1.0.0",
                "protocol_version": 1,
                "world": {
                    "id": world_id,
                    "label": label,
                    "description": description,
                    "image": image,
                    "entry_room_id": "entry",
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _heartbeat(self, instance_id: str, account_ids: list[str]) -> None:
        response = self.client.post(
            "/api/mc/heartbeat",
            headers={"X-MC-Token": MC_TOKEN},
            json={
                "instance_id": instance_id,
                "users_online": len(account_ids),
                "online_account_ids": account_ids,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"])

    def test_fleet_worlds_group_running_instances_and_presence(self) -> None:
        self._register(
            instance_id="tutorial-1",
            world_id="tutorial",
            label="The Little House",
            description="A pocket-sized home.",
            image="rooms/hub.jpg",
            client_url="https://127.0.0.1:5100",
        )
        self._register(
            instance_id="scammon-1",
            world_id="scammon-academia",
            label="Scammon Academia",
            description="A cheery little school.",
            image="rooms/hall.png",
            client_url="https://127.0.0.1:5101",
        )
        self._heartbeat("tutorial-1", ["peep-a", "peep-b"])
        self._heartbeat("scammon-1", ["peep-c"])

        response = self.client.get("/api/mc/worlds", headers={"X-MC-Token": MC_TOKEN})
        self.assertEqual(response.status_code, 200, response.text)
        worlds = response.json()["worlds"]
        self.assertEqual([world["id"] for world in worlds], ["scammon-academia", "tutorial"])
        by_id = {world["id"]: world for world in worlds}
        self.assertEqual(by_id["tutorial"]["users_online"], 2)
        self.assertEqual(by_id["tutorial"]["online_account_ids"], ["peep-a", "peep-b"])
        self.assertEqual(by_id["tutorial"]["description"], "A pocket-sized home.")
        self.assertEqual(by_id["tutorial"]["image"], "rooms/hub.jpg")
        self.assertTrue(by_id["tutorial"]["instances"][0]["image_url"].endswith("/assets/world-image"))

    def test_destination_prefers_requested_host(self) -> None:
        self._register(
            instance_id="tutorial-1",
            world_id="tutorial",
            label="The Little House",
            description="A pocket-sized home.",
            image="",
            client_url="https://first.example:5100",
        )
        self._register(
            instance_id="tutorial-2",
            world_id="tutorial",
            label="The Little House",
            description="A pocket-sized home.",
            image="",
            client_url="https://second.example:5101",
        )
        validator = AsyncMock(side_effect=lambda runtime, record: record.client_url)
        with patch("server.mission_control.entry._validate_running_destination", new=validator):
            response = self.client.get(
                "/api/mc/instances/tutorial/destination",
                params={"host": "second.example"},
                headers={"X-MC-Token": MC_TOKEN},
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["instance_id"], "tutorial-2")
        self.assertEqual(payload["client_url"], "https://second.example:5101")

    def test_fleet_worlds_requires_token_and_excludes_stopped_worlds(self) -> None:
        self._register(
            instance_id="tutorial-1",
            world_id="tutorial",
            label="The Little House",
            description="A pocket-sized home.",
            image="",
            client_url="https://127.0.0.1:5100",
        )
        self.assertEqual(self.client.get("/api/mc/worlds").status_code, 403)
        deregistered = self.client.post(
            "/api/mc/deregister",
            headers={"X-MC-Token": MC_TOKEN},
            json={"instance_id": "tutorial-1"},
        )
        self.assertEqual(deregistered.status_code, 200, deregistered.text)
        response = self.client.get("/api/mc/worlds", headers={"X-MC-Token": MC_TOKEN})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["worlds"], [])


class CrossWorldWorldListTests(unittest.TestCase):
    def _service(self, handler) -> CrossWorldService:
        config = SimpleNamespace(
            mc_endpoint="mc.example:8001",
            mc_token=MC_TOKEN,
            mc_insecure_tls=False,
            mc_ca_file=None,
            client_url="https://testserver:5000",
            host="testserver",
        )
        return CrossWorldService(
            config=config,
            hub=Mock(),
            profiles=Mock(),
            world_id="tutorial",
            progression=Mock(),
            powers=Mock(),
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

    def test_list_worlds_selects_same_host_destination(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/mc/worlds")
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "worlds": [
                        {
                            "id": "tutorial",
                            "label": "The Little House",
                            "description": "A pocket-sized home.",
                            "image": "rooms/hub.jpg",
                            "users_online": 2,
                            "online_account_ids": ["peep-a", "peep-b"],
                            "instances": [
                                {"instance_id": "other", "client_url": "https://elsewhere:5000", "image_url": "https://elsewhere:5000/assets/world-image"},
                                {"instance_id": "tutorial-1", "client_url": "https://testserver:5100", "image_url": "https://testserver:5100/assets/world-image"},
                            ],
                        },
                        {
                            "id": "scammon-academia",
                            "label": "Scammon Academia",
                            "description": "School.",
                            "image": "",
                            "users_online": 0,
                            "online_account_ids": [],
                            "instances": [
                                {"instance_id": "scammon-1", "client_url": "https://testserver:5101", "image_url": ""},
                            ],
                        },
                    ],
                },
            )

        service = self._service(handler)
        worlds = asyncio.run(service.list_worlds())
        self.assertEqual([world["id"] for world in worlds], ["tutorial", "scammon-academia"])
        self.assertTrue(worlds[0]["current"])
        self.assertEqual(worlds[0]["image_url"], "https://testserver:5100/assets/world-image")
        self.assertEqual(worlds[0]["online_account_ids"], ["peep-a", "peep-b"])
        self.assertFalse(worlds[1]["current"])
