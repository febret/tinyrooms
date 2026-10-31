"""Multiverse core view discovery, travel, and presentation contracts."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from server.commands.outcomes import CommandError
from server.content.activities import load_activity_definitions
from server.content.common import ContentError
from server.services.cross_world import CrossWorldService
from tests.common import (
    REPO_ROOT,
    IntegrationTestCase,
    RuntimeTestCase,
    load_test_world,
    websocket_headers,
)
from tests.mc_helpers import McHttpTestCase


MC_TOKEN = "shared"


class MultiverseContentTests(unittest.TestCase):
    def test_multiverse_is_not_an_activity(self) -> None:
        world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        self.assertNotIn("multiverse", world.activities)
        core = load_activity_definitions(REPO_ROOT / "data" / "core" / "activities.yaml", source="test")
        self.assertNotIn("multiverse", core)

    def test_activity_skill_must_be_non_empty(self) -> None:
        with TemporaryDirectory() as root:
            path = Path(root) / "activities.yaml"
            path.write_text("test:\n  title: Test\n  skill: '   '\n", encoding="utf-8")
            with self.assertRaisesRegex(ContentError, "skill must be a non-empty string"):
                load_activity_definitions(path, source="test")

    def test_activity_flag_must_be_non_empty(self) -> None:
        with TemporaryDirectory() as root:
            path = Path(root) / "activities.yaml"
            path.write_text("test:\n  title: Test\n  flag: '   '\n", encoding="utf-8")
            with self.assertRaisesRegex(ContentError, "flag must be a non-empty string"):
                load_activity_definitions(path, source="test")


class WorldImageRouteTests(RuntimeTestCase):
    def test_world_image_is_served(self) -> None:
        response = self.client.get("/assets/world-image")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.content)
        self.assertIn(response.headers.get("content-type", ""), {"image/jpeg", "image/png"})


class MultiverseCoreAssetsTests(RuntimeTestCase):
    def test_core_view_document_and_assets_are_served(self) -> None:
        index = self.client.get("/")
        self.assertEqual(index.status_code, 200, index.text)
        self.assertIn("/app/css/multiverse.css", index.text)
        self.assertIn("/app/js/ui.js", index.text)
        for path in (
            "/app/js/views/multiverse-view.js",
            "/app/css/multiverse.css",
            "/app/assets/textures/multiverse-nebula.png",
            "/app/assets/textures/multiverse-vortex.png",
            "/app/assets/textures/multiverse-world-placeholder.png",
            "/assets/sounds/multiverse-open.wav",
            "/assets/sounds/multiverse-close.wav",
            "/assets/sounds/multiverse-select.wav",
            "/assets/sounds/multiverse-travel.wav",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertTrue(response.content, path)


class MultiverseCommandIntegrationTests(IntegrationTestCase):
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
        self.assertFalse(runtime.profiles.has_multiverse_access(account_id))
        runtime.config = replace(runtime.config, mc_endpoint="mc.example:8001", mc_token=MC_TOKEN)
        runtime.cross_world._config = runtime.config  # noqa: SLF001
        runtime.cross_world._client = self._client_for()  # noqa: SLF001

        with self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(credentials["session_token"], credentials["csrf_token"]),
        ) as socket:
            socket.receive_json()
            used = self.command(socket, "multiverse-unlock", f".use @card:{stack_id}")
            self.assertTrue(used["ok"], used)
            self.assertTrue(runtime.profiles.has_multiverse_access(account_id))
            owned = [
                stack
                for stack in runtime.profiles.list_inventory(account_id, runtime.world.id)
                if stack.card_def_id == "multiverse-map"
            ]
            self.assertEqual([stack.quantity for stack in owned], [1])

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

    def test_multiverse_commands_require_access_without_the_flag(self) -> None:
        credentials = self.create_ready_account("multiverse-locked")
        runtime = self.runtime()
        account_id = self.account_id(credentials)
        self.assertFalse(runtime.profiles.has_multiverse_access(account_id))

        with self.client.websocket_connect(
            "/ws",
            headers=websocket_headers(credentials["session_token"], credentials["csrf_token"]),
        ) as socket:
            socket.receive_json()
            listing = self.command(socket, "multiverse-denied", ".multiverse_worlds")
            self.assertFalse(listing["ok"], listing)
            self.assertIn("unlock cross-world travel", listing["message"])


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
