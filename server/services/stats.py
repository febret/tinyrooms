"""Server-authoritative stats, counters, Energy, buffs, and status reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3

from server.content.cards import CardCatalog
from server.content.gameplay import GameplayContent
from server.game.buffs import BuffInstance, active_modifiers, expire
from server.game.modifiers import Modifier, bonuses_to_modifiers, clamp_counter
from server.game.state import EffectivePeepState, compute_effective_state
from server.profiles import AccountRecord, ProfileRepository, UserProfileRecord
from server.security import utc_now
from server.state.migrations import DatabaseHub

BASE_HEALTH_FALLBACK = 50.0
BASE_CLEANLINESS_FALLBACK = 100.0
NON_EQUIP_TYPES = frozenset({"emote", "core", "skill"})


@dataclass(frozen=True, slots=True)
class PeepSnapshot:
    """A consistent view of an account's effective state and counters."""

    account: AccountRecord
    effective: EffectivePeepState
    health: float
    energy: float
    cleanliness: float

    @property
    def statuses(self) -> tuple[str, ...]:
        """Return the active status ids."""

        return self.effective.statuses

    def payload(self) -> dict[str, object]:
        """Serialize counters and effective state for the client."""

        return {
            "health": self.health,
            "energy": self.energy,
            "cleanliness": self.cleanliness,
            "max_health": self.effective.max_health,
            "max_energy": self.effective.max_energy,
            "max_cleanliness": self.effective.max_cleanliness,
            "stats": self.effective.stats,
            "statuses": list(self.effective.statuses),
        }


def normalize_counters(raw: object) -> dict[str, float]:
    """Coerce persisted world counters into the canonical {health, cleanliness} shape."""

    if not isinstance(raw, dict):
        return {"health": BASE_HEALTH_FALLBACK, "cleanliness": BASE_CLEANLINESS_FALLBACK}
    health = raw.get("health", raw.get("max_health", BASE_HEALTH_FALLBACK))
    cleanliness = raw.get("cleanliness", raw.get("max_cleanliness", BASE_CLEANLINESS_FALLBACK))
    try:
        health_value = float(health)
        cleanliness_value = float(cleanliness)
    except (TypeError, ValueError):
        return {"health": BASE_HEALTH_FALLBACK, "cleanliness": BASE_CLEANLINESS_FALLBACK}
    return {"health": max(0.0, health_value), "cleanliness": max(0.0, cleanliness_value)}


