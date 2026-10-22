"""Tests for vibe persistence, descriptors, and periodic room rules."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import unittest

from server.behaviors.context import BehaviorContext
from server.behaviors.events import BehaviorEvent, PeepRef
from server.game.modifiers import Modifier
from server.security import utc_now
from server.services.friends import FriendsService
from server.services.stats import StatsService
from server.services.vibes import VibesService, describe_vibe
from server.state.npc_peep_states import NpcPeepStateRepository
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

    def test_tables_store_player_and_world_sources_separately(self) -> None:
        account = self.create_account("vibe-source")
        self.vibes.adjust(account.id, "caretaker", 7)
        self.vibes.adjust("caretaker", account.id, -3)

        self.assertEqual(self.vibes.get(account.id, "caretaker"), 7)
        self.assertEqual(self.vibes.get("caretaker", account.id), -3)
        with self.hub.locked() as connection:
            player_row = connection.execute(
                "SELECT value FROM main.vibes WHERE source_peep_id = ? AND target_peep_id = ?",
                (account.id, "caretaker"),
            ).fetchone()
            world_row = connection.execute(
                "SELECT value FROM world.vibes WHERE source_peep_id = ? AND target_peep_id = ?",
                ("caretaker", account.id),
            ).fetchone()
        self.assertEqual(int(player_row["value"]), 7)
        self.assertEqual(int(world_row["value"]), -3)

    def test_scores_clamp_and_zero_rows_are_kept(self) -> None:
        account = self.create_account("vibe-clamp")
        self.assertEqual(self.vibes.adjust(account.id, "caretaker", 999), VIBE_MAX)
        self.assertEqual(self.vibes.adjust(account.id, "caretaker", -999), VIBE_MIN)
        self.assertEqual(self.vibes.adjust(account.id, "caretaker", 100), 0)
        with self.hub.locked() as connection:
            row = connection.execute(
                "SELECT value FROM main.vibes WHERE source_peep_id = ? AND target_peep_id = ?",
                (account.id, "caretaker"),
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
