"""Random roommate candidates for TinyTown classified ads."""

from __future__ import annotations

from dataclasses import dataclass
import json
import random
import uuid

from mods.tinytown.catalog import (
    MAX_NPCS_PER_HOUSE,
    ROOMMATE_ARCHETYPES,
    ROOMMATE_AVATARS,
    ROOMMATE_BATCH_SIZE,
    ROOMMATE_FIRST_NAMES,
    ROOMMATE_LAST_NAMES,
    TRAITS_BY_ID,
)
from server.security import utc_now


HEADLINES = {
    "artsy": "Seeks a bright wall and a patient roommate.",
    "bookish": "Quiet reader, excellent tea maker, light sleeper.",
    "clean": "Will label the spice jars. Fair warning.",
    "cozy": "Professional blanket enthusiast seeks warm corner.",
    "energetic": "Early riser, late swimmer, always up for a walk.",
    "foodie": "Cooks for the whole house. Will accept compliments.",
    "friendly": "Here for good mornings and better neighbours.",
    "grumpy": "Not unfriendly. Just selective. Very tidy.",
    "outdoorsy": "Mud on the boots, flowers on the sill.",
    "social": "House dinners, game nights, spontaneous hallway chats.",
    "tinkerer": "Owns the right screwdriver. Usually two.",
    "stargazer": "Will trade roof access for quiet conversation.",
}


@dataclass(frozen=True, slots=True)
class RoommateCandidate:
    """One persisted roommate advertisement."""

    candidate_id: str
    owner_account_id: str
    house_id: str
    name: str
    avatar: str
    traits: tuple[str, ...]
    stats: dict[str, float]
    headline: str
    created_at: str