def parse_timestamp(value: str) -> datetime | None:
    """Parse a stored ISO timestamp, returning None when malformed."""

    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class StatsService:
    """Owns effective-state calculation and all counter/Energy mutations."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        catalog: CardCatalog,
        content: GameplayContent,
        world_id: str,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._catalog = catalog
        self._content = content
        self._world_id = world_id

    @property
    def content(self) -> GameplayContent:
        """Expose loaded gameplay content to sibling services."""

        return self._content

    def _card_modifiers(self, account_id: str, profile: UserProfileRecord) -> tuple[Modifier, ...]:
        stacks = {stack.stack_id: stack for stack in self._profiles.list_inventory(account_id, self._world_id)}
        modifiers: list[Modifier] = []
        for stack in stacks.values():
            if not stack.equipped:
                continue
            definition = self._catalog.cards.get(stack.card_def_id)
            if definition is None or definition.type in NON_EQUIP_TYPES:
                continue
            modifiers.extend(bonuses_to_modifiers(definition.bonuses, multiplier=stack.quantity))
        slot_counts: dict[str, int] = {}
        for stack_id in profile.skills:
            if stack_id is None:
                continue
            slot_counts[stack_id] = slot_counts.get(stack_id, 0) + 1
        for stack_id, count in slot_counts.items():
            stack = stacks.get(stack_id)
            if stack is None:
                continue
            definition = self._catalog.cards.get(stack.card_def_id)
            if definition is None:
                continue
            # A single owned copy can only ever fill one slot.
            effective = min(count, stack.quantity)
            modifiers.extend(bonuses_to_modifiers(definition.bonuses, multiplier=effective))
        return tuple(modifiers)

    def _buff_instances(self, profile: UserProfileRecord) -> list[BuffInstance]:
        raw = profile.buffs.get("instances") if isinstance(profile.buffs, dict) else None
        if not isinstance(raw, list):
            return []
        instances: list[BuffInstance] = []
        for entry in raw:
            if isinstance(entry, dict) and entry.get("expires_at"):
                try:
                    instances.append(BuffInstance.from_payload(entry))
                except (KeyError, ValueError):
                    continue
        return instances

    def collect_modifiers(self, account_id: str, profile: UserProfileRecord, now: datetime) -> tuple[Modifier, ...]:
        """Combine equipment, slotted skills, and active buffs into modifiers."""

        instances = expire(self._buff_instances(profile), now)
        return (*self._card_modifiers(account_id, profile), *active_modifiers(instances, now))

    def compute_state(
        self,
        account: AccountRecord,
        profile: UserProfileRecord,
        *,
        now: datetime | None = None,
        energy: float | None = None,
    ) -> EffectivePeepState:
        """Compute effective state without persisting anything."""

        moment = now or utc_now()
        counters = normalize_counters(profile.counters)
        current_energy = account.shared_energy if energy is None else energy
        modifiers = self.collect_modifiers(account.id, profile, moment)
        return compute_effective_state(
            self._content,
            level=account.level,
            counters={**counters, "energy": current_energy},
            previous_statuses=profile.active_statuses,
            modifiers=modifiers,
        )

    def _recharge_energy(
        self,
        account: AccountRecord,
        profile: UserProfileRecord,
        now: datetime,
    ) -> tuple[float, str]:
        """Accrue whole minutes of recovery and return (energy, last_energy_at).

        Recovering in whole-minute steps keeps Energy at exactly zero until a
        full minute passes, so Tired applies and clears per the design.
        """

        last = parse_timestamp(account.last_energy_at)
        if last is None:
            return account.shared_energy, account.last_energy_at
        whole_minutes = int(max(0.0, (now - last).total_seconds()) // 60)
        if whole_minutes <= 0:
            return account.shared_energy, account.last_energy_at
        maximum = self.compute_state(account, profile, now=now).max_energy
        gained = whole_minutes * self._content.juice.energy_recharge_rate
        energy = min(float(maximum), account.shared_energy + gained)
        advanced = last + timedelta(minutes=whole_minutes)
        return energy, advanced.isoformat()

    def _reconcile(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        *,
        now: datetime,
    ) -> PeepSnapshot:
        account = self._profiles.get_account_by_id(account_id)
        profile = self._profiles.get_user_profile(account_id)
        if account is None or profile is None:
            raise ValueError("Unknown account.")
        energy, last_energy_at = self._recharge_energy(account, profile, now)
        state = self.compute_state(account, profile, now=now, energy=energy)
        counters = normalize_counters(profile.counters)
        health = clamp_counter(counters["health"], state.max_health)
        cleanliness = clamp_counter(counters["cleanliness"], state.max_cleanliness)
        if energy != account.shared_energy or last_energy_at != account.last_energy_at:
            self._profiles.update_account_progress(
                connection,
                account_id,
                level=account.level,
                kudos=account.kudos,
                bops=account.bops,
                energy=energy,
                last_energy_at=last_energy_at,
                last_daily_claim=account.last_daily_claim,
            )
            account = self._profiles.get_account_by_id(account_id) or account
        if health != counters["health"] or cleanliness != counters["cleanliness"]:
            self._profiles.write_counters(connection, account_id, {"health": health, "cleanliness": cleanliness})
        if tuple(state.statuses) != profile.active_statuses:
            self._profiles.update_profile_in_transaction(
                connection,
                account_id,
                lambda data: data.__setitem__("statuses", list(state.statuses)),
            )
        return PeepSnapshot(
            account=account,
            effective=state,
            health=health,
            energy=energy,
            cleanliness=cleanliness,
        )

    def reconcile(self, account_id: str) -> PeepSnapshot:
        """Recharge, clamp, and reconcile statuses inside one transaction."""

        with self._hub.transaction() as connection:
            return self._reconcile(connection, account_id, now=utc_now())

    def snapshot(self, account_id: str) -> PeepSnapshot:
        """Return a reconciled snapshot without mutating beyond required writes."""

        return self.reconcile(account_id)

    def reconcile_in_transaction(self, connection: sqlite3.Connection, account_id: str) -> PeepSnapshot:
        """Reconcile Energy and statuses inside a caller-owned transaction."""

        return self._reconcile(connection, account_id, now=utc_now())

    def mutate(
        self,
        account_id: str,
        *,
        health_delta: float = 0.0,
        cleanliness_delta: float = 0.0,
        energy_delta: float = 0.0,
    ) -> PeepSnapshot:
        """Apply counter deltas, discarding overflow beyond maximums."""

        with self._hub.transaction() as connection:
            snapshot = self._reconcile(connection, account_id, now=utc_now())
            health = clamp_counter(snapshot.health + health_delta, snapshot.effective.max_health)
            cleanliness = clamp_counter(
                snapshot.cleanliness + cleanliness_delta, snapshot.effective.max_cleanliness
            )
            energy = clamp_counter(snapshot.energy + energy_delta, snapshot.effective.max_energy)
            return self._persist_counters(connection, snapshot, health, energy, cleanliness)

    def spend_energy(
        self,
        account_id: str,
        amount: float,
        *,
        allow_while_tired: bool = False,
    ) -> PeepSnapshot:
        """Charge Energy transactionally, rejecting without cost when unaffordable."""

        with self._hub.transaction() as connection:
            return self._charge_energy(connection, account_id, amount, allow_while_tired=allow_while_tired)

    def charge_in_transaction(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        amount: float,
        *,
        allow_while_tired: bool = False,
    ) -> PeepSnapshot:
        """Charge Energy inside a caller-owned transaction."""

        return self._charge_energy(connection, account_id, amount, allow_while_tired=allow_while_tired)

    def _charge_energy(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        amount: float,
        *,
        allow_while_tired: bool,
    ) -> PeepSnapshot:
        snapshot = self._reconcile(connection, account_id, now=utc_now())
        if "tired" in snapshot.statuses and not allow_while_tired:
            raise ValueError("You are too tired for that. Rest up first.")
        if amount > snapshot.energy:
            raise ValueError("You do not have enough Energy for that.")
        energy = clamp_counter(snapshot.energy - max(0.0, amount), snapshot.effective.max_energy)
        return self._persist_counters(connection, snapshot, snapshot.health, energy, snapshot.cleanliness)

    def apply_in_transaction(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        *,
        health_delta: float = 0.0,
        cleanliness_delta: float = 0.0,
        energy_delta: float = 0.0,
    ) -> PeepSnapshot:
        """Apply counter deltas inside a caller-owned transaction."""

        snapshot = self._reconcile(connection, account_id, now=utc_now())
        health = clamp_counter(snapshot.health + health_delta, snapshot.effective.max_health)
        cleanliness = clamp_counter(
            snapshot.cleanliness + cleanliness_delta, snapshot.effective.max_cleanliness
        )
        energy = clamp_counter(snapshot.energy + energy_delta, snapshot.effective.max_energy)
        return self._persist_counters(connection, snapshot, health, energy, cleanliness)

    def _persist_counters(
        self,
        connection: sqlite3.Connection,
        snapshot: PeepSnapshot,
        health: float,
        energy: float,
        cleanliness: float,
    ) -> PeepSnapshot:
        now = utc_now()
        profile = self._profiles.get_user_profile(snapshot.account.id)
        if profile is None:
            raise ValueError("Unknown account.")
        counters = {"health": health, "cleanliness": cleanliness}
        modifiers = self.collect_modifiers(snapshot.account.id, profile, now)
        state = compute_effective_state(
            self._content,
            level=snapshot.account.level,
            counters={**counters, "energy": energy},
            previous_statuses=snapshot.statuses,
            modifiers=modifiers,
        )
        health = clamp_counter(health, state.max_health)
        cleanliness = clamp_counter(cleanliness, state.max_cleanliness)
        energy = clamp_counter(energy, state.max_energy)
        self._profiles.write_counters(
            connection, snapshot.account.id, {"health": health, "cleanliness": cleanliness}
        )
        self._profiles.update_account_progress(
            connection,
            snapshot.account.id,
            level=snapshot.account.level,
            kudos=snapshot.account.kudos,
            bops=snapshot.account.bops,
            energy=energy,
            last_energy_at=now.isoformat(),
            last_daily_claim=snapshot.account.last_daily_claim,
        )
        if tuple(state.statuses) != profile.active_statuses:
            self._profiles.update_profile_in_transaction(
                connection,
                snapshot.account.id,
                lambda data: data.__setitem__("statuses", list(state.statuses)),
            )
        account = self._profiles.get_account_by_id(snapshot.account.id)
        return PeepSnapshot(
            account=account or snapshot.account,
            effective=state,
            health=health,
            energy=energy,
            cleanliness=cleanliness,
        )

    def add_buff(self, account_id: str, instance: BuffInstance) -> PeepSnapshot:
        """Apply a buff instance and return the updated snapshot."""

        from server.game.buffs import apply_buff

        now = utc_now()
        with self._hub.transaction() as connection:
            self._reconcile(connection, account_id, now=now)
            profile = self._profiles.get_user_profile(account_id)
            if profile is None:
                raise ValueError("Unknown account.")
            result = apply_buff(self._buff_instances(profile), instance, now)
            self._profiles.write_buffs(connection, account_id, [item.to_payload() for item in result])
            return self._reconcile(connection, account_id, now=now)
