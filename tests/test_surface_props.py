from __future__ import annotations

import asyncio
import base64
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from PIL import Image

from server.commands.context import build_command_context
from server.commands.core import dispatch_command
from server.commands.parser import parse_command
from server.connections import LiveConnection, SyntheticConnection
from server.content.surface_props import (
    DEFAULT_SIGN_STYLE,
    DEFAULT_WHITEBOARD_FRAME,
    SIGN_STYLE_IDS,
    normalize_legacy_whiteboard,
    rasterize_legacy_whiteboard,
    validate_sign_style,
    validate_sign_text,
    validate_whiteboard,
    validate_whiteboard_frame,
    whiteboard_options,
)
from server.services.prop_surfaces import PropSurfaceService
from server.services.whiteboard_images import WhiteboardImageStore
from tests.common import (
    IntegrationTestCase,
    ServiceTestCase,
    auth_cookies,
    auth_headers,
)


class SurfaceContentTests(unittest.TestCase):
    def board_data_url(self, color: str = "#ffffff") -> str:
        image = Image.new("RGB", (1024, 640), color)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

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

    def test_whiteboard_validates_image_references_and_frames(self) -> None:
        digest = "0" * 64
        surface = validate_whiteboard({
            "image_url": f"/assets/whiteboards/{digest}.png",
            "image_hash": digest,
            "frame": {
                "outer": "float",
                "inner": "double",
                "matte": "linen",
                "main": "#7A5230",
                "accent": "#C9A45C",
            },
        })
        self.assertEqual(surface["image_hash"], digest)
        self.assertEqual(surface["frame"]["main"], "#7a5230")
        blank = validate_whiteboard({})
        self.assertEqual(blank["image_url"], "")
        self.assertEqual(blank["image_hash"], "")
        self.assertEqual(blank["frame"], DEFAULT_WHITEBOARD_FRAME)
        with self.assertRaises(ValueError):
            validate_whiteboard({
                "image_url": f"/assets/whiteboards/{digest}.png",
                "image_hash": "1" * 64,
                "frame": DEFAULT_WHITEBOARD_FRAME,
            })
        with self.assertRaises(ValueError):
            validate_whiteboard({
                "image_url": "",
                "image_hash": digest,
                "frame": DEFAULT_WHITEBOARD_FRAME,
            })
        with self.assertRaises(ValueError):
            validate_whiteboard({"strokes": [], "texts": []})
        with self.assertRaises(ValueError):
            validate_whiteboard({"image_url": "", "image_hash": "", "frame": {}, "extra": True})

    def test_whiteboard_frame_styles_and_options(self) -> None:
        frame = validate_whiteboard_frame(None)
        self.assertEqual(frame, DEFAULT_WHITEBOARD_FRAME)
        options = whiteboard_options()
        self.assertEqual(len(options["frame_styles"]["outer"]), 5)
        self.assertEqual(len(options["frame_styles"]["inner"]), 5)
        self.assertEqual(len(options["frame_styles"]["matte"]), 5)
        self.assertEqual(options["default_frame"], DEFAULT_WHITEBOARD_FRAME)
        with self.assertRaises(ValueError):
            validate_whiteboard_frame({"outer": "marble"})
        with self.assertRaises(ValueError):
            validate_whiteboard_frame({"main": "red"})

    def test_legacy_whiteboard_normalizes_and_rasterizes(self) -> None:
        legacy = normalize_legacy_whiteboard({
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
        self.assertEqual(legacy["strokes"][0]["color"], "#d64545")
        image = rasterize_legacy_whiteboard(legacy)
        self.assertTrue(image.startswith("data:image/png;base64,"))
        raw = base64.b64decode(image.split(",", 1)[1])
        with Image.open(io.BytesIO(raw)) as probe:
            self.assertEqual(probe.size, (1024, 640))
        with self.assertRaises(ValueError):
            normalize_legacy_whiteboard({"strokes": [{"color": "red", "width": 4, "points": [[1, 2]]}]})


class PropSurfaceServiceTests(ServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.image_directory = TemporaryDirectory()
        self.addCleanup(self.image_directory.cleanup)
        self.images = WhiteboardImageStore(Path(self.image_directory.name))
        self.surfaces = PropSurfaceService(
            self.hub, self.images, allow_legacy_whiteboards=True
        )
        self.account = self.create_account("surface-owner")

    def board_data_url(self, color: str = "#ffffff") -> str:
        image = Image.new("RGB", (1024, 640), color)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

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
        self.assertEqual(empty.content["image_url"], "")
        self.assertEqual(empty.content["frame"], DEFAULT_WHITEBOARD_FRAME)
        saved = self.surfaces.save_whiteboard(
            "room:test",
            "custom:board",
            self.account.id,
            {"image": self.board_data_url("#d64545"), "frame": None},
        )
        self.assertEqual(saved.revision, 1)
        self.assertTrue(saved.content["image_url"].startswith("/assets/whiteboards/"))
        self.assertTrue(self.images.exists(saved.content["image_hash"]))
        reread = self.surfaces.get("room:test", "custom:board", "whiteboard")
        self.assertEqual(reread.content, saved.content)
        self.surfaces.prune_room("room:test", {"custom:board"})
        self.assertEqual(self.surfaces.get("room:test", "custom:board", "whiteboard").revision, 1)
        self.surfaces.prune_room("room:test", set())
        self.assertEqual(self.surfaces.get("room:test", "custom:board", "whiteboard").revision, 0)

    def test_legacy_whiteboard_upload_requires_svg_boards(self) -> None:
        legacy = {"strokes": [], "texts": []}
        converted = self.surfaces.save_whiteboard("room:test", "custom:legacy", self.account.id, legacy)
        self.assertTrue(converted.content["image_url"].startswith("/assets/whiteboards/"))
        strict = PropSurfaceService(self.hub, self.images, allow_legacy_whiteboards=False)
        with self.assertRaisesRegex(ValueError, "svg-boards"):
            strict.save_whiteboard("room:test", "custom:strict", self.account.id, legacy)

    def test_locked_whiteboards_reject_content_edits(self) -> None:
        installed = self.surfaces.install_whiteboard(
            "room:test",
            "custom:locked-board",
            self.account.id,
            {"image": self.board_data_url("#2f6fdb"), "frame": None},
            locked=True,
        )
        self.assertTrue(installed.locked)
        self.assertEqual(installed.locked_by, self.account.id)
        self.assertTrue(self.surfaces.is_locked("room:test", "custom:locked-board"))
        with self.assertRaisesRegex(ValueError, "locked"):
            self.surfaces.save_whiteboard(
                "room:test",
                "custom:locked-board",
                self.account.id,
                {"image": self.board_data_url("#ffffff"), "frame": None},
            )

    def test_activity_surface_requires_a_bound_whiteboard(self) -> None:
        class Activity:
            kind = "whiteboard"
            room_id = "room:test"
            config = {"prop_instance_id": "custom:board"}

        saved = self.surfaces.save_activity_surface(
            Activity(), self.account.id, {"image": self.board_data_url(), "frame": None}
        )
        self.assertIsNotNone(saved)
        self.assertEqual(saved.revision, 1)

        class SignActivity(Activity):
            kind = "sign"

        self.assertIsNone(
            self.surfaces.save_activity_surface(SignActivity(), self.account.id, {"image": self.board_data_url(), "frame": None})
        )


class SurfaceRuntimeTests(IntegrationTestCase):
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
        self.assertEqual(board["surface"]["content"]["image_url"], "")
        self.assertEqual(board["surface"]["content"]["frame"], DEFAULT_WHITEBOARD_FRAME)
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
