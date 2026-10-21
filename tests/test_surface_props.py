from __future__ import annotations

import asyncio
import unittest
from unittest.mock import Mock

from server.commands.context import build_command_context
from server.commands.core import dispatch_command
from server.commands.parser import parse_command
from server.connections import LiveConnection, SyntheticConnection
from server.content.surface_props import (
    DEFAULT_SIGN_STYLE,
    SIGN_STYLE_IDS,
    validate_sign_style,
    validate_sign_text,
    validate_whiteboard,
)
from server.services.prop_surfaces import PropSurfaceService
from tests.common import (
    Milestone2IntegrationTestCase,
    ServiceTestCase,
    auth_cookies,
    auth_headers,
)


class SurfaceContentTests(unittest.TestCase):
    def test_sign_text_normalizes_newlines_and_rejects_overflow(self) -> None:
        self.assertEqual(validate_sign_text({"text": "Hello\r\nworld"}), {"text": "Hello\nworld"})
        with self.assertRaises(ValueError):
            validate_sign_text({"text": ""})
        with self.assertRaises(ValueError):
            validate_sign_text({"text": "x" * 241})
        with self.assertRaises(ValueError):
            validate_sign_text({"text": "\n".join(["line"] * 9)})

    def test_sign_style_defaults_and_validates(self) -> None:
        self.assertEqual(validate_sign_style(None), DEFAULT_SIGN_STYLE)
        for style_id in SIGN_STYLE_IDS:
            self.assertEqual(validate_sign_style(style_id), style_id)
        with self.assertRaises(ValueError):
            validate_sign_style("marble")

    def test_whiteboard_validates_and_normalizes(self) -> None:
        surface = validate_whiteboard({
            "strokes": [{
                "color": "#D64545",
                "width": 6,
                "points": [[10, 20], [30, 40]],
            }],
            "texts": [{
                "text": "Note",
                "x": 12,
                "y": 34,
                "size": 48,
                "color": "#1F2933",
            }],
        })
        self.assertEqual(surface["strokes"][0]["color"], "#d64545")
        self.assertEqual(surface["strokes"][0]["points"], [[10, 20], [30, 40]])
        self.assertEqual(surface["texts"][0]["text"], "Note")
        with self.assertRaises(ValueError):
            validate_whiteboard({"strokes": [{"color": "red", "width": 4, "points": [[1, 2]]}]})
        with self.assertRaises(ValueError):
            validate_whiteboard({"strokes": [], "texts": [], "extra": True})
        with self.assertRaises(ValueError):
            validate_whiteboard({"strokes": [{"color": "#000000", "width": 4, "points": [[2000, 2]]}]})


