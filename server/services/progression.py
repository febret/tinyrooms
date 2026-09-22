"""Progression: levels, Kudos, Bops, skill slots, and the reward ledger."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3

from server.content.cards import CardCatalog
from server.content.gameplay import GameplayContent
from server.profiles import AccountRecord, ProfileRepository
from server.security import utc_now
from server.services.stats import PeepSnapshot, StatsService
from server.state.migrations import DatabaseHub

SKILL_RANKS = ("Script Kiddo", "Hacker", "Leet")
SKILL_SLOTS_PER_RANK = 5
MAX_SKILL_SLOTS = len(SKILL_RANKS) * SKILL_SLOTS_PER_RANK


@dataclass(frozen=True, slots=True)
class SkillSlot:
    """A single skill-grid slot and its occupant stack, if any."""

    index: int
    rank: str
    unlocked: bool
    stack_id: str | None


@dataclass(frozen=True, slots=True)
class LevelUpResult:
    """Outcome of an explicit level-up."""

    account: AccountRecord
    snapshot: PeepSnapshot
    spent: int


class ProgressionService:
    """Owns level transitions, currencies, skill slotting, and reward idempotency."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        stats: StatsService,
        catalog: CardCatalog,
        content: GameplayContent,
        world_id: str,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._stats = stats
        self._catalog = catalog
        self._content = content
        self._world_id = world_id

    def _rank_index(self, rank: str | None) -> int:
        if rank in SKILL_RANKS:
            return SKILL_RANKS.index(rank)
        return 0

    def skill_slots(self, account: AccountRecord, profile) -> list[SkillSlot]:
        """Return all skill slots with lock state and occupants."""

        stored = list(profile.skills)
        slots: list[SkillSlot] = []
        for index in range(MAX_SKILL_SLOTS):
            rank = SKILL_RANKS[index // SKILL_SLOTS_PER_RANK]
            occupant = stored[index] if index < len(stored) else None
            slots.append(
                SkillSlot(
                    index=index,
                    rank=rank,
                    unlocked=index < account.level,
                    stack_id=occupant,
                )
            )
        return slots

    def _write_skills(self, connection: sqlite3.Connection, account_id: str, slots: list[str | None]) -> None:
        self._profiles.update_profile_in_transaction(
            connection,
            account_id,
            lambda data: data.__setitem__("skills", slots),
        )

    def slot_skill(self, account: AccountRecord, slot_index: int, stack_id: str) -> PeepSnapshot:
        """Place one owned skill copy into an unlocked, eligible slot."""

        with self._hub.transaction() as connection:
            profile = self._profiles.get_user_profile(account.id)
            if profile is None:
                raise ValueError("Unknown account.")
            if slot_index < 0 or slot_index >= MAX_SKILL_SLOTS:
                raise ValueError("That skill slot does not exist.")
            if slot_index >= account.level:
                raise ValueError("That skill slot is still locked.")
            stack = self._profiles.get_inventory_stack(account.id, self._world_id, stack_id)
            if stack is None:
                raise ValueError("That skill card is not in your inventory.")
            definition = self._catalog.cards.get(stack.card_def_id)
            if definition is None or definition.type != "skill":
                raise ValueError("Only skill cards can fill skill slots.")
            slot_rank = slot_index // SKILL_SLOTS_PER_RANK
            if slot_rank < self._rank_index(definition.rank):
                raise ValueError(f"{definition.label} needs a higher-rank slot.")
            stored = list(profile.skills)
            while len(stored) < MAX_SKILL_SLOTS:
                stored.append(None)
            existing = sum(1 for entry in stored if entry == stack_id)
            if existing >= stack.quantity:
                raise ValueError("All copies of that skill are already slotted.")
            stored[slot_index] = stack_id
            self._write_skills(connection, account.id, stored)
            return self._stats.reconcile_in_transaction(connection, account.id)

    def remove_skill(self, account: AccountRecord, slot_index: int) -> PeepSnapshot:
        """Remove and free a slotted skill for free."""

        with self._hub.transaction() as connection:
            profile = self._profiles.get_user_profile(account.id)
            if profile is None:
                raise ValueError("Unknown account.")
            if slot_index < 0 or slot_index >= MAX_SKILL_SLOTS:
                raise ValueError("That skill slot does not exist.")
            stored = list(profile.skills)
            while len(stored) < MAX_SKILL_SLOTS:
                stored.append(None)
            if not stored[slot_index]:
                raise ValueError("That skill slot is already empty.")
            stored[slot_index] = None
            self._write_skills(connection, account.id, stored)
            return self._stats.reconcile_in_transaction(connection, account.id)

    def level_up(self, account: AccountRecord) -> LevelUpResult:
        """Spend only the Kudos required for the next level, retaining surplus."""

        if account.level >= self._content.levels.max_level:
            raise ValueError("You are already at the highest level.")
        cost = self._content.levels.kudos_to_next(account.level)
        if cost is None:
            raise ValueError("You are already at the highest level.")
        if account.kudos < cost:
            raise ValueError(f"You need {cost - account.kudos} more Kudos to level up.")
        with self._hub.transaction() as connection:
            current = self._profiles.get_account_by_id(account.id)
            if current is None:
                raise ValueError("Unknown account.")
            if current.level >= self._content.levels.max_level:
                raise ValueError("You are already at the highest level.")
            updated = self._profiles.update_account_progress(
                connection,
                account.id,
                level=current.level + 1,
                kudos=current.kudos - cost,
                bops=current.bops,
                energy=current.shared_energy,
                last_energy_at=current.last_energy_at,
                last_daily_claim=current.last_daily_claim,
            )
            snapshot = self._stats.reconcile_in_transaction(connection, account.id)
        return LevelUpResult(account=updated, snapshot=snapshot, spent=cost)

    def claim_daily_bops(self, account: AccountRecord) -> tuple[int, AccountRecord]:
        """Grant the once-per-game-day Bops allowance at the claim-time level."""

        now = utc_now()
        today = now.date().isoformat()
        if account.last_daily_claim is not None and str(account.last_daily_claim)[:10] == today:
            raise ValueError("You have already claimed your Daily Bops today.")
        amount = self._content.bops.daily_bops(account.level)
        with self._hub.transaction() as connection:
            current = self._profiles.get_account_by_id(account.id)
            if current is None:
                raise ValueError("Unknown account.")
            if current.last_daily_claim is not None and str(current.last_daily_claim)[:10] == today:
                raise ValueError("You have already claimed your Daily Bops today.")
            updated = self._profiles.update_account_progress(
                connection,
                account.id,
                level=current.level,
                kudos=current.kudos,
                bops=current.bops + amount,
                energy=current.shared_energy,
                last_energy_at=current.last_energy_at,
                last_daily_claim=now.isoformat(),
            )
        return amount, updated

    def grant_kudos(
        self,
        account_id: str,
        amount: int,
        *,
        ledger_key: str | None = None,
        kind: str = "kudos",
    ) -> bool:
        """Grant Kudos, optionally exactly once via the reward ledger."""

        if ledger_key:
            return self.reward_once(account_id, ledger_key, kudos=amount, kind=kind)
        return self._grant(account_id, kudos=amount, cards=(), ledger_key=None, kind=kind)

    def reward_once(
        self,
        account_id: str,
        ledger_key: str,
        *,
        kudos: int = 0,
        cards: tuple[str, ...] | list[str] = (),
        kind: str = "reward",
    ) -> bool:
        """Apply a reward exactly once, returning False on a duplicate."""

        return self._grant(
            account_id,
            kudos=kudos,
            cards=tuple(cards),
            ledger_key=ledger_key,
            kind=kind,
        )

    def has_reward(self, account_id: str, ledger_key: str) -> bool:
        """Return whether a ledger key has already been granted."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT 1 FROM reward_ledger WHERE ledger_key = ? AND account_id = ?",
                (ledger_key, account_id),
            ).fetchone()
        return row is not None

    def _grant(
        self,
        account_id: str,
        *,
        kudos: int,
        cards: tuple[str, ...],
        ledger_key: str | None,
        kind: str,
    ) -> bool:
        now = utc_now()
        with self._hub.transaction() as connection:
            if ledger_key is not None:
                existing = connection.execute(
                    "SELECT 1 FROM reward_ledger WHERE ledger_key = ? AND account_id = ?",
                    (ledger_key, account_id),
                ).fetchone()
                if existing is not None:
                    return False
            account = self._profiles.get_account_by_id(account_id)
            if account is None:
                raise ValueError("Unknown account.")
            if ledger_key is not None:
                connection.execute(
                    """
                    INSERT INTO reward_ledger (ledger_key, account_id, world_id, kind, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ledger_key,
                        account_id,
                        self._world_id,
                        kind,
                        json.dumps({"kudos": kudos, "cards": list(cards)}),
                        now.isoformat(),
                    ),
                )
            for card_id in cards:
                self._grant_card(connection, account_id, card_id)
            updated_kudos = account.kudos + kudos
            self._profiles.update_account_progress(
                connection,
                account_id,
                level=account.level,
                kudos=updated_kudos,
                bops=account.bops,
                energy=account.shared_energy,
                last_energy_at=account.last_energy_at,
                last_daily_claim=account.last_daily_claim,
            )
        return True

    def _grant_card(self, connection: sqlite3.Connection, account_id: str, card_id: str) -> None:
        definition = self._catalog.cards.get(card_id)
        if definition is None:
            raise ValueError(f"Unknown reward card '{card_id}'.")
        if not definition.collectible:
            raise ValueError(f"Core card '{card_id}' cannot be granted as a reward.")
        scope = "world" if definition.source == self._world_id else "global"
        world_id = self._world_id if scope == "world" else None
        self._profiles.add_inventory_card(
            connection,
            account_id=account_id,
            world_id=world_id,
            card_def_id=card_id,
            quantity=1,
            scope=scope,
            stack_limit=definition.stack_limit,
        )
