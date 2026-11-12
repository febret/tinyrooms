"""Shared peep sticker collection: encounters, snapshots, and milestone rewards."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import asyncio
import sqlite3
import unittest

from server.commands.context import build_command_context
from server.commands.core import dispatch_command
from server.commands.parser import parse_command
from server.connections import SyntheticConnection
from server.content.worlds import PeepDefinition
from server.profiles import ProfileRepository
from server.serialization import serialize_account
from server.services.peep_collection import (
    MILESTONE_BOPS,
    MILESTONE_KUDOS,
    PeepCollectionService,
    peep_key,
)
from server.services.progression import ProgressionService
from server.services.stats import StatsService
from server.state.encountered_peeps_schema import ENCOUNTERED_PEEPS_COLUMNS
from server.state.migrations import PROFILE_SCHEMA_VERSION, DatabaseHub, ensure_profile_database

from tests.common import WORLD_ID, IntegrationTestCase, ServiceTestCase


class FakeVibes:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], int] = {}

    def get_global(self, source: str, target: str) -> int:
        return self.values.get((source, target), 0)


def _world(world_id: str, image_path: Path, count: int, tags: tuple[str, ...] = ()) -> SimpleNamespace:
    peeps = {
        f"peep{index}": PeepDefinition(
            id=f"peep{index}",
            label=f"Peep {index}",
            description=f"Peep number {index}.",
            room_id="hub",
            image_name=image_path.name,
            image_path=image_path,
            script_name=None,
            actions=(),
            dialog=None,
            activity=None,
            tags=tags,
        )
        for index in range(count)
    }
    return SimpleNamespace(
        id=world_id,
        label=world_id.title(),
        peeps=peeps,
        rooms={"hub": SimpleNamespace(label="The Hub")},
    )


class PeepCollectionTests(ServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        root = Path(self.temporary_directory.name)
        self.image = root / "peep.png"
        self.image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        self.stickers_root = root / "stickers"
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.progression = ProgressionService(self.hub, self.profiles, self.stats, self.catalog, self.content, WORLD_ID)
        self.vibes = FakeVibes()
        self.account = self.create_account("collector")

    def service(self, world_id: str = WORLD_ID, count: int = 25, tags: tuple[str, ...] = ()) -> PeepCollectionService:
        return PeepCollectionService(
            hub=self.hub,
            profiles=self.profiles,
            progression=self.progression,
            world=_world(world_id, self.image, count, tags),
            stickers_root=self.stickers_root,
            vibes=self.vibes,
        )

    def test_first_encounter_snapshots_peep_and_copies_picture(self) -> None:
        service = self.service()
        result = service.record_encounter(self.account.id, "peep0", room_id="hub")
        self.assertTrue(result.new)
        peep = result.peep
        self.assertEqual(peep.peep_key, peep_key(WORLD_ID, "peep0"))
        self.assertEqual(peep.label, "Peep 0")
        self.assertEqual(peep.description, "Peep number 0.")
        self.assertEqual(peep.traits["room_label"], "The Hub")
        self.assertTrue((service.images_root / peep.image_name).is_file())
        self.assertTrue(peep.image_url.startswith("/assets/peep-stickers/"))
        self.assertTrue(any("Peep 0" in str(event.get("text")) for event in result.events))

    def test_repeat_encounter_is_not_new(self) -> None:
        service = self.service()
        service.record_encounter(self.account.id, "peep0", room_id="hub")
        again = service.record_encounter(self.account.id, "peep0", room_id="hub")
        self.assertFalse(again.new)
        self.assertEqual(again.events, [])
        self.assertEqual(again.milestones, [])
        self.assertEqual(service.collection_payload(self.account.id)["count"], 1)

    def test_unknown_peep_is_ignored(self) -> None:
        result = self.service().record_encounter(self.account.id, "nobody")
        self.assertFalse(result.new)
        self.assertIsNone(result.peep)

    def test_same_peep_id_in_two_worlds_counts_twice(self) -> None:
        self.service("alpha").record_encounter(self.account.id, "peep0")
        self.service("beta").record_encounter(self.account.id, "peep0")
        payload = self.service().collection_payload(self.account.id)
        self.assertEqual(payload["count"], 2)
        self.assertEqual({peep["world_id"] for peep in payload["peeps"]}, {"alpha", "beta"})

    def test_every_ten_new_peeps_pays_once(self) -> None:
        service = self.service()
        start = self.reload_account(self.account)
        for index in range(9):
            self.assertEqual(service.record_encounter(self.account.id, f"peep{index}").milestones, [])
        self.assertEqual(self.reload_account(self.account).bops, start.bops)
        tenth = service.record_encounter(self.account.id, "peep9")
        self.assertEqual(tenth.milestones, [1])
        account = self.reload_account(self.account)
        self.assertEqual(account.bops, start.bops + MILESTONE_BOPS)
        self.assertEqual(account.kudos, start.kudos + MILESTONE_KUDOS)
        service.record_encounter(self.account.id, "peep9")
        for index in range(10, 20):
            service.record_encounter(self.account.id, f"peep{index}")
        account = self.reload_account(self.account)
        self.assertEqual(account.bops, start.bops + 2 * MILESTONE_BOPS)
        self.assertEqual(account.kudos, start.kudos + 2 * MILESTONE_KUDOS)
        self.assertEqual(service.collection_payload(self.account.id)["next_milestone_at"], 30)

    def test_milestones_survive_a_fresh_service(self) -> None:
        for index in range(10):
            self.service().record_encounter(self.account.id, f"peep{index}")
        before = self.reload_account(self.account)
        self.assertEqual(self.service().record_encounter(self.account.id, "peep10").milestones, [])
        self.assertEqual(self.reload_account(self.account).bops, before.bops)

    def test_collections_are_per_account(self) -> None:
        other = self.create_account("stranger")
        service = self.service()
        service.record_encounter(self.account.id, "peep0")
        self.assertEqual(service.collection_payload(other.id)["count"], 0)


class PeepEncounterCommandTests(IntegrationTestCase):
    """Look and talk commands record encounters through the live runtime."""

    def _dispatch(self, account, command: str, room_id: str = "foyer"):
        runtime = self.runtime()
        context = build_command_context(
            runtime,
            account=account,
            connection=SyntheticConnection(account_id=account.id, username=account.username_display, room_id=room_id),
            serialize_user=lambda target: serialize_account(runtime, target),
        )
        return asyncio.run(dispatch_command(context, parse_command(command)))

    def test_talk_records_once_and_refreshes_user_payload(self) -> None:
        runtime = self.runtime()
        player = runtime.profiles.create_account("sticker-fan", "password123!", runtime.world.id, "foyer")
        first = self._dispatch(player, ".talk caretaker")
        collection = first.payload["user"]["peep_collection"]
        self.assertEqual([peep["peep_id"] for peep in collection["peeps"]], ["caretaker"])
        self.assertTrue(any(event.get("type") == "toast" for event in first.private_events))
        second = self._dispatch(player, ".look @peep:caretaker")
        self.assertNotIn("user", second.payload)
        self.assertEqual(runtime.peep_collection.collection_payload(player.id)["count"], 1)


class EncounteredPeepsMigrationTests(unittest.TestCase):
    def test_v15_profile_database_upgrades_to_add_collection(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.sqlite3"
            ensure_profile_database(path)
            connection = sqlite3.connect(path)
            try:
                connection.execute("DROP TABLE encountered_peeps")
                connection.execute("PRAGMA user_version = 15")
                connection.commit()
            finally:
                connection.close()
            ensure_profile_database(path)
            connection = sqlite3.connect(path)
            try:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                columns = [row[1] for row in connection.execute("PRAGMA table_info(encountered_peeps)")]
            finally:
                connection.close()
        self.assertEqual(version, PROFILE_SCHEMA_VERSION)
        self.assertEqual(tuple(columns), ENCOUNTERED_PEEPS_COLUMNS)


if __name__ == "__main__":
    unittest.main()
