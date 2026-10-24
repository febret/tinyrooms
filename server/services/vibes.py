"""Directed relationship scores between peeps and their periodic room rules."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
import sqlite3
from typing import TYPE_CHECKING

from server.commands.outcomes import PendingRoomBroadcast
from server.content.worlds import WorldDefinition
from server.security import utc_now
from server.services.stats import StatsService
from server.state.migrations import DatabaseHub
from server.state.npc_peep_states import NpcPeepStateRepository
from server.state.vibes import VibesRepository

if TYPE_CHECKING:
    from server.services.dynamic_cards import DynamicCardDrops


PERIODIC_SECONDS = 60
STINKY_VIBE_DELTA = -1
CHARISMA_VIBE_BASE = 1

VIBE_BANDS: tuple[tuple[int, int, str], ...] = (
    (76, 100, "Supreme BFF 😍"),
    (51, 75, "BFF 🥰"),
    (26, 50, "Buddy 😃"),
    (1, 25, "Friend 🙂"),
    (-25, -1, "Annoyance 🙄"),
    (-50, -26, "Enemy 😤"),
    (-75, -51, "Nemesis 😡"),
    (-100, -76, "Archnemesis 👿"),
)


def describe_vibe(value: int) -> str:
    """Return the player-facing descriptor for a vibe score."""

    score = int(value)
    if score == 0:
        return "Neutral 😐"
    for low, high, label in VIBE_BANDS:
        if low <= score <= high:
            return label
    return "Neutral 😐"


class VibesService:
    """Owns vibe persistence, pair views, and the shared room timer rules."""

    def __init__(
        self,
        *,
        hub: DatabaseHub,
        world: WorldDefinition,
        stats: StatsService,
        peep_states: NpcPeepStateRepository | None = None,
        connections: object | None = None,
        card_drops: DynamicCardDrops | None = None,
    ) -> None:
        self._hub = hub
        self._world = world
        self._stats = stats
        self._peep_states = peep_states
        self._connections = connections
        self._card_drops = card_drops
        self._repo = VibesRepository(hub)
        self._last_room_update: dict[str, datetime] = {}

    @property
    def world_id(self) -> str:
        """Return the active world id used to scope score rows."""

        return self._world.id

    def _is_world_peep(self, peep_id: str) -> bool:
        return peep_id in self._world.peeps

    def get(self, source_peep_id: str, target_peep_id: str) -> int:
        """Return a directed score, defaulting to zero."""

        if not source_peep_id or not target_peep_id or source_peep_id == target_peep_id:
            return 0
        return self._repo.get(
            self.world_id,
            source_peep_id,
            target_peep_id,
            world_source=self._is_world_peep(source_peep_id),
        )

    def outgoing(self, source_peep_id: str) -> dict[str, int]:
        """Return every target score for one source peep."""

        return self._repo.outgoing(
            self.world_id,
            source_peep_id,
            world_source=self._is_world_peep(source_peep_id),
        )

    def pairs_for(self, viewer_id: str, target_ids: Iterable[str]) -> dict[str, dict[str, object]]:
        """Return both directions of the viewer's score for each target."""

        targets = [target for target in dict.fromkeys(target_ids) if target and target != viewer_id]
        if not targets:
            return {}
        toward = self.outgoing(viewer_id)
        from_world = self._repo.incoming(self.world_id, viewer_id, world_source=True)
        from_profile = self._repo.incoming(self.world_id, viewer_id, world_source=False)
        result: dict[str, dict[str, object]] = {}
        for target in targets:
            outgoing_value = int(toward.get(target, 0))
            incoming_value = int(from_world.get(target, from_profile.get(target, 0)))
            result[target] = self.pair_payload(outgoing_value, incoming_value)
        return result

    @staticmethod
    def pair_payload(toward: int, source: int) -> dict[str, object]:
        """Serialize both directions of a pair for the client."""

        return {
            "toward": {"value": int(toward), "label": describe_vibe(toward)},
            "from": {"value": int(source), "label": describe_vibe(source)},
        }

    def adjust(self, source_peep_id: str, target_peep_id: str, delta: int) -> int:
        """Apply one delta in a new transaction."""

        if not source_peep_id or not target_peep_id or source_peep_id == target_peep_id:
            return 0
        with self._hub.transaction() as connection:
            return self.adjust_in_transaction(
                connection, source_peep_id, target_peep_id, delta
            )

    def adjust_in_transaction(
        self,
        connection: sqlite3.Connection,
        source_peep_id: str,
        target_peep_id: str,
        delta: int,
    ) -> int:
        """Apply one delta inside a caller-owned transaction."""

        if not source_peep_id or not target_peep_id or source_peep_id == target_peep_id or int(delta) == 0:
            return self.get(source_peep_id, target_peep_id)
        values = self.adjust_many_in_transaction(
            connection, ((source_peep_id, target_peep_id, int(delta)),)
        )
        return values.get((source_peep_id, target_peep_id), self.get(source_peep_id, target_peep_id))

    def adjust_many(self, deltas: Iterable[tuple[str, str, int]]) -> dict[tuple[str, str], int]:
        """Apply grouped deltas in one new transaction."""

        with self._hub.transaction() as connection:
            return self.adjust_many_in_transaction(connection, deltas)

    def adjust_many_in_transaction(
        self,
        connection: sqlite3.Connection,
        deltas: Iterable[tuple[str, str, int]],
    ) -> dict[tuple[str, str], int]:
        """Apply grouped deltas inside a caller-owned transaction."""

        entries = [
            (source, target, int(delta), self._is_world_peep(source))
            for source, target, delta in deltas
        ]
        return self._repo.adjust_many_in_transaction(connection, self.world_id, entries)

    def update_room(
        self,
        room_id: str,
        user_ids: Iterable[str],
        *,
        now: datetime | None = None,
    ) -> list[PendingRoomBroadcast]:
        """Apply the minute-based stinky and charisma rules for one room.

        Stinky occupants may also drop personalized dynamic cards through the
        optional card-drop collaborator; drops work even for a solo peep with
        no vibe pairs to update.
        """

        moment = now or utc_now()
        previous = self._last_room_update.get(room_id)
        if previous is not None and moment - previous < timedelta(seconds=PERIODIC_SECONDS):
            return []

        users = [str(account_id) for account_id in dict.fromkeys(user_ids) if str(account_id)]
        npc_ids: list[str] = []
        if self._peep_states is not None:
            npc_ids = sorted(
                peep_id
                for peep_id in self._peep_states.peep_ids_in(room_id)
                if peep_id in self._world.peeps
                and self._peep_states.room_for(peep_id) == room_id
            )
        peeps = [*users, *npc_ids]
        views = self._stats.views(users) if users else {}

        stinky_users = [
            account_id
            for account_id in users
            if views.get(account_id) is not None and "stinky" in views[account_id].statuses
        ]
        drop_broadcasts: list[PendingRoomBroadcast] = []
        if self._card_drops is not None and stinky_users:
            drop_broadcasts = self._card_drops.maybe_drop(room_id, stinky_users, now=moment)

        if len(peeps) < 2:
            if not drop_broadcasts:
                return []
            return [
                *drop_broadcasts,
                PendingRoomBroadcast(
                    room_id=room_id,
                    event={"type": "room.refresh", "room_id": room_id},
                ),
            ]
        self._last_room_update[room_id] = moment

        deltas: dict[tuple[str, str], int] = {}

        for target_id in users:
            view = views.get(target_id)
            if view is None:
                continue
            charisma = int(view.effective.stats.get("charisma", CHARISMA_VIBE_BASE))
            delta = charisma - CHARISMA_VIBE_BASE
            if delta:
                for source_id in peeps:
                    if source_id != target_id:
                        key = (source_id, target_id)
                        deltas[key] = deltas.get(key, 0) + delta

        for target_id in peeps:
            view = views.get(target_id)
            if view is None or "stinky" not in view.statuses:
                continue
            for source_id in peeps:
                if source_id != target_id:
                    key = (source_id, target_id)
                    deltas[key] = deltas.get(key, 0) + STINKY_VIBE_DELTA

        updated: dict[tuple[str, str], int] = {}
        if deltas:
            updated = self.adjust_many(
                (source, target, delta) for (source, target), delta in deltas.items()
            )
        if not updated and not drop_broadcasts:
            return []
        return [
            *drop_broadcasts,
            PendingRoomBroadcast(
                room_id=room_id,
                event={"type": "room.refresh", "room_id": room_id},
            ),
        ]

    async def on_room_tick(self, room_id: str) -> list[PendingRoomBroadcast]:
        """Tick hook entry point for rooms with live players."""

        if self._connections is None:
            return []
        occupants = await self._connections.list_room(room_id)
        user_ids = [
            str(getattr(occupant, "account_id", ""))
            for occupant in occupants
            if getattr(occupant, "account_id", None)
        ]
        return self.update_room(room_id, user_ids)
