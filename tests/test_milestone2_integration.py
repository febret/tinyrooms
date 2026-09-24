"""Milestone 2 end-to-end command and broadcast integration tests."""

from __future__ import annotations

import unittest

from tests.test_milestone1 import (
    RuntimeTestCase,
    auth_cookies,
    auth_headers,
    websocket_headers,
)


class Milestone2IntegrationTestCase(RuntimeTestCase):
    """Shared helpers for live-server Milestone 2 tests."""

    def runtime(self):
        return self.app.state.runtime

    def bootstrap(self, credentials) -> dict[str, object]:
        response = self.client.get(
            "/api/bootstrap",
            cookies=auth_cookies(credentials["session_token"], credentials["csrf_token"]),
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["user"]

    def account_id(self, credentials) -> str:
        return self.bootstrap(credentials)["id"]

    def grant_card(self, account_id: str, card_id: str, quantity: int = 1) -> str:
        runtime = self.runtime()
        definition = runtime.catalog.cards[card_id]
        scope = "world" if definition.source == runtime.world.id else "global"
        world_id = runtime.world.id if scope == "world" else None
        with runtime.hub.transaction() as connection:
            stacks = runtime.profiles.add_inventory_card(
                connection,
                account_id=account_id,
                world_id=world_id,
                card_def_id=card_id,
                quantity=quantity,
                scope=scope,
                stack_limit=definition.stack_limit,
            )
        return stacks[0].stack_id

    def set_bops(self, account_id: str, bops: int) -> None:
        runtime = self.runtime()
        with runtime.hub.transaction() as connection:
            account = runtime.profiles.get_account_by_id(account_id)
            runtime.profiles.update_account_progress(
                connection,
                account_id,
                level=account.level,
                kudos=account.kudos,
                bops=bops,
                energy=account.shared_energy,
                last_energy_at=account.last_energy_at,
                last_daily_claim=account.last_daily_claim,
            )

    def drain_until(self, socket, event_type: str) -> dict[str, object]:
        for _ in range(12):
            message = socket.receive_json()
            if message.get("type") == "room.event" and message["event"].get("type") == event_type:
                return message["event"]
        raise AssertionError(f"Never received room event {event_type!r}.")


class BootstrapPayloadTests(Milestone2IntegrationTestCase):
    """The bootstrap payload exposes the Milestone 2 self state."""

    def test_bootstrap_has_counters_stats_skills_friends_packs(self) -> None:
        user = self.bootstrap(self.create_ready_account("ada"))
        self.assertEqual(user["level"], 0)
        self.assertEqual(user["bops"], 10)
        self.assertEqual(user["counters"]["max_health"], 50)
        self.assertEqual(user["counters"]["max_energy"], 80)
        self.assertEqual(user["stats"]["constitution"], 1)
        self.assertEqual(user["statuses"], [])
        self.assertEqual(len(user["skills"]), 15)
        self.assertEqual(user["friends"]["friends"], [])
        pack_ids = {pack["id"] for pack in user["packs"]}
        self.assertEqual(pack_ids, {"base", "tutorial", "memebase"})


class ProgressionIntegrationTests(Milestone2IntegrationTestCase):
    """Level Up, Daily Bops, and skills over the command protocol."""

    def test_claim_daily_bops_once(self) -> None:
        credentials = self.create_ready_account("bea")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            first = self.command(socket, "bops-1", ".claim_bops")
            self.assertTrue(first["ok"])
            self.assertEqual(first["payload"]["user"]["bops"], 11)
            second = self.command(socket, "bops-2", ".claim_bops")
            self.assertFalse(second["ok"])

    def test_level_up_spends_kudos(self) -> None:
        credentials = self.create_ready_account("cam")
        account_id = self.account_id(credentials)
        self.runtime().progression.reward_once(account_id, "test:level-up", kudos=5)
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            result = self.command(socket, "level-1", ".level_up")
            self.assertTrue(result["ok"])
            self.assertEqual(result["payload"]["user"]["level"], 1)
            self.assertEqual(result["payload"]["user"]["kudos"], 4)

    def test_skill_slotting_updates_effective_stats(self) -> None:
        credentials = self.create_ready_account("dee")
        account_id = self.account_id(credentials)
        self.runtime().progression.reward_once(account_id, "test:skill", kudos=1)
        stack_id = self.grant_card(account_id, "sturdy")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(credentials["session_token"], credentials["csrf_token"])
        ) as socket:
            socket.receive_json()
            self.assertTrue(self.command(socket, "level-1", ".level_up")["ok"])
            result = self.command(socket, "skill-1", f".skill @card:{stack_id} 0")
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["payload"]["user"]["stats"]["constitution"], 2)
            self.assertEqual(result["payload"]["user"]["counters"]["max_health"], 100)


