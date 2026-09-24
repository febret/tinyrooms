"""Milestone 3 Phase F: World Editor and Card Database coverage."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import os
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from server.config import load_config
from server.content.cards import load_card_catalog
from server.mods import load_mods
from server.services.audit import AuditService
from server.services.card_database import CardDatabaseService
from server.services.world_editor import (
    PUBLISHED_REVISION_KEY,
    DraftValidationError,
    PublishConfirmationRequired,
    PublishValidationError,
    WorldEditorService,
)
from server.services.world_reconcile import reconcile as reconcile_world
from server.state.world_state import WorldStateRepository
from tests.common import REPO_ROOT, WORLD_ID, ServiceTestCase, load_test_world
from tests.test_milestone1 import (
    RuntimeTestCase,
    auth_cookies,
    auth_headers,
)


def _link_or_copy(source: str, destination: str) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _copy_world(destination: Path) -> Path:
    if not destination.is_dir():
        shutil.copytree(REPO_ROOT / "worlds" / "tutorial", destination, copy_function=_link_or_copy)
    return destination


WORLD_COPY_NAME = "tutorial"


def remove_room(draft: dict, room_id: str) -> None:
    """Delete a room and every reference to it, mirroring the editor UI."""

    del draft["rooms"][room_id]
    for room in draft["rooms"].values():
        for exit_id, exit_definition in list((room.get("exits") or {}).items()):
            if exit_definition.get("target") == room_id:
                del room["exits"][exit_id]
    if draft.get("world", {}).get("entry_room") == room_id:
        draft["world"]["entry_room"] = next(iter(draft["rooms"]))


class WorldEditorServiceTestCase(ServiceTestCase):
    """Provide an isolated world copy and WorldEditorService."""

    def setUp(self) -> None:
        super().setUp()
        self.world_root = _copy_world(Path(self.temporary_directory.name) / WORLD_COPY_NAME)
        self.config = replace(
            load_config(
                env={
                    "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "open-sesame",
                    "TRSERVER_USERS_PATH": str(Path(self.temporary_directory.name) / "users"),
                    "TRSERVER_WORLD_PATH": str(self.world_root),
                    "TRSERVER_WORLDSTATE_PATH": str(Path(self.temporary_directory.name) / "worldstate.sqlite3"),
                    "TRSERVER_FEATURES": "world-editor,card-database",
                    "TRSERVER_MODS": "*",
                    "TRSERVER_TIMEZONE": "UTC",
                },
                repo_root=REPO_ROOT,
            ),
            local_path=Path(self.temporary_directory.name),
            drafts_path=Path(self.temporary_directory.name) / "drafts",
            revisions_path=Path(self.temporary_directory.name) / "revisions",
        )
        self.world_state = WorldStateRepository(self.hub)
        self.world = load_test_world(self.world_root)
        self.world_state.initialize_world(self.world)
        self.audit = AuditService(self.hub, self.world.id)
        self.loaded_mods = load_mods(self.config)
        self.service = WorldEditorService(
            self.config,
            self.hub,
            self.world_state,
            self.audit,
            self.loaded_mods,
        )

    def draft(self) -> dict:
        return self.service.load_draft()

    def publish(self, draft: dict, confirm: bool = False):
        return self.service.publish(
            draft,
            actor_account_id="test-actor",
            confirm=confirm,
        )


class DraftLifecycleTests(WorldEditorServiceTestCase):
    """Draft isolation and validation behavior."""

    def test_load_draft_mirrors_published_files(self) -> None:
        draft = self.draft()
        self.assertEqual(draft["world"]["id"], WORLD_ID)
        self.assertIn("hub", draft["rooms"])
        self.assertEqual(draft["draft_revision"], 0)

    def test_save_draft_never_mutates_the_world(self) -> None:
        rooms_file = self.world_root / "rooms" / "rooms.yaml"
        before = rooms_file.read_bytes()
        draft = self.draft()
        draft["rooms"]["hub"]["label"] = "Renamed Hub"
        info = self.service.save_draft(draft)
        self.assertEqual(info.draft_revision, 1)
        self.assertEqual(rooms_file.read_bytes(), before)
        self.assertTrue(self.service.draft_path().is_file())
        self.assertEqual(load_test_world(self.world_root).rooms["hub"].label, "The Hub")

    def test_discard_draft_rebuilds_from_published(self) -> None:
        draft = self.draft()
        draft["rooms"]["hub"]["label"] = "Renamed Hub"
        self.service.save_draft(draft)
        self.assertTrue(self.service.discard_draft())
        rebuilt = self.draft()
        self.assertEqual(rebuilt["rooms"]["hub"]["label"], "The Hub")
        self.assertEqual(rebuilt["draft_revision"], 0)

    def test_invalid_structure_is_rejected_on_save(self) -> None:
        draft = self.draft()
        draft["rooms"]["hub"]["exits"]["exit0"]["target"] = "missing-room"
        with self.assertRaises(DraftValidationError):
            self.service.save_draft(draft)


class PublishTests(WorldEditorServiceTestCase):
    """Publish validation, confirmations, backups, and atomicity."""

    def test_invalid_publish_leaves_files_untouched(self) -> None:
        rooms_file = self.world_root / "rooms" / "rooms.yaml"
        before = rooms_file.read_bytes()
        draft = self.draft()
        draft["rooms"]["hub"]["board_image"] = "missing-board.png"
        with self.assertRaises(PublishValidationError):
            self.publish(draft)
        self.assertEqual(rooms_file.read_bytes(), before)
        self.assertFalse((self.config.revisions_path / self.service.world_key).exists())

    def test_publish_records_revision_and_backup(self) -> None:
        draft = self.draft()
        draft["rooms"]["hub"]["label"] = "Hub v2"
        result = self.publish(draft)
        self.assertEqual(result.revision, 1)
        backup = self.config.revisions_path / self.service.world_key / "1"
        self.assertTrue((backup / "manifest.json").is_file())
        self.assertTrue((backup / "rooms" / "rooms.yaml").is_file())
        self.assertEqual(self.world_state.read_world_meta(PUBLISHED_REVISION_KEY), "1")
        self.assertEqual(load_test_world(self.world_root).rooms["hub"].label, "Hub v2")

        draft = self.draft()
        draft["rooms"]["hub"]["label"] = "Hub v3"
        second = self.publish(draft)
        self.assertEqual(second.revision, 2)

    def test_publish_restores_files_on_write_failure(self) -> None:
        rooms_file = self.world_root / "rooms" / "rooms.yaml"
        before = rooms_file.read_bytes()
        draft = self.draft()
        draft["rooms"]["hub"]["label"] = "Hub v2"
        calls = {"count": 0}
        real_replace = os.replace

        def flaky_replace(source, target):
            calls["count"] += 1
            if calls["count"] >= 2:
                raise OSError("simulated write failure")
            return real_replace(source, target)

        with mock.patch("server.services.world_editor.os.replace", side_effect=flaky_replace):
            with self.assertRaises(OSError):
                self.publish(draft)
        self.assertEqual(rooms_file.read_bytes(), before)

    def test_deleted_room_requires_confirmation(self) -> None:
        draft = self.draft()
        remove_room(draft, "garden")
        with self.assertRaises(PublishConfirmationRequired) as context:
            self.publish(draft)
        self.assertIn("garden", context.exception.rooms)
        self.assertTrue(any(change.room_id == "garden" for change in context.exception.changes))

    def test_confirmed_deletion_removes_orphaned_room_cards(self) -> None:
        account = self.create_account("mover")
        with self.hub.transaction() as connection:
            self.profiles.set_remembered_room(connection, account.id, WORLD_ID, "garden")
            self.world_state.add_room_card(
                connection,
                room_id="garden",
                card_def_id="tasty-toast",
                quantity=1,
                pos=(50.0, 50.0, 0.0),
                placed_by_account_id=account.id,
            )
        draft = self.draft()
        remove_room(draft, "garden")
        with self.assertRaises(PublishConfirmationRequired):
            self.publish(draft)

        result = self.publish(draft, confirm=True)
        self.assertGreaterEqual(result.revision, 1)
        self.assertGreaterEqual(result.reconciled.removed_card_stacks, 1)
        self.assertIn("garden", result.reconciled.deleted_rooms)

        self.assertEqual(self.world_state.list_room_cards("garden"), [])
        inventory = self.profiles.list_inventory(account.id, WORLD_ID)
        self.assertFalse(any(stack.card_def_id == "tasty-toast" for stack in inventory))
        # Occupancy is repaired lazily by the room service, not during publish.
        profile = self.profiles.user_profile_for(account.id, WORLD_ID, "garden")
        self.assertEqual(profile.remembered_room, "garden")


class ReconciliationTests(WorldEditorServiceTestCase):
    """Live state survives a publish."""

    def test_progress_and_unrelated_cards_survive(self) -> None:
        account = self.create_account("keeper")
        self.grant_card(account, "seal-plushie", 2)
        self.set_progress(account, level=3, kudos=7)
        with self.hub.transaction() as connection:
            self.world_state.add_room_card(
                connection,
                room_id="playroom",
                card_def_id="tomato-sauce",
                quantity=1,
                pos=(20.0, 20.0, 0.0),
                placed_by_account_id=account.id,
            )
        draft = self.draft()
        draft["rooms"]["hub"]["label"] = "Hub Renamed"
        self.publish(draft)

        refreshed = self.profiles.get_account_by_id(account.id)
        self.assertEqual(refreshed.level, 3)
        self.assertEqual(refreshed.kudos, 7)
        inventory = self.profiles.list_inventory(account.id, WORLD_ID)
        self.assertTrue(any(stack.card_def_id == "seal-plushie" for stack in inventory))
        remaining = self.world_state.list_room_cards("playroom")
        self.assertTrue(any(stack.card_def_id == "tomato-sauce" for stack in remaining))

    def test_removed_prop_requires_confirmation(self) -> None:
        draft = self.draft()
        del draft["rooms"]["hub"]["props"]["welcome-plant"]
        with self.assertRaises(PublishConfirmationRequired) as context:
            self.publish(draft)
        self.assertTrue(
            any(change.kind == "removed_prop" and change.room_id == "hub" for change in context.exception.changes)
        )
        self.publish(draft, confirm=True)


class CardDatabaseTests(WorldEditorServiceTestCase):
    """Card Database payload is complete and read-only."""

    def test_payload_includes_packs_recipes_and_errors(self) -> None:
        catalog = load_card_catalog(self.config.cardsets_path, self.world_root)
        service = CardDatabaseService(catalog, self.world.recipes, self.world.id, self.world_root)
        payload = service.payload()
        self.assertTrue(payload["cards"])
        self.assertTrue(payload["packs"])
        self.assertTrue(any(recipe["id"] == "bagged-poop" for recipe in payload["recipes"]))
        self.assertIsInstance(payload["errors"], list)
        card = payload["cards"][0]
        for forbidden in ("inventory", "equipped", "grant", "quantity"):
            self.assertNotIn(forbidden, card)
        for key in ("image_url", "scope", "type", "rarity", "packs", "recipes"):
            self.assertIn(key, card)


class WorldEditorHttpTests(RuntimeTestCase):
    """HTTP route gating and round trips."""

    features = "dev_sample_activity,world-editor,card-database"

    def setUp(self) -> None:
        self._world_directory = TemporaryDirectory()
        self.addCleanup(self._world_directory.cleanup)
        self.world_path = _copy_world(Path(self._world_directory.name) / WORLD_COPY_NAME)
        super().setUp()

    def _runtime(self):
        return self.app.state.runtime

    def _builder_account(self, username: str) -> dict[str, str]:
        credentials = self.create_ready_account(username)
        runtime = self._runtime()
        account = runtime.profiles.get_account_by_username(username)
        runtime.powers.grant(account.id, account.id, "builder")
        return credentials

    def test_editor_routes_require_power(self) -> None:
        credentials = self.create_ready_account("plain")
        cookies = auth_cookies(credentials["session_token"], credentials["csrf_token"])
        response = self.client.get("/api/world-editor/draft", cookies=cookies)
        self.assertEqual(response.status_code, 403)
        page = self.client.get("/world-editor/", cookies=cookies)
        self.assertEqual(page.status_code, 403)

    def test_draft_round_trip_and_publish(self) -> None:
        credentials = self._builder_account("builder1")
        cookies = auth_cookies(credentials["session_token"], credentials["csrf_token"])
        headers = auth_headers(credentials["csrf_token"])

        draft_response = self.client.get("/api/world-editor/draft", cookies=cookies)
        self.assertEqual(draft_response.status_code, 200, draft_response.text)
        draft = draft_response.json()["draft"]
        self.assertEqual(draft_response.json()["world_key"], WORLD_ID)
        self.assertTrue(draft_response.json()["catalog"]["props"])

        draft["rooms"]["hub"]["label"] = "HTTP Hub"
        save = self.client.put(
            "/api/world-editor/draft",
            json={"draft": draft},
            cookies=cookies,
            headers=headers,
        )
        self.assertEqual(save.status_code, 200, save.text)

        validate = self.client.post(
            "/api/world-editor/validate",
            json={"draft": draft},
            cookies=cookies,
            headers=headers,
        )
        self.assertEqual(validate.status_code, 200, validate.text)
        self.assertTrue(validate.json()["report"]["valid"])

        publish = self.client.post(
            "/api/world-editor/publish",
            json={"draft": draft},
            cookies=cookies,
            headers=headers,
        )
        self.assertEqual(publish.status_code, 200, publish.text)
        self.assertEqual(publish.json()["result"]["revision"], 1)
        self.assertEqual(self._runtime().world.rooms["hub"].label, "HTTP Hub")

    def test_publish_requires_confirmation_for_deletion(self) -> None:
        credentials = self._builder_account("builder2")
        cookies = auth_cookies(credentials["session_token"], credentials["csrf_token"])
        headers = auth_headers(credentials["csrf_token"])
        draft = self.client.get("/api/world-editor/draft", cookies=cookies).json()["draft"]
        remove_room(draft, "garden")
        publish = self.client.post(
            "/api/world-editor/publish",
            json={"draft": draft},
            cookies=cookies,
            headers=headers,
        )
        self.assertEqual(publish.status_code, 409, publish.text)
        self.assertEqual(publish.json()["code"], "confirmation_required")
        self.assertIn("garden", publish.json()["rooms"])

        confirmed = self.client.post(
            "/api/world-editor/publish",
            json={"draft": draft, "confirm": True},
            cookies=cookies,
            headers=headers,
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertNotIn("garden", self._runtime().world.rooms)

    def test_card_database_is_read_only(self) -> None:
        credentials = self._builder_account("builder3")
        cookies = auth_cookies(credentials["session_token"], credentials["csrf_token"])
        response = self.client.get("/api/card-database", cookies=cookies)
        self.assertEqual(response.status_code, 200, response.text)
        database = response.json()["database"]
        self.assertTrue(database["cards"])
        self.assertTrue(database["packs"])
        self.assertIsInstance(database["errors"], list)

    def test_card_database_requires_power(self) -> None:
        credentials = self.create_ready_account("plain2")
        cookies = auth_cookies(credentials["session_token"], credentials["csrf_token"])
        response = self.client.get("/api/card-database", cookies=cookies)
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
