"""Direct profile-database access for the mission-control User Manager."""

from __future__ import annotations

from datetime import timedelta
import json
import sqlite3
from typing import Any

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

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        audit: McAuditLog,
        *,
        card_catalog_for: Any = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._audit = audit
        self._card_catalog_for = card_catalog_for

    def _definition_for(self, world_id: str | None, card_def_id: str) -> Any | None:
        """Return the card definition for a grant, or None when unknown."""

        if self._card_catalog_for is None:
            return None
        try:
            catalog = self._card_catalog_for(world_id)
        except Exception:  # noqa: BLE001 - validation must fail closed
            return None
        if catalog is None:
            return None
        return getattr(catalog, "cards", {}).get(card_def_id)

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
        profile_view = None
        if profile is not None:
            profile_view = dict(profile)
            try:
                parsed_profile = json.loads(str(profile_view.get("profile_json") or "{}"))
            except (TypeError, ValueError):
                parsed_profile = {}
            if isinstance(parsed_profile, dict):
                profile_view["last_instance_id"] = parsed_profile.get("last_instance_id")
        return {
            "account": account,
            "profile": profile_view,
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

    def edit_inventory(self, actor: str, account_id: str, stack_id: str, quantity: int) -> None:
        """Set an absolute quantity on one owned inventory stack."""

        amount = _as_int(quantity, "quantity")
        if amount < 1:
            raise ValueError("'quantity' must be at least 1. Use delete to remove a stack.")
        with self._hub.transaction() as connection:
            row = connection.execute(
                "SELECT stack_id, card_def_id, world_id FROM profile_card_stacks WHERE account_id = ? AND stack_id = ?",
                (account_id, stack_id),
            ).fetchone()
            if row is None:
                raise ValueError("Unknown inventory stack.")
            definition = self._definition_for(row["world_id"], str(row["card_def_id"]))
            if definition is None:
                raise ValueError("That stack's card is not in this world's catalog.")
            limit = int(getattr(definition, "stack_limit", 1) or 1)
            if amount > limit:
                raise ValueError(f"'quantity' cannot exceed the stack limit of {limit}.")
            self._profiles.set_stack_quantity(
                connection, account_id=account_id, stack_id=stack_id, quantity=amount
            )
        self._audit.record(
            actor,
            "user.inventory.update",
            target=account_id,
            result="ok",
            detail={"stack_id": stack_id, "quantity": amount},
        )

    def delete_inventory(self, actor: str, account_id: str, stack_id: str) -> None:
        """Delete one owned inventory stack."""

        with self._hub.transaction() as connection:
            row = connection.execute(
                "SELECT stack_id FROM profile_card_stacks WHERE account_id = ? AND stack_id = ?",
                (account_id, stack_id),
            ).fetchone()
            if row is None:
                raise ValueError("Unknown inventory stack.")
            connection.execute(
                "DELETE FROM profile_card_stacks WHERE account_id = ? AND stack_id = ?",
                (account_id, stack_id),
            )
        self._audit.record(
            actor,
            "user.inventory.delete",
            target=account_id,
            result="ok",
            detail={"stack_id": stack_id},
        )

    def add_inventory(
        self,
        actor: str,
        account_id: str,
        card_def_id: str,
        quantity: int,
        world_id: str | None,
        scope: str,
    ) -> dict[str, object]:
        """Grant one new inventory stack to an account and return it."""

        card = str(card_def_id or "").strip()
        if not card:
            raise ValueError("A card id is required.")
        amount = _as_int(quantity, "quantity")
        if amount < 1:
            raise ValueError("'quantity' must be at least 1.")
        if scope not in {"global", "world"}:
            raise ValueError("'scope' must be 'global' or 'world'.")
        world = (str(world_id).strip() if world_id else "") or None
        if scope == "world" and not world:
            raise ValueError("A world id is required for world-scoped stacks.")
        if scope == "global":
            world = None
        account = self._profiles.get_account_by_id(account_id)
        if account is None:
            raise ValueError("Unknown account.")
        definition = self._definition_for(world, card)
        if definition is None:
            raise ValueError("Unknown card for the selected world. Check the card id.")
        limit = int(getattr(definition, "stack_limit", 1) or 1)
        if amount > limit:
            raise ValueError(f"'quantity' cannot exceed the stack limit of {limit}.")
        with self._hub.transaction() as connection:
            stack = self._profiles.create_inventory_stack(
                connection,
                account_id=account_id,
                world_id=world,
                card_def_id=card,
                quantity=amount,
                scope=scope,
            )
        self._audit.record(
            actor,
            "user.inventory.add",
            target=account_id,
            result="ok",
            detail={"stack_id": stack.stack_id, "card_def_id": card, "quantity": amount,
                    "world_id": world, "scope": scope},
        )
        return {
            "stack_id": stack.stack_id,
            "account_id": stack.account_id,
            "world_id": stack.world_id,
            "card_def_id": stack.card_def_id,
            "quantity": stack.quantity,
            "scope": stack.scope,
            "equipped": stack.equipped,
            "pinned": stack.pinned,
        }


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
