"""Mission-control operator authentication and session management.

Mission-control sessions are independent of world accounts: a single operator
passphrase is compared in constant time and successful logins issue an opaque
session plus CSRF token using the shared security primitives.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hmac
import threading

from server.security import IssuedSession, create_session, hash_session_token, utc_now


MC_SESSION_COOKIE = "tr_mc_session"
MC_CSRF_COOKIE = "tr_mc_csrf"


@dataclass(frozen=True, slots=True)
class McSession:
    """A stored mission-control operator session."""

    token_hash: str
    csrf_token: str
    operator: str
    expires_at: datetime


class McSessionStore:
    """In-memory store for mission-control sessions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, McSession] = {}

    def login(self, passphrase: str, expected: str, *, operator: str = "operator") -> IssuedSession:
        """Validate the passphrase and issue a new session, raising on mismatch."""

        if not hmac.compare_digest(passphrase.encode("utf-8"), expected.encode("utf-8")):
            raise PermissionError("Invalid passphrase.")
        issued = create_session()
        session = McSession(
            token_hash=issued.token_hash,
            csrf_token=issued.csrf_token,
            operator=operator,
            expires_at=issued.expires_at,
        )
        with self._lock:
            self._sessions[issued.token_hash] = session
        return issued

    def get(self, token: str | None) -> McSession | None:
        """Return the live session for a plaintext token, expiring stale ones."""

        if not token:
            return None
        token_hash = hash_session_token(token)
        with self._lock:
            session = self._sessions.get(token_hash)
            if session is None:
                return None
            if session.expires_at <= utc_now():
                self._sessions.pop(token_hash, None)
                return None
            return session

    def logout(self, token: str | None) -> None:
        """Drop the session for a plaintext token."""

        if not token:
            return
        with self._lock:
            self._sessions.pop(hash_session_token(token), None)

    def count(self) -> int:
        """Return the number of live sessions."""

        with self._lock:
            return len(self._sessions)