class ActionIntegrationTests(Milestone2IntegrationTestCase):
    """Card actions, emotes, and room broadcasts."""

    def test_healing_broadcasts_counter_update(self) -> None:
        alice = self.create_ready_account("eve")
        bob = self.create_ready_account("fay")
        alice_id = self.account_id(alice)
        bob_id = self.account_id(bob)
        stack_id = self.grant_card(alice_id, "tomato-sauce")
        self.runtime().stats.mutate(bob_id, health_delta=-30)
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as alice_socket:
            alice_socket.receive_json()
            with self.client.websocket_connect(
                "/ws", headers=websocket_headers(bob["session_token"], bob["csrf_token"])
            ) as bob_socket:
                bob_socket.receive_json()
                alice_socket.receive_json()
                self.assertTrue(self.command(alice_socket, "equip-1", f".equip @card:{stack_id}")["ok"])
                result = self.command(
                    alice_socket,
                    "use-1",
                    f".use @card:{stack_id} @peep:{bob_id}",
                )
                self.assertTrue(result["ok"], result)
                event = self.drain_until(bob_socket, "counter.updated")
                self.assertEqual(event["target_id"], bob_id)
                self.assertEqual(event["health_delta"], 25)

    def test_emote_broadcasts_bubble(self) -> None:
        alice = self.create_ready_account("gil")
        bob = self.create_ready_account("hal")
        stack_id = self.grant_card(self.account_id(alice), "smile")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as alice_socket:
            alice_socket.receive_json()
            with self.client.websocket_connect(
                "/ws", headers=websocket_headers(bob["session_token"], bob["csrf_token"])
            ) as bob_socket:
                bob_socket.receive_json()
                alice_socket.receive_json()
                result = self.command(alice_socket, "emote-1", f".emote @card:{stack_id}")
                self.assertTrue(result["ok"], result)
                event = self.drain_until(bob_socket, "emote.bubble")
                self.assertEqual(event["card_id"], "smile")

    def test_animation_emote_broadcasts_gif_bubble(self) -> None:
        alice = self.create_ready_account("mio")
        stack_id = self.grant_card(self.account_id(alice), "wave")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            result = self.command(socket, "emote-wave", f".emote @card:{stack_id}")
            self.assertTrue(result["ok"], result)
            event = self.drain_until(socket, "emote.bubble")
            self.assertEqual(event["card_id"], "wave")
            self.assertTrue(event["bubble"]["image_url"].endswith("wave.gif"))


class SocialShopIntegrationTests(Milestone2IntegrationTestCase):
    """Friends, packs, sticker swaps, and stack commands."""

    def test_friend_request_accept_flow(self) -> None:
        alice = self.create_ready_account("joy")
        bob = self.create_ready_account("kim")
        bob_id = self.account_id(bob)
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            result = self.command(socket, "friend-1", f".friend add @peep:{bob_id}")
            self.assertTrue(result["ok"], result)
            self.assertEqual(len(result["payload"]["user"]["friends"]["outgoing"]), 1)
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(bob["session_token"], bob["csrf_token"])
        ) as socket:
            socket.receive_json()
            incoming = self.bootstrap(bob)["friends"]["incoming"]
            self.assertEqual(len(incoming), 1)
            result = self.command(socket, "friend-2", f".friend accept @peep:{incoming[0]['account_id']}")
            self.assertTrue(result["ok"], result)
            self.assertEqual(len(result["payload"]["user"]["friends"]["friends"]), 1)

    def test_buy_pack_is_idempotent(self) -> None:
        alice = self.create_ready_account("lyn")
        alice_id = self.account_id(alice)
        self.set_bops(alice_id, 50)
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            first = self.command(socket, "buy-1", ".buy_pack base op-live-1")
            self.assertTrue(first["ok"], first)
            self.assertEqual(first["payload"]["purchase"]["bops_spent"], 10)
            self.assertEqual(len(first["payload"]["purchase"]["cards"]), 3)
            second = self.command(socket, "buy-2", ".buy_pack base op-live-1")
            self.assertTrue(second["ok"])
            self.assertTrue(second["payload"]["purchase"]["replayed"])
            self.assertEqual(second["payload"]["user"]["bops"], 40)

    def test_swap_sticker_charges(self) -> None:
        alice = self.create_ready_account("mia")
        alice_id = self.account_id(alice)
        self.set_bops(alice_id, 30)
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            result = self.command(socket, "swap-1", ".swap_sticker s2.png")
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["payload"]["user"]["sticker"], "s2.png")
            self.assertEqual(result["payload"]["user"]["bops"], 20)

    def test_split_and_merge_stacks(self) -> None:
        alice = self.create_ready_account("ned")
        alice_id = self.account_id(alice)
        stack_id = self.grant_card(alice_id, "juicy-drink", quantity=5)
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            split = self.command(socket, "split-1", f".split @card:{stack_id} 2")
            self.assertTrue(split["ok"], split)
            new_stack = next(
                entry
                for entry in split["payload"]["inventory"]
                if entry["stack_id"] != stack_id and entry["definition"]["id"] == "juicy-drink"
            )
            merge = self.command(
                socket,
                "merge-1",
                f".merge @card:{new_stack['stack_id']} @card:{stack_id}",
            )
            self.assertTrue(merge["ok"], merge)
            total = sum(
                entry["quantity"]
                for entry in merge["payload"]["inventory"]
                if entry["definition"]["id"] == "juicy-drink"
            )
            self.assertEqual(total, 5)

    def test_pin_peep_persists(self) -> None:
        alice = self.create_ready_account("ola")
        bob = self.create_ready_account("pat")
        bob_id = self.account_id(bob)
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            result = self.command(socket, "pin-1", f".pin_peep @peep:{bob_id}")
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["payload"]["pinned_peeps"], [bob_id])
        self.assertEqual(self.bootstrap(alice)["pinned_peeps"], [bob_id])


