"""Household NPC peeps: customization, stats, and autonomous house life."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import random
import re
import uuid

from mods.tinytown.catalog import (
    ACTION_LABELS,
    ACTION_ROLES,
    AVATARS,
    AVATARS_BY_ID,
    MAX_NAME_LENGTH,
    MAX_NPCS_PER_HOUSE,
    TRAITS,
    TRAITS_BY_ID,
)
from mods.tinytown.roommate_text import roommate_ad
from mods.tinytown.interests import INTERESTS_BY_ID, interest_label, random_interests
from mods.tinytown.jobs import (
    JOB_INTERVAL_SECONDS,
    assign_job,
    job_description,
    job_label,
    valid_job,
)
from mods.tinytown.roommate_systems import RoommateSystemsMixin
from server.broadcast import broadcast_room_event
from server.content.worlds import PeepDefinition, QuickAction
from server.security import utc_now


LOGGER = logging.getLogger("tinyrooms.mod.tinytown")

SIM_INTERVAL_SECONDS = 20.0
MAX_CATCHUP_SECONDS = 300.0
MAX_STAT = 100.0

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,'!?-]*$")

ACTION_RATES: dict[str, dict[str, float]] = {
    "idle": {"energy": -1.0, "cleanliness": -0.8, "health": -0.05},
    "sleep": {"energy": 15.0, "cleanliness": -0.1, "health": 0.5},
    "rest": {"energy": 6.5, "cleanliness": -0.3, "health": 0.25},
    "bathe": {"energy": -0.4, "cleanliness": 36.0, "health": 0.1},
    "eat": {"energy": 5.5, "cleanliness": -2.5, "health": 7.5},
    "paint": {"energy": -2.0, "cleanliness": -4.0, "health": 0.7},
    "read": {"energy": -0.8, "cleanliness": -0.4, "health": 0.35},
    "garden": {"energy": -3.2, "cleanliness": -6.5, "health": 1.7},
    "swim": {"energy": -4.0, "cleanliness": 9.0, "health": 2.3},
    "tinker": {"energy": -2.1, "cleanliness": -4.6, "health": 0.55},
    "socialize": {"energy": -1.2, "cleanliness": -1.0, "health": 0.9},
    "stargaze": {"energy": -0.6, "cleanliness": -0.3, "health": 0.45},
}

ACTION_PROP_TAGS: dict[str, tuple[str, ...]] = {
    "sleep": ("bed",),
    "rest": ("bed", "seating", "sofa"),
    "bathe": ("bathroom", "toilet"),
    "eat": ("table", "kitchen", "prep-table"),
    "paint": ("art", "desk", "table"),
    "read": ("book", "shelf", "desk", "seating"),
    "garden": ("plant", "outdoor", "garden"),
    "swim": ("pool", "bathroom"),
    "tinker": ("desk", "shelf", "utility"),
    "socialize": ("seating", "sofa", "table"),
    "stargaze": ("art", "seating"),
}

GENERIC_LINES: dict[str, tuple[str, ...]] = {
    "idle": (
        "Just doing a little lap of the room.",
        "Everything is where I left it. Suspicious.",
        "I love this hallway. Very hallway.",
        "One more wander and then I will decide something.",
    ),
    "sleep": (
        "Five more minutes. Maybe six.",
        "This pillow has excellent opinions about naps.",
        "Zzz... no, I am awake. Mostly.",
    ),
    "rest": (
        "Just resting my eyes for a moment.",
        "This is a very good sitting spot.",
        "I could stay here all afternoon.",
    ),
    "bathe": (
        "Ah. Much better.",
        "Hot water is a kind of magic.",
        "I found a whole new level of clean.",
    ),
    "eat": (
        "This is exactly what I needed.",
        "Cooking for one is still cooking.",
        "I am putting the kettle on. For morale.",
    ),
    "paint": (
        "Hold still, inspiration.",
        "This colour is doing something wonderful.",
        "A little more light right there...",
    ),
    "read": (
        "One more page. Just one.",
        "This book is getting good.",
        "I have read this sentence three times. Lovely sentence.",
    ),
    "garden": (
        "The tomatoes are showing off again.",
        "A little water, a little gossip.",
        "Look at that leaf. Perfect leaf.",
    ),
    "swim": (
        "The water is perfect today.",
        "Three laps and then a nap.",
        "I could float here forever.",
    ),
    "tinker": (
        "There. That hinge is much happier.",
        "I knew this screwdriver would come in useful.",
        "Almost fixed. Probably fixed.",
    ),
    "socialize": (
        "Anyone want tea? I am making tea.",
        "This house feels best with company.",
        "You have to see what I found.",
    ),
    "stargaze": (
        "That one is definitely a constellation.",
        "The sky is busy tonight.",
        "I think I just saw something blink.",
    ),
}

TRAIT_LINES: dict[str, dict[str, tuple[str, ...]]] = {
    "artsy": {"paint": ("The light in here is doing most of the work.", "This wall has been waiting for me."), "idle": ("I am mentally rearranging the art.",)},
    "bookish": {"read": ("I am two chapters from the good part.", "Do not disturb, plot is thickening."), "socialize": ("You must hear about this book.",)},
    "clean": {"bathe": ("I could see a smudge from the doorway.",), "idle": ("I will just tidy this one corner. And that one.",)},
    "cozy": {"rest": ("This blanket is a personality now.", "Warm. Soft. Correct.",), "sleep": ("Best nap spot in the whole town.",)},
    "energetic": {"swim": ("Race you to the deep end!", "That was a warm-up lap.",), "garden": ("Weeding is cardio if you commit.",)},
    "foodie": {"eat": ("Needs a pinch of salt. Then perfection.", "I am testing a new recipe on myself.",), "socialize": ("Who wants to taste something?",)},
    "friendly": {"socialize": ("I am so glad you are here!", "The house feels brighter already.",), "idle": ("I should write someone a nice note.",)},
    "grumpy": {"idle": ("Hmph. The cushions are conspiring.", "I am not complaining. I am observing.",), "read": ("Fine. I will read the manual.",)},
    "outdoorsy": {"garden": ("The soil is perfect today.", "Mud is just outside with extra steps.",), "swim": ("Nothing beats cold water.",)},
    "social": {"socialize": ("Gather round, I have news.", "Who is up for a house meeting?",), "eat": ("Meals taste better with company.",)},
    "tinkerer": {"tinker": ("I improved it. Nobody asked, but I improved it.", "There is always one more loose screw.",)},
    "stargazer": {"stargaze": ("That is Orion. Or a very confident plane.", "The moon is especially smug tonight.",), "read": ("I am reading about black holes again.",)},
}

PROP_LINES = (
    "{target} is looking especially good today.",
    "I never get tired of {target}.",
    "Who chose {target}? Excellent choice.",
    "Hm, {target}. Yes. Approved.",
)

VIBE_LIKED_LINES = (
    "{name} always makes this house feel better.",
    "I am glad {name} is around.",
    "I should tell {name} they have excellent taste.",
    "It is a good day when {name} is home.",
)

VIBE_DISLIKED_LINES = (
    "{name} has been leaving crumbs everywhere again.",
    "I think {name} and I need a little space.",
    "Hmph. Somebody has been moving my things. Probably {name}.",
    "I am being very patient with {name} today.",
)


@dataclass(frozen=True, slots=True)
class NpcRecord:
    npc_id: str
    house_id: str
    owner_account_id: str
    name: str
    avatar: str
    traits: tuple[str, ...]
    stats: dict[str, float]
    room_id: str
    action: str
    target: str
    last_tick: str
    likes: str = ""
    dislikes: str = ""
    job_id: str = ""
    job_claim_json: str = ""
    job_ready_at: str = ""
    job_cooldown_until: str = ""


class NpcHouse(RoommateSystemsMixin):
    """Owns household NPCs, their stats, and their autonomous day."""

    def __init__(self, housing: object) -> None:
        self.housing = housing
        self.runtime = housing.runtime
        self.world = housing.runtime.world
        self.hub = housing.runtime.hub
        self.profiles = housing.runtime.profiles
        self.rooms = housing.runtime.rooms
        self.layout = housing.runtime.layout
        self.peep_states = housing.runtime.peep_states
        self.world_state = housing.runtime.world_state
        self.vibes = getattr(housing.runtime, "vibes", None)
        self._task: asyncio.Task[None] | None = None
        self._random = random.Random()
        self._relationship_accum: dict[str, float] = {}
        self._last_banter: dict[str, float] = {}

    # -- persistence ---------------------------------------------------------

    @staticmethod
    def _column(row: object, key: str, default: str = "") -> str:
        try:
            keys = row.keys()  # type: ignore[union-attr]
        except AttributeError:
            keys = ()
        if key not in keys:
            return default
        value = row[key]  # type: ignore[index]
        return str(value) if value is not None else default

    def _rows(self) -> list[NpcRecord]:
        with self.hub.locked() as connection:
            rows = connection.execute(
                "SELECT * FROM world.tinytown_npcs ORDER BY created_at, npc_id"
            ).fetchall()
        records: list[NpcRecord] = []
        for row in rows:
            try:
                traits = tuple(str(item) for item in json.loads(row["traits_json"]))
                stats = {str(key): float(value) for key, value in json.loads(row["stats_json"]).items()}
            except (TypeError, ValueError):
                continue
            records.append(
                NpcRecord(
                    npc_id=str(row["npc_id"]),
                    house_id=str(row["house_id"]),
                    owner_account_id=str(row["owner_account_id"]),
                    name=str(row["name"]),
                    avatar=str(row["avatar"]),
                    traits=traits,
                    stats=stats,
                    room_id=str(row["room_id"]),
                    action=str(row["action"]),
                    target=str(row["target"]),
                    last_tick=str(row["last_tick"]),
                    likes=self._column(row, "likes_interest"),
                    dislikes=self._column(row, "dislikes_interest"),
                    job_id=self._column(row, "job_id"),
                    job_claim_json=self._column(row, "job_claim_json"),
                    job_ready_at=self._column(row, "job_ready_at"),
                    job_cooldown_until=self._column(row, "job_cooldown_until"),
                )
            )
        return records

    def record_for(self, npc_id: str) -> NpcRecord | None:
        return next((record for record in self._rows() if record.npc_id == npc_id), None)

    def records_for_house(self, house_id: str) -> list[NpcRecord]:
        return [record for record in self._rows() if record.house_id == house_id]

    def _write(
        self,
        record: NpcRecord,
        *,
        created: bool,
        expected_last_tick: str | None = None,
    ) -> bool:
        with self.hub.transaction() as connection:
            if created:
                connection.execute(
                    """
                    INSERT INTO world.tinytown_npcs (
                        npc_id, house_id, owner_account_id, name, avatar, traits_json,
                        stats_json, room_id, action, target, last_tick, created_at, updated_at,
                        likes_interest, dislikes_interest, job_id, job_claim_json,
                        job_ready_at, job_cooldown_until
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.npc_id,
                        record.house_id,
                        record.owner_account_id,
                        record.name,
                        record.avatar,
                        json.dumps(list(record.traits)),
                        json.dumps(record.stats),
                        record.room_id,
                        record.action,
                        record.target,
                        record.last_tick,
                        record.last_tick,
                        record.last_tick,
                        record.likes,
                        record.dislikes,
                        record.job_id,
                        record.job_claim_json,
                        record.job_ready_at,
                        record.job_cooldown_until,
                    ),
                )
                return True
            parameters: list[object] = [
                record.name,
                record.avatar,
                json.dumps(list(record.traits)),
                json.dumps(record.stats),
                record.room_id,
                record.action,
                record.target,
                record.last_tick,
                utc_now().isoformat(),
                record.likes,
                record.dislikes,
                record.job_id,
                record.job_claim_json,
                record.job_ready_at,
                record.job_cooldown_until,
                record.npc_id,
            ]
            statement = """
                UPDATE world.tinytown_npcs SET
                    name = ?, avatar = ?, traits_json = ?, stats_json = ?, room_id = ?,
                    action = ?, target = ?, last_tick = ?, updated_at = ?,
                    likes_interest = ?, dislikes_interest = ?, job_id = ?,
                    job_claim_json = ?, job_ready_at = ?, job_cooldown_until = ?
                WHERE npc_id = ?
            """
            if expected_last_tick is not None:
                statement += " AND last_tick = ?"
                parameters.append(expected_last_tick)
            cursor = connection.execute(statement, parameters)
            return cursor.rowcount > 0

    def _delete(self, npc_id: str) -> None:
        with self.hub.transaction() as connection:
            connection.execute("DELETE FROM world.tinytown_npcs WHERE npc_id = ?", (npc_id,))

    # -- runtime peeps -------------------------------------------------------

    def _avatar_file(self, avatar: str) -> str:
        choice = AVATARS_BY_ID.get(avatar)
        return choice.file if choice is not None else AVATARS[0].file

    def _actions(self, npc_id: str) -> tuple[QuickAction, ...]:
        return (
            QuickAction(label="Check in", command=f".tinytown npc {npc_id}"),
            QuickAction(label="Play together", command=f".tinytown play {npc_id}"),
            QuickAction(label="Talk", command=f".talk {npc_id}"),
        )

    def _describe(self, record: NpcRecord) -> str:
        labels = [TRAITS_BY_ID[trait].label for trait in record.traits if trait in TRAITS_BY_ID]
        traits = " and ".join(labels) if labels else "one of a kind"
        working = f" {job_label(record.job_id).lower()}" if valid_job(record.job_id) else ""
        return (
            f"{record.name} is {traits}.{working} fancies {interest_label(record.likes)} "
            f"and avoids {interest_label(record.dislikes)}. "
            f"{ACTION_LABELS.get(record.action, 'pottering about').capitalize()}."
        )

    def _register_peep(self, record: NpcRecord) -> None:
        from mods.tinytown.roommate_dialog import build_roommate_dialog, condition_label
        from server.services.vibes import describe_vibe

        avatar_file = self._avatar_file(record.avatar)
        image_path = (self.world.root_path / "peeps" / avatar_file).resolve()
        dialog = None
        try:
            dialog = build_roommate_dialog(
                record,
                owner_toward_label=self._vibe_label(record.owner_account_id, record.npc_id, describe_vibe),
                owner_from_label=self._vibe_label(record.npc_id, record.owner_account_id, describe_vibe),
                housemates=self._housemate_cards(record, describe_vibe),
                needs_blurb=self._needs_blurb(record),
                job_label_text=job_label(record.job_id),
                job_description_text=job_description(record.job_id),
                job_state=self._job_dialog_state(record),
                job_gate_blurb=self._job_gate_blurb(record),
                job_ready=self._job_ready_payload(record),
                energy_label=condition_label(record.stats.get("energy", 70.0)),
                health_label=condition_label(record.stats.get("health", 80.0)),
                cleanliness_label=condition_label(record.stats.get("cleanliness", 80.0)),
            )
        except Exception:  # noqa: BLE001 - a roommate is never left speechless by a bug
            LOGGER.exception("tinytown.roommate_dialog_failed")
            dialog = None
        self.world.peeps[record.npc_id] = PeepDefinition(
            id=record.npc_id,
            label=record.name,
            description=self._describe(record),
            room_id=record.room_id,
            image_name=avatar_file,
            image_path=image_path,
            script_name=None,
            actions=self._actions(record.npc_id),
            dialog=dialog,
            activity=None,
        )
        if self.peep_states is not None:
            self.peep_states.record(record.npc_id, record.room_id)

    def prepare(self) -> None:
        if self.world.id != "tinytown":
            return
        for record in self._rows():
            if self.housing.record_for(record.house_id) is None:
                continue
            if record.room_id not in self.world.rooms:
                house = self.housing.record_for(record.house_id)
                if house is None:
                    continue
                try:
                    room_id = self.housing.entry_room(house)
                except ValueError:
                    continue
                record = self._with(record, room_id=room_id)
                self._write(record, created=False)
            record = self._ensure_identity(record)
            self._register_peep(record)

    @staticmethod
    def _with(record: NpcRecord, **changes: object) -> NpcRecord:
        values = {
            "npc_id": record.npc_id,
            "house_id": record.house_id,
            "owner_account_id": record.owner_account_id,
            "name": record.name,
            "avatar": record.avatar,
            "traits": record.traits,
            "stats": record.stats,
            "room_id": record.room_id,
            "action": record.action,
            "target": record.target,
            "last_tick": record.last_tick,
            "likes": record.likes,
            "dislikes": record.dislikes,
            "job_id": record.job_id,
            "job_claim_json": record.job_claim_json,
            "job_ready_at": record.job_ready_at,
            "job_cooldown_until": record.job_cooldown_until,
        }
        values.update(changes)
        return NpcRecord(**values)  # type: ignore[arg-type]

    # -- catalogs and management --------------------------------------------

    def catalog_payload(self) -> dict[str, object]:
        return {
            "avatars": [
                {
                    "id": avatar.id,
                    "label": avatar.label,
                    "image_url": f"/assets/world/{self.world.id}/peeps/{avatar.file}",
                }
                for avatar in AVATARS
            ],
            "traits": [
                {"id": trait.id, "label": trait.label, "description": trait.description}
                for trait in TRAITS
            ],
            "max_name_length": MAX_NAME_LENGTH,
            "max_npcs": MAX_NPCS_PER_HOUSE,
        }

    def household_payload(self, account: object, house_id: str | None = None) -> dict[str, object]:
        houses = self.housing.records_for_owner(account.id)
        chosen = None
        if house_id:
            chosen = next((record for record in houses if record.house_id == house_id), None)
        if chosen is None and houses:
            chosen = houses[0]
        npcs: list[dict[str, object]] = []
        if chosen is not None:
            template = self.housing.template_for(chosen)
            for record in self.records_for_house(chosen.house_id):
                room_label = next(
                    (room.label for room in template.rooms if chosen.room_ids.get(room.key) == record.room_id),
                    "somewhere in the house",
                )
                npcs.append(self.npc_summary(record, room_label))
        payload = self.catalog_payload()
        payload.update(
            {
                "houses": [self.housing.house_payload(record, account.id) for record in houses],
                "house_id": chosen.house_id if chosen is not None else "",
                "npcs": npcs,
            }
        )
        return payload

    def npc_summary(self, record: NpcRecord, room_label: str) -> dict[str, object]:
        from mods.tinytown.roommate_dialog import condition_label

        return {
            "id": record.npc_id,
            "name": record.name,
            "avatar": record.avatar,
            "avatar_url": f"/assets/world/{self.world.id}/peeps/{self._avatar_file(record.avatar)}",
            "traits": [
                {"id": trait, "label": TRAITS_BY_ID[trait].label}
                for trait in record.traits
                if trait in TRAITS_BY_ID
            ],
            "condition": {
                "energy": condition_label(record.stats.get("energy", 70.0)),
                "health": condition_label(record.stats.get("health", 80.0)),
                "cleanliness": condition_label(record.stats.get("cleanliness", 80.0)),
            },
            "likes": {
                "id": record.likes,
                "label": interest_label(record.likes),
            },
            "dislikes": {
                "id": record.dislikes,
                "label": interest_label(record.dislikes),
            },
            "job": {
                "id": record.job_id,
                "label": job_label(record.job_id),
            },
            "action": record.action,
            "action_label": ACTION_LABELS.get(record.action, record.action),
            "target": record.target,
            "room_id": record.room_id,
            "room_label": room_label,
            "description": roommate_ad(record.traits).description,
        }

    def _require_owned_house(self, account: object, house_id: str):
        record = self.housing.record_for(house_id)
        if record is None:
            raise ValueError("That house does not exist.")
        if record.owner_account_id != account.id:
            raise ValueError("You can only manage your own household.")
        return record

    def require_owned_house(self, account: object, house_id: str):
        """Public ownership guard for cross-service adopt flows."""

        return self._require_owned_house(account, house_id)

    @staticmethod
    def _validate_name(raw: str) -> str:
        name = " ".join(str(raw).strip().split())
        if not name or len(name) > MAX_NAME_LENGTH or not _NAME.match(name):
            raise ValueError(
                f"Names must be {MAX_NAME_LENGTH} characters or fewer, start with a letter or number, "
                "and use letters, numbers, spaces, and basic punctuation."
            )
        return name

    def _validate_traits(self, raw: object) -> tuple[str, ...]:
        values = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
        traits: list[str] = []
        for value in values:
            trait = str(value).strip()
            if not trait:
                continue
            if trait not in TRAITS_BY_ID:
                raise ValueError(f"Unknown trait '{trait}'.")
            if trait not in traits:
                traits.append(trait)
        if len(traits) != 2:
            raise ValueError("Choose exactly two traits.")
        return tuple(traits)

    def _validate_avatar(self, raw: str) -> str:
        avatar = str(raw).strip()
        if avatar not in AVATARS_BY_ID:
            raise ValueError("Choose one of the available looks.")
        return avatar

    def _initial_stats(self, traits: tuple[str, ...]) -> dict[str, float]:
        stats = {"energy": 76.0, "health": 88.0, "cleanliness": 82.0}
        for trait_id in traits:
            trait = TRAITS_BY_ID[trait_id]
            if trait.energy_drain < 1.0:
                stats["energy"] += 5
            if trait.cleanliness_drain > 1.3:
                stats["cleanliness"] += 6
            if trait.id == "energetic":
                stats["health"] += 4
        return stats

    def add(
        self,
        account: object,
        house_id: str,
        name: str,
        avatar: str,
        traits: object,
        *,
        likes: str = "",
        dislikes: str = "",
        job_id: str = "",
    ) -> NpcRecord:
        house = self._require_owned_house(account, house_id)
        if len(self.records_for_house(house_id)) >= MAX_NPCS_PER_HOUSE:
            raise ValueError(f"A house can hold at most {MAX_NPCS_PER_HOUSE} household peeps.")
        now = utc_now().isoformat()
        validated_traits = self._validate_traits(traits)
        if (
            likes not in INTERESTS_BY_ID
            or dislikes not in INTERESTS_BY_ID
            or likes == dislikes
        ):
            likes, dislikes = random_interests(self._random)
        from datetime import timedelta

        first_shift_at = (utc_now() + timedelta(seconds=JOB_INTERVAL_SECONDS)).isoformat()
        record = NpcRecord(
            npc_id=f"ttnpc:{uuid.uuid4().hex}",
            house_id=house_id,
            owner_account_id=account.id,
            name=self._validate_name(name),
            avatar=self._validate_avatar(avatar),
            traits=validated_traits,
            stats=self._initial_stats(validated_traits),
            room_id=self.housing.entry_room(house),
            action="idle",
            target="",
            last_tick=now,
            likes=likes,
            dislikes=dislikes,
            job_id=job_id if valid_job(job_id) else assign_job(self._random, validated_traits),
            job_claim_json="",
            job_ready_at="",
            job_cooldown_until=first_shift_at,
        )
        self._write(record, created=True)
        self._register_peep(record)
        return record

    def edit(
        self,
        account: object,
        npc_id: str,
        *,
        name: str | None = None,
        avatar: str | None = None,
        traits: object | None = None,
    ) -> NpcRecord:
        record = self.record_for(npc_id)
        if record is None:
            raise ValueError("That household peep does not exist.")
        self._require_owned_house(account, record.house_id)
        changes: dict[str, object] = {}
        if name is not None:
            changes["name"] = self._validate_name(name)
        if avatar is not None:
            changes["avatar"] = self._validate_avatar(avatar)
        if traits is not None:
            changes["traits"] = self._validate_traits(traits)
        changes["last_tick"] = utc_now().isoformat()
        updated = self._with(record, **changes)
        self._write(updated, created=False)
        self._register_peep(updated)
        return updated

    def remove(self, account: object, npc_id: str) -> NpcRecord:
        record = self.record_for(npc_id)
        if record is None:
            raise ValueError("That household peep does not exist.")
        self._require_owned_house(account, record.house_id)
        self._delete(npc_id)
        self.world.peeps.pop(npc_id, None)
        self.rooms.sprites.forget_npc(npc_id)
        return record

    # -- interaction ---------------------------------------------------------

    def checkin(self, account: object, npc_id: str, room_id: str) -> tuple[NpcRecord, str, str]:
        from mods.tinytown.roommate_dialog import condition_label

        record = self.record_for(npc_id)
        if record is None or record.npc_id not in self.world.peeps:
            raise ValueError("That household peep does not exist.")
        if record.room_id != room_id:
            raise ValueError("That peep is somewhere else in the house right now.")
        traits = [TRAITS_BY_ID[trait].label for trait in record.traits if trait in TRAITS_BY_ID]
        summary = (
            f"{record.name} ({', '.join(traits)}) is {ACTION_LABELS.get(record.action, 'pottering about')}. "
            f"Energy feels {condition_label(record.stats.get('energy', 0))}, "
            f"health {condition_label(record.stats.get('health', 0))}, "
            f"cleanliness {condition_label(record.stats.get('cleanliness', 0))}. "
            f"Fancies {interest_label(record.likes)}; avoids {interest_label(record.dislikes)}."
        )
        line = self._line(record, record.action, record.target)
        return record, f"{summary} \"{line}\"", line

    def play(self, account: object, npc_id: str, room_id: str) -> tuple[NpcRecord, str, dict[str, float]]:
        record = self.record_for(npc_id)
        if record is None or record.npc_id not in self.world.peeps:
            raise ValueError("That household peep does not exist.")
        if record.room_id != room_id:
            raise ValueError("That peep is somewhere else in the house right now.")
        stats = dict(record.stats)
        stats["energy"] = self._clamp(stats.get("energy", 70) - 6)
        stats["health"] = self._clamp(stats.get("health", 80) + 3)
        stats["cleanliness"] = self._clamp(stats.get("cleanliness", 80) - 4)
        updated = self._with(record, stats=stats, action="socialize", last_tick=utc_now().isoformat())
        self._write(updated, created=False)
        if self.vibes is not None:
            self.vibes.adjust(npc_id, account.id, 3)
            self.vibes.adjust(account.id, npc_id, 2)
        line = self._random.choice(
            (
                "That was fun! Let's do it again.",
                "You are good company, you know that?",
                "I needed that. My energy is back.",
                "Same time tomorrow?",
            )
        )
        return updated, line, stats

    # -- autonomy ------------------------------------------------------------

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(MAX_STAT, float(value)))

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if self.world.id != "tinytown":
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = loop.create_task(self._loop())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(SIM_INTERVAL_SECONDS)
            try:
                await self.advance(emit=True)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - autonomy must never stop the world loop
                LOGGER.exception("tinytown.npc_autonomy_failed")

    def _roles_for(self, record: NpcRecord, house: object | None = None) -> dict[str, str]:
        house = house if house is not None else self.housing.record_for(record.house_id)
        if house is None:
            return {}
        try:
            template = self.housing.template_for(house)
        except ValueError:
            return {}
        return {room.role: house.room_ids[room.key] for room in template.rooms if room.key in house.room_ids}

    def _trait_weights(self, traits: tuple[str, ...]) -> dict[str, float]:
        weights: dict[str, float] = {}
        for trait_id in traits:
            trait = TRAITS_BY_ID.get(trait_id)
            if trait is None:
                continue
            for action, weight in trait.weights:
                weights[action] = weights.get(action, 1.0) + weight
        return weights

    def _choose_action(self, record: NpcRecord, roles: dict[str, str]) -> str:
        stats = record.stats
        traits = [TRAITS_BY_ID[trait] for trait in record.traits if trait in TRAITS_BY_ID]
        energy = stats.get("energy", 70)
        health = stats.get("health", 80)
        clean = stats.get("cleanliness", 80)
        rest_want = max((trait.rest_want for trait in traits), default=1.0)
        clean_want = max((trait.cleanliness_want for trait in traits), default=1.0)

        def available(action: str) -> bool:
            action_roles = dict(ACTION_ROLES).get(action, ())
            return any(role in roles for role in action_roles)

        wake_at = min(MAX_STAT - 5.0, 82.0 * rest_want)
        if record.action in {"sleep", "rest"} and energy < wake_at:
            return record.action
        if record.action == "bathe" and clean < 90:
            return "bathe"
        if record.action == "eat" and health < 72:
            return "eat"
        if clean < 32 * clean_want and available("bathe"):
            return "bathe"
        if health < 38 and available("eat"):
            return "eat"
        if energy < 28 * rest_want and available("sleep"):
            return "sleep"
        if energy < 45 * rest_want and available("rest"):
            return "rest"

        weights = self._trait_weights(record.traits)
        if energy < 55:
            weights["rest"] = weights.get("rest", 1.0) + 2.0
            weights["read"] = weights.get("read", 1.0) + 1.0
        if clean < 60:
            weights["bathe"] = weights.get("bathe", 1.0) + 1.5
        if health < 70:
            weights["eat"] = weights.get("eat", 1.0) + 2.0
        candidates = [
            (action, max(0.1, weights.get(action, 1.0)))
            for action in ACTION_RATES
            if action != "idle" and available(action)
        ]
        if not candidates:
            return "idle"
        total = sum(weight for _action, weight in candidates)
        roll = self._random.random() * total
        for action, weight in candidates:
            roll -= weight
            if roll <= 0:
                return action
        return candidates[-1][0]

    def _desired_room(self, record: NpcRecord, action: str, roles: dict[str, str]) -> str | None:
        for role in dict(ACTION_ROLES).get(action, ()):
            room_id = roles.get(role)
            if room_id:
                return room_id
        return None

    def _pick_target(self, record: NpcRecord, action: str) -> str:
        try:
            props = self.layout.effective_props(record.room_id)
        except (KeyError, ValueError):
            return ""
        wanted = ACTION_PROP_TAGS.get(action, ())
        matches: list[str] = []
        fallback: list[str] = []
        for prop in props:
            definition = self.world.props.get(prop.prop_id)
            if definition is None or definition.hidden:
                continue
            fallback.append(definition.label)
            if any(tag in definition.tags for tag in wanted):
                matches.append(definition.label)
        pool = matches or fallback
        if not pool:
            return ""
        return self._random.choice(pool)

    def _vibe_line(self, record: NpcRecord) -> str | None:
        if self.vibes is None:
            return None
        scores = self.vibes.outgoing(record.npc_id)
        ranked = sorted(
            ((target, int(score)) for target, score in scores.items() if abs(int(score)) >= 10),
            key=lambda entry: abs(entry[1]),
            reverse=True,
        )
        if not ranked:
            return None
        target, score = ranked[0]
        name = ""
        peep = self.world.peeps.get(target)
        if peep is not None:
            name = peep.label
        else:
            account = self.profiles.get_account_by_id(target)
            if account is not None:
                name = account.username_display
        if not name:
            return None
        lines = VIBE_LIKED_LINES if score > 0 else VIBE_DISLIKED_LINES
        return self._random.choice(lines).format(name=name)

    def _line(self, record: NpcRecord, action: str, target: str) -> str:
        vibe_line = self._vibe_line(record)
        if vibe_line is not None and self._random.random() < 0.32:
            return vibe_line
        for trait_id in record.traits:
            trait_lines = TRAIT_LINES.get(trait_id, {}).get(action)
            if trait_lines and self._random.random() < 0.6:
                return self._random.choice(trait_lines)
        if target and self._random.random() < 0.4:
            return self._random.choice(PROP_LINES).format(target=target)
        return self._random.choice(GENERIC_LINES.get(action, GENERIC_LINES["idle"]))

    def _apply_rates(self, record: NpcRecord, action: str, minutes: float) -> dict[str, float]:
        rates = ACTION_RATES.get(action, ACTION_RATES["idle"])
        stats = dict(record.stats)
        energy_multiplier = 1.0
        cleanliness_multiplier = 1.0
        for trait_id in record.traits:
            trait = TRAITS_BY_ID.get(trait_id)
            if trait is None:
                continue
            energy_multiplier *= trait.energy_drain
            cleanliness_multiplier *= trait.cleanliness_drain
        stats["energy"] = stats.get("energy", 70) + rates["energy"] * minutes * (
            1.0 if rates["energy"] > 0 else energy_multiplier
        )
        stats["cleanliness"] = stats.get("cleanliness", 80) + rates["cleanliness"] * minutes * (
            1.0 if rates["cleanliness"] > 0 else cleanliness_multiplier
        )
        stats["health"] = stats.get("health", 80) + rates["health"] * minutes
        for key in ("energy", "health", "cleanliness"):
            stats[key] = self._clamp(stats.get(key, 80.0))
        return stats

    async def _move_to(self, record: NpcRecord, room_id: str, *, emit: bool) -> NpcRecord:
        if room_id == record.room_id or room_id not in self.world.rooms:
            return record
        if emit:
            try:
                result = await self.rooms.summon_npc(record.npc_id, room_id)
            except ValueError:
                return record
            await broadcast_room_event(self.runtime, room_id=result.source_room_id, event=result.source_event)
            await broadcast_room_event(self.runtime, room_id=result.destination_room_id, event=result.destination_event)
        elif self.peep_states is not None:
            with self.hub.transaction() as connection:
                self.peep_states.set_in_transaction(connection, record.npc_id, room_id)
            self.peep_states.record(record.npc_id, room_id)
        self.rooms.sprites.forget_npc(record.npc_id)
        self.rooms.sprites.ensure_npc(record.npc_id, room_id)
        return self._with(record, room_id=room_id)

    async def advance(
        self,
        *,
        now: object | None = None,
        elapsed_seconds: float | None = None,
        emit: bool = False,
    ) -> None:
        """Advance every household NPC by one simulation step."""

        if self.world.id != "tinytown":
            return
        moment = now or utc_now()
        records = self._rows()
        if not records:
            return
        houses = {
            house_id: self.housing.record_for(house_id)
            for house_id in {record.house_id for record in records}
        }
        house_npcs: dict[str, list[str]] = {}
        for record in records:
            house_npcs.setdefault(record.house_id, []).append(record.npc_id)
        house_elapsed: dict[str, float] = {}
        room_ids = {record.room_id for record in records}
        occupied: set[str] = set()
        if emit and getattr(self.runtime, "connections", None) is not None:
            for room_id in room_ids:
                try:
                    if await self.runtime.connections.list_room(room_id):
                        occupied.add(room_id)
                except Exception:  # noqa: BLE001 - occupancy is best effort
                    continue
        spoken_rooms: set[str] = set()

        for record in records:
            house = houses.get(record.house_id)
            if house is None:
                continue
            try:
                self.housing.template_for(house)
            except ValueError:
                continue
            previous_last_tick = record.last_tick
            if elapsed_seconds is None:
                try:
                    from datetime import datetime

                    previous = datetime.fromisoformat(record.last_tick)
                    elapsed = max(0.0, min(MAX_CATCHUP_SECONDS, (moment - previous).total_seconds()))
                except (TypeError, ValueError):
                    elapsed = SIM_INTERVAL_SECONDS
            else:
                elapsed = max(0.0, min(MAX_CATCHUP_SECONDS, float(elapsed_seconds)))
            minutes = elapsed / 60.0
            roles = self._roles_for(record, house)
            action = self._choose_action(record, roles)
            desired = self._desired_room(record, action, roles)
            if desired is not None and desired != record.room_id:
                record = await self._move_to(record, desired, emit=emit)
            stats = self._apply_rates(record, action, minutes)
            target = self._pick_target(record, action) if action != "idle" else ""
            record = self._with(
                record,
                action=action,
                target=target,
                stats=stats,
                last_tick=moment.isoformat(),
            )
            if not self._write(record, created=False, expected_last_tick=previous_last_tick):
                continue
            self._register_peep(record)
            if emit:
                await self._emit(record, occupied, spoken_rooms)
            self._adjust_vibes(record, house_npcs.get(record.house_id, []))
            house_elapsed.setdefault(record.house_id, elapsed)

        for house_id, house_elapsed_seconds in house_elapsed.items():
            self._accumulate_house_clocks(house_id, house_elapsed_seconds)
        self._run_house_ticks(houses, moment)
        if emit:
            await self._emit_banter(houses, occupied)

    async def _emit(self, record: NpcRecord, occupied: set[str], spoken_rooms: set[str]) -> None:
        if record.room_id not in occupied:
            return
        deltas = {
            "energy": record.stats.get("energy", 0.0),
            "health": record.stats.get("health", 0.0),
            "cleanliness": record.stats.get("cleanliness", 0.0),
        }
        await broadcast_room_event(
            self.runtime,
            room_id=record.room_id,
            event={
                "type": "counter.updated",
                "room_id": record.room_id,
                "target_id": record.npc_id,
                "target_label": record.name,
                "health": deltas["health"],
                "energy": deltas["energy"],
                "cleanliness": deltas["cleanliness"],
                "max_health": MAX_STAT,
                "max_energy": MAX_STAT,
                "max_cleanliness": MAX_STAT,
                "statuses": [],
                "decals": [],
                "source_id": record.npc_id,
            },
        )
        if record.action not in {"sleep", "bathe"} and self._random.random() < 0.32:
            try:
                position = self.rooms.sprites.random_npc_position(record.npc_id, record.room_id)
            except (KeyError, ValueError):
                position = None
            if position is not None:
                await broadcast_room_event(
                    self.runtime,
                    room_id=record.room_id,
                    event={
                        "type": "peep.sprite",
                        "room_id": record.room_id,
                        "peep_id": record.npc_id,
                        "position": list(position),
                    },
                )
        if record.room_id in spoken_rooms or self._random.random() > 0.4:
            return
        spoken_rooms.add(record.room_id)
        text = self._line(record, record.action, record.target)
        self.world_state.append_chat_message(
            record.room_id,
            {
                "speaker_id": record.npc_id,
                "speaker": record.name,
                "style": "expression",
                "text": text,
            },
        )
        await broadcast_room_event(
            self.runtime,
            room_id=record.room_id,
            event={
                "type": "emote.bubble",
                "room_id": record.room_id,
                "source_id": record.npc_id,
                "speaker_id": record.npc_id,
                "source": record.name,
                "bubble": {"kind": "expression", "text": text},
                "card_id": None,
            },
        )

    def _adjust_vibes(self, record: NpcRecord, peer_ids: list[str]) -> None:
        if self.vibes is None or self._random.random() > 0.22:
            return
        targets = [peer_id for peer_id in peer_ids if peer_id != record.npc_id]
        targets.append(record.owner_account_id)
        target = self._random.choice(targets)
        positivity = 1.0
        for trait_id in record.traits:
            trait = TRAITS_BY_ID.get(trait_id)
            if trait is not None:
                positivity *= trait.positivity
        delta = 2 if positivity >= 1.0 else -2
        if self._random.random() < 0.25:
            delta = -delta
        self.vibes.adjust(record.npc_id, target, delta)
        self.vibes.adjust(target, record.npc_id, max(1, delta))

    # -- serializer hook -----------------------------------------------------

    def npc_payload(self, peep: object, room_id: str | None) -> dict[str, object] | None:
        peep_id = getattr(peep, "id", None)
        if not isinstance(peep_id, str) or not peep_id.startswith("ttnpc:"):
            return None
        record = self.record_for(peep_id)
        if record is None:
            return None
        if room_id is not None and record.room_id != room_id:
            return None
        return {
            "description": self._describe(record),
            "counters": {
                "health": round(record.stats.get("health", 80.0), 1),
                "energy": round(record.stats.get("energy", 70.0), 1),
                "cleanliness": round(record.stats.get("cleanliness", 80.0), 1),
                "max_health": MAX_STAT,
                "max_energy": MAX_STAT,
                "max_cleanliness": MAX_STAT,
            },
        }
