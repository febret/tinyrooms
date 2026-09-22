"""Milestone 2 social (friends) and shop (packs, sticker swap) tests."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import random
import unittest

from server.content.cards import load_card_catalog
from server.content.gameplay import load_gameplay_content
from server.profiles import ProfileRepository
from server.services.friends import FriendsService
from server.services.shop import DEFAULT_RARITY_WEIGHTS, ShopService
from server.state.migrations import DatabaseHub, ensure_profile_database, ensure_world_database
from tests.common import REPO_ROOT

WORLD_ID = "tutorial"
EXPRESSION_CARDS = {"smile", "sigh", "growl", "goof"}
BASE_SKILLS = {"sturdy", "nimble", "charming", "stylish"}
BASE_PACK_CARDS = EXPRESSION_CARDS | BASE_SKILLS
TUTORIAL_PACK_CARDS = {
    "ballet-shoes",
    "fancy-wallet",
    "hand-light",
    "juicy-drink",
    "lucille",
    "plastic-bag",
    "poop-in-a-bag",
    "poop",
    "pooper-scooper",
    "seal-plushie",
    "tasty-toast",
    "tomato-sauce",
}


class SocialShopTestCase(unittest.TestCase):
    """Provide isolated services for shop and friend tests."""

    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        profile_path = root / "profiles.sqlite3"
        world_path = root / "worldstate.sqlite3"
        ensure_profile_database(profile_path)
        ensure_world_database(world_path)
        self.hub = DatabaseHub(profile_path, world_path)
        self.addCleanup(self.hub.close)
        self.profiles = ProfileRepository(self.hub)
        self.content = load_gameplay_content(REPO_ROOT / "data" / "core")
        self.catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", REPO_ROOT / "worlds" / WORLD_ID)
        self.stickers = {f"s{index}" for index in range(1, 22)}
        self.shop = ShopService(
            self.hub,
            self.profiles,
            self.catalog,
            self.content,
            WORLD_ID,
            rng=random.Random(1234),
        )
        self.friends = FriendsService(self.hub, self.profiles, is_online=lambda account_id: True)
        self.alice = self.profiles.create_account("Alice", "password123!", WORLD_ID, "hub")
        self.bob = self.profiles.create_account("Bob", "password123!", WORLD_ID, "hub")

    def _set_bops(self, account, bops: int):
        with self.hub.transaction() as connection:
            return self.profiles.update_account_progress(
                connection,
                account.id,
                level=account.level,
                kudos=account.kudos,
                bops=bops,
                energy=account.shared_energy,
                last_energy_at=account.last_energy_at,
                last_daily_claim=account.last_daily_claim,
            )

    def _reload(self, account):
        return self.profiles.get_account_by_id(account.id)


class PackCatalogTests(SocialShopTestCase):
    """Pack catalogs and rarity selection."""

    def test_pack_previews_hide_contents_and_match_design(self) -> None:
        previews = {preview.id: preview for preview in self.shop.packs()}
        self.assertEqual(previews["base"].price, 10)
        self.assertEqual(previews["base"].size, 3)
        self.assertEqual(previews["tutorial"].price, 10)
        self.assertEqual(previews["tutorial"].size, 3)

    def test_exact_pack_catalogs(self) -> None:
        self.assertEqual(set(self.catalog.packs["base"].cards), BASE_PACK_CARDS)
        self.assertEqual(set(self.catalog.packs["tutorial"].cards), TUTORIAL_PACK_CARDS)

    def test_base_pack_draws_only_common_members(self) -> None:
        draws = self.shop.draw(self.catalog.packs["base"])
        self.assertEqual(len(draws), 3)
        for definition in draws:
            self.assertIn(definition.id, BASE_PACK_CARDS)
            self.assertEqual(definition.rarity or "Common", "Common")

    def test_deterministic_rng_repeats_draws(self) -> None:
        first = [definition.id for definition in self.shop.draw(self.catalog.packs["tutorial"], random.Random(7))]
        second = [definition.id for definition in self.shop.draw(self.catalog.packs["tutorial"], random.Random(7))]
        self.assertEqual(first, second)

    def test_weights_are_renormalized_over_present_rarities(self) -> None:
        self.assertEqual(DEFAULT_RARITY_WEIGHTS["Common"], 70.0)
        self.assertEqual(DEFAULT_RARITY_WEIGHTS["Legendary"], 0.2)


class PurchaseTests(SocialShopTestCase):
    """Exactly-once pack purchases."""

    def test_purchase_charges_and_grants(self) -> None:
        self._set_bops(self.alice, 50)
        before = {stack.stack_id for stack in self.profiles.list_inventory(self.alice.id, WORLD_ID)}
        result = self.shop.purchase(self._reload(self.alice), "base", "op-1")
        self.assertEqual(result.bops_spent, 10)
        self.assertEqual(result.account.bops, 40)
        self.assertFalse(result.replayed)
        after = {stack.stack_id for stack in self.profiles.list_inventory(self.alice.id, WORLD_ID)}
        self.assertTrue(after - before)

    def test_replay_same_operation_does_not_charge_or_duplicate(self) -> None:
        self._set_bops(self.alice, 50)
        first = self.shop.purchase(self._reload(self.alice), "tutorial", "op-2")
        second = self.shop.purchase(self._reload(self.alice), "tutorial", "op-2")
        self.assertEqual(second.bops_spent, 0)
        self.assertEqual(second.account.bops, first.account.bops)
        self.assertTrue(second.replayed)
        self.assertEqual([c.id for c in first.cards], [c.id for c in second.cards])

    def test_insufficient_bops_changes_nothing(self) -> None:
        self._set_bops(self.alice, 5)
        stacks_before = self.profiles.list_inventory(self.alice.id, WORLD_ID)
        with self.assertRaises(ValueError):
            self.shop.purchase(self._reload(self.alice), "base", "op-3")
        self.assertEqual(self._reload(self.alice).bops, 5)
        self.assertEqual(len(self.profiles.list_inventory(self.alice.id, WORLD_ID)), len(stacks_before))

    def test_swap_sticker_charges_only_when_different(self) -> None:
        self._set_bops(self.alice, 30)
        self.profiles.set_sticker(self.alice.id, "s1")
        same = self.shop.swap_sticker(self._reload(self.alice), "s1", self.stickers)
        self.assertEqual(same.bops, 30)
        changed = self.shop.swap_sticker(self._reload(self.alice), "s2", self.stickers)
        self.assertEqual(changed.bops, 20)
        self.assertEqual(changed.sticker, "s2")
        again = self.shop.swap_sticker(changed, "s2", self.stickers)
        self.assertEqual(again.bops, 20)

    def test_swap_sticker_insufficient_funds_rejected(self) -> None:
        self._set_bops(self.alice, 3)
        with self.assertRaises(ValueError):
            self.shop.swap_sticker(self._reload(self.alice), "s3", self.stickers)
        self.assertEqual(self._reload(self.alice).bops, 3)


class FriendRequestTests(SocialShopTestCase):
    """Friend request lifecycle and race-safe mutual creation."""

    def test_send_and_accept_creates_mutual_friendship(self) -> None:
        self.assertEqual(self.friends.send_request(self.alice, self.bob), "requested")
        incoming = self.friends.serialize(self.bob.id).incoming
        self.assertEqual([entry.account_id for entry in incoming], [self.alice.id])
        self.friends.accept_request(self._reload(self.bob), self.alice.id)
        self.assertEqual([entry.account_id for entry in self.friends.serialize(self.alice.id).friends], [self.bob.id])
        self.assertEqual([entry.account_id for entry in self.friends.serialize(self.bob.id).friends], [self.alice.id])
        self.assertEqual(self.friends.serialize(self.alice.id).outgoing, ())

    def test_decline_removes_request_without_friendship(self) -> None:
        self.friends.send_request(self.alice, self.bob)
        self.friends.decline_request(self._reload(self.bob), self.alice.id)
        self.assertEqual(self.friends.serialize(self.alice.id).friends, ())
        self.assertEqual(self.friends.serialize(self.bob.id).incoming, ())

    def test_cancel_outgoing_request(self) -> None:
        self.friends.send_request(self.alice, self.bob)
        self.friends.cancel_request(self._reload(self.alice), self.bob.id)
        self.assertEqual(self.friends.serialize(self.bob.id).incoming, ())

    def test_mutual_requests_auto_accept_into_single_friendship(self) -> None:
        self.friends.send_request(self.alice, self.bob)
        outcome = self.friends.send_request(self._reload(self.bob), self.alice)
        self.assertEqual(outcome, "friends")
        alice_friends = self.friends.serialize(self.alice.id).friends
        bob_friends = self.friends.serialize(self.bob.id).friends
        self.assertEqual([entry.account_id for entry in alice_friends], [self.bob.id])
        self.assertEqual([entry.account_id for entry in bob_friends], [self.alice.id])

    def test_remove_friend_for_both(self) -> None:
        self.friends.send_request(self.alice, self.bob)
        self.friends.accept_request(self._reload(self.bob), self.alice.id)
        self.friends.remove_friend(self._reload(self.alice), self.bob.id)
        self.assertEqual(self.friends.serialize(self.alice.id).friends, ())
        self.assertEqual(self.friends.serialize(self.bob.id).friends, ())

    def test_duplicate_send_rejected(self) -> None:
        self.friends.send_request(self.alice, self.bob)
        with self.assertRaises(ValueError):
            self.friends.send_request(self._reload(self.alice), self.bob)

    def test_online_status_reported(self) -> None:
        self.friends.send_request(self.alice, self.bob)
        self.friends.accept_request(self._reload(self.bob), self.alice.id)
        friend = self.friends.serialize(self.alice.id).friends[0]
        self.assertTrue(friend.online)


if __name__ == "__main__":
    unittest.main()
