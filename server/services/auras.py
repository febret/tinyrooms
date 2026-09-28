"""Room auras: source-scoped modifiers plus optional one-shot buffs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time as datetime_time, timedelta

from server.content.worlds import AuraDefinition, WorldDefinition
from server.game.buffs import BuffInstance, DAILY, TIMED
from server.game.modifiers import Modifier
from server.security import utc_now
from server.services.stats import StatsService
from server.state.migrations import DatabaseHub


class AuraService:
    """Applies a room's aura while present and removes it immediately on leave.

    An aura entry may also declare a named ``source``; while present, that source
    is active and any status keyed to it (for example the ``scared`` status) is
    applied. An entry may be gated by ``requires_prop``: when that prop is not
    visible (hidden or, for a dark room, unlit) the whole aura is suppressed.
    """

    def __init__(
        self,
        hub: DatabaseHub,
        stats: StatsService,
        world: WorldDefinition,
        environment: object | None = None,
    ) -> None:
        self._hub = hub
        self._stats = stats
        self._world = world
        self._environment = environment
        self._applied: set[tuple[str, str]] = set()

    @staticmethod
    def source_for(room_id: str) -> str:
        """Return the source key used for a room's stat-aura contribution."""

        return f"aura:{room_id}"

    def _available(self, room_id: str, aura: Sequence[AuraDefinition]) -> bool:
        """Return whether every prop-gated aura entry is currently visible."""

        if self._environment is None:
            return True
        room = self._world.rooms.get(room_id)
        for entry in aura:
            if entry.requires_prop is None:
                continue
            if not self._environment.is_prop_visible(room_id, entry.requires_prop):
                return False
            if room is not None:
                instance = room.props.get(entry.requires_prop)
                definition = self._world.props.get(instance.prop_id) if instance is not None else None
                if (
                    definition is not None
                    and definition.requires_light
                    and self._environment.lighting(room_id) == "dark"
                ):
                    return False
        return True

    def enter(self, account_id: str, room_id: str) -> None:
        """Apply the room aura idempotently, skipping when already present."""

        room = self._world.rooms.get(room_id)
        if room is None or not room.aura:
            return
        if not self._available(room_id, room.aura):
            self.leave(account_id, room_id)
            return
        source = self.source_for(room_id)
        modifiers = tuple(
            Modifier(target=entry.stat, flat=entry.delta)
            for entry in room.aura
            if entry.stat is not None
        )
        if modifiers and (account_id, source) not in self._applied:
            self._applied.add((account_id, source))
            self._stats.apply_source(account_id, source, modifiers)
        for entry in room.aura:
            if entry.source is not None and (account_id, entry.source) not in self._applied:
                self._applied.add((account_id, entry.source))
                self._stats.apply_source(account_id, entry.source, ())
            if entry.buff_id is None:
                continue
            self._stats.add_buff(account_id, self._buff_instance(entry))

    def leave(self, account_id: str, room_id: str) -> None:
        """Remove a room's aura contributions without touching timed buffs."""

        room = self._world.rooms.get(room_id)
        keys = {self.source_for(room_id)}
        if room is not None:
            keys.update(entry.source for entry in room.aura if entry.source is not None)
        for key in keys:
            if (account_id, key) not in self._applied:
                continue
            self._applied.discard((account_id, key))
            self._stats.remove_source(account_id, key)

    @staticmethod
    def _buff_instance(entry: AuraDefinition) -> BuffInstance:
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
