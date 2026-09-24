"""Direct profile-database access for the mission-control User Manager."""

from __future__ import annotations

from datetime import timedelta
import json
import sqlite3

from server.content.worlds import POWER_NAMES
from server.mission_control.audit import McAuditLog
from server.profiles import AccountRecord, ProfileRepository
from server.security import utc_now
from server.state.migrations import DatabaseHub


_EDITABLE_FIELDS = frozenset(
    {
        "level",
        "kudos",
        "bops",
        "shared_energy",
        "sticker",
        "initial_sticker_complete",
        "muted",
        "mute_minutes",
        "powers",
    }
)


def _rows_as_dicts(connection: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> list[dict[str, object]]:
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def _parse_powers(raw: object) -> list[str]:
    if not isinstance(raw, str):
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(power) for power in parsed]


class UserManager:
    """Search, inspect, and edit accounts in the shared profile database."""

    def __init__(self, hub: DatabaseHub, profiles: ProfileRepository, audit: McAuditLog) -> None:
        self._hub = hub
        self._profiles = profiles
        self._audit = audit

    def search(self, query: str | None = None, *, limit: int = 50) -> list[dict[str, object]]:
        """List account summaries, optionally filtered by username or id."""

        accounts = self._profiles.search_accounts(query, limit=limit)
        return self._summaries(accounts)

    def _summaries(self, accounts: list[AccountRecord]) -> list[dict[str, object]]:
        if not accounts:
            return []
        account_ids = [account.id for account in accounts]
        placeholders = ", ".join("?" for _ in account_ids)
        powers: dict[str, list[str]] = {}
        last_visits: dict[str, str | None] = {}
        with self._hub.locked() as connection:
            for row in connection.execute(
                f"SELECT id, powers FROM accounts WHERE id IN ({placeholders})",
                account_ids,
            ):
                powers[row["id"]] = _parse_powers(row["powers"])
            for row in connection.execute(
                f"SELECT account_id, last_visit_at FROM user_profiles WHERE account_id IN ({placeholders})",
                account_ids,
            ):
                last_visits[row["account_id"]] = row["last_visit_at"]
        return [
            self._summary(account, powers=powers.get(account.id, []), last_visit_at=last_visits.get(account.id))
            for account in accounts
        ]

    def _summary(self, account: AccountRecord, *, powers: list[str], last_visit_at: str | None) -> dict[str, object]:
        return {
            "id": account.id,
            "username": account.username_display,
            "level": account.level,
            "kudos": account.kudos,
            "bops": account.bops,
            "sticker": account.sticker,
            "initial_sticker_complete": account.initial_sticker_complete,
            "created_at": account.created_at,
            "last_visit_at": last_visit_at,
            "powers": powers,
        }

    def detail(self, account_id: str) -> dict[str, object] | None:
        """Return an account plus related rows across profile tables."""

        with self._hub.locked() as connection:
            account_row = connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if account_row is None:
                return None
            account = dict(account_row)
            account["powers"] = _parse_powers(account.get("powers"))
            profile = connection.execute(
                "SELECT * FROM user_profiles WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            sessions = _rows_as_dicts(
                connection,
                "SELECT token_hash, generation, created_at, expires_at, last_seen_at FROM sessions WHERE account_id = ? ORDER BY created_at DESC",
                (account_id,),
            )
            stacks = _rows_as_dicts(
                connection,
                "SELECT * FROM profile_card_stacks WHERE account_id = ? ORDER BY created_at",
                (account_id,),
            )
            ledger = _rows_as_dicts(
                connection,
                "SELECT * FROM reward_ledger WHERE account_id = ? ORDER BY created_at DESC LIMIT 100",
                (account_id,),
            )
            purchases = _rows_as_dicts(
                connection,
                "SELECT * FROM pack_purchases WHERE account_id = ? ORDER BY created_at DESC LIMIT 100",
                (account_id,),
            )
            tasks = _rows_as_dicts(
                connection,
                "SELECT * FROM task_progress WHERE account_id = ? ORDER BY started_at DESC LIMIT 100",
                (account_id,),
            )
            memories = _rows_as_dicts(
                connection,
                "SELECT * FROM memories WHERE account_id = ? ORDER BY created_at DESC LIMIT 100",
                (account_id,),
            )
            audit = _rows_as_dicts(
                connection,
                "SELECT * FROM audit_log WHERE actor_account_id = ? OR target = ? ORDER BY audit_id DESC LIMIT 100",
                (account_id, account_id),
            )
        return {
            "account": account,
            "profile": None if profile is None else dict(profile),
            "sessions": sessions,
            "profile_card_stacks": stacks,
            "reward_ledger": ledger,
            "pack_purchases": purchases,
            "task_progress": tasks,
            "memories": memories,
            "audit_log": audit,
        }

    def edit(self, actor: str, account_id: str, fields: dict[str, object]) -> dict[str, object]:
        """Apply supported edits, auditing every change."""

        unknown = set(fields) - _EDITABLE_FIELDS
        if unknown:
            raise ValueError(f"Unsupported field(s): {', '.join(sorted(unknown))}.")
        account = self._profiles.get_account_by_id(account_id)
        if account is None:
            raise ValueError("Unknown account.")

        kwargs: dict[str, object] = {}
        if "level" in fields:
            kwargs["level"] = _as_int(fields["level"], "level")
        if "kudos" in fields:
            kwargs["kudos"] = _as_int(fields["kudos"], "kudos")
        if "bops" in fields:
            kwargs["bops"] = _as_int(fields["bops"], "bops")
        if "shared_energy" in fields:
            kwargs["shared_energy"] = _as_float(fields["shared_energy"], "shared_energy")
        if "sticker" in fields:
            kwargs["sticker"] = None if fields["sticker"] is None else str(fields["sticker"])
        if "initial_sticker_complete" in fields:
            kwargs["initial_sticker_complete"] = bool(fields["initial_sticker_complete"])
        if "muted" in fields or "mute_minutes" in fields:
            muted = bool(fields.get("muted", False))
            if muted:
                minutes = _as_int(fields.get("mute_minutes", 60), "mute_minutes")
                kwargs["muted_until"] = (utc_now() + timedelta(minutes=max(1, minutes))).isoformat()
                kwargs["muted_by"] = actor
            else:
                kwargs["muted_until"] = None
                kwargs["muted_by"] = None
        if kwargs:
            self._profiles.admin_update_account(account_id, **kwargs)

        if "powers" in fields:
            requested = fields["powers"]
            if not isinstance(requested, list):
                raise ValueError("powers must be a list.")
            normalized = sorted({str(power) for power in requested})
            invalid = [power for power in normalized if power not in POWER_NAMES]
            if invalid:
                raise ValueError(f"Unknown power(s): {', '.join(invalid)}.")
            self._profiles.admin_set_powers(account_id, normalized)

        changed = sorted(set(fields))
        self._audit.record(actor, "user.edit", target=account_id, result="ok", detail={"fields": changed})
        updated = self._profiles.get_account_by_id(account_id)
        if updated is None:
            raise ValueError("Unknown account.")
        return self._summaries([updated])[0]


def _as_int(value: object, label: str) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'{label}' must be an integer.") from exc


def _as_float(value: object, label: str) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'{label}' must be a number.") from exc