class RoommateCandidates:
    """Generate and adopt the five roommates advertised for one home."""

    def __init__(self, housing: object) -> None:
        self.housing = housing
        self.runtime = housing.runtime
        self.world = housing.runtime.world
        self.hub = housing.runtime.hub
        self.npcs = housing.npcs
        self._random = random.Random()

    def _rows(self, owner_id: str, house_id: str) -> list[RoommateCandidate]:
        with self.hub.locked() as connection:
            rows = connection.execute(
                """
                SELECT * FROM world.tinytown_roommate_candidates
                WHERE owner_account_id = ? AND house_id = ?
                ORDER BY created_at, candidate_id
                """,
                (owner_id, house_id),
            ).fetchall()
        candidates = []
        for row in rows:
            try:
                traits = tuple(str(item) for item in json.loads(row["traits_json"]))
                stats = {str(key): float(value) for key, value in json.loads(row["stats_json"]).items()}
            except (TypeError, ValueError):
                continue
            candidates.append(
                RoommateCandidate(
                    candidate_id=str(row["candidate_id"]),
                    owner_account_id=str(row["owner_account_id"]),
                    house_id=str(row["house_id"]),
                    name=str(row["name"]),
                    avatar=str(row["avatar"]),
                    traits=traits,
                    stats=stats,
                    headline=str(row["headline"]),
                    created_at=str(row["created_at"]),
                )
            )
        return candidates

    def _candidate_for(self, candidate_id: str) -> RoommateCandidate | None:
        with self.hub.locked() as connection:
            row = connection.execute(
                "SELECT * FROM world.tinytown_roommate_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            traits = tuple(str(item) for item in json.loads(row["traits_json"]))
            stats = {str(key): float(value) for key, value in json.loads(row["stats_json"]).items()}
        except (TypeError, ValueError):
            return None
        return RoommateCandidate(
            candidate_id=str(row["candidate_id"]),
            owner_account_id=str(row["owner_account_id"]),
            house_id=str(row["house_id"]),
            name=str(row["name"]),
            avatar=str(row["avatar"]),
            traits=traits,
            stats=stats,
            headline=str(row["headline"]),
            created_at=str(row["created_at"]),
        )

    def _insert(self, candidate: RoommateCandidate) -> None:
        with self.hub.transaction() as connection:
            connection.execute(
                """
                INSERT INTO world.tinytown_roommate_candidates (
                    candidate_id, owner_account_id, house_id, name, avatar,
                    traits_json, stats_json, headline, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.candidate_id,
                    candidate.owner_account_id,
                    candidate.house_id,
                    candidate.name,
                    candidate.avatar,
                    json.dumps(list(candidate.traits)),
                    json.dumps(candidate.stats),
                    candidate.headline,
                    candidate.created_at,
                ),
            )

    def _delete(self, candidate_id: str) -> None:
        with self.hub.transaction() as connection:
            connection.execute(
                "DELETE FROM world.tinytown_roommate_candidates WHERE candidate_id = ?",
                (candidate_id,),
            )

    def _new_candidate(self, account: object, house_id: str, existing: list[RoommateCandidate]) -> RoommateCandidate:
        used_names = {candidate.name for candidate in existing}
        used_avatars = {candidate.avatar for candidate in existing}
        used_pairs = {tuple(sorted(candidate.traits)) for candidate in existing}
        for _attempt in range(80):
            name = f"{self._random.choice(ROOMMATE_FIRST_NAMES)} {self._random.choice(ROOMMATE_LAST_NAMES)}"
            if name in used_names:
                continue
            avatar = self._random.choice(ROOMMATE_AVATARS)
            if avatar.id in used_avatars:
                continue
            traits = tuple(self._random.choice(ROOMMATE_ARCHETYPES))
            if tuple(sorted(traits)) in used_pairs:
                continue
            headline = self._random.choice(
                tuple(HEADLINES[trait] for trait in traits if trait in HEADLINES)
            )
            return RoommateCandidate(
                candidate_id=f"ttcand:{uuid.uuid4().hex}",
                owner_account_id=account.id,
                house_id=house_id,
                name=name,
                avatar=avatar.id,
                traits=traits,
                stats=self.npcs._initial_stats(traits),
                headline=headline,
                created_at=utc_now().isoformat(),
            )
        raise ValueError("The classified desk ran out of roommates. Try opening the page again.")

    def ensure_batch(self, account: object, house_id: str) -> list[RoommateCandidate]:
        house = self.npcs._require_owned_house(account, house_id)
        del house
        candidates = self._rows(account.id, house_id)
        household = self.npcs.records_for_house(house_id)
        if len(household) >= MAX_NPCS_PER_HOUSE:
            return candidates
        while len(candidates) < ROOMMATE_BATCH_SIZE:
            candidate = self._new_candidate(account, house_id, candidates)
            self._insert(candidate)
            candidates.append(candidate)
        return candidates

    def _payload(self, candidate: RoommateCandidate) -> dict[str, object]:
        avatar = next((item for item in ROOMMATE_AVATARS if item.id == candidate.avatar), ROOMMATE_AVATARS[0])
        return {
            "id": candidate.candidate_id,
            "name": candidate.name,
            "avatar": candidate.avatar,
            "avatar_url": f"/assets/world/{self.world.id}/peeps/{avatar.file}",
            "traits": [
                {"id": trait, "label": TRAITS_BY_ID[trait].label}
                for trait in candidate.traits
                if trait in TRAITS_BY_ID
            ],
            "stats": {
                "energy": round(candidate.stats.get("energy", 76.0), 1),
                "health": round(candidate.stats.get("health", 88.0), 1),
                "cleanliness": round(candidate.stats.get("cleanliness", 82.0), 1),
                "max_energy": 100.0,
                "max_health": 100.0,
                "max_cleanliness": 100.0,
            },
            "headline": candidate.headline,
        }

    def candidates_payload(self, account: object, house_id: str | None = None) -> dict[str, object]:
        household = self.npcs.household_payload(account, house_id)
        chosen = str(household.get("house_id") or "")
        if not chosen:
            household.update({"candidates": [], "max_npcs": MAX_NPCS_PER_HOUSE})
            return household
        candidates = self.ensure_batch(account, chosen)
        household.update(
            {
                "candidates": [self._payload(candidate) for candidate in candidates],
                "max_npcs": MAX_NPCS_PER_HOUSE,
            }
        )
        return household

    def adopt(self, account: object, candidate_id: str) -> dict[str, object]:
        candidate = self._candidate_for(candidate_id)
        if candidate is None or candidate.owner_account_id != account.id:
            raise ValueError("That roommate advertisement has expired.")
        if len(self.npcs.records_for_house(candidate.house_id)) >= MAX_NPCS_PER_HOUSE:
            raise ValueError("That household already has all four rooms taken.")
        npc = self.npcs.add(
            account,
            candidate.house_id,
            candidate.name,
            candidate.avatar,
            candidate.traits,
        )
        self._delete(candidate.candidate_id)
        payload = self.candidates_payload(account, candidate.house_id)
        payload["adopted"] = {"id": npc.npc_id, "name": npc.name}
        return payload
