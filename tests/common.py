"""Shared fixtures for the test suite."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from server.app import create_app
from server.content.cards import cutscene_card_references, load_card_catalog
from server.content.gameplay import load_gameplay_content
from server.config import load_config
from server.profiles import AccountRecord, ProfileRepository
from server.security import utc_now
from server.state.migrations import DatabaseHub, ensure_profile_database, ensure_world_database

REPO_ROOT = Path(__file__).resolve().parents[1]
WORLD_ID = "tutorial"
ENTRY_ROOM = "hub"
TEST_ORIGIN = "https://testserver:5000"
TEST_PASSWORD = "password123!"


def auth_headers(csrf_token: str) -> dict[str, str]:
    """Build authenticated request headers."""

    return {"origin": TEST_ORIGIN, "x-csrf-token": csrf_token}


def auth_cookies(session_token: str, csrf_token: str) -> dict[str, str]:
    """Build authenticated request cookies."""

    return {"tr_session": session_token, "tr_csrf": csrf_token}


def websocket_headers(session_token: str, csrf_token: str) -> dict[str, str]:
    """Build authenticated WebSocket headers."""

    return {
        "cookie": f"tr_session={session_token}; tr_csrf={csrf_token}",
        "origin": TEST_ORIGIN,
    }


def repo_mods():
    """Discover the checked-in mods used by the test worlds."""

    from server.mods import discover_mods

    return discover_mods(REPO_ROOT / "mods")


def load_world_activities():
    """Merge the core and mod activity catalogs for world loading."""

    from server.config import KNOWN_FEATURES
    from server.content.activities import load_activity_definitions
    from server.mods import load_mod_activity_definitions

    core = load_activity_definitions(
        REPO_ROOT / "data" / "core" / "activities.yaml",
        source="core",
        known_features=KNOWN_FEATURES,
    )
    mod_activities = load_mod_activity_definitions(repo_mods().values(), known_features=KNOWN_FEATURES)
    return {**core, **mod_activities}


def load_world_cutscenes():
    """Merge the core and mod cutscene catalogs for world loading."""

    from server.config import KNOWN_FEATURES
    from server.content.cutscenes import load_cutscene_definitions, merge_cutscene_definitions
    from server.mods import load_mod_cutscene_definitions

    core = load_cutscene_definitions(
        REPO_ROOT / "data" / "core" / "cutscenes.yaml",
        source="core",
        script_roots=(REPO_ROOT / "data" / "cutscenes",),
        known_features=KNOWN_FEATURES,
    )
    mod_cutscenes = load_mod_cutscene_definitions(repo_mods().values(), known_features=KNOWN_FEATURES)
    return merge_cutscene_definitions(core, mod_cutscenes)


def load_world_cutscene_roots():
    """Return the mod cutscene script roots for world loading."""

    return tuple(mod.cutscenes_path for mod in repo_mods().values() if mod.cutscenes_path.is_dir())


def load_world_propsets():
    """Return the core propset roots for world loading."""

    return (REPO_ROOT / "data" / "propsets",)


def load_world_mod_props():
    """Return the ``(mod_id, props_dir)`` pairs for world loading."""

    return tuple(
        (mod.id, mod.props_path)
        for mod in repo_mods().values()
        if (mod.props_path / "props.yaml").is_file()
    )


def load_world_fx():
    """Return the core prop-effect definitions, shared across test worlds."""

    from server.content.fx import load_effect_catalog

    return load_effect_catalog(REPO_ROOT / "data" / "fx")


def load_test_world(world_path: Path, card_ids: set[str] | None = None):
    """Load a world definition with core + mod activities and props applied."""

    from server.config import KNOWN_FEATURES
    from server.content.worlds import load_world_definition

    catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", world_path)
    if card_ids is None:
        card_ids = set(catalog.cards)
    return load_world_definition(
        world_path,
        card_ids,
        core_activities=load_world_activities(),
        core_cutscenes=load_world_cutscenes(),
        cutscene_cards=cutscene_card_references(catalog),
        cutscene_roots=load_world_cutscene_roots(),
        known_features=KNOWN_FEATURES,
        propsets_root=load_world_propsets(),
        mod_props=load_world_mod_props(),
        fx_root=REPO_ROOT / "data" / "fx",
        extra_recipes=catalog.recipes,
    )


class ServiceTestCase(unittest.TestCase):
    """Provide isolated profile/world databases and shared content for service tests."""

    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
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

    def create_account(self, username: str, *, room: str = ENTRY_ROOM) -> AccountRecord:
        """Create a ready test account in the active world."""

        return self.profiles.create_account(username, "password123!", WORLD_ID, room)

    def reload_account(self, account: AccountRecord) -> AccountRecord:
        """Re-read an account from the database."""

        return self.profiles.get_account_by_id(account.id)

    def set_progress(
        self,
        account: AccountRecord,
        *,
        level: int | None = None,
        kudos: int | None = None,
        bops: int | None = None,
    ) -> AccountRecord:
        """Persist selected account progression fields in one transaction."""

        with self.hub.transaction() as connection:
            return self.profiles.update_progress(connection, account, level=level, kudos=kudos, bops=bops)

    def set_energy(self, account: AccountRecord, energy: float, *, minutes_ago: float = 0.0) -> AccountRecord:
        """Set current Energy and age the recharge clock by whole minutes."""

        with self.hub.transaction() as connection:
            return self.profiles.update_progress(
                connection,
                account,
                energy=energy,
                last_energy_at=(utc_now() - timedelta(minutes=minutes_ago)).isoformat(),
            )

    def grant_card(self, account: AccountRecord, card_id: str, quantity: int = 1, *, scope: str = "world") -> str:
        """Add cards to an account, merging into existing stacks, and return the first stack id."""

        definition = self.catalog.cards[card_id]
        with self.hub.transaction() as connection:
            stacks = self.profiles.add_inventory_card(
                connection,
                account_id=account.id,
                world_id=WORLD_ID if scope == "world" else None,
                card_def_id=card_id,
                quantity=quantity,
                scope=scope,
                stack_limit=definition.stack_limit,
            )
        return stacks[0].stack_id

    def create_stack(self, account: AccountRecord, card_id: str, quantity: int = 1, *, scope: str = "world"):
        """Insert a brand-new inventory stack without merging."""

        with self.hub.transaction() as connection:
            return self.profiles.create_inventory_stack(
                connection,
                account_id=account.id,
                world_id=WORLD_ID if scope == "world" else None,
                card_def_id=card_id,
                quantity=quantity,
                scope=scope,
            )


class RuntimeTestCase(unittest.TestCase):
    """Provide an isolated app, profile directory, and world-state database."""

    features = "dev_sample_activity"
    mods = "classrooms"
    world_path: Path | None = None

    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.runtime_path = Path(self.temporary_directory.name)
        self.config = load_config(
            env={
                "TRSERVER_NEW_ACCOUNT_PASSPHRASE": "open-sesame",
                "TRSERVER_USERS_PATH": str(self.runtime_path / "users"),
                "TRSERVER_WORLD_PATH": str(self.world_path or (REPO_ROOT / "worlds" / "tutorial")),
                "TRSERVER_WORLDSTATE_PATH": str(self.runtime_path / "worldstate.sqlite3"),
                "TRSERVER_FEATURES": self.features,
                "TRSERVER_MODS": self.mods,
                "TRSERVER_TIMEZONE": "UTC",
                "TRSERVER_HOST": "testserver",
                "TRSERVER_PORT": "5000",
            },
            repo_root=REPO_ROOT,
        )
        self.config = replace(
            self.config,
            local_path=self.runtime_path,
            drafts_path=self.runtime_path / "drafts",
            revisions_path=self.runtime_path / "revisions",
        )
        self._open_client()

    def tearDown(self) -> None:
        self._close_client()
        self.temporary_directory.cleanup()

    def _open_client(self) -> None:
        self.app = create_app(self.config)
        self.client_context = TestClient(self.app, base_url=TEST_ORIGIN)
        self.client = self.client_context.__enter__()

    def _close_client(self) -> None:
        if hasattr(self, "client_context"):
            self.client_context.__exit__(None, None, None)
            del self.client_context

    def restart(self) -> None:
        """Restart the application while retaining disposable databases."""

        self._close_client()
        self._open_client()

    def create_account(
        self,
        username: str,
        password: str = TEST_PASSWORD,
    ) -> dict[str, str]:
        """Create an account and return its session credentials."""

        response = self.client.post(
            "/api/auth/create",
            json={
                "username": username,
                "password": password,
                "passphrase": "open-sesame",
            },
            headers={"origin": TEST_ORIGIN},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {
            "session_token": response.cookies["tr_session"],
            "csrf_token": response.cookies["tr_csrf"],
        }

    def create_ready_account(self, username: str) -> dict[str, str]:
        """Create an account and confirm its initial sticker."""

        credentials = self.create_account(username)
        self.confirm_sticker(credentials)
        return credentials

    def confirm_sticker(
        self,
        credentials: dict[str, str],
        sticker: str = "s1.png",
    ) -> dict[str, object]:
        """Confirm an initial sticker for an account."""

        response = self.client.post(
            "/api/stickers/confirm",
            json={"sticker": sticker},
            headers=auth_headers(credentials["csrf_token"]),
            cookies=auth_cookies(
                credentials["session_token"],
                credentials["csrf_token"],
            ),
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def command(
        self,
        socket,
        request_id: str,
        command: str,
    ) -> dict[str, object]:
        """Send a command and return its private result."""

        socket.send_json(
            {
                "v": 1,
                "type": "command",
                "request_id": request_id,
                "command": command,
            }
        )
        result = socket.receive_json()
        self.assertEqual(result["type"], "result")
        self.assertEqual(result["request_id"], request_id)
        return result


class IntegrationTestCase(RuntimeTestCase):
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
