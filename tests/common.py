"""Shared fixtures for the test suite."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from server.content.cards import load_card_catalog
from server.content.gameplay import load_gameplay_content
from server.profiles import AccountRecord, ProfileRepository
from server.security import utc_now
from server.state.migrations import DatabaseHub, ensure_profile_database, ensure_world_database

REPO_ROOT = Path(__file__).resolve().parents[1]
WORLD_ID = "tutorial"
ENTRY_ROOM = "hub"


def repo_mods():
    """Discover the checked-in mods used by the tutorial world."""

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


def load_test_world(world_path: Path, card_ids: set[str] | None = None):
    """Load a world definition with core + mod activities and props applied."""

    from server.config import KNOWN_FEATURES
    from server.content.worlds import load_world_definition

    if card_ids is None:
        catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", world_path)
        card_ids = set(catalog.cards)
    return load_world_definition(
        world_path,
        card_ids,
        core_activities=load_world_activities(),
        known_features=KNOWN_FEATURES,
        propsets_root=load_world_propsets(),
        mod_props=load_world_mod_props(),
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
