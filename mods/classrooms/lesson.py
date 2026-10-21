"""Lesson engine for Scammon Academia classrooms.

Owns the generated student roster, materializes students as runtime peeps for a
live lesson, tracks Energy/attention through the shared student behavior script,
and grades the class test into a teacher GPA and Bops reward.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import random
import sqlite3

from mods.classrooms.lesson_state import QUARTER_AWARDS, LessonStateRepository, StudentRecord
from mods.classrooms.lessons import (
    GRADE_POINTS,
    OFFSTAGE_ROOM,
    SKILL_TAG_PREFIX,
    SUBJECT_IDS,
    SUBJECT_LABELS,
    SUBJECT_TAG_PREFIX,
    affinity,
    letter_grade,
    max_energy_for,
    starting_attention,
    starting_energy,
)
from mods.classrooms.roster import load_student_manifest, random_roster
from mods.classrooms.vibes import classroom_niceness_delta, grade_vibe_delta
from server.behaviors.events import BehaviorEvent, PeepRef
from server.commands.cutscenes import deliver, play_cutscene
from server.commands.outcomes import (
    CommandContext,
    CommandError,
    CommandOutcome,
    apply_behavior_inventory,
)
from server.commands.parser import ParsedCommand, parse_target
from server.content.worlds import PeepDefinition, QuickAction, RoomDefinition, WorldDefinition
from server.profiles import AccountRecord, ProfileRepository
from server.security import utc_now
from server.services.progression import ProgressionService
from server.state.migrations import DatabaseHub
from server.state.npc_peep_states import NpcPeepStateRepository
from server.state.world_state import PlayerRoomRecord, WorldStateRepository


CLASS_SIZE = 5
STUDENT_SCRIPT = "student.py"
BOPS_PER_GPA = 5

SESSION_ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class StudentTest:
    """One student's per-subject test result."""

    student: StudentRecord
    attention: float
    energy: float
    subjects: dict[str, str]

    @property
    def points(self) -> float:
        """Return the mean grade-point value across the student's subjects."""

        if not self.subjects:
            return 0.0
        return sum(GRADE_POINTS[letter] for letter in self.subjects.values()) / len(self.subjects)


@dataclass(frozen=True, slots=True)
class LessonTestResult:
    """Aggregate result of a lesson's test."""

    grade: int
    gpa: float
    bops: int
    results: tuple[StudentTest, ...]


