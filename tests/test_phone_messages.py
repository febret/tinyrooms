"""Phone message inbox: friend SMS, threads, caps, and NPC delivery."""

from __future__ import annotations

import unittest

from server.services.friends import FriendsService
from server.services.phone_messages import (
    MAX_MESSAGES_PER_THREAD,
    MAX_THREADS,
    PhoneMessageService,
    clean_body,
    friend_thread_key,
    npc_ids_from_thread_key,
    npc_thread_key,
    parse_thread_key,
    system_thread_key,
)
from tests.common import ServiceTestCase


def befriend(test: ServiceTestCase, first, second) -> FriendsService:
    """Create a mutual friendship between two accounts."""

    friends = FriendsService(test.hub, test.profiles)
    friends.send_request(first, second)
    friends.accept_request(second, first.id)
    return friends


class ThreadKeyTests(unittest.TestCase):
    def test_round_trips(self) -> None:
        self.assertEqual(parse_thread_key(friend_thread_key("abc")), ("player", "abc"))
        self.assertEqual(
            parse_thread_key(npc_thread_key("tinytown", "ttnpc:one")),
            ("npc", "tinytown:ttnpc:one"),
        )
        self.assertEqual(parse_thread_key(system_thread_key("events")), ("system", "events"))
        self.assertIsNone(parse_thread_key("bogus"))
        self.assertIsNone(parse_thread_key("player:"))
        self.assertIsNone(parse_thread_key("npc:nowhere"))

    def test_npc_ids(self) -> None:
        self.assertEqual(
            npc_ids_from_thread_key(npc_thread_key("tinytown", "ttnpc:one")),
            ("tinytown", "ttnpc:one"),
        )
        self.assertIsNone(npc_ids_from_thread_key(friend_thread_key("abc")))

    def test_body_rules(self) -> None:
        self.assertEqual(clean_body("  hello   there "), "hello there")
        with self.assertRaises(ValueError):
            clean_body("   ")
        with self.assertRaises(ValueError):
            clean_body("x" * 161)


