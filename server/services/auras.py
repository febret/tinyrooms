"""Room auras: source-scoped modifiers plus optional one-shot buffs."""

from __future__ import annotations

from datetime import datetime, time as datetime_time, timedelta

from server.content.worlds import WorldDefinition
from server.game.buffs import BuffInstance, DAILY, TIMED
from server.game.modifiers import Modifier
from server.security import utc_now
from server.services.stats import StatsService
from server.state.migrations import DatabaseHub


class AuraService:
    """Applies a room's aura while present and removes it immediately on leave."""

    def __init__(self, hub: DatabaseHub, stats: StatsService, world: WorldDefinition) -> None:
        self._hub = hub
        self._stats = stats
        self._world = world

    @staticmethod
    def source_for(room_id: str) -> str:
        """Return the source key used for a room's aura contribution."""

        return f"aura:{room_id}"

    def enter(self, account_id: str, room_id: str) -> None:
        """Apply the room aura idempotently, skipping when already present."""

        room = self._world.rooms.get(room_id)
        if room is None or not room.aura:
            return
        source = self.source_for(room_id)
        if self._stats.has_source(account_id, source):
            return
        modifiers = tuple(
            Modifier(target=entry.stat, flat=entry.delta)
            for entry in room.aura
            if entry.stat is not None
        )
        if modifiers:
            self._stats.apply_source(account_id, source, modifiers)
        for entry in room.aura:
            if entry.buff_id is None:
                continue
            self._stats.add_buff(account_id, self._buff_instance(entry))

    def leave(self, account_id: str, room_id: str) -> None:
        """Remove a room's aura contribution without touching timed buffs."""

        if not self._stats.has_source(account_id, self.source_for(room_id)):
            return
        self._stats.remove_source(account_id, self.source_for(room_id))

    @staticmethod
    def _buff_instance(entry) -> BuffInstance:
        now = utc_now()
        if entry.daily:
            expires = datetime.combine((now + timedelta(days=1)).date(), datetime_time.min, tzinfo=now.tzinfo)
            kind = DAILY
        elif entry.duration_seconds is not None:
            expires = now + timedelta(seconds=float(entry.duration_seconds))
            kind = TIMED
        else:
            expires = now
            kind = TIMED
        return BuffInstance(id=str(entry.buff_id), label=str(entry.buff_id), kind=kind, expires_at=expires)
