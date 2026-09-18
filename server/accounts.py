"""Account and session service layer for Tinyrooms."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import time

from server.config import AppConfig
from server.profiles import AccountRecord, ProfileRepository, SessionRecord
from server.security import RateLimiter, SecurityError, normalize_username, validate_password, verify_password


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Successful account creation or login payload."""

    account: AccountRecord
    session_token: str
    csrf_token: str
    expires_at: str


class AuthenticationError(SecurityError):
    """Raised when account authentication fails."""


class AccountConflictError(ValueError):
    """Raised when an account cannot be created because its username exists."""


class AccountService:
    """Account lifecycle service for create/login/logout and sticker completion."""

    def __init__(self, config: AppConfig, profiles: ProfileRepository, world_id: str, entry_room_id: str) -> None:
        self._config = config
        self._profiles = profiles
        self._world_id = world_id
        self._entry_room_id = entry_room_id
        self._create_limiter = RateLimiter()
        self._login_limiter = RateLimiter()

    def _limit(self, limiter: RateLimiter, bucket: str, *, limit: int, window_seconds: int) -> None:
        limiter.check(bucket, limit=limit, window_seconds=window_seconds, now_ts=time.time())

    def list_stickers(self) -> list[str]:
        """Return the available sticker asset filenames."""

        stickers: list[str] = []
        for path in sorted(self._config.stickers_path.iterdir()):
            if not path.is_file():
                continue
            if path.name.lower() == "readme.md":
                continue
            if path.suffix.lower() not in {".png", ".webp", ".jpg", ".jpeg"}:
                continue
            stickers.append(path.name)
        if not stickers:
            raise ValueError("No sticker assets were found under data/stickers.")
        return stickers

    def create_account(self, username: str, password: str, passphrase: str, source_key: str) -> LoginResult:
        """Create an account, issue a session, and return login data."""

        self._limit(self._create_limiter, f"create:ip:{source_key}", limit=5, window_seconds=60)
        display_name, username_key = normalize_username(username)
        self._limit(self._create_limiter, f"create:user:{username_key}", limit=3, window_seconds=60)
        validate_password(password)
        if passphrase != self._config.new_account_passphrase:
            raise AuthenticationError("The new-account passphrase is incorrect.")
        try:
            account = self._profiles.create_account(
                display_name,
                password,
                self._world_id,
                self._entry_room_id,
            )
        except ValueError as exc:
            raise AccountConflictError(str(exc)) from exc
        issued, _ = self._profiles.issue_session(account.id)
        return LoginResult(
            account=account,
            session_token=issued.token,
            csrf_token=issued.csrf_token,
            expires_at=issued.expires_at.isoformat(),
        )

    def login(self, username: str, password: str, source_key: str) -> LoginResult:
        """Authenticate an existing account and issue a fresh session."""

        self._limit(self._login_limiter, f"login:ip:{source_key}", limit=10, window_seconds=60)
        _, username_key = normalize_username(username)
        self._limit(self._login_limiter, f"login:user:{username_key}", limit=6, window_seconds=60)
        validate_password(password)
        account = self._profiles.get_account_by_username(username)
        if account is None or not verify_password(password, account.password_hash):
            raise AuthenticationError("Incorrect username or password.")
        issued, _ = self._profiles.issue_session(account.id)
        refreshed = self._profiles.get_account_by_id(account.id)
        return LoginResult(
            account=refreshed,
            session_token=issued.token,
            csrf_token=issued.csrf_token,
            expires_at=issued.expires_at.isoformat(),
        )

    def authenticate(self, token: str | None) -> SessionRecord | None:
        """Resolve a session token into an active session record."""

        if not token:
            return None
        session = self._profiles.get_session_by_token(token)
        if session is None:
            return None
        if datetime.fromisoformat(session.expires_at).astimezone(UTC) <= datetime.now(tz=UTC):
            self._profiles.revoke_session(token)
            return None
        self._profiles.touch_session(token)
        return session

    def logout(self, token: str | None) -> None:
        """Revoke a session token when present."""

        if token:
            self._profiles.revoke_session(token)

    def confirm_initial_sticker(self, account_id: str, sticker_name: str) -> AccountRecord:
        """Validate and persist the initial sticker choice."""

        available = set(self.list_stickers())
        if sticker_name not in available:
            raise ValueError("Unknown sticker selection.")
        return self._profiles.set_sticker(account_id, sticker_name)
