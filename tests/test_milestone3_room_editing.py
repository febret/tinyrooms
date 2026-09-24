"""Milestone 3 Phase E room-owner decorative editing tests."""

from __future__ import annotations

import unittest

from server.services.environment import EnvironmentService
from server.services.ownership import OwnershipService
from server.services.room_layout import RoomLayoutService
from server.state.world_state import LayoutRevisionConflict, WorldStateRepository
from tests.common import REPO_ROOT, ServiceTestCase, WORLD_ID, load_test_world
from tests.test_milestone1 import auth_cookies, auth_headers, websocket_headers
from tests.test_milestone2_integration import Milestone2IntegrationTestCase


class RoomLayoutServiceTests(ServiceTestCase):
    """Validation, permission, and atomicity of the layout service."""

    def setUp(self) -> None:
        super().setUp()
        self.world = load_test_world(REPO_ROOT / "worlds" / WORLD_ID)
        self.world_state = WorldStateRepository(self.hub)
        self.world_state.initialize_world(self.world)
        self.ownership = OwnershipService(self.hub, self.profiles, self.world_state, self.world)
        self.environment = EnvironmentService(self.hub, self.world, self.world_state)
        self.layout = RoomLayoutService(
            self.hub,
            self.world,
            self.world_state,
            self.ownership,
            self.environment,
        )

    def owner(self, username: str = "alice", room: str = "hub"):
        account = self.create_account(username, room=room)
        self.ownership.grant(room, account.id)
        return account

    def editable_instance(self, prop_id: str, instance_id: str) -> dict[str, object]:
        return {
            "id": instance_id,
            "prop_id": prop_id,
            "position": [40, 40, 0],
            "rotation": [0, 0, 0],
            "scale": 1.0,
        }

    def test_owner_builder_and_admin_can_edit_but_unrelated_users_cannot(self) -> None:
        owner = self.owner("alice")
        stranger = self.create_account("bob")
        builder = self.create_account("carol")
        admin = self.create_account("dave")

        def layout_for(account, power):
            ownership = OwnershipService(
                self.hub,
                self.profiles,
                self.world_state,
                self.world,
                has_power=lambda account_id, candidate: candidate == power and account_id == account.id,
            )
            return RoomLayoutService(self.hub, self.world, self.world_state, ownership, self.environment)

        self.assertTrue(self.layout.can_edit(owner, "hub"))
        self.assertFalse(self.layout.can_edit(stranger, "hub"))
        self.assertTrue(layout_for(builder, "builder").can_edit(builder, "hub"))
        self.assertTrue(layout_for(admin, "admin").can_edit(admin, "hub"))
        with self.assertRaises(ValueError):
            self.layout.save(stranger, "hub", 0, {"props": []})

    def test_transform_bounds_scale_and_rotation_are_validated(self) -> None:
        owner = self.owner()
        base = self.layout.view(owner, "hub")["revision"]
        with self.assertRaises(ValueError):
            self.layout.save(owner, "hub", base, {"props": [self.editable_instance("plant", "welcome-plant") | {"position": [150, 10, 0]}]})
        with self.assertRaises(ValueError):
            self.layout.save(owner, "hub", base, {"props": [self.editable_instance("plant", "welcome-plant") | {"position": [10, 10, 99]}]})
        with self.assertRaises(ValueError):
            self.layout.save(owner, "hub", base, {"props": [self.editable_instance("plant", "welcome-plant") | {"scale": 99}]})
        update = self.layout.save(
            owner,
            "hub",
            base,
            {"props": [self.editable_instance("plant", "welcome-plant") | {"rotation": [0, 400, -30]}]},
        )
        self.assertEqual(update.revision, base + 1)
        plant = next(prop for prop in self.layout.effective_props("hub") if prop.id == "welcome-plant")
        self.assertEqual(plant.rot, (0.0, 40.0, 330.0))

    def test_invalid_and_duplicate_instance_ids_are_rejected(self) -> None:
        owner = self.owner()
        base = self.layout.view(owner, "hub")["revision"]
        with self.assertRaises(ValueError):
            self.layout.save(
                owner,
                "hub",
                base,
                {"props": [self.editable_instance("plant", "welcome-plant"), self.editable_instance("plant", "welcome-plant")]},
            )
        with self.assertRaises(ValueError):
            self.layout.save(owner, "hub", base, {"props": [self.editable_instance("plant", "made-up-id")]})
        with self.assertRaises(ValueError):
            self.layout.save(owner, "hub", base, {"props": [self.editable_instance("plant", "custom:not-a-uuid")]})

    def test_non_editable_props_are_rejected_atomically(self) -> None:
        owner = self.owner()
        before = self.layout.view(owner, "hub")
        with self.assertRaises(ValueError):
            self.layout.save(
                owner,
                "hub",
                before["revision"],
                {"props": [self.editable_instance("portal", "portal0")]},
            )
        after = self.layout.view(owner, "hub")
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["props"], before["props"])

    def test_stale_revision_conflict_commits_nothing(self) -> None:
        owner = self.owner()
        base = self.layout.view(owner, "hub")["revision"]
        self.layout.save(owner, "hub", base, {"props": [self.editable_instance("plant", "welcome-plant") | {"position": [11, 11, 0]}]})
        with self.assertRaises(LayoutRevisionConflict):
            self.layout.save(owner, "hub", base, {"props": []})
        layout = self.world_state.read_room_layout("hub")
        self.assertEqual(layout["revision"], base + 1)
        self.assertEqual(layout["props"][0]["position"], [11.0, 11.0, 0.0])

    def test_environment_whitelist_rejects_gameplay_values(self) -> None:
        owner = self.owner()
        base = self.layout.view(owner, "hub")["revision"]
        for patch in (
            {"lighting": "dark"},
            {"dark": True},
            {"hidden_props": {"portal0": True}},
            {"palette": ["not-a-color"]},
            {"board_image_style": "spiral"},
        ):
            with self.assertRaises(ValueError):
                self.layout.save(owner, "hub", base, {"props": [], "environment": patch})
        update = self.layout.save(
            owner,
            "hub",
            base,
            {"props": [], "environment": {"palette": ["#112233", "#445566", "#778899"], "board_image_style": "tile"}},
        )
        self.assertEqual(update.environment["board_image_style"], "tile")
        board = self.layout.effective_board("hub")
        self.assertEqual(board["board_image_style"], "tile")
        self.assertEqual(board["palette"], ["#112233", "#445566", "#778899"])
        self.assertNotIn("lighting", update.environment)

    def test_atomic_save_failure_preserves_previous_layout(self) -> None:
        owner = self.owner()
        base = self.layout.view(owner, "hub")["revision"]
        first = self.layout.save(owner, "hub", base, {"props": [self.editable_instance("plant", "welcome-plant") | {"position": [25, 25, 0]}]})
        with self.assertRaises(ValueError):
            self.layout.save(
                owner,
                "hub",
                first.revision,
                {
                    "props": [
                        self.editable_instance("plant", "welcome-plant") | {"position": [30, 30, 0]},
                        self.editable_instance("portal", "portal0"),
                    ]
                },
            )
        plant = next(prop for prop in self.layout.effective_props("hub") if prop.id == "welcome-plant")
        self.assertEqual(plant.pos, (25.0, 25.0, 0.0))
        self.assertEqual(self.world_state.read_room_layout("hub")["revision"], first.revision)

    def test_effective_props_merge_non_editable_and_allow_removal(self) -> None:
        owner = self.owner()
        initial = {prop.id for prop in self.layout.effective_props("hub")}
        self.assertIn("portal0", initial)
        self.assertIn("welcome-plant", initial)
        base = self.layout.view(owner, "hub")["revision"]
        self.layout.save(owner, "hub", base, {"props": []})
        remaining = {prop.id for prop in self.layout.effective_props("hub")}
        self.assertIn("portal0", remaining)
        self.assertNotIn("welcome-plant", remaining)

    def test_view_library_exposes_only_approved_props(self) -> None:
        owner = self.owner()
        view = self.layout.view(owner, "hub")
        library = {entry["prop_id"] for entry in view["library"]}
        self.assertEqual(library, {"plant"})
        self.assertIn("palette", view["environment_whitelist"])
        self.assertNotIn("lighting", view["environment_whitelist"])

    def test_custom_prop_instances_can_be_added(self) -> None:
        owner = self.owner()
        base = self.layout.view(owner, "hub")["revision"]
        custom_id = "custom:00000000-0000-4000-8000-000000000001"
        update = self.layout.save(
            owner,
            "hub",
            base,
            {"props": [self.editable_instance("plant", custom_id)]},
        )
        self.assertEqual(update.revision, base + 1)
        self.assertIn(custom_id, {prop.id for prop in self.layout.effective_props("hub")})


