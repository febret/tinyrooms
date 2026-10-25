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
from mods.tinytown.roommate_text import roommate_ad
from server.security import utc_now


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
    likes: str = ""
    dislikes: str = ""
    job_hint: str = ""


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
            keys = row.keys() if hasattr(row, "keys") else ()
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
                    likes=str(row["likes_interest"]) if "likes_interest" in keys and row["likes_interest"] else "",
                    dislikes=str(row["dislikes_interest"]) if "dislikes_interest" in keys and row["dislikes_interest"] else "",
                    job_hint=str(row["job_hint"]) if "job_hint" in keys and row["job_hint"] else "",
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
        keys = row.keys() if hasattr(row, "keys") else ()
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
            likes=str(row["likes_interest"]) if "likes_interest" in keys and row["likes_interest"] else "",
            dislikes=str(row["dislikes_interest"]) if "dislikes_interest" in keys and row["dislikes_interest"] else "",
            job_hint=str(row["job_hint"]) if "job_hint" in keys and row["job_hint"] else "",
        )

    def _insert(self, candidate: RoommateCandidate) -> None:
        with self.hub.transaction() as connection:
            connection.execute(
                """
                INSERT INTO world.tinytown_roommate_candidates (
                    candidate_id, owner_account_id, house_id, name, avatar,
                    traits_json, stats_json, headline, created_at,
                    likes_interest, dislikes_interest, job_hint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    candidate.likes,
                    candidate.dislikes,
                    candidate.job_hint,
                ),
            )

    def _delete(self, candidate_id: str) -> None:
        with self.hub.transaction() as connection:
            connection.execute(
                "DELETE FROM world.tinytown_roommate_candidates WHERE candidate_id = ?",
                (candidate_id,),
            )

    def _new_candidate(self, account: object, house_id: str, existing: list[RoommateCandidate]) -> RoommateCandidate:
        from mods.tinytown.interests import random_interests
        from mods.tinytown.jobs import assign_job

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
            headline = roommate_ad(traits).headline
            likes, dislikes = random_interests(self._random)
            hint = assign_job(self._random, traits)
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
                likes=likes,
                dislikes=dislikes,
                job_hint=hint,
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
        from mods.tinytown.interests import interest_blurb, interest_label
        from mods.tinytown.jobs import job_label
        from mods.tinytown.roommate_dialog import condition_label

        avatar = next((item for item in ROOMMATE_AVATARS if item.id == candidate.avatar), ROOMMATE_AVATARS[0])
        likes_blurb = interest_blurb(candidate.likes) if candidate.likes else ""
        job_line = f" Handy around the house as a budding {job_label(candidate.job_hint).lower()}." if candidate.job_hint else ""
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
            "condition": {
                "energy": condition_label(candidate.stats.get("energy", 76.0)),
                "health": condition_label(candidate.stats.get("health", 88.0)),
                "cleanliness": condition_label(candidate.stats.get("cleanliness", 82.0)),
            },
            "likes": {
                "id": candidate.likes,
                "label": interest_label(candidate.likes) if candidate.likes else "quiet hobbies",
            },
            "dislikes": {
                "id": candidate.dislikes,
                "label": interest_label(candidate.dislikes) if candidate.dislikes else "loud mornings",
            },
            "job_hint": {
                "id": candidate.job_hint,
                "label": job_label(candidate.job_hint) if candidate.job_hint else "House Helper",
            },
            "headline": candidate.headline,
            "description": f"{roommate_ad(candidate.traits).description} {likes_blurb}.{job_line}".strip(),
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

    def adopt(self, account: object, candidate_id: str, house_id: str | None = None) -> dict[str, object]:
        candidate = self._candidate_for(candidate_id)
        if candidate is None or candidate.owner_account_id != account.id:
            raise ValueError("That roommate advertisement has expired.")
        target_house_id = str(house_id or candidate.house_id)
        self.npcs.require_owned_house(account, target_house_id)
        if len(self.npcs.records_for_house(target_house_id)) >= MAX_NPCS_PER_HOUSE:
            raise ValueError("That household already has all four rooms taken.")
        npc = self.npcs.add(
            account,
            target_house_id,
            candidate.name,
            candidate.avatar,
            candidate.traits,
        )
        self._delete(candidate.candidate_id)
        house = self.housing.record_for(target_house_id)
        house_label = self.housing.template_for(house).label if house is not None else "their new home"
        payload = self.candidates_payload(account, target_house_id)
        payload["adopted"] = {
            "id": npc.npc_id,
            "name": npc.name,
            "house_id": target_house_id,
            "house_label": house_label,
        }
        return payload