class LessonService:
    """Generates students, runs lessons, and records teacher scores."""

    def __init__(
        self,
        *,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        world_state: WorldStateRepository,
        world: WorldDefinition,
        peep_states: NpcPeepStateRepository,
        behaviors: object,
        progression: ProgressionService,
        vibes: object | None = None,
        layout: object | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._world_state = world_state
        self._world = world
        self._peep_states = peep_states
        self._behaviors = behaviors
        self._progression = progression
        self._vibes = vibes
        self._layout = layout
        self._repo = LessonStateRepository(hub)
        self._student_script_path = world.root_path / "peeps" / STUDENT_SCRIPT

    # -- Setup ---------------------------------------------------------------

    def prepare(self) -> None:
        """Load the authored roster (or generate a fallback) and register peeps."""

        manifest = load_student_manifest(self._world.root_path)
        if manifest is not None:
            current = [student.to_payload() for student in self._repo.all_students()]
            wanted = [student.to_payload() for student in manifest]
            if current != wanted:
                self._repo.insert_students(manifest)
        elif not self._repo.has_roster():
            self._repo.insert_students(random_roster())
        for student in self._repo.all_students():
            self._register_student(student)
        self._peep_states.sync_world(self._world)

    def _register_student(self, student: StudentRecord) -> None:
        if student.student_id in self._world.peeps:
            return
        image_path = (self._world.root_path / "peeps" / student.avatar).resolve()
        self._world.peeps[student.student_id] = PeepDefinition(
            id=student.student_id,
            label=student.label,
            description=self._describe(student),
            room_id=OFFSTAGE_ROOM,
            image_name=student.avatar,
            image_path=image_path,
            script_name=STUDENT_SCRIPT,
            actions=(),
            dialog=None,
            activity=None,
        )
        register = getattr(self._behaviors, "register_peep", None)
        if register is not None and self._student_script_path.is_file():
            register(student.student_id, self._student_script_path)

    @staticmethod
    def _describe(student: StudentRecord) -> str:
        loves = " and ".join(SUBJECT_LABELS.get(subject, subject) for subject in student.favorites) or "school"
        tricky = SUBJECT_LABELS.get(student.tricky, student.tricky)
        return f"A Grade {student.grade} student. Loves {loves}. Finds {tricky} tricky."

    # -- Quick actions -------------------------------------------------------

    def room_quick_actions(self, account: AccountRecord, room: RoomDefinition) -> tuple[QuickAction, ...]:
        """Return lesson controls for the account's own classroom."""

        record = self._world_state.get_player_room(room.id)
        if record is None or record.owner_account_id != account.id:
            return ()
        session = self._repo.get_session(room.id)
        if session is not None and session.get("status") == SESSION_ACTIVE:
            return (
                QuickAction(label="Give Test", command=".classroom lesson test"),
                QuickAction(label="End Lesson", command=".classroom lesson cancel"),
            )
        return (QuickAction(label="Start Lesson", command=".classroom lesson start"),)

    # -- Lesson lifecycle ----------------------------------------------------

    def start_lesson(self, account: AccountRecord, room_id: str) -> tuple[StudentRecord, ...]:
        """Populate the owner's classroom with five students of its grade."""

        record = self._world_state.get_player_room(room_id)
        if record is None or record.owner_account_id != account.id:
            raise ValueError("You can only start a lesson in your own classroom.")
        session = self._repo.get_session(room_id)
        if session is not None and session.get("status") == SESSION_ACTIVE:
            raise ValueError("A lesson is already in progress.")
        grade = self._grade_of(record)
        roster = self._repo.roster_for_grade(grade)
        if not roster:
            raise ValueError("No students are enrolled in this grade.")
        chosen = random.sample(roster, k=min(CLASS_SIZE, len(roster)))
        session_payload = {
            "status": SESSION_ACTIVE,
            "grade": grade,
            "teacher_account_id": account.id,
            "student_ids": [student.student_id for student in chosen],
            "started_at": utc_now().isoformat(),
        }
        with self._hub.transaction() as connection:
            self._repo.save_session(connection, room_id, session_payload)
            for student in chosen:
                self._peep_states.set_in_transaction(connection, student.student_id, room_id)
                self._write_student_state(connection, student, room_id, account.id)
        for student in chosen:
            self._peep_states.record(student.student_id, room_id)
        return tuple(chosen)

    def has_active_lesson(self, room_id: str) -> bool:
        """Return whether a lesson is currently running in a room."""

        session = self._repo.get_session(room_id)
        return session is not None and session.get("status") == SESSION_ACTIVE

    def cancel_lesson(self, account: AccountRecord, room_id: str) -> None:
        """End a lesson without test scores."""

        session = self._require_active(account, room_id)
        self._end_session(session["student_ids"], room_id)

    def give_test(self, account: AccountRecord, room_id: str) -> LessonTestResult:
        """Grade the class, record the teacher's GPA, and reward Bops."""

        session = self._require_active(account, room_id)
        grade = int(session.get("grade", 1))
        student_ids = [str(value) for value in session.get("student_ids", []) if isinstance(value, str)]
        roster = {student.student_id: student for student in self._repo.all_students()}
        students = [roster[student_id] for student_id in student_ids if student_id in roster]

        results: list[StudentTest] = []
        taught_subjects: set[str] = set()
        states: dict[str, dict[str, object]] = {}
        for student in students:
            state = self._read_student_state(student.student_id)
            states[student.student_id] = state
            taught_subjects.update(item for item in state.get("topics", []) if isinstance(item, str))

        if not taught_subjects:
            raise ValueError("Teach at least one topic before giving the test.")

        subject_order = [subject for subject in SUBJECT_IDS if subject in taught_subjects]
        for student in students:
            state = states[student.student_id]
            attention = float(state.get("attention", starting_attention(student.trait)))
            energy = float(state.get("energy", starting_energy(student.trait)))
            energy_max = float(state.get("max_energy", max_energy_for(student.trait)))
            subjects = {
                subject: letter_grade(
                    attention=attention,
                    energy=energy,
                    max_energy=energy_max,
                    affinity=affinity(subject, student.favorites, student.tricky),
                )
                for subject in subject_order
            }
            results.append(StudentTest(student=student, attention=attention, energy=energy, subjects=subjects))

        total_points = sum(result.points for result in results)
        gpa = round(total_points / max(1, len(results)), 3)
        bops = max(1, int(round(gpa * BOPS_PER_GPA)))
        vibe_deltas = self._lesson_vibe_deltas(results, account.id, room_id)

        with self._hub.transaction() as connection:
            self._repo.record_score(
                connection,
                account_id=account.id,
                world_id=self._world.id,
                grade=grade,
                gpa=gpa,
                bops=bops,
                students=len(results),
            )
            self._progression.grant_in_transaction(
                connection,
                account.id,
                bops=bops,
                ledger_key=f"lesson:{room_id}:{session.get('started_at', '')}",
                kind="lesson",
            )
            if self._vibes is not None and vibe_deltas:
                self._vibes.adjust_many_in_transaction(connection, vibe_deltas)
            quarter_number, _lessons, quarter_ended = self._repo.bump_quarter(connection)
            if quarter_ended:
                scores = self._repo.read_scores(connection, self._world.id)
                ranked = self._repo.rank_scores(scores, limit=len(QUARTER_AWARDS))
                for index, entry in enumerate(ranked):
                    self._progression.grant_in_transaction(
                        connection,
                        str(entry["account_id"]),
                        bops=QUARTER_AWARDS[index],
                        ledger_key=f"quarter:{self._world.id}:{quarter_number}:{entry['account_id']}",
                        kind="lesson",
                    )
                self._repo.reset_scores(connection)
                self._repo.reset_quarter(connection)
            self._finish_session(connection, room_id, student_ids)
        self._end_session_peeps(student_ids, room_id)
        return LessonTestResult(grade=grade, gpa=gpa, bops=bops, results=tuple(results))

    def scoreboard(self, account: AccountRecord, *, limit: int = 5) -> list[dict[str, object]]:
        """Return the quarter's top teachers ranked by average GPA."""

        rows = self._repo.scoreboard(self._world.id, limit=limit)
        accounts = self._profiles.get_accounts_by_ids([str(row["account_id"]) for row in rows])
        board: list[dict[str, object]] = []
        for rank, row in enumerate(rows, start=1):
            account_record = accounts.get(str(row["account_id"]))
            board.append(
                {
                    "rank": rank,
                    "account_id": row["account_id"],
                    "username": account_record.username_display if account_record is not None else "A teacher",
                    "sticker": account_record.sticker if account_record is not None else None,
                    "average_gpa": row["average_gpa"],
                    "best_gpa": row["best_gpa"],
                    "lessons": row["lessons"],
                    "total_bops": row["total_bops"],
                    "is_you": str(row["account_id"]) == account.id,
                }
            )
        return board

    def personal_average(self, account: AccountRecord) -> float | None:
        """Return the account's average GPA in the current quarter."""

        return self._repo.teacher_average_gpa(account.id, self._world.id)

    def quarter(self) -> dict[str, int]:
        """Return the current quarter number and lesson progress."""

        return self._repo.quarter_state()

    # -- Internals -----------------------------------------------------------

    @staticmethod
    def _grade_of(record: PlayerRoomRecord) -> int:
        try:
            grade = int(record.door.get("grade", 1))
        except (TypeError, ValueError):
            grade = 1
        return min(max(grade, 1), 8)

    def _require_active(self, account: AccountRecord, room_id: str) -> dict[str, object]:
        record = self._world_state.get_player_room(room_id)
        if record is None or record.owner_account_id != account.id:
            raise ValueError("You can only run a lesson in your own classroom.")
        session = self._repo.get_session(room_id)
        if session is None or session.get("status") != SESSION_ACTIVE:
            raise ValueError("There is no lesson in progress.")
        return session

    def _initial_state(
        self,
        student: StudentRecord,
        room_id: str,
        teacher_account_id: str,
    ) -> dict[str, object]:
        return {
            "label": student.label,
            "teacher_account_id": teacher_account_id,
            "grade": student.grade,
            "favorites": list(student.favorites),
            "tricky": student.tricky,
            "trait": student.trait,
            "energy": starting_energy(student.trait),
            "max_energy": max_energy_for(student.trait),
            "attention": starting_attention(student.trait),
            "topics": [],
            "lesson_room": room_id,
        }

    def _write_student_state(
        self,
        connection: sqlite3.Connection,
        student: StudentRecord,
        room_id: str,
        teacher_account_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO world.behavior_state (namespace, instance_id, state_json, updated_at)
            VALUES ('peep', ?, ?, ?)
            ON CONFLICT(namespace, instance_id) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (
                student.student_id,
                json.dumps(self._initial_state(student, room_id, teacher_account_id)),
                utc_now().isoformat(),
            ),
        )

    def _lesson_vibe_deltas(
        self,
        results: list[StudentTest],
        teacher_account_id: str,
        room_id: str,
    ) -> list[tuple[str, str, int]]:
        niceness = classroom_niceness_delta(self._classroom_prop_ids(room_id))
        deltas: list[tuple[str, str, int]] = []
        for result in results:
            delta = grade_vibe_delta(result.points) + niceness
            if delta:
                deltas.append((result.student.student_id, teacher_account_id, delta))
        return deltas

    def _classroom_prop_ids(self, room_id: str) -> list[str]:
        if self._layout is None:
            return []
        prop_ids: list[str] = []
        for prop in self._layout.effective_props(room_id):
            definition = self._world.props.get(prop.prop_id)
            if definition is not None and definition.hidden:
                continue
            prop_ids.append(prop.prop_id)
        return prop_ids

    def _read_student_state(self, student_id: str) -> dict[str, object]:
        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT state_json FROM world.behavior_state WHERE namespace = 'peep' AND instance_id = ?",
                (student_id,),
            ).fetchone()
        if row is None:
            return {}
        try:
            payload = json.loads(str(row["state_json"]))
        except (TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _clear_student_states(self, connection: sqlite3.Connection, student_ids: list[str]) -> None:
        for student_id in student_ids:
            connection.execute(
                "DELETE FROM world.behavior_state WHERE namespace = 'peep' AND instance_id = ?",
                (student_id,),
            )

    def _finish_session(self, connection: sqlite3.Connection, room_id: str, student_ids: list[str]) -> None:
        """Clear student lesson state and the room session in one transaction."""

        self._clear_student_states(connection, student_ids)
        self._repo.clear_session(connection, room_id)

    def _end_session(self, student_ids: object, room_id: str) -> None:
        ids = [str(value) for value in student_ids] if isinstance(student_ids, list) else []
        with self._hub.transaction() as connection:
            self._finish_session(connection, room_id, ids)
        self._end_session_peeps(ids, room_id)

    def _end_session_peeps(self, student_ids: list[str], room_id: str) -> None:
        with self._hub.transaction() as connection:
            for student_id in student_ids:
                self._peep_states.set_in_transaction(connection, student_id, OFFSTAGE_ROOM)
        for student_id in student_ids:
            self._peep_states.record(student_id, OFFSTAGE_ROOM)


def _first_tag(definition: object, prefix: str) -> str | None:
    for tag in getattr(definition, "tags", ()) or ():
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return None


async def teach_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """Teach a topic item card to the class in the current room."""

    if not command.args or not command.args[0].startswith("@"):
        raise CommandError("Use '.teach @card:<stack_id>'.")
    target = parse_target(command.args[0])
    if target.kind != "card":
        raise CommandError("Use '.teach @card:<stack_id>'.")
    room_id = context.connection.room_id
    if room_id is None:
        raise CommandError("You are not currently in a room.")
    stack_id = target.value
    stack = context.profiles.get_inventory_stack(context.account.id, context.world.id, stack_id)
    if stack is None or not context.cards.has_definition(stack.card_def_id):
        raise CommandError("That card stack is not in your inventory.")
    definition = context.cards.definition(stack.card_def_id)
    if "topic" not in definition.tags:
        raise CommandError(f"{definition.label} is not a topic card.")
    skill_id = _first_tag(definition, SKILL_TAG_PREFIX)
    if skill_id is not None and not context.progression.has_slotted_skill(context.account, skill_id):
        subject = SUBJECT_LABELS.get(_first_tag(definition, SUBJECT_TAG_PREFIX) or "", "that subject")
        raise CommandError(f"Slot the {subject} skill before teaching it.")
    classroom = context.mods.get("classrooms")
    lessons = getattr(classroom, "lessons", None)
    if lessons is None or not lessons.has_active_lesson(room_id):
        raise CommandError("There is no class to teach right now.")
    cost = int(definition.energy_cost or 0)
    if cost:
        context.stats.charge(context.account, cost)
    behavior = await context.behaviors.dispatch(
        BehaviorEvent(
            type="card_play",
            actor=PeepRef(kind="user", peep_id=None, account_id=context.account.id),
            target=None,
            room_id=room_id,
            action="teach",
            data={"card_id": definition.id, "stack_id": stack_id},
        )
    )
    if behavior is None or not getattr(behavior, "acted", False):
        return CommandOutcome(message="There is no class to teach right now.", toast=True, log=False)
    outcome = CommandOutcome(message=f"You teach {definition.label}.", toast=False)
    outcome.private_events.extend(getattr(behavior, "private_events", []))
    outcome.room_broadcasts.extend(getattr(behavior, "room_broadcasts", []))
    apply_behavior_inventory(context, outcome, behavior)
    if definition.cutscene:
        launch = await play_cutscene(
            context,
            reference=definition.cutscene,
            room_id=room_id,
            audience="room",
            origin="topic",
            params={"card": f"$card:{definition.id}"},
        )
        private_events, room_broadcasts = deliver(launch)
        outcome.private_events.extend(private_events)
        outcome.room_broadcasts.extend(room_broadcasts)
    return outcome
