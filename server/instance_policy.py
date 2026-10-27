"""Shared per-instance policy for invitations, guest caps, and world caps.

Mission Control and every participating world read the same JSON file from the
shared users directory. Writes are atomic and the file is private to the
deployment user. When the file is absent, callers may supply legacy fallback
values from their environment.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

POLICY_VERSION = 1
POLICY_FILENAME = "instance-policy.json"
INVITATION_MIN_LENGTH = 6
INVITATION_MAX_LENGTH = 128
MAX_GUESTS_MIN = 1
MAX_GUESTS_MAX = 10000
MAX_WORLDS_MIN = 1
MAX_WORLDS_MAX = 64


class InstancePolicyError(ValueError):
    """Raised when policy values cannot be read or validated."""


class AccountLimitError(ValueError):
    """Raised when account creation would exceed the instance guest cap."""

    code = "account_limit_reached"


class WorldLimitError(ValueError):
    """Raised when starting a world would exceed the instance world cap."""

    code = "world_limit_reached"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_invitation_code(value: str) -> str:
    text = str(value or "").strip()
    if not INVITATION_MIN_LENGTH <= len(text) <= INVITATION_MAX_LENGTH:
        raise InstancePolicyError(
            f"invitation_code must be between {INVITATION_MIN_LENGTH} and "
            f"{INVITATION_MAX_LENGTH} characters."
        )
    if any(ord(character) < 32 for character in text):
        raise InstancePolicyError("invitation_code contains control characters.")
    return text


def validate_max_guests(value: object) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise InstancePolicyError("max_guests must be an integer.") from exc
    if not MAX_GUESTS_MIN <= number <= MAX_GUESTS_MAX:
        raise InstancePolicyError(
            f"max_guests must be between {MAX_GUESTS_MIN} and {MAX_GUESTS_MAX}."
        )
    return number


def validate_max_worlds(value: object) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise InstancePolicyError("max_worlds must be an integer.") from exc
    if not MAX_WORLDS_MIN <= number <= MAX_WORLDS_MAX:
        raise InstancePolicyError(
            f"max_worlds must be between {MAX_WORLDS_MIN} and {MAX_WORLDS_MAX}."
        )
    return number


@dataclass(frozen=True, slots=True)
class InstancePolicy:
    """One validated instance policy snapshot."""

    invitation_code: str
    max_guests: int
    max_worlds: int
    updated_at: str = ""
    version: int = POLICY_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "invitation_code": self.invitation_code,
            "max_guests": self.max_guests,
            "max_worlds": self.max_worlds,
            "updated_at": self.updated_at,
        }


def default_policy_path(users_path: Path) -> Path:
    return Path(users_path) / POLICY_FILENAME


class InstancePolicyStore:
    """Cached, atomically updated policy file for one instance."""

    def __init__(
        self,
        path: Path,
        *,
        fallback_invitation: str = "",
        fallback_max_guests: int = 0,
        fallback_max_worlds: int = 0,
    ) -> None:
        self.path = Path(path)
        self._fallback = InstancePolicy(
            invitation_code=str(fallback_invitation or ""),
            max_guests=int(fallback_max_guests or 0),
            max_worlds=int(fallback_max_worlds or 0),
            updated_at="",
        )
        self._cached: InstancePolicy | None = None
        self._signature: tuple[int, int] | None = None
        self._lock = threading.Lock()

    def _read_file(self) -> InstancePolicy:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._fallback
        except (OSError, ValueError) as exc:
            raise InstancePolicyError(
                f"Instance policy could not be read: {self.path}"
            ) from exc
        if not isinstance(payload, dict):
            raise InstancePolicyError("Instance policy must be a JSON object.")
        invitation = payload.get("invitation_code", self._fallback.invitation_code)
        if not isinstance(invitation, str):
            raise InstancePolicyError("invitation_code must be a string.")
        try:
            max_guests = int(payload.get("max_guests", self._fallback.max_guests))
            max_worlds = int(payload.get("max_worlds", self._fallback.max_worlds))
        except (TypeError, ValueError) as exc:
            raise InstancePolicyError("Policy caps must be integers.") from exc
        if max_guests > MAX_GUESTS_MAX or max_worlds > MAX_WORLDS_MAX:
            raise InstancePolicyError("Policy caps exceed the supported range.")
        return InstancePolicy(
            invitation_code=invitation,
            max_guests=max_guests,
            max_worlds=max_worlds,
            updated_at=str(payload.get("updated_at") or ""),
            version=int(payload.get("version") or POLICY_VERSION),
        )

    def load(self) -> InstancePolicy:
        """Return the current policy, reloading only when the file changes."""

        try:
            stat = self.path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            return self._fallback
        with self._lock:
            if signature == self._signature and self._cached is not None:
                return self._cached
            policy = self._read_file()
            self._cached = policy
            self._signature = signature
            return policy

    def update(
        self,
        *,
        invitation_code: str | None = None,
        max_guests: int | None = None,
        max_worlds: int | None = None,
    ) -> InstancePolicy:
        """Validate, merge, and atomically persist a policy change."""

        if invitation_code is None and max_guests is None and max_worlds is None:
            return self.load()
        current = self.load()
        changes: dict[str, object] = {}
        if invitation_code is not None:
            changes["invitation_code"] = validate_invitation_code(invitation_code)
        if max_guests is not None:
            changes["max_guests"] = validate_max_guests(max_guests)
        if max_worlds is not None:
            changes["max_worlds"] = validate_max_worlds(max_worlds)
        updated = replace(
            current,
            **changes,
            version=POLICY_VERSION,
            updated_at=_utc_now_iso(),
        )
        self._write(updated)
        return updated

    def _write(self, policy: InstancePolicy) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(policy.to_dict(), sort_keys=True, indent=2) + "\n"
        descriptor, temporary = tempfile.mkstemp(
            prefix=".instance-policy-", dir=str(self.path.parent), text=True
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self.path)
        finally:
            try:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            except OSError:
                pass
        try:
            stat = self.path.stat()
            self._signature = (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            self._signature = None
        with self._lock:
            self._cached = policy
