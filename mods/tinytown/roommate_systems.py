"""Roommate life systems: dialog context, job readiness, ticks, and banter.

This mixin keeps ``npcs.NpcHouse`` under the first-party size guard. It only
uses attributes initialized by ``NpcHouse.__init__`` and the persistence
helpers defined there.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from mods.tinytown.interests import INTERESTS_BY_ID
from mods.tinytown.jobs import (
    JOB_INTERVAL_SECONDS,
    artist_price,
    artist_title,
    bff_band,
    cleaner_find,
    cook_outputs,
    engineer_payout,
    generate_painting_surface,
    musician_gig,
    positive_band,
    requirement_blurb,
    requirement_met,
    valid_job,
)
from mods.tinytown.needs import (
    count_fixtures,
    describe_needs,
    owner_drift,
    shortfall_kinds,
)
from mods.tinytown.relationships import (
    HOUSE_VIBE_INTERVAL_SECONDS,
    apply_house_tick,
    describe_pair_reason,
)
from server.broadcast import broadcast_room_event
from server.security import utc_now


if TYPE_CHECKING:
    from mods.tinytown.npcs import NpcRecord


LOGGER = logging.getLogger("tinyrooms.mod.tinytown")


def parse_claim_action(action: str) -> tuple[str, str, str] | None:
    """Split a ``tinytown_claim:<npc>:<bucket>:<kind>`` action.

    NPC ids contain a colon (``ttnpc:<uuid>``), so the suffix must be split
    from the right instead of treating every colon as a separator.
    """

    prefix = "tinytown_claim:"
    if not action.startswith(prefix):
        return None
    parts = action[len(prefix):].rsplit(":", 2)
    if len(parts) != 3:
        return None
    npc_id, bucket, kind = (part.strip() for part in parts)
    if not npc_id or not bucket or not kind:
        return None
    return npc_id, bucket, kind


class RoommateSystemsMixin:
    """Dialog context, hourly jobs, reciprocal ticks, and ambient banter."""

    # -- dialog context --------------------------------------------------------

    def _ensure_identity(self, record: NpcRecord) -> NpcRecord:
        """Backfill interests and a job for roommates created before the overhaul."""

        from mods.tinytown.interests import random_interests
        from mods.tinytown.jobs import assign_job

        changes: dict[str, object] = {}
        if record.likes not in INTERESTS_BY_ID or record.dislikes not in INTERESTS_BY_ID:
            likes, dislikes = random_interests(self._random)
            changes["likes"] = record.likes if record.likes in INTERESTS_BY_ID else likes
            changes["dislikes"] = record.dislikes if record.dislikes in INTERESTS_BY_ID else dislikes
            if changes["likes"] == changes["dislikes"]:
                changes["dislikes"] = dislikes if dislikes != changes["likes"] else likes
        if not valid_job(record.job_id):
            changes["job_id"] = assign_job(self._random, record.traits)
        if changes:
            updated = self._with(record, **changes)
            self._write(updated, created=False)
            return updated
        return record

    def _vibe_label(self, source_id: str, target_id: str, describe) -> str:
        if self.vibes is None:
            return describe(0)
        try:
            return describe(self.vibes.get(source_id, target_id))
        except Exception:  # noqa: BLE001 - banter context must never break registration
            return describe(0)

    def _housemate_cards(self, record: NpcRecord, describe) -> list[dict[str, str]]:
        cards: list[dict[str, str]] = []
        for mate in self.records_for_house(record.house_id):
            if mate.npc_id == record.npc_id:
                continue
            cards.append(
                {
                    "name": mate.name,
                    "toward_label": self._vibe_label(record.npc_id, mate.npc_id, describe),
                    "from_label": self._vibe_label(mate.npc_id, record.npc_id, describe),
                    "reason": describe_pair_reason(
                        getattr(record, "likes", ""),
                        getattr(record, "dislikes", ""),
                        getattr(mate, "likes", ""),
                        getattr(mate, "dislikes", ""),
                    ),
                }
            )
        return cards[:3]

    def _house_tag_counts(self, house: object) -> dict[str, int]:
        from collections import Counter

        counts: Counter[str] = Counter()
        for tags in self._house_tag_lists(house):
            counts.update(tags)
        return dict(counts)

    def _house_tag_lists(self, house: object) -> list[tuple[str, ...]]:
        tag_lists: list[tuple[str, ...]] = []
        room_ids = getattr(house, "room_ids", {}) or {}
        for room_id in room_ids.values():
            try:
                props = self.layout.effective_props(str(room_id))
            except (KeyError, ValueError, AttributeError):
                continue
            for prop in props or []:
                try:
                    definition = self.world.props.get(prop.prop_id)
                except (AttributeError, KeyError):
                    continue
                if definition is None:
                    continue
                tag_lists.append(tuple(str(tag) for tag in getattr(definition, "tags", ())))
        return tag_lists

    def _needs_blurb(self, record: NpcRecord) -> str:
        house = self.housing.record_for(record.house_id)
        if house is None:
            return "The house feels fine, as far as I can tell."
        mates = self.records_for_house(record.house_id)
        try:
            counts = count_fixtures(self._house_tag_lists(house))
        except Exception:  # noqa: BLE001 - fixture counting is best effort
            counts = {"beds": 0, "toilets": 0, "baths": 0}
        return describe_needs(counts, len(mates))

    def _job_gate_blurb(self, record: NpcRecord) -> str:
        house = self.housing.record_for(record.house_id)
        tag_counts = self._house_tag_counts(house) if house is not None else {}
        if not requirement_met(record.job_id, tag_counts):
            return f"I still need {requirement_blurb(record.job_id)}."
        if self.vibes is not None:
            try:
                score = int(self.vibes.get(record.owner_account_id, record.npc_id))
            except Exception:  # noqa: BLE001 - vibe gating is best effort
                score = 0
            if not positive_band(score):
                if bff_band(score):
                    detail = "we are the very best of friends"
                elif score >= 26:
                    detail = "we are getting on swimmingly"
                else:
                    detail = "we are still getting to know each other"
                return f"the workshop is fine, but {detail} first."
        return "everything is in place and I'm raring to go."

    def _job_dialog_state(self, record: NpcRecord) -> str:
        if not valid_job(record.job_id):
            return "resting"
        if record.job_claim_json:
            return "ready"
        return "waiting"

    def _job_ready_payload(self, record: NpcRecord) -> dict[str, object] | None:
        if not record.job_claim_json:
            return None
        try:
            payload = json.loads(record.job_claim_json)
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    # -- dialog settlement ---------------------------------------------------

    def on_dialog_choice(self, account: object, peep_id: str, choice: object) -> None:
        """Settle roommate job claims after a dialog commits."""

        action = str(getattr(choice, "action", "") or "")
        if action.startswith("tinytown_claim:"):
            self._settle_claim(account, peep_id, action)

    def _settle_claim(self, account: object, peep_id: str, action: str) -> None:
        parsed = parse_claim_action(action)
        if parsed is None:
            return
        npc_id, bucket, kind = parsed
        if npc_id != peep_id:
            return
        record = self.record_for(npc_id)
        if record is None:
            return
        payload = self._job_ready_payload(record)
        if not isinstance(payload, dict) or str(payload.get("bucket")) != str(bucket):
            return
        try:
            if kind == "art":
                self._list_npc_painting(account, record, payload)
            elif kind == "routine":
                self._run_comedian_routine(record)
        except Exception:  # noqa: BLE001 - settlement failures must not break dialog
            LOGGER.exception("tinytown.claim_settlement_failed")
        cleared = self._with(
            record,
            job_claim_json="",
            job_ready_at="",
            job_cooldown_until=self._shift_iso(utc_now().isoformat(), JOB_INTERVAL_SECONDS),
        )
        self._write(cleared, created=False)
        self._register_peep(cleared)

    def _list_npc_painting(self, account: object, record: NpcRecord, payload: dict[str, object]) -> None:
        market = self.housing.market
        title = str(payload.get("title") or artist_title(self._random, record.name))
        price = payload.get("price")
        try:
            price_value = int(price) if price is not None else artist_price(0)
        except (TypeError, ValueError):
            price_value = artist_price(0)
        surface = payload.get("surface")
        if not isinstance(surface, dict):
            surface = generate_painting_surface(self._random, record.name)
        bucket = str(payload.get("bucket") or "0")
        market.list_generated(
            account,
            source_room_id=record.room_id,
            title=title,
            description=f"Painted by {record.name}, resident easel artist.",
            price=price_value,
            surface=surface,
            source_instance_id=f"npcpaint:{record.npc_id}:{bucket}",
        )

    def _run_comedian_routine(self, record: NpcRecord) -> None:
        if self.vibes is None:
            return
        mates = [mate for mate in self.records_for_house(record.house_id) if mate.npc_id != record.npc_id]
        deltas = [(record.npc_id, mate.npc_id, 2) for mate in mates]
        deltas += [(mate.npc_id, record.npc_id, 1) for mate in mates]
        if deltas:
            self.vibes.adjust_many(deltas)

    # -- house clocks, jobs, and banter --------------------------------------

    def _accumulate_house_clocks(self, house_id: str, elapsed: float) -> None:
        self._relationship_accum[house_id] = self._relationship_accum.get(house_id, 0.0) + elapsed

    def _run_house_ticks(self, houses: dict[str, object], moment: object) -> None:
        moment_iso = moment.isoformat() if hasattr(moment, "isoformat") else str(moment)
        for house_id, house in houses.items():
            if house is None:
                continue
            if self._relationship_accum.get(house_id, 0.0) < HOUSE_VIBE_INTERVAL_SECONDS:
                continue
            self._relationship_accum[house_id] = 0.0
            self._apply_relationship_tick(house_id, house)
            self._apply_job_readiness(house_id, house, moment_iso)

    async def _emit_banter(self, houses: dict[str, object], occupied: set[str]) -> None:
        from mods.tinytown.banter import BANTER_CHANCE, BANTER_COOLDOWN_SECONDS, choose_banter

        now_ts = utc_now().timestamp()
        for house_id in houses:
            records = self.records_for_house(house_id)
            if len(records) < 2:
                continue
            rooms = {record.room_id for record in records} & occupied
            if not rooms:
                continue
            room_id = sorted(rooms)[0]
            last = self._last_banter.get(room_id, 0.0)
            try:
                last = float(last)
            except (TypeError, ValueError):
                last = 0.0
            if now_ts - last < BANTER_COOLDOWN_SECONDS:
                continue
            if self._random.random() > BANTER_CHANCE:
                continue
            outgoing: dict[str, dict[str, int]] = {}
            if self.vibes is not None:
                for record in records:
                    try:
                        outgoing[record.npc_id] = self.vibes.outgoing(record.npc_id)
                    except Exception:  # noqa: BLE001 - banter is best effort
                        outgoing[record.npc_id] = {}
            text = choose_banter(self._random, records, outgoing)
            if not text:
                continue
            speaker = records[0]
            self._last_banter[room_id] = now_ts
            self.world_state.append_chat_message(
                room_id,
                {"speaker_id": speaker.npc_id, "speaker": speaker.name, "style": "expression", "text": text},
            )
            await broadcast_room_event(
                self.runtime,
                room_id=room_id,
                event={
                    "type": "emote.bubble",
                    "room_id": room_id,
                    "source_id": speaker.npc_id,
                    "speaker_id": speaker.npc_id,
                    "source": speaker.name,
                    "bubble": {"kind": "expression", "text": text},
                    "card_id": None,
                },
            )

    def _apply_relationship_tick(self, house_id: str, house: object) -> None:
        records = self.records_for_house(house_id)
        if not records:
            return
        comedian_ids = self._warm_comedians(records)
        apply_house_tick(self.vibes, records, comedian_ids=comedian_ids)
        try:
            mates = self.records_for_house(house_id)
            counts = count_fixtures(self._house_tag_lists(house))
        except Exception:  # noqa: BLE001 - needs drift is best effort
            return
        drift = owner_drift(shortfall_kinds(counts, len(mates)))
        if drift and self.vibes is not None:
            owner = mates[0].owner_account_id if mates else None
            if owner is not None:
                self.vibes.adjust_many([(mate.npc_id, owner, drift) for mate in mates])
        for record in self.records_for_house(house_id):
            self._register_peep(record)

    def _warm_comedians(self, records: list[NpcRecord]) -> set[str]:
        """Return comedian NPCs in good spirits whose presence softens friction."""

        if self.vibes is None:
            return set()
        warm: set[str] = set()
        for record in records:
            if record.job_id != "comedian":
                continue
            try:
                score = int(self.vibes.get(record.npc_id, record.owner_account_id))
            except Exception:  # noqa: BLE001 - aura checks are best effort
                continue
            if positive_band(score):
                warm.add(record.npc_id)
        return warm

    def _apply_job_readiness(self, house_id: str, house: object, moment_iso: str) -> None:
        for record in self.records_for_house(house_id):
            updated = self._maybe_ready_job(record, house, moment_iso)
            if updated is not None:
                self._register_peep(updated)

    def _recipe_outputs(self) -> list[str]:
        catalog = getattr(self.runtime, "catalog", None)
        recipes = getattr(catalog, "recipes", {}) or {}
        outputs: list[str] = []
        for recipe in recipes.values():
            for ingredient in getattr(recipe, "output", ()):
                card_id = str(getattr(ingredient, "card_id", ""))
                if card_id:
                    outputs.append(card_id)
        return outputs

    @staticmethod
    def _hour_bucket(moment_iso: str) -> int:
        from datetime import datetime

        try:
            moment = datetime.fromisoformat(str(moment_iso))
        except (TypeError, ValueError):
            return 0
        return int(moment.timestamp() // 3600)

    @staticmethod
    def _iso_in_future(value: str, moment_iso: str) -> bool:
        return bool(value) and str(value) > str(moment_iso)

    def _maybe_ready_job(self, record: NpcRecord, house: object, moment_iso: str) -> NpcRecord | None:
        """Create an hourly job payload when workshop and vibes allow it."""

        if not valid_job(record.job_id):
            return None
        if record.job_claim_json:
            return None
        if self._iso_in_future(record.job_cooldown_until, moment_iso):
            return None
        tag_counts = self._house_tag_counts(house)
        if not requirement_met(record.job_id, tag_counts):
            self._write(
                self._with(record, job_cooldown_until=self._shift_iso(moment_iso, 600.0)),
                created=False,
            )
            return None
        score = 0
        if self.vibes is not None:
            try:
                score = int(self.vibes.get(record.owner_account_id, record.npc_id))
            except Exception:  # noqa: BLE001 - vibe gating is best effort
                score = 0
        if not positive_band(score):
            self._write(
                self._with(record, job_cooldown_until=self._shift_iso(moment_iso, 600.0)),
                created=False,
            )
            return None
        bucket = self._hour_bucket(moment_iso)
        payload: dict[str, object] = {"bucket": bucket}
        if record.job_id == "cook":
            dishes = cook_outputs(self._recipe_outputs(), self._random, generous=bff_band(score))
            if not dishes:
                return None
            payload["cards"] = dishes
        elif record.job_id == "engineer":
            payload["bops"] = engineer_payout(self._random, score)
        elif record.job_id == "cleaner":
            catalog = getattr(self.runtime, "catalog", None)
            known = set(getattr(catalog, "cards", {}) or {})
            pool = [card for card in self._cleaner_pool() if card in known] or list(self._cleaner_pool())
            payload["cards"] = [cleaner_find(pool, self._random)]
        elif record.job_id == "musician":
            set_name, verdict, payout = musician_gig(self._random, score)
            payload.update({"bops": payout, "set_name": set_name, "verdict": verdict})
        elif record.job_id == "artist":
            payload.update(
                {
                    "title": artist_title(self._random, record.name),
                    "price": artist_price(score),
                    "surface": generate_painting_surface(self._random, record.name),
                }
            )
        elif record.job_id == "comedian":
            payload["routine"] = True
        updated = self._with(
            record,
            job_claim_json=json.dumps(payload),
            job_ready_at=moment_iso,
        )
        self._write(updated, created=False)
        return updated

    def _cleaner_pool(self) -> list[str]:
        from mods.tinytown.jobs import CLEANER_CARD_POOL

        return list(CLEANER_CARD_POOL)

    @staticmethod
    def _shift_iso(moment_iso: str, seconds: float) -> str:
        from datetime import datetime, timedelta

        try:
            moment = datetime.fromisoformat(str(moment_iso))
        except (TypeError, ValueError):
            return str(moment_iso)
        return (moment + timedelta(seconds=float(seconds))).isoformat()
