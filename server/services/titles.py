"""Global titles: unlockable salutations, nicknames, and suffixes for peep labels."""

from __future__ import annotations

import json
import re
import sqlite3

from server.content.gameplay import GameplayContent
from server.content.titles import TitlePart
from server.profiles import (
    AccountRecord,
    ProfileRepository,
    UserProfileRecord,
    normalize_title_selection,
)
from server.state.migrations import DatabaseHub


TITLE_SLOTS = ("salutation", "nickname", "suffix")
MAX_CREW_NAME_LENGTH = 24
CREW_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 _\-']+$")

# Best-effort backfill sources for counters that predate the titles system.
# Progress is read from shared task_progress (any world); the maximum observed
# progress seeds the lifetime counter once.
COOK_BACKFILL_TASK_IDS = (
    "lounge-first-craft",
    "lounge-prep-work",
    "lounge-mixer-magic",
    "lounge-pizza-night",
)
TEACH_BACKFILL_TASK_ID = "ten-lessons"


class TitleService:
    """Owns title unlock computation, selection, and lifetime activity counters."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        content: GameplayContent,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._content = content

    @property
    def parts(self) -> dict[str, TitlePart]:
        """Return all title parts keyed by part id."""

        return self._content.titles.parts

    def catalog_payload(self) -> list[dict[str, object]]:
        """Serialize every title part for the client."""

        return [part.to_payload() for part in self._content.titles.parts.values()]

    def _backfill_counts(self, connection: sqlite3.Connection, account_id: str, profile: dict[str, object]) -> None:
        """Seed lifetime counters once from historical task progress, if any."""

        try:
            cooked = int(profile.get("cooked_count", 0) or 0)
        except (TypeError, ValueError):
            cooked = 0
        try:
            taught = int(profile.get("taught_count", 0) or 0)
        except (TypeError, ValueError):
            taught = 0
        if cooked > 0 and taught > 0:
            return
        rows = connection.execute(
            "SELECT task_id, status, steps_json, steps_meta_json FROM task_progress WHERE account_id = ?",
            (account_id,),
        ).fetchall()
        best_cooked = 0
        best_taught = 0
        for row in rows:
            task_id = str(row["task_id"])
            try:
                steps = json.loads(row["steps_json"]) if row["steps_json"] else []
            except (TypeError, ValueError):
                steps = []
            try:
                meta = json.loads(row["steps_meta_json"]) if row["steps_meta_json"] else []
            except (TypeError, ValueError):
                meta = []
            amounts = {
                str(entry.get("step_id", "")): int(entry.get("amount", 0) or 0)
                for entry in meta
                if isinstance(entry, dict)
            }
            progress = 0
            for entry in steps:
                if not isinstance(entry, dict):
                    continue
                current = int(entry.get("progress", 0) or 0)
                if str(row["status"]) == "completed":
                    current = max(current, amounts.get(str(entry.get("step_id", "")), current))
                progress += current
            if task_id in COOK_BACKFILL_TASK_IDS:
                best_cooked = max(best_cooked, progress)
            if task_id == TEACH_BACKFILL_TASK_ID:
                best_taught = max(best_taught, progress)
        if cooked <= 0 and best_cooked > 0:
            profile["cooked_count"] = best_cooked
        if taught <= 0 and best_taught > 0:
            profile["taught_count"] = best_taught

    def _unlock_ids(
        self,
        account: AccountRecord,
        counts: dict[str, object],
        completed: set[str],
    ) -> list[str]:
        """Return the sorted unlocked title ids for the given account state."""

        try:
            cooked = int(counts.get("cooked_count", 0) or 0)
        except (TypeError, ValueError):
            cooked = 0
        try:
            taught = int(counts.get("taught_count", 0) or 0)
        except (TypeError, ValueError):
            taught = 0
        unlocked: list[str] = []
        for part in self._content.titles.parts.values():
            unlock = part.unlock
            if unlock.kind == "level" and account.level >= int(unlock.level or 0):
                unlocked.append(part.id)
            elif unlock.kind == "task" and str(unlock.task_id) in completed:
                unlocked.append(part.id)
            elif unlock.kind == "cook" and cooked >= int(unlock.count or 0):
                unlocked.append(part.id)
            elif unlock.kind == "teach" and taught >= int(unlock.count or 0):
                unlocked.append(part.id)
        return sorted(unlocked)

    def read_unlocked(
        self,
        account: AccountRecord,
        profile: UserProfileRecord,
    ) -> tuple[list[str], int, int]:
        """Compute unlocks without persisting them.

        Returns ``(unlocked_ids, cooked_count, taught_count)`` so callers can
        render the payload without opening a write transaction.
        """

        counts: dict[str, object] = {
            "cooked_count": profile.cooked_count,
            "taught_count": profile.taught_count,
        }
        with self._hub.locked() as connection:
            self._backfill_counts(connection, account.id, counts)
            rows = connection.execute(
                "SELECT task_id FROM task_progress WHERE account_id = ? AND status = 'completed'",
                (account.id,),
            ).fetchall()
            completed = {str(row["task_id"]) for row in rows}
        unlocked = self._unlock_ids(account, counts, completed)
        return unlocked, int(counts.get("cooked_count", 0) or 0), int(counts.get("taught_count", 0) or 0)

    def sync_unlocked(self, account_id: str) -> tuple[list[str], list[dict[str, object]]]:
        """Persist the recomputed unlock set and return (unlocked, newly_unlocked)."""

        with self._hub.transaction() as connection:
            account = self._profiles.get_account_by_id(account_id)
            if account is None:
                raise ValueError("Unknown account.")
            record = self._profiles.get_user_profile(account_id)
            if record is None:
                raise ValueError("Unknown account.")
            return self.sync_unlocked_in_transaction(connection, account, record)

    def sync_unlocked_in_transaction(
        self,
        connection: sqlite3.Connection,
        account: AccountRecord,
        profile: UserProfileRecord,
    ) -> tuple[list[str], list[dict[str, object]]]:
        """Recompute and persist unlocks inside a caller-owned transaction."""

        completed_rows = connection.execute(
            "SELECT task_id FROM task_progress WHERE account_id = ? AND status = 'completed'",
            (account.id,),
        ).fetchall()
        completed = {str(row["task_id"]) for row in completed_rows}

        def mutate(data: dict[str, object]) -> None:
            self._backfill_counts(connection, account.id, data)
            data["unlocked_titles"] = self._unlock_ids(account, data, completed)

        previous = set(profile.unlocked_titles)
        updated = self._profiles.update_profile_in_transaction(connection, account.id, mutate)
        unlocked_now = sorted(updated.unlocked_titles)
        catalog = self._content.titles.parts
        newly = sorted(set(unlocked_now) - previous)
        return unlocked_now, [catalog[part_id].to_payload() for part_id in newly if part_id in catalog]

    def record_cook(self, account_id: str) -> list[dict[str, object]]:
        """Increment the lifetime cooked counter and return newly unlocked parts."""

        return self._record_activity(account_id, "cooked_count")

    def record_lesson(self, account_id: str) -> list[dict[str, object]]:
        """Increment the lifetime taught counter and return newly unlocked parts."""

        return self._record_activity(account_id, "taught_count")

    def _record_activity(self, account_id: str, counter_key: str) -> list[dict[str, object]]:
        with self._hub.transaction() as connection:
            account = self._profiles.get_account_by_id(account_id)
            if account is None:
                raise ValueError("Unknown account.")
            profile = self._profiles.get_user_profile(account_id)
            if profile is None:
                raise ValueError("Unknown account.")

            def mutate(data: dict[str, object]) -> None:
                try:
                    data[counter_key] = max(0, int(data.get(counter_key, 0) or 0)) + 1
                except (TypeError, ValueError):
                    data[counter_key] = 1

            self._profiles.update_profile_in_transaction(connection, account_id, mutate)
            current = self._profiles.get_account_by_id(account_id) or account
            record = self._profiles.get_user_profile(account_id) or profile
            _, newly = self.sync_unlocked_in_transaction(connection, current, record)
            return newly

    def set_part(self, account_id: str, slot: str, part_id: str | None) -> dict[str, object]:
        """Select (or clear) the title part for *slot* after validating ownership."""

        if slot not in TITLE_SLOTS:
            raise ValueError("Title slot must be salutation, nickname, or suffix.")
        if part_id is not None:
            part = self._content.titles.parts.get(part_id)
            if part is None or part.slot != slot:
                raise ValueError("That title could not be found.")
        with self._hub.transaction() as connection:
            account = self._profiles.get_account_by_id(account_id)
            if account is None:
                raise ValueError("Unknown account.")
            profile = self._profiles.get_user_profile(account_id)
            if profile is None:
                raise ValueError("Unknown account.")
            self.sync_unlocked_in_transaction(connection, account, profile)
            fresh = self._profiles.get_user_profile(account_id) or profile
            if part_id is not None and part_id not in set(fresh.unlocked_titles):
                raise ValueError("That title is still locked.")
            self._profiles.update_profile_in_transaction(
                connection,
                account_id,
                lambda data: _write_selection(data, slot, part_id),
            )
        return self.selection_payload(account_id)

    def set_crew_name(self, account_id: str, crew_name: str) -> dict[str, object]:
        """Set (or clear) the free-text crew name after validation."""

        cleaned = crew_name.strip()
        if cleaned and (len(cleaned) > MAX_CREW_NAME_LENGTH or not CREW_NAME_PATTERN.match(cleaned)):
            raise ValueError(
                f"Crew name must be up to {MAX_CREW_NAME_LENGTH} letters, digits, spaces, _, - or '."
            )
        with self._hub.transaction() as connection:
            account = self._profiles.get_account_by_id(account_id)
            if account is None:
                raise ValueError("Unknown account.")
            self._profiles.update_profile_in_transaction(
                connection,
                account_id,
                lambda data: _write_selection(data, "crew_name", cleaned),
            )
        return self.selection_payload(account_id)

    def selection_payload(self, account_id: str) -> dict[str, object]:
        """Return the current selection plus the composed display label."""

        account = self._profiles.get_account_by_id(account_id)
        profile = self._profiles.get_user_profile(account_id)
        if account is None or profile is None:
            raise ValueError("Unknown account.")
        selection = self._filtered_selection(profile)
        selection["display_label"] = self.display_label(account.username_display, selection)
        return selection

    def _filtered_selection(self, profile: UserProfileRecord) -> dict[str, object]:
        """Return the stored selection with locked/unknown parts cleared."""

        selection = dict(profile.title_selection)
        catalog = self._content.titles.parts
        unlocked = set(profile.unlocked_titles)
        for slot in TITLE_SLOTS:
            value = selection.get(slot)
            part = catalog.get(str(value)) if isinstance(value, str) else None
            if part is None or part.slot != slot or str(value) not in unlocked:
                selection[slot] = None
        crew_name = selection.get("crew_name")
        selection["crew_name"] = crew_name if isinstance(crew_name, str) else ""
        return selection

    def display_label_for(self, account_id: str) -> str:
        """Return the composed peep label for one account without syncing."""

        account = self._profiles.get_account_by_id(account_id)
        profile = self._profiles.get_user_profile(account_id)
        if account is None:
            return ""
        if profile is None:
            return account.username_display
        return self.display_label(account.username_display, self._filtered_selection(profile))

    def display_labels(self, accounts: list[AccountRecord]) -> dict[str, str]:
        """Return composed peep labels for many accounts with one profile fetch."""

        if not accounts:
            return {}
        profiles = self._profiles.get_user_profiles_by_ids([account.id for account in accounts])
        labels: dict[str, str] = {}
        for account in accounts:
            profile = profiles.get(account.id)
            if profile is None:
                labels[account.id] = account.username_display
            else:
                labels[account.id] = self.display_label(account.username_display, self._filtered_selection(profile))
        return labels

    def display_label(self, username: str, selection: dict[str, object]) -> str:
        """Compose the full peep label from *username* and a title selection."""

        catalog = self._content.titles.parts
        label = str(username)
        salutation_id = selection.get("salutation")
        nickname_id = selection.get("nickname")
        suffix_id = selection.get("suffix")
        crew_name = str(selection.get("crew_name", "") or "").strip()
        salutation = catalog.get(str(salutation_id)) if isinstance(salutation_id, str) else None
        nickname = catalog.get(str(nickname_id)) if isinstance(nickname_id, str) else None
        suffix = catalog.get(str(suffix_id)) if isinstance(suffix_id, str) else None
        if nickname is not None and nickname.slot == "nickname":
            label = f'{label} "{nickname.label}"'
        if crew_name:
            label = f"{label} {crew_name}"
        if salutation is not None and salutation.slot == "salutation":
            label = f"{salutation.label} {label}"
        if suffix is not None and suffix.slot == "suffix":
            label = f"{label}, {suffix.label}"
        return label

    def serialize_for(self, account: AccountRecord) -> dict[str, object]:
        """Build the client-facing titles payload without writing to the DB."""

        profile = self._profiles.get_user_profile(account.id)
        if profile is None:
            raise ValueError("Unknown account.")
        unlocked, cooked, taught = self.read_unlocked(account, profile)
        return {
            "catalog": self.catalog_payload(),
            "unlocked": unlocked,
            "selection": self.selection_payload(account.id),
            "cooked_count": cooked,
            "taught_count": taught,
        }


def _write_selection(data: dict[str, object], key: str, value: str | None) -> None:
    raw = data.get("titles")
    selection = normalize_title_selection(raw)
    selection[key] = value
    data["titles"] = selection
