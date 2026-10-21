"""Cafeteria lunch rotation and shared-trait vibe updates."""

from __future__ import annotations

from datetime import datetime, timedelta
import random

from mods.classrooms.lesson_state import LessonStateRepository, StudentRecord
from mods.classrooms.lessons import OFFSTAGE_ROOM
from server.commands.outcomes import PendingRoomBroadcast
from server.content.worlds import WorldDefinition
from server.security import utc_now
from server.services.vibes import VibesService
from server.state.migrations import DatabaseHub
from server.state.npc_peep_states import NpcPeepStateRepository


CAFETERIA_ROOM_ID = "cafeteria"
LUNCH_GROUP_SIZE = 6
LUNCH_VISIT_SECONDS = 120
SHARED_TRAIT_SECONDS = 60
SHARED_TRAIT_DELTA = 1


class CafeteriaService:
    """Keeps a rotating group of students in the cafeteria and updates vibes."""

    def __init__(
        self,
        *,
        hub: DatabaseHub,
        world: WorldDefinition,
        peep_states: NpcPeepStateRepository,
        vibes: VibesService,
        repo: LessonStateRepository | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._hub = hub
        self._world = world
        self._peep_states = peep_states
        self._vibes = vibes
        self._repo = repo or LessonStateRepository(hub)
        self._random = rng or random
        self._lunch_group: tuple[str, ...] = ()
        self._lunch_expires_at: datetime | None = None
        self._last_trait_update: datetime | None = None

    def on_room_tick(self, room_id: str, *, now: datetime | None = None) -> list[PendingRoomBroadcast]:
        """Rotate lunch and refresh shared-trait vibes for the cafeteria."""

        moment = now or utc_now()
        if room_id != CAFETERIA_ROOM_ID or room_id not in self._world.rooms:
            return []
        students = {student.student_id: student for student in self._repo.all_students()}
        if not students:
            return []
        changed = self._rotate_lunch(room_id, students, moment)
        changed = self._update_shared_traits(room_id, students, moment) or changed
        if not changed:
            return []
        return [
            PendingRoomBroadcast(
                room_id=room_id,
                event={"type": "room.refresh", "room_id": room_id},
            )
        ]

    def _present_students(
        self,
        room_id: str,
        students: dict[str, StudentRecord],
    ) -> list[str]:
        return sorted(
            peep_id
            for peep_id in self._peep_states.peep_ids_in(room_id)
            if peep_id in students and peep_id in self._world.peeps
        )

    def _rotate_lunch(
        self,
        room_id: str,
        students: dict[str, StudentRecord],
        moment: datetime,
    ) -> bool:
        present = self._present_students(room_id, students)
        if not self._lunch_group:
            if present:
                self._lunch_group = tuple(present)
                self._lunch_expires_at = moment + timedelta(seconds=LUNCH_VISIT_SECONDS)
                return False
            return self._seat_group(room_id, students, moment, previous=())

        expiry = self._lunch_expires_at
        if expiry is not None and moment < expiry:
            return False
        previous = tuple(
            peep_id
            for peep_id in self._lunch_group
            if self._peep_states.room_for(peep_id) == room_id
        )
        self._move_students(previous, OFFSTAGE_ROOM)
        self._lunch_group = ()
        self._lunch_expires_at = None
        return self._seat_group(room_id, students, moment, previous=previous) or bool(previous)

    def _seat_group(
        self,
        room_id: str,
        students: dict[str, StudentRecord],
        moment: datetime,
        *,
        previous: tuple[str, ...],
    ) -> bool:
        candidates = [
            peep_id
            for peep_id in sorted(students)
            if peep_id in self._world.peeps
            and self._peep_states.room_for(peep_id) == OFFSTAGE_ROOM
            and peep_id not in previous
        ]
        if not candidates:
            candidates = [
                peep_id
                for peep_id in sorted(students)
                if peep_id in self._world.peeps
                and self._peep_states.room_for(peep_id) == OFFSTAGE_ROOM
            ]
        if not candidates:
            return False
        chosen = tuple(self._random.sample(candidates, k=min(LUNCH_GROUP_SIZE, len(candidates))))
        self._move_students(chosen, room_id)
        self._lunch_group = chosen
        self._lunch_expires_at = moment + timedelta(seconds=LUNCH_VISIT_SECONDS)
        return bool(chosen)

    def _move_students(self, peep_ids: tuple[str, ...], room_id: str) -> None:
        moving = [
            peep_id
            for peep_id in peep_ids
            if self._peep_states.room_for(peep_id) != room_id
        ]
        if not moving:
            return
        with self._hub.transaction() as connection:
            for peep_id in moving:
                self._peep_states.set_in_transaction(connection, peep_id, room_id)
        for peep_id in moving:
            self._peep_states.record(peep_id, room_id)

    def _update_shared_traits(
        self,
        room_id: str,
        students: dict[str, StudentRecord],
        moment: datetime,
    ) -> bool:
        previous = self._last_trait_update
        if previous is not None and moment - previous < timedelta(seconds=SHARED_TRAIT_SECONDS):
            return False
        self._last_trait_update = moment
        present = self._present_students(room_id, students)
        deltas: list[tuple[str, str, int]] = []
        for source_id in present:
            source_trait = students[source_id].trait
            if not source_trait:
                continue
            for target_id in present:
                if source_id == target_id:
                    continue
                if students[target_id].trait == source_trait:
                    deltas.append((source_id, target_id, SHARED_TRAIT_DELTA))
        if not deltas:
            return False
        self._vibes.adjust_many(deltas)
        return True
