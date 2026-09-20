"""Security helpers for passwords, sessions, CSRF, and rate limits."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
import hashlib
import hmac
import secrets
import threading

from server.config import AppConfig


SESSION_COOKIE = "tr_session"
CSRF_COOKIE = "tr_csrf"
DEFAULT_SESSION_DAYS = 14
PASSWORD_SALT_BYTES = 16
SESSION_TOKEN_BYTES = 32
CSRF_TOKEN_BYTES = 24
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_LENGTH = 64


class SecurityError(ValueError):
    """Raised when a security check fails."""


class RateLimitError(SecurityError):
    """Raised when a rate limit is exceeded."""


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A newly issued server-side session token."""

    token: str
    token_hash: str
    csrf_token: str
    expires_at: datetime


def utc_now() -> datetime:
    """Return the current UTC timestamp."""

    return datetime.now(tz=UTC)


def normalize_username(username: str) -> tuple[str, str]:
    """Validate and normalize a username."""

    display = username.strip()
    if not 3 <= len(display) <= 24:
        raise SecurityError("Username must be between 3 and 24 characters.")
    if not display[0].isalnum():
        raise SecurityError("Username must start with a letter or digit.")
    for char in display:
        if not (char.isalnum() or char in {"-", "_"}):
            raise SecurityError("Username may contain only letters, digits, '-' and '_'.")
    return display, display.casefold()


def validate_password(password: str) -> str:
    """Validate a plaintext password and return it unchanged."""

    if len(password) < 8:
        raise SecurityError("Password must be at least 8 characters.")
    if len(password) > 256:
        raise SecurityError("Password is too long.")
    return password


def hash_password(password: str) -> str:
    """Hash a password with scrypt."""

    password_bytes = validate_password(password).encode("utf-8")
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    derived = hashlib.scrypt(
        password_bytes,
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_LENGTH,
    )
    return (
        "scrypt"
        f"${SCRYPT_N}"
        f"${SCRYPT_R}"
        f"${SCRYPT_P}"
        f"${salt.hex()}"
        f"${derived.hex()}"
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a plaintext password against a stored hash."""

    try:
        algorithm, n_text, r_text, p_text, salt_hex, digest_hex = encoded_hash.split("$")
    except ValueError:
        return False
    if algorithm != "scrypt":
        return False
    try:
        derived = hashlib.scrypt(
            validate_password(password).encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n_text),
            r=int(r_text),
            p=int(p_text),
            dklen=len(bytes.fromhex(digest_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived.hex(), digest_hex)


def create_session() -> IssuedSession:
    """Create a new opaque session token and CSRF token."""

    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    csrf_token = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
    expires_at = utc_now() + timedelta(days=DEFAULT_SESSION_DAYS)
    return IssuedSession(
        token=token,
        token_hash=hash_session_token(token),
        csrf_token=csrf_token,
        expires_at=expires_at,
    )


def hash_session_token(token: str) -> str:
    """Hash a session token for server-side storage."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def require_matching_csrf(expected: str, presented: str | None) -> None:
    """Validate a CSRF token against the stored token."""

    if not presented:
        raise SecurityError("Missing CSRF token.")
    if not hmac.compare_digest(expected, presented):
        raise SecurityError("Invalid CSRF token.")


def validate_origin(origin: str | None, config: AppConfig) -> None:
    """Require and validate the browser origin."""

    if origin is None or not origin.strip():
        raise SecurityError("Missing Origin header.")
    candidate = origin.strip()
    if candidate in config.allowed_origins:
        return
    if config.is_wildcard_bind and _is_same_port_https_origin(candidate, config.port):
        return
    raise SecurityError(f"Origin '{origin}' is not allowed.")


def _is_same_port_https_origin(candidate: str, port: int) -> bool:
    """Check a wildcard-bind origin shares the server scheme and port."""

    try:
        parsed = urlparse(candidate)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    if parsed.username or parsed.password:
        return False
    hostname = parsed.hostname
    if hostname is None or not hostname.strip():
        return False
    if hostname in {"0.0.0.0", "::"}:
        return False
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return False
    try:
        origin_port = parsed.port
    except ValueError:
        return False
    if origin_port is None:
        return port == 443
    return origin_port == port


class RateLimiter:
    """Simple in-memory sliding-window rate limiter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = {}

    def check(self, key: str, *, limit: int, window_seconds: int, now_ts: float) -> None:
        """Validate the current key against the configured limit."""

        with self._lock:
            queue = self._events.setdefault(key, deque())
            floor = now_ts - window_seconds
            while queue and queue[0] < floor:
                queue.popleft()
            if len(queue) >= limit:
                raise RateLimitError("Too many attempts. Please wait and try again.")
            queue.append(now_ts)