class FriendTextTests(ServiceTestCase):
    def test_send_writes_both_phones(self) -> None:
        alice = self.create_account("alice")
        bob = self.create_account("bob")
        befriend(self, alice, bob)
        phone = PhoneMessageService(self.hub, self.profiles)

        outgoing, incoming = phone.send_to_friend(alice, bob, "hey there", "tutorial")

        self.assertEqual(outgoing.direction, "out")
        self.assertEqual(incoming.direction, "in")
        self.assertEqual(incoming.body, "hey there")
        alice_threads = phone.list_threads(alice.id)
        bob_threads = phone.list_threads(bob.id)
        self.assertEqual(len(alice_threads), 1)
        self.assertEqual(alice_threads[0].thread_key, friend_thread_key(bob.id))
        self.assertEqual(alice_threads[0].unread, 0)
        self.assertEqual(len(bob_threads), 1)
        self.assertEqual(bob_threads[0].thread_key, friend_thread_key(alice.id))
        self.assertEqual(bob_threads[0].unread, 1)
        self.assertEqual(bob_threads[0].peer_name, "alice")
        self.assertEqual(phone.unread_count(bob.id), 1)
        self.assertEqual(phone.unread_count(alice.id), 0)

    def test_strangers_cannot_text(self) -> None:
        alice = self.create_account("alice")
        bob = self.create_account("bob")
        phone = PhoneMessageService(self.hub, self.profiles)
        with self.assertRaises(ValueError):
            phone.send_to_friend(alice, bob, "hello", "tutorial")

    def test_self_text_rejected(self) -> None:
        alice = self.create_account("alice")
        phone = PhoneMessageService(self.hub, self.profiles)
        with self.assertRaises(ValueError):
            phone.send_to_friend(alice, alice, "hello", "tutorial")

    def test_open_marks_read(self) -> None:
        alice = self.create_account("alice")
        bob = self.create_account("bob")
        befriend(self, alice, bob)
        phone = PhoneMessageService(self.hub, self.profiles)
        phone.send_to_friend(alice, bob, "one", "tutorial")
        phone.send_to_friend(alice, bob, "two", "tutorial")

        thread, messages = phone.open_thread(bob.id, friend_thread_key(alice.id))

        self.assertIsNotNone(thread)
        self.assertEqual([message.body for message in messages], ["one", "two"])
        self.assertEqual(phone.unread_count(bob.id), 0)
        self.assertEqual(phone.list_threads(bob.id)[0].unread, 0)

    def test_unfriend_keeps_history_but_blocks_sends(self) -> None:
        alice = self.create_account("alice")
        bob = self.create_account("bob")
        friends = befriend(self, alice, bob)
        phone = PhoneMessageService(self.hub, self.profiles)
        phone.send_to_friend(alice, bob, "before", "tutorial")
        friends.remove_friend(alice, bob.id)
        with self.assertRaises(ValueError):
            phone.send_to_friend(alice, bob, "after", "tutorial")
        thread, messages = phone.open_thread(bob.id, friend_thread_key(alice.id))
        self.assertIsNotNone(thread)
        self.assertEqual([message.body for message in messages], ["before"])

    def test_thread_cap_drops_oldest(self) -> None:
        alice = self.create_account("alice")
        bob = self.create_account("bob")
        befriend(self, alice, bob)
        phone = PhoneMessageService(self.hub, self.profiles)
        for index in range(MAX_MESSAGES_PER_THREAD + 5):
            phone.send_to_friend(alice, bob, f"msg {index}", "tutorial")
        _, messages = phone.open_thread(bob.id, friend_thread_key(alice.id))
        self.assertEqual(len(messages), MAX_MESSAGES_PER_THREAD)
        self.assertEqual(messages[0].body, "msg 5")

    def test_thread_count_cap_drops_oldest_thread(self) -> None:
        alice = self.create_account("alice")
        phone = PhoneMessageService(self.hub, self.profiles)
        for index in range(MAX_THREADS + 3):
            phone.deliver_inbound(
                alice.id,
                system_thread_key(f"source-{index}"),
                f"Source {index}",
                f"hello {index}",
                "tutorial",
            )
        threads = phone.list_threads(alice.id)
        self.assertEqual(len(threads), MAX_THREADS)
        keys = {thread.thread_key for thread in threads}
        self.assertNotIn(system_thread_key("source-0"), keys)
        self.assertIn(system_thread_key(f"source-{MAX_THREADS + 2}"), keys)


class NpcDeliveryTests(ServiceTestCase):
    def test_inbound_and_exchange(self) -> None:
        alice = self.create_account("alice")
        phone = PhoneMessageService(self.hub, self.profiles)
        thread_key = npc_thread_key("tinytown", "ttnpc:one")

        phone.deliver_inbound(alice.id, thread_key, "Wren", "hi from home", "tinytown")
        thread, messages = phone.open_thread(alice.id, thread_key)
        self.assertIsNotNone(thread)
        self.assertEqual(thread.kind, "npc")
        self.assertEqual(thread.peer_name, "Wren")
        self.assertEqual(len(messages), 1)

        outgoing, incoming = phone.append_npc_exchange(
            alice,
            thread_key,
            outbound_body="hey wren",
            inbound_body="hey you",
            inbound_sender="Wren",
            world_id="tinytown",
            peer_name="Wren",
        )
        self.assertEqual(outgoing.direction, "out")
        self.assertEqual(incoming.direction, "in")
        _, messages = phone.open_thread(alice.id, thread_key)
        self.assertEqual([message.body for message in messages], ["hi from home", "hey wren", "hey you"])
        self.assertEqual(phone.unread_count(alice.id), 0)

    def test_system_reply_stays_local(self) -> None:
        alice = self.create_account("alice")
        phone = PhoneMessageService(self.hub, self.profiles)
        thread_key = system_thread_key("events")
        phone.deliver_inbound(alice.id, thread_key, "Town Crier", "festival soon", "tinytown")
        stored = phone.store_outbound(alice, thread_key, "thanks", "tinytown")
        self.assertEqual(stored.direction, "out")
        _, messages = phone.open_thread(alice.id, thread_key)
        self.assertEqual(len(messages), 2)


if __name__ == "__main__":
    unittest.main()
