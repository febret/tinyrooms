"""Directed relationship scores between peeps and their periodic room rules."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
import sqlite3
from typing import TYPE_CHECKING

from server.commands.outcomes import PendingRoomBroadcast
from server.content.worlds import WorldDefinition
from server.gameplay_options import DEFAULT_GAMEPLAY_OPTIONS, GameplayOptions
from server.security import utc_now
from server.services.stats import StatsService
from server.state.migrations import DatabaseHub
from server.state.npc_peep_states import NpcPeepStateRepository
from server.state.vibes import GLOBAL_WORLD_ID, VibesRepository

if TYPE_CHECKING:
    from server.services.dynamic_cards import DynamicCardDrops


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
        options: GameplayOptions = DEFAULT_GAMEPLAY_OPTIONS,
    ) -> None:
        self._hub = hub
        self._world = world
        self._stats = stats
        self._peep_states = peep_states
        self._connections = connections
        self._card_drops = card_drops
        self._options = options
        self._repo = VibesRepository(hub)
        self._repo.globalize_world_rows()
        self._last_room_update: dict[str, datetime] = {}

    @property
    def world_id(self) -> str:
        """Return the active world id used to scope score rows."""

        return self._world.id

    def _is_world_peep(self, peep_id: str) -> bool:
        return peep_id in self._world.peeps

    def global_id(self, peep_id: str) -> str:
        """Return the cross-world id: ``"<world>:<peep>"`` for current-world peeps."""

        if self._is_world_peep(peep_id):
            return f"{self.world_id}:{peep_id}"
        return peep_id

    def _local_id(self, global_id: str) -> str:
        prefix = f"{self.world_id}:"
        if global_id.startswith(prefix) and self._is_world_peep(global_id[len(prefix):]):
            return global_id[len(prefix):]
        return global_id

    def _scope(self, source_peep_id: str, target_peep_id: str) -> str:
        if self._is_world_peep(source_peep_id) and self._is_world_peep(target_peep_id):
            return self.world_id
        return GLOBAL_WORLD_ID

    def _storage_key(self, source_peep_id: str, target_peep_id: str) -> tuple[str, str, str]:
        scope = self._scope(source_peep_id, target_peep_id)
        if scope:
            return scope, source_peep_id, target_peep_id
        return scope, self.global_id(source_peep_id), self.global_id(target_peep_id)

    def get(self, source_peep_id: str, target_peep_id: str) -> int:
        """Return a directed score, defaulting to zero."""

        if not source_peep_id or not target_peep_id or source_peep_id == target_peep_id:
            return 0
        return self._repo.get(*self._storage_key(source_peep_id, target_peep_id))

    def get_global(self, source_id: str, target_id: str) -> int:
        """Return a global-row score for already-global ids, defaulting to zero."""

        if not source_id or not target_id or source_id == target_id:
            return 0
        return self._repo.get(GLOBAL_WORLD_ID, source_id, target_id)

    def outgoing(self, source_peep_id: str) -> dict[str, int]:
        """Return every target score for one source peep, keyed by local ids."""

        result: dict[str, int] = {}
        if self._is_world_peep(source_peep_id):
            result.update(self._repo.outgoing(self.world_id, source_peep_id))
        for target, value in self._repo.outgoing(
            GLOBAL_WORLD_ID, self.global_id(source_peep_id)
        ).items():
            result[self._local_id(target)] = value
        return result

    def _incoming(self, target_peep_id: str) -> dict[str, int]:
        result: dict[str, int] = {}
        if self._is_world_peep(target_peep_id):
            result.update(self._repo.incoming(self.world_id, target_peep_id))
        for source, value in self._repo.incoming(
            GLOBAL_WORLD_ID, self.global_id(target_peep_id)
        ).items():
            result[self._local_id(source)] = value
        return result

    def pairs_for(self, viewer_id: str, target_ids: Iterable[str]) -> dict[str, dict[str, object]]:
        """Return both directions of the viewer's score for each target."""

        targets = [target for target in dict.fromkeys(target_ids) if target and target != viewer_id]
        if not targets:
            return {}
        toward = self.outgoing(viewer_id)
        incoming = self._incoming(viewer_id)
        result: dict[str, dict[str, object]] = {}
        for target in targets:
            result[target] = self.pair_payload(
                int(toward.get(target, 0)), int(incoming.get(target, 0))
            )
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

        local_keys: dict[tuple[str, str, str], tuple[str, str]] = {}
        entries: list[tuple[str, str, str, int]] = []
        for source, target, delta in deltas:
            if not source or not target or source == target:
                continue
            key = self._storage_key(source, target)
            local_keys[key] = (source, target)
            entries.append((*key, int(delta)))
        updated = self._repo.adjust_many_in_transaction(connection, entries)
        return {local_keys[key]: value for key, value in updated.items()}

    def adjust_global_many_in_transaction(
        self,
        connection: sqlite3.Connection,
        deltas: Iterable[tuple[str, str, int]],
    ) -> dict[tuple[str, str], int]:
        """Apply deltas to global rows using already-global ids."""

        updated = self._repo.adjust_many_in_transaction(
            connection,
            ((GLOBAL_WORLD_ID, source, target, int(delta)) for source, target, delta in deltas),
        )
        return {(source, target): value for (_, source, target), value in updated.items()}

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
        if previous is not None and moment - previous < timedelta(
            seconds=self._options.constants.vibe_check_seconds
        ):
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
            statuses_by_account = {
                account_id: set(views[account_id].statuses)
                for account_id in stinky_users
                if views.get(account_id) is not None
            }
            drop_broadcasts = self._card_drops.maybe_drop(
                room_id,
                stinky_users,
                now=moment,
                statuses_by_account=statuses_by_account,
            )

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
            base = self._options.constants.charisma_vibe_base
            charisma = int(view.effective.stats.get("charisma", base))
            delta = charisma - base
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
                    deltas[key] = deltas.get(key, 0) + self._options.constants.stinky_vibe_delta

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
