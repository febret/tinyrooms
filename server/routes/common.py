"""Shared helpers for the World Editor and Card Database HTTP routes."""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from server.config import AppConfig
from server.profiles import SessionRecord
from server.security import CSRF_COOKIE, SESSION_COOKIE, require_matching_csrf, validate_origin


EDITOR_POWERS = frozenset({"builder", "game-master", "admin"})


def get_runtime(request: Request):
    """Return the process runtime state."""

    return request.app.state.runtime


def require_session(runtime, request: Request) -> SessionRecord:
    """Return the session or raise 401."""

    session = runtime.accounts.authenticate(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return session


def enforce_authenticated_post(runtime, request: Request, session: SessionRecord) -> None:
    """Validate Origin and CSRF for a state-changing request."""

    validate_origin(request.headers.get("origin"), runtime.config)
    csrf_cookie = request.cookies.get(CSRF_COOKIE)
    if csrf_cookie is None:
        raise HTTPException(status_code=403, detail="Missing CSRF cookie.")
    require_matching_csrf(session.csrf_token, request.headers.get("x-csrf-token"))
    require_matching_csrf(session.csrf_token, csrf_cookie)


def feature_enabled(config: AppConfig, feature: str) -> bool:
    """Return whether a feature flag is enabled."""

    return feature in config.features


def require_editor_access(runtime, request: Request, *, feature: str):
    """Gate an editor route by feature flag, session, and editor power.

    Returns the account record. Feature-disabled requests 404, unauthenticated
    requests 401, and authenticated-but-unauthorized requests 403. Denied
    attempts are audited.
    """

    if not feature_enabled(runtime.config, feature):
        raise HTTPException(status_code=404, detail="Not found.")
    session = require_session(runtime, request)
    account = runtime.profiles.get_account_by_id(session.account_id)
    if account is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    effective = runtime.powers.effective(account)
    if not (effective & EDITOR_POWERS):
        runtime.audit.safe_record(
            account.id,
            "world_editor.access_denied",
            feature,
            "denied",
            {"feature": feature},
        )
        raise HTTPException(status_code=403, detail="You do not have permission.")
    return account


def require_admin_access(runtime, request: Request, *, feature: str):
    """Gate an admin-only route by feature flag, session, and admin power.

    Feature-disabled requests 404, unauthenticated requests 401, and
    authenticated-but-unauthorized requests 403. Denied attempts are audited.
    """

    if not feature_enabled(runtime.config, feature):
        raise HTTPException(status_code=404, detail="Not found.")
    session = require_session(runtime, request)
    account = runtime.profiles.get_account_by_id(session.account_id)
    if account is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if "admin" not in runtime.powers.effective(account):
        runtime.audit.safe_record(
            account.id,
            "prop_editor.access_denied",
            feature,
            "denied",
            {"feature": feature},
        )
        raise HTTPException(status_code=403, detail="You do not have permission.")
    return account


def json_error(status_code: int, code: str, message: str) -> JSONResponse:
    """Return a uniform JSON error envelope."""

    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "code": code, "message": message},
    )
