"""Tests for vibe persistence, descriptors, and periodic room rules."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest

from server.behaviors.context import BehaviorContext
from server.behaviors.events import BehaviorEvent, PeepRef
from server.game.modifiers import Modifier
from server.security import utc_now
from server.services.friends import FriendsService
from server.services.stats import StatsService
from server.services.vibes import VibesService, describe_vibe
from server.state.npc_peep_states import NpcPeepStateRepository
from server.state.migrations import PROFILE_SCHEMA_VERSION, ensure_profile_database
from server.state.vibes import VIBE_MAX, VIBE_MIN
from tests.common import REPO_ROOT, WORLD_ID, RuntimeTestCase, ServiceTestCase, load_test_world


class VibesServiceTests(ServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        self.stats = StatsService(self.hub, self.profiles, self.catalog, self.content, WORLD_ID)
        self.peep_states = NpcPeepStateRepository(self.hub, self.world)
        with self.hub.transaction() as connection:
            self.peep_states.set_in_transaction(connection, "caretaker", "hub")
        self.peep_states.record("caretaker", "hub")
        self.vibes = VibesService(
            hub=self.hub,
            world=self.world,
            stats=self.stats,
            peep_states=self.peep_states,
        )

    def _rows(self, table: str) -> list[tuple[str, str, str, int]]:
        with self.hub.locked() as connection:
            rows = connection.execute(
                f"SELECT world_id, source_peep_id, target_peep_id, value FROM {table} "
                "ORDER BY world_id, source_peep_id, target_peep_id"
            ).fetchall()
        return [tuple(row) for row in rows]

    def test_player_pairs_are_global_and_npc_pairs_stay_in_world(self) -> None:
        account = self.create_account("vibe-source")
        other = self.create_account("vibe-other")
        self.world.peeps.setdefault("ghost", self.world.peeps["caretaker"])
        self.addCleanup(self.world.peeps.pop, "ghost", None)
        self.vibes.adjust(account.id, "caretaker", 7)
        self.vibes.adjust("caretaker", account.id, -3)
        self.vibes.adjust(account.id, other.id, 5)
        self.vibes.adjust("caretaker", "ghost", 9)

        self.assertEqual(self.vibes.get(account.id, "caretaker"), 7)
        self.assertEqual(self.vibes.get("caretaker", account.id), -3)
        self.assertEqual(self.vibes.get(account.id, other.id), 5)
        self.assertEqual(self.vibes.get("caretaker", "ghost"), 9)
        self.assertEqual(
            sorted(self._rows("main.vibes")),
            sorted([
                ("", account.id, other.id, 5),
                ("", account.id, "tutorial:caretaker", 7),
                ("", "tutorial:caretaker", account.id, -3),
            ]),
        )
        self.assertEqual(self._rows("world.vibes"), [("tutorial", "caretaker", "ghost", 9)])

    def test_global_id_and_local_mapping(self) -> None:
        account = self.create_account("vibe-map")
        self.assertEqual(self.vibes.global_id("caretaker"), "tutorial:caretaker")
        self.assertEqual(self.vibes.global_id(account.id), account.id)
        self.vibes.adjust(account.id, "caretaker", 4)
        with self.hub.transaction() as connection:
            result = self.vibes.adjust_global_many_in_transaction(
                connection,
                [(account.id, "tinytown:ttnpc:abc", 6), ("tinytown:ttnpc:abc", account.id, 150)],
            )
        self.assertEqual(
            result,
            {(account.id, "tinytown:ttnpc:abc"): 6, ("tinytown:ttnpc:abc", account.id): 100},
        )
        self.assertEqual(
            self.vibes.outgoing(account.id), {"caretaker": 4, "tinytown:ttnpc:abc": 6}
        )
        self.assertEqual(self.vibes.outgoing("caretaker"), {})
        self.assertEqual(self.vibes.get_global(account.id, "tutorial:caretaker"), 4)
        self.assertEqual(self.vibes.get_global("tinytown:ttnpc:abc", account.id), 100)
        self.assertEqual(self.vibes.get_global(account.id, "tinytown:nobody"), 0)
        self.assertEqual(self.vibes.get_global("", account.id), 0)
        self.assertEqual(self.vibes.get_global(account.id, account.id), 0)
        pairs = self.vibes.pairs_for(account.id, ["caretaker", "tinytown:ttnpc:abc"])
        self.assertEqual(pairs["caretaker"]["toward"]["value"], 4)
        self.assertEqual(pairs["tinytown:ttnpc:abc"]["from"]["value"], 100)
        self.assertEqual(
            self.vibes.adjust_many([(account.id, "caretaker", 1), ("caretaker", account.id, 2)]),
            {(account.id, "caretaker"): 5, ("caretaker", account.id): 2},
        )

    def test_cross_world_visibility(self) -> None:
        account = self.create_account("vibe-cross")
        other_world = SimpleNamespace(id="tinytown", peeps={"ttnpc:abc": object()})
        town = VibesService(hub=self.hub, world=other_world, stats=self.stats)
        town.adjust("ttnpc:abc", account.id, 11)
        self.assertEqual(self.vibes.get_global("tinytown:ttnpc:abc", account.id), 11)
        self.assertEqual(self.vibes.outgoing(account.id), {})
        self.vibes.adjust(account.id, "caretaker", 3)
        self.assertEqual(town.get_global(account.id, "tutorial:caretaker"), 3)
        self.assertEqual(town.outgoing(account.id), {"tutorial:caretaker": 3})
        self.assertEqual(
            town.pairs_for(account.id, ["ttnpc:abc"])["ttnpc:abc"]["from"]["value"], 11
        )

    def test_world_player_rows_move_to_profile_at_startup(self) -> None:
        account = self.create_account("vibe-move")
        with self.hub.transaction() as connection:
            connection.execute(
                "INSERT INTO world.vibes VALUES ('tutorial', 'caretaker', ?, -8, '2026-02-01T00:00:00+00:00')",
                (account.id,),
            )
            connection.execute(
                "INSERT INTO world.vibes VALUES ('tutorial', 'caretaker', 'ghost', 3, '2026-02-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO main.vibes VALUES ('', 'tutorial:caretaker', ?, 50, '2026-01-01T00:00:00+00:00')",
                (account.id,),
            )
        VibesService(hub=self.hub, world=self.world, stats=self.stats)
        VibesService(hub=self.hub, world=self.world, stats=self.stats)
        self.assertEqual(self._rows("world.vibes"), [("tutorial", "caretaker", "ghost", 3)])
        self.assertEqual(self._rows("main.vibes"), [("", "tutorial:caretaker", account.id, -8)])

    def test_scores_clamp_and_zero_rows_are_kept(self) -> None:
        account = self.create_account("vibe-clamp")
        self.assertEqual(self.vibes.adjust(account.id, "caretaker", 999), VIBE_MAX)
        self.assertEqual(self.vibes.adjust(account.id, "caretaker", -999), VIBE_MIN)
        self.assertEqual(self.vibes.adjust(account.id, "caretaker", 100), 0)
        with self.hub.locked() as connection:
            row = connection.execute(
                "SELECT value FROM main.vibes WHERE source_peep_id = ? AND target_peep_id = ?",
                (account.id, "tutorial:caretaker"),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(int(row["value"]), 0)

    def test_descriptors_cover_both_directions(self) -> None:
        self.assertEqual(describe_vibe(0), "Neutral 😐")
        self.assertEqual(describe_vibe(1), "Friend 🙂")
        self.assertEqual(describe_vibe(100), "Supreme BFF 😍")
        self.assertEqual(describe_vibe(-1), "Annoyance 🙄")
        self.assertEqual(describe_vibe(-100), "Archnemesis 👿")

    def test_periodic_rules_apply_stinky_and_charisma_once_per_minute(self) -> None:
        stinky = self.create_account("vibe-stinky")
        charming = self.create_account("vibe-charming")
        with self.hub.transaction() as connection:
            self.profiles.write_counters(
                connection,
                stinky.id,
                {"health": 50, "cleanliness": 0},
            )
        self.stats.apply_source(
            charming.id,
            "test-charisma",
            (Modifier(target="charisma", flat=2),),
        )

        now = utc_now()
        broadcasts = self.vibes.update_room("hub", [stinky.id, charming.id], now=now)
        self.assertEqual(len(broadcasts), 1)
        self.assertEqual(self.vibes.get(charming.id, stinky.id), -2)
        self.assertEqual(self.vibes.get("caretaker", stinky.id), -2)
        self.assertEqual(self.vibes.get(stinky.id, charming.id), 2)
        self.assertEqual(self.vibes.get("caretaker", charming.id), 2)

        self.assertEqual(
            self.vibes.update_room("hub", [stinky.id, charming.id], now=now + timedelta(seconds=30)),
            [],
        )
        self.assertEqual(self.vibes.get(charming.id, stinky.id), -2)
        self.vibes.update_room("hub", [stinky.id, charming.id], now=now + timedelta(seconds=61))
        self.assertEqual(self.vibes.get(charming.id, stinky.id), -4)

    def test_pairs_for_returns_both_directions(self) -> None:
        account = self.create_account("vibe-pair")
        self.vibes.adjust(account.id, "caretaker", 12)
        self.vibes.adjust("caretaker", account.id, -4)
        pair = self.vibes.pairs_for(account.id, ["caretaker"])["caretaker"]
        self.assertEqual(pair["toward"], {"value": 12, "label": "Friend 🙂"})
        self.assertEqual(pair["from"], {"value": -4, "label": "Annoyance 🙄"})

    def test_friend_payload_includes_reciprocal_vibes(self) -> None:
        viewer = self.create_account("vibe-friend-viewer")
        friend = self.create_account("vibe-friend")
        friends = FriendsService(self.hub, self.profiles, vibes=self.vibes)
        friends.send_request(viewer, friend)
        friends.accept_request(friend, viewer.id)
        self.vibes.adjust(viewer.id, friend.id, 30)
        self.vibes.adjust(friend.id, viewer.id, -5)

        payload = friends.serialize(viewer.id).as_dict()["friends"]
        self.assertEqual(payload[0]["vibes"]["toward"], {"value": 30, "label": "Buddy 😃"})
        self.assertEqual(payload[0]["vibes"]["from"], {"value": -5, "label": "Annoyance 🙄"})

    def test_context_vibe_toward_uses_callback(self) -> None:
        actor = PeepRef(kind="npc", peep_id="caretaker", account_id=None)
        context = BehaviorContext(
            event=BehaviorEvent(type="tick", actor=actor),
            actor=actor,
            target=None,
            room={},
            world={},
            state={},
            now=utc_now(),
            vibe_toward=lambda target: 7 if target == "molly" else 0,
        )
        self.assertEqual(context.vibe_toward("molly"), 7)
        self.assertEqual(context.vibe_toward(""), 0)

        without_callback = BehaviorContext(
            event=BehaviorEvent(type="tick", actor=actor),
            actor=actor,
            target=None,
            room={},
            world={},
            state={},
            now=utc_now(),
        )
        self.assertEqual(without_callback.vibe_toward("molly"), 0)


class VibesRuntimeTests(RuntimeTestCase):
    def test_snapshot_includes_vibes_for_an_npc(self) -> None:
        runtime = self.app.state.runtime
        account = runtime.profiles.create_account(
            "vibe-viewer",
            "password123!",
            runtime.world.id,
            "foyer",
        )
        runtime.vibes.adjust(account.id, "caretaker", 4)
        snapshot = asyncio.run(runtime.rooms.build_snapshot(account, "foyer"))
        caretaker = next(npc for npc in snapshot["npcs"] if npc["id"] == "caretaker")
        self.assertEqual(caretaker["vibes"]["toward"], {"value": 4, "label": "Friend 🙂"})


if __name__ == "__main__":
    unittest.main()
