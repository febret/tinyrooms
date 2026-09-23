"""User powers and world-local moderation state."""

from __future__ import annotations

from datetime import datetime, timedelta
import json

from server.content.worlds import POWER_NAMES, WorldDefinition
from server.profiles import AccountRecord, ProfileRepository
from server.security import utc_now
from server.services.audit import AuditService
from server.state.migrations import DatabaseHub


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _parse_powers(value: object) -> set[str]:
    if not isinstance(value, str):
        return set()
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return set()
    if not isinstance(parsed, list):
        return set()
    return {str(power) for power in parsed}


class PowersService:
    """Resolves effective powers and enforces world-local moderation state.

    Powers come from three sources: the world definition's ``powers:`` mapping,
    the ``TRSERVER_ADMINS`` bootstrap list, and explicit grants stored in the
    ``powers`` column of the ``accounts`` table. Grant and revoke changes are
    recorded in the audit log.
    """

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        world: WorldDefinition,
        bootstrap_admins: frozenset[str],
        audit: AuditService,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._world = world
        self._bootstrap_admins = frozenset(bootstrap_admins)
        self._audit = audit

    def _world_powers_for(self, account: AccountRecord) -> frozenset[str]:
        return frozenset(self._world.powers.get(account.username_key, ()))

    def _db_powers_for(self, account_id: str) -> frozenset[str]:
        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT powers FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        if row is None:
            return frozenset()
        return frozenset(_parse_powers(row["powers"]))

    def effective(self, account: AccountRecord) -> frozenset[str]:
        """Return every power an account holds in the active world."""

        powers = set(self._world_powers_for(account))
        powers.update(self._db_powers_for(account.id))
        if account.username_key in self._bootstrap_admins:
            powers.add("admin")
        return frozenset(power for power in powers if power in POWER_NAMES)

    def has_power(self, account_id: str, power: str) -> bool:
        """Return whether an account holds *power* in the active world."""

        account = self._profiles.get_account_by_id(account_id)
        if account is None:
            return False
        return power in self.effective(account)

    def grant(self, actor_id: str, target_account_id: str, power: str) -> None:
        """Grant a power, writing an audit entry."""

        if power not in POWER_NAMES:
            raise ValueError(f"Unknown power '{power}'.")
        try:
            with self._hub.transaction() as connection:
                row = connection.execute(
                    "SELECT powers FROM accounts WHERE id = ?",
                    (target_account_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("Unknown account.")
                powers = _parse_powers(row["powers"])
                powers.add(power)
                connection.execute(
                    "UPDATE accounts SET powers = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(sorted(powers)), utc_now().isoformat(), target_account_id),
                )
        except Exception:
            self._audit.safe_record(actor_id, f"power.grant.{power}", target_account_id, "error")
            raise
        self._audit.safe_record(actor_id, f"power.grant.{power}", target_account_id, "ok")

    def revoke(self, actor_id: str, target_account_id: str, power: str) -> None:
        """Revoke a granted power, writing an audit entry."""

        try:
            with self._hub.transaction() as connection:
                row = connection.execute(
                    "SELECT powers FROM accounts WHERE id = ?",
                    (target_account_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("Unknown account.")
                powers = _parse_powers(row["powers"])
                powers.discard(power)
                connection.execute(
                    "UPDATE accounts SET powers = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(sorted(powers)), utc_now().isoformat(), target_account_id),
                )
        except Exception:
            self._audit.safe_record(actor_id, f"power.revoke.{power}", target_account_id, "error")
            raise
        self._audit.safe_record(actor_id, f"power.revoke.{power}", target_account_id, "ok")

    def is_muted(self, account_id: str) -> bool:
        """Return whether the account is currently muted."""

        return self.mute_until(account_id) is not None

    def mute_until(self, account_id: str) -> datetime | None:
        """Return the mute expiry instant, if the account is muted."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT muted_until FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        if row is None:
            return None
        muted_until = _parse_timestamp(row["muted_until"])
        if muted_until is None or muted_until <= utc_now():
            return None
        return muted_until

    def mute(self, actor_id: str, target_account_id: str, minutes: int) -> datetime:
        """Mute an account for *minutes*, writing an audit entry."""

        if minutes < 1:
            raise ValueError("Mute duration must be at least one minute.")
        until = utc_now() + timedelta(minutes=minutes)
        try:
            with self._hub.transaction() as connection:
                updated = connection.execute(
                    """
                    UPDATE accounts
                    SET muted_until = ?, muted_by = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (until.isoformat(), actor_id, utc_now().isoformat(), target_account_id),
                ).rowcount
                if not updated:
                    raise ValueError("Unknown account.")
        except Exception:
            self._audit.safe_record(actor_id, "moderation.mute", target_account_id, "error")
            raise
        self._audit.safe_record(
            actor_id,
            "moderation.mute",
            target_account_id,
            "ok",
            {"minutes": minutes, "until": until.isoformat()},
        )
        return until

    def unmute(self, actor_id: str, target_account_id: str) -> None:
        """Clear any mute for an account, writing an audit entry."""

        try:
            with self._hub.transaction() as connection:
                connection.execute(
                    "UPDATE accounts SET muted_until = NULL, muted_by = NULL, updated_at = ? WHERE id = ?",
                    (utc_now().isoformat(), target_account_id),
                )
        except Exception:
            self._audit.safe_record(actor_id, "moderation.unmute", target_account_id, "error")
            raise
        self._audit.safe_record(actor_id, "moderation.unmute", target_account_id, "ok")
