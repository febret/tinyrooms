"""User Manager inventory and Vibes Manager tests."""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from tests.mc_helpers import McHttpTestCase


def _seed_world_vibes(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE vibes ("
        "world_id TEXT NOT NULL, source_peep_id TEXT NOT NULL, target_peep_id TEXT NOT NULL, "
        "value INTEGER NOT NULL CHECK (value BETWEEN -100 AND 100), updated_at TEXT NOT NULL, "
        "PRIMARY KEY (world_id, source_peep_id, target_peep_id))"
    )
    connection.execute(
        "INSERT INTO vibes VALUES ('tutorial', 'barkeep', 'regular', 10, '2026-01-01T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()


def _world_vibes(path: Path) -> list[tuple]:
    connection = sqlite3.connect(path)
    rows = connection.execute(
        "SELECT world_id, source_peep_id, target_peep_id, value FROM vibes ORDER BY source_peep_id"
    ).fetchall()
    connection.close()
    return [tuple(row) for row in rows]


class InventoryEndpointTests(McHttpTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.login()
        self.runtime = self.app.state.mc
        self.account = self.runtime.profiles.create_account(
            "inventoryplayer", "password123!", "tutorial", "hub"
        )

    def test_add_edit_and_delete_stack(self) -> None:
        added = self.client.post(
            f"/api/mission-control/users/{self.account.id}/inventory",
            headers=self.csrf_headers(),
            json={"card_def_id": "stinky-poop", "quantity": 2},
        )
        self.assertEqual(added.status_code, 200, added.text)
        stack_id = added.json()["stack"]["stack_id"]

        detail = self.client.get(f"/api/mission-control/users/{self.account.id}").json()["user"]
        owned = [stack for stack in detail["profile_card_stacks"] if stack["card_def_id"] == "stinky-poop"]
        self.assertEqual(len(owned), 1)
        self.assertEqual(owned[0]["quantity"], 2)

        edited = self.client.patch(
            f"/api/mission-control/users/{self.account.id}/inventory/{stack_id}",
            headers=self.csrf_headers(),
            json={"quantity": 5},
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        detail = self.client.get(f"/api/mission-control/users/{self.account.id}").json()["user"]
        owned = [stack for stack in detail["profile_card_stacks"] if stack["stack_id"] == stack_id]
        self.assertEqual(len(owned), 1)
        self.assertEqual(owned[0]["quantity"], 5)

        deleted = self.client.request(
            "DELETE",
            f"/api/mission-control/users/{self.account.id}/inventory/{stack_id}",
            headers=self.csrf_headers(),
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        detail = self.client.get(f"/api/mission-control/users/{self.account.id}").json()["user"]
        owned = [stack for stack in detail["profile_card_stacks"] if stack["stack_id"] == stack_id]
        self.assertEqual(owned, [])

    def test_add_world_stack_and_validation(self) -> None:
        missing_world = self.client.post(
            f"/api/mission-control/users/{self.account.id}/inventory",
            headers=self.csrf_headers(),
            json={"card_def_id": "stinky-poop", "quantity": 1, "scope": "world"},
        )
        self.assertEqual(missing_world.status_code, 400)
        self.assertEqual(missing_world.json()["code"], "inventory_rejected")

        world_stack = self.client.post(
            f"/api/mission-control/users/{self.account.id}/inventory",
            headers=self.csrf_headers(),
            json={"card_def_id": "stinky-poop", "quantity": 1, "world_id": "tutorial", "scope": "world"},
        )
        self.assertEqual(world_stack.status_code, 200, world_stack.text)
        self.assertEqual(world_stack.json()["stack"]["world_id"], "tutorial")

        zero = self.client.patch(
            f"/api/mission-control/users/{self.account.id}/inventory/{world_stack.json()['stack']['stack_id']}",
            headers=self.csrf_headers(),
            json={"quantity": 0},
        )
        self.assertEqual(zero.status_code, 400)

    def test_unknown_cards_and_over_limit_quantities_rejected(self) -> None:
        unknown = self.client.post(
            f"/api/mission-control/users/{self.account.id}/inventory",
            headers=self.csrf_headers(),
            json={"card_def_id": "no-such-card", "quantity": 1},
        )
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(unknown.json()["code"], "inventory_rejected")

        over_limit = self.client.post(
            f"/api/mission-control/users/{self.account.id}/inventory",
            headers=self.csrf_headers(),
            json={"card_def_id": "stinky-poop", "quantity": 100},
        )
        self.assertEqual(over_limit.status_code, 400)

    def test_stack_operations_reject_other_accounts(self) -> None:
        added = self.client.post(
            f"/api/mission-control/users/{self.account.id}/inventory",
            headers=self.csrf_headers(),
            json={"card_def_id": "stinky-poop", "quantity": 1},
        ).json()["stack"]
        other = self.runtime.profiles.create_account("otherplayer", "password123!", "tutorial", "hub")

        edited = self.client.patch(
            f"/api/mission-control/users/{other.id}/inventory/{added['stack_id']}",
            headers=self.csrf_headers(),
            json={"quantity": 3},
        )
        self.assertEqual(edited.status_code, 400)

        deleted = self.client.request(
            "DELETE",
            f"/api/mission-control/users/{other.id}/inventory/{added['stack_id']}",
            headers=self.csrf_headers(),
        )
        self.assertEqual(deleted.status_code, 400)


class VibesEndpointTests(McHttpTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.login()
        self.runtime = self.app.state.mc

    def test_profile_vibe_round_trip(self) -> None:
        account = self.runtime.profiles.create_account("vibeplayer", "password123!", "tutorial", "hub")
        created = self.client.patch(
            "/api/mission-control/vibes",
            headers=self.csrf_headers(),
            json={
                "store": "profile",
                "world_id": "tutorial",
                "source_peep_id": account.id,
                "target_peep_id": "barkeep",
                "value": 25,
            },
        )
        self.assertEqual(created.status_code, 200, created.text)

        listed = self.client.get("/api/mission-control/vibes?q=vibeplayer", headers={}).json()
        self.assertEqual(len(listed["rows"]), 1)
        row = listed["rows"][0]
        self.assertEqual(row["value"], 25)
        self.assertEqual(row["source_label"], "vibeplayer")

        updated = self.client.patch(
            "/api/mission-control/vibes",
            headers=self.csrf_headers(),
            json={
                "store": "profile",
                "world_id": "tutorial",
                "source_peep_id": account.id,
                "target_peep_id": "barkeep",
                "value": -50,
            },
        )
        self.assertEqual(updated.json()["vibe"]["value"], -50)

        deleted = self.client.request(
            "DELETE",
            "/api/mission-control/vibes",
            headers=self.csrf_headers(),
            params={
                "store": "profile",
                "world_id": "tutorial",
                "source_peep_id": account.id,
                "target_peep_id": "barkeep",
            },
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        missing = self.client.request(
            "DELETE",
            "/api/mission-control/vibes",
            headers=self.csrf_headers(),
            params={
                "store": "profile",
                "world_id": "tutorial",
                "source_peep_id": account.id,
                "target_peep_id": "barkeep",
            },
        )
        self.assertEqual(missing.status_code, 400)

    def test_vibe_validation(self) -> None:
        rejected = self.client.patch(
            "/api/mission-control/vibes",
            headers=self.csrf_headers(),
            json={
                "store": "profile",
                "world_id": "tutorial",
                "source_peep_id": "a",
                "target_peep_id": "b",
                "value": 500,
            },
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(rejected.json()["code"], "vibes_rejected")

        unknown_store = self.client.patch(
            "/api/mission-control/vibes",
            headers=self.csrf_headers(),
            json={
                "store": "instance:missing",
                "world_id": "tutorial",
                "source_peep_id": "a",
                "target_peep_id": "b",
                "value": 5,
            },
        )
        self.assertEqual(unknown_store.status_code, 400)

    def test_world_database_vibes(self) -> None:
        root = Path(self.temporary_directory.name)
        world_db = root / "worldstate.sqlite3"
        _seed_world_vibes(world_db)
        record = self.runtime.registry.register_spawned(
            name="tutorial",
            endpoint="https://127.0.0.1:5099",
            instance_dir=str(root / "instance"),
            process_handle=None,
            base_path="/tutorial",
            spawn_config={
                "name": "tutorial",
                "world_path": str(root / "world"),
                "worldstate_path": str(world_db),
                "users_path": str(root / "users"),
                "host": "127.0.0.1",
                "port": 5099,
                "features": "",
                "admins": "",
                "mods": "*",
                "base_path": "/tutorial",
            },
        )
        store = f"instance:{record.instance_id}"

        listed = self.client.get("/api/mission-control/vibes").json()
        world_rows = [row for row in listed["rows"] if row["store"] == store]
        self.assertEqual(len(world_rows), 1)
        self.assertEqual(world_rows[0]["value"], 10)
        self.assertIn(store, [entry["id"] for entry in listed["stores"]])

        updated = self.client.patch(
            "/api/mission-control/vibes",
            headers=self.csrf_headers(),
            json={
                "store": store,
                "world_id": "tutorial",
                "source_peep_id": "barkeep",
                "target_peep_id": "regular",
                "value": -20,
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(_world_vibes(world_db), [("tutorial", "barkeep", "regular", -20)])

        deleted = self.client.request(
            "DELETE",
            "/api/mission-control/vibes",
            headers=self.csrf_headers(),
            params={
                "store": store,
                "world_id": "tutorial",
                "source_peep_id": "barkeep",
                "target_peep_id": "regular",
            },
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(_world_vibes(world_db), [])


if __name__ == "__main__":
    unittest.main()