class RoomAndActivityIntegrationTests(Milestone2IntegrationTestCase):
    """Room-change Energy cost and the shop UI."""

    def test_room_change_costs_one_energy(self) -> None:
        alice = self.create_ready_account("quin")
        alice_id = self.account_id(alice)
        before = self.runtime().stats.snapshot(alice_id).energy
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            result = self.command(socket, "go-1", ".go @way:exit0")
            self.assertTrue(result["ok"], result)
        after = self.runtime().stats.snapshot(alice_id).energy
        self.assertAlmostEqual(before - after, 1, delta=0.2)

    def test_shop_command_opens_shop_ui(self) -> None:
        alice = self.create_ready_account("rae")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            result = self.command(socket, "shop-1", ".shop")
            self.assertTrue(result["ok"], result)
            self.assertIsNone(result["payload"].get("activity"))
            self.assertIn({"type": "shop.open"}, result["events"])
            packs = self.command(socket, "packs-1", ".packs")
            self.assertEqual({pack["id"] for pack in packs["payload"]["packs"]}, {"base", "tutorial", "memebase"})

    def test_hub_has_no_shop_prop(self) -> None:
        alice = self.create_ready_account("sue")
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            room = socket.receive_json()["room"]
            self.assertFalse(any(prop["behavior"] == "shop" for prop in room["props"]))


class SellIntegrationTests(Milestone2IntegrationTestCase):
    """Selling cards over the command protocol."""

    def test_sell_card_credits_bops_and_updates_inventory(self) -> None:
        alice = self.create_ready_account("val")
        account_id = self.account_id(alice)
        stack_id = self.grant_card(account_id, "juicy-drink", 2)
        self.set_bops(account_id, 5)
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            result = self.command(socket, "sell-1", f".sell @card:{stack_id} 1")
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["payload"]["user"]["bops"], 6)
            self.assertEqual(
                result["payload"]["sale"],
                {"card_id": "juicy-drink", "quantity": 1, "bops_gained": 1},
            )
            self.assertIn(
                {"type": "toast", "tone": "success", "text": "+1 Bops", "silent": True},
                result["events"],
            )
            sold = next(stack for stack in result["payload"]["inventory"] if stack["stack_id"] == stack_id)
            self.assertEqual(sold["quantity"], 1)
            self.assertEqual(sold["definition"]["sell_price"], 1)

    def test_sell_rejects_quest_card(self) -> None:
        alice = self.create_ready_account("wade")
        account_id = self.account_id(alice)
        stack_id = self.grant_card(account_id, "house-key", 1)
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            result = self.command(socket, "sell-2", f".sell @card:{stack_id} 1")
            self.assertFalse(result["ok"])


class MergeAllIntegrationTests(Milestone2IntegrationTestCase):
    """Consolidating duplicate stacks over the command protocol."""

    def test_merge_all_consolidates_duplicate_stacks(self) -> None:
        alice = self.create_ready_account("xen")
        account_id = self.account_id(alice)
        runtime = self.runtime()
        with runtime.hub.transaction() as connection:
            runtime.profiles.create_inventory_stack(
                connection,
                account_id=account_id,
                world_id=runtime.world.id,
                card_def_id="juicy-drink",
                quantity=4,
                scope="world",
            )
            runtime.profiles.create_inventory_stack(
                connection,
                account_id=account_id,
                world_id=runtime.world.id,
                card_def_id="juicy-drink",
                quantity=3,
                scope="world",
            )
        with self.client.websocket_connect(
            "/ws", headers=websocket_headers(alice["session_token"], alice["csrf_token"])
        ) as socket:
            socket.receive_json()
            result = self.command(socket, "merge-all-1", ".merge_all")
            self.assertTrue(result["ok"], result)
            stacks = [stack for stack in result["payload"]["inventory"] if stack["definition"]["id"] == "juicy-drink"]
            self.assertEqual(len(stacks), 1)
            self.assertEqual(stacks[0]["quantity"], 7)


if __name__ == "__main__":
    unittest.main()