class RoomLayoutHttpTests(Milestone2IntegrationTestCase):
    """The HTTP layout endpoints enforce session, CSRF, and revisions."""

    def grant_ownership(self, credentials, room: str = "hub") -> None:
        account_id = self.account_id(credentials)
        self.runtime().ownership.grant(room, account_id)

    def test_layout_requires_a_session(self) -> None:
        response = self.client.get("/api/rooms/hub/layout")
        self.assertEqual(response.status_code, 401)

    def test_get_and_save_layout_round_trip(self) -> None:
        credentials = self.create_ready_account("erin")
        self.grant_ownership(credentials)
        cookies = auth_cookies(credentials["session_token"], credentials["csrf_token"])
        headers = auth_headers(credentials["csrf_token"])
        fetched = self.client.get("/api/rooms/hub/layout", cookies=cookies)
        self.assertEqual(fetched.status_code, 200, fetched.text)
        layout = fetched.json()["layout"]
        self.assertTrue(layout["can_edit"])
        saved = self.client.post(
            "/api/rooms/hub/layout",
            json={
                "base_revision": layout["revision"],
                "patch": {"props": [{"id": "welcome-plant", "prop_id": "plant", "position": [20, 20, 0], "rotation": [0, 0, 0], "scale": 1.0}]},
            },
            headers=headers,
            cookies=cookies,
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["layout"]["revision"], layout["revision"] + 1)
        self.assertEqual(saved.json()["layout"]["props"][0]["position"], [20, 20, 0])

    def test_stale_revision_returns_conflict_with_current_layout(self) -> None:
        credentials = self.create_ready_account("fred")
        self.grant_ownership(credentials)
        cookies = auth_cookies(credentials["session_token"], credentials["csrf_token"])
        headers = auth_headers(credentials["csrf_token"])
        first = self.client.post(
            "/api/rooms/hub/layout",
            json={"base_revision": 0, "patch": {"props": []}},
            headers=headers,
            cookies=cookies,
        )
        self.assertEqual(first.status_code, 200, first.text)
        stale = self.client.post(
            "/api/rooms/hub/layout",
            json={"base_revision": 0, "patch": {"props": []}},
            headers=headers,
            cookies=cookies,
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        body = stale.json()
        self.assertEqual(body["code"], "revision_conflict")
        self.assertEqual(body["layout"]["revision"], 1)

    def test_layout_post_requires_csrf_and_permission(self) -> None:
        credentials = self.create_ready_account("gina")
        cookies = auth_cookies(credentials["session_token"], credentials["csrf_token"])
        missing_csrf = self.client.post(
            "/api/rooms/hub/layout",
            json={"base_revision": 0, "patch": {"props": []}},
            headers={"origin": "https://testserver:5000"},
            cookies=cookies,
        )
        self.assertEqual(missing_csrf.status_code, 403)
        forbidden = self.client.post(
            "/api/rooms/hub/layout",
            json={"base_revision": 0, "patch": {"props": []}},
            headers=auth_headers(credentials["csrf_token"]),
            cookies=cookies,
        )
        self.assertEqual(forbidden.status_code, 400, forbidden.text)
        missing_room = self.client.get("/api/rooms/nope/layout", cookies=cookies)
        self.assertEqual(missing_room.status_code, 404)

    def test_save_broadcasts_layout_updated_and_snapshot_flags(self) -> None:
        owner = self.create_ready_account("hope")
        self.grant_ownership(owner)
        viewer = self.create_ready_account("ivan")
        cookies = auth_cookies(owner["session_token"], owner["csrf_token"])
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(viewer["session_token"], viewer["csrf_token"])
        ) as viewer_socket:
            viewer_socket.receive_json()
            with self.client.websocket_connect(
                "/ws", headers=websocket_headers(owner["session_token"], owner["csrf_token"])
            ) as owner_socket:
                snapshot = owner_socket.receive_json()["room"]
                viewer_socket.receive_json()
                self.assertTrue(snapshot["can_edit_room"])
                self.assertEqual(snapshot["layout_revision"], 0)
                saved = self.client.post(
                    "/api/rooms/hub/layout",
                    json={"base_revision": 0, "patch": {"props": []}},
                    headers=auth_headers(owner["csrf_token"]),
                    cookies=cookies,
                )
                self.assertEqual(saved.status_code, 200, saved.text)
                event = self.drain_until(viewer_socket, "room.layout.updated")
                self.assertEqual(event["revision"], 1)
                self.assertNotIn("welcome-plant", {prop["id"] for prop in event["props"]})


if __name__ == "__main__":
    unittest.main()
