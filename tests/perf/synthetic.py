"""Builders for synthetic, scaled worlds used by the performance suite.

The world generator itself lives in ``tools/perf_world.py`` so the disposable
browser-test runtime can share it. This module adds the service-graph wiring
that the in-process benchmarks drive directly.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, Iterator

from server.connections import ConnectionRegistry
from server.content.cards import load_card_catalog
from server.content.gameplay import load_gameplay_content
from server.profiles import ProfileRepository
from server.services.activities import ActivityService
from server.services.cards import CardService
from server.services.environment import EnvironmentService
from server.services.room_effects import RoomEffectService
from server.services.rooms import RoomService
from server.services.stats import StatsService
from server.state.migrations import DatabaseHub, ensure_profile_database, ensure_world_database
from server.state.world_state import WorldStateRepository
from tests.common import REPO_ROOT, WORLD_ID, load_test_world
from tools.perf_world import ENTRY_ROOM, card_pool, build_scaled_world

__all__ = [
    "ENTRY_ROOM",
    "SyntheticRuntime",
    "build_scaled_world",
    "card_pool",
    "entity_counts",
    "make_hub",
    "temp_world",
]


def make_hub(root: Path) -> DatabaseHub:
    """Create a fresh profile + world database pair under *root*."""

    profile_path = root / "profiles.sqlite3"
    world_path = root / "worldstate.sqlite3"
    ensure_profile_database(profile_path)
    ensure_world_database(world_path)
    return DatabaseHub(profile_path, world_path)


@contextmanager
def temp_world(**scale: Any) -> Iterator[tuple[Path, "SyntheticRuntime", DatabaseHub]]:
    """Yield ``(root, runtime, hub)`` for a scaled world, closing the database first.

    Windows refuses to delete a directory that still holds an open SQLite file,
    so the hub has to be closed before the temporary directory is removed. Doing
    that in one place keeps every caller honest.
    """

    holder = TemporaryDirectory()
    root = Path(holder.name)
    try:
        world_path = build_scaled_world(root, **scale)
        runtime = SyntheticRuntime(world_path)
        hub = make_hub(root)
        try:
            yield root, runtime, hub
        finally:
            hub.close()
    finally:
        holder.cleanup()


class SyntheticRuntime:
    """A loaded world plus the service graph that serves it."""

    def __init__(self, world_path: Path) -> None:
        self.world_path = world_path
        self.catalog = load_card_catalog(REPO_ROOT / "data" / "cardsets", world_path)
        self.world = load_test_world(world_path, set(self.catalog.cards))
        self.content = load_gameplay_content(REPO_ROOT / "data" / "core")
        self.connections = ConnectionRegistry()
        self.rooms: RoomService | None = None
        self.hub: DatabaseHub | None = None

    def bind(self, hub: DatabaseHub) -> RoomService:
        """Create repositories over *hub*, seed the world, and wire a RoomService."""

        profiles = ProfileRepository(hub)
        world_state = WorldStateRepository(hub)
        world_state.initialize_world(self.world)
        self.hub = hub
        self.profiles = profiles
        self.world_state = world_state
        self.cards = CardService(hub, profiles, world_state, self.catalog, WORLD_ID, {})
        self.stats = StatsService(hub, profiles, self.catalog, self.content, WORLD_ID)
        self.environment = EnvironmentService(hub, self.world, world_state)
        self.room_effects = RoomEffectService()
        self.rooms = RoomService(
            hub=hub,
            profiles=profiles,
            world_state=world_state,
            connections=self.connections,
            card_service=self.cards,
            activities=ActivityService(SimpleNamespace(features=frozenset())),
            world=self.world,
            stats=self.stats,
            environment=self.environment,
            room_effects=self.room_effects,
        )
        return self.rooms

    def create_account(self, username: str, *, room: str = ENTRY_ROOM):
        """Create a ready account in the bound profile database."""

        return self.profiles.create_account(username, "password123!", WORLD_ID, room)


def entity_counts(snapshot: dict[str, Any]) -> dict[str, int]:
    """Summarise the entity counts a snapshot carries, for reporting."""

    return {
        "props": len(snapshot.get("props") or []),
        "npcs": len(snapshot.get("npcs") or []),
        "exits": len(snapshot.get("exits") or []),
        "room_cards": len(snapshot.get("room_cards") or []),
        "occupants": len(snapshot.get("occupants") or []),
        "inventory": len(snapshot.get("inventory") or []),
    }