class PropSurfaceServiceTests(ServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.surfaces = PropSurfaceService(self.hub)
        self.account = self.create_account("surface-owner")

    def test_sign_saves_are_last_write_wins_with_increasing_revisions(self) -> None:
        first = self.surfaces.save_sign("room:test", "custom:one", self.account.id, {"text": "First"})
        second = self.surfaces.save_sign("room:test", "custom:one", self.account.id, {"text": "Second"})
        self.assertEqual(first.revision, 1)
        self.assertEqual(second.revision, 2)
        stored = self.surfaces.get("room:test", "custom:one", "sign")
        self.assertEqual(stored.content, {"text": "Second"})
        self.assertEqual(stored.revision, 2)

    def test_whiteboard_defaults_and_pruning(self) -> None:
        empty = self.surfaces.get("room:test", "custom:board", "whiteboard")
        self.assertEqual(empty.revision, 0)
        self.assertEqual(empty.content, {"strokes": [], "texts": []})
        saved = self.surfaces.save_whiteboard(
            "room:test",
            "custom:board",
            self.account.id,
            {"strokes": [], "texts": [{"text": "Hi", "x": 1, "y": 2, "size": 24, "color": "#1f2933"}]},
        )
        self.assertEqual(saved.revision, 1)
        self.surfaces.prune_room("room:test", {"custom:board"})
        self.assertEqual(self.surfaces.get("room:test", "custom:board", "whiteboard").revision, 1)
        self.surfaces.prune_room("room:test", set())
        self.assertEqual(self.surfaces.get("room:test", "custom:board", "whiteboard").revision, 0)

    def test_activity_surface_requires_a_bound_whiteboard(self) -> None:
        class Activity:
            kind = "whiteboard"
            room_id = "room:test"
            config = {"prop_instance_id": "custom:board"}

        saved = self.surfaces.save_activity_surface(
            Activity(), self.account.id, {"strokes": [], "texts": []}
        )
        self.assertIsNotNone(saved)
        self.assertEqual(saved.revision, 1)

        class SignActivity(Activity):
            kind = "sign"

        self.assertIsNone(
            self.surfaces.save_activity_surface(SignActivity(), self.account.id, {"strokes": [], "texts": []})
        )


class SurfaceRuntimeTests(Milestone2IntegrationTestCase):
    def setUp(self) -> None:
        super().setUp()
        runtime = self.runtime()
        self.account = runtime.profiles.create_account(
            "surface-player",
            "password123!",
            runtime.world.id,
            runtime.world.entry_room_id,
        )
        self.room_id = runtime.world.entry_room_id
        self._place_prop("custom:sign-1", "builtin:sign")
        self._place_prop("custom:board-1", "builtin:whiteboard")

    def _place_prop(self, instance_id: str, prop_id: str) -> None:
        runtime = self.runtime()
        layout = runtime.world_state.read_room_layout(self.room_id)
        props = list(layout["props"] or [])
        props.append({
            "id": instance_id,
            "prop_id": prop_id,
            "position": [50, 50, 0],
            "rotation": [0, 0, 0],
            "scale": 1,
            "locked": False,
        })
        with runtime.hub.transaction() as connection:
            runtime.world_state.write_room_layout(
                connection,
                self.room_id,
                props,
                {},
                expected_revision=int(layout["revision"]),
            )

    def _dispatch(self, command: str):
        runtime = self.runtime()
        context = build_command_context(
            runtime,
            account=self.account,
            connection=SyntheticConnection(
                account_id=self.account.id,
                username=self.account.username_display,
                room_id=self.room_id,
            ),
            serialize_user=lambda target: {},
        )
        return asyncio.run(dispatch_command(context, parse_command(command)))

    def test_sign_command_returns_editor_payload(self) -> None:
        outcome = self._dispatch(".sign custom:sign-1")
        editor = outcome.payload["sign_editor"]
        self.assertEqual(editor["instance_id"], "custom:sign-1")
        self.assertEqual(editor["surface"]["kind"], "sign")
        self.assertEqual(editor["surface"]["content"]["text"], "New sign")
        self.assertIn("styles", editor["options"])

    def test_play_whiteboard_binds_instance_config(self) -> None:
        outcome = self._dispatch(".play custom:board-1")
        activity = outcome.payload["activity"]
        self.assertEqual(activity["kind"], "whiteboard")
        self.assertEqual(activity["config"]["prop_instance_id"], "custom:board-1")
        self.assertEqual(activity["config"]["surface"]["kind"], "whiteboard")

    def test_sign_and_whiteboard_serialize_default_surfaces_and_actions(self) -> None:
        runtime = self.runtime()
        snapshot = asyncio.run(runtime.rooms.build_snapshot(self.account, self.room_id))
        props = {prop["id"]: prop for prop in snapshot["props"]}
        sign = props["custom:sign-1"]
        self.assertEqual(sign["render_kind"], "sign")
        self.assertEqual(sign["sign_style"], "wood")
        self.assertEqual(sign["surface"]["content"], {"text": "New sign"})
        self.assertEqual(sign["quick_actions"][0]["command"], ".sign custom:sign-1")
        board = props["custom:board-1"]
        self.assertEqual(board["render_kind"], "whiteboard")
        self.assertEqual(board["surface"]["content"], {"strokes": [], "texts": []})
        self.assertEqual(board["quick_actions"][0]["command"], ".play custom:board-1")

    def test_room_occupant_can_save_sign_text_through_http(self) -> None:
        credentials = self.create_ready_account("sign-editor")
        account_id = self.account_id(credentials)
        runtime = self.runtime()
        connection = LiveConnection(
            websocket=Mock(),
            account_id=account_id,
            username="sign-editor",
            generation=0,
        )
        asyncio.run(runtime.connections.register(connection))
        asyncio.run(runtime.connections.set_room(account_id, self.room_id))
        response = self.client.post(
            f"/api/rooms/{self.room_id}/signs/custom:sign-1",
            json={"text": "Hello room"},
            headers=auth_headers(credentials["csrf_token"]),
            cookies=auth_cookies(credentials["session_token"], credentials["csrf_token"]),
        )
        self.assertEqual(response.status_code, 200, response.text)
        surface = response.json()["surface"]
        self.assertEqual(surface["content"], {"text": "Hello room"})
        self.assertEqual(surface["revision"], 1)
        stored = self.runtime().surfaces.get(self.room_id, "custom:sign-1", "sign")
        self.assertEqual(stored.content, {"text": "Hello room"})

    def test_non_occupant_cannot_save_sign_text_through_http(self) -> None:
        credentials = self.create_ready_account("sign-outsider")
        response = self.client.post(
            f"/api/rooms/{self.room_id}/signs/custom:sign-1",
            json={"text": "Hello room"},
            headers=auth_headers(credentials["csrf_token"]),
            cookies=auth_cookies(credentials["session_token"], credentials["csrf_token"]),
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["code"], "sign_rejected")
