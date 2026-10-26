"""Shared helpers for the World Editor and Card Database HTTP routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response

from server.base_path import render_html
from server.config import AppConfig, ConfigError, ensure_contained
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
    """Gate an editor route by feature flag, session, and editor power."""

    return require_power_access(
        runtime,
        request,
        feature=feature,
        powers=EDITOR_POWERS,
        audit_action="world_editor.access_denied",
    )


def require_power_access(
    runtime,
    request: Request,
    *,
    feature: str,
    powers: frozenset[str] | set[str],
    audit_action: str,
):
    """Gate a route by feature flag, session, and any of the given powers.

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
    if not (runtime.powers.effective(account) & set(powers)):
        runtime.audit.safe_record(
            account.id,
            audit_action,
            feature,
            "denied",
            {"feature": feature},
        )
        raise HTTPException(status_code=403, detail="You do not have permission.")
    return account


def require_admin_access(runtime, request: Request, *, feature: str, audit_action: str | None = None):
    """Gate an admin-only route by feature flag, session, and admin power."""

    return require_power_access(
        runtime,
        request,
        feature=feature,
        powers=frozenset({"admin"}),
        audit_action=audit_action or "prop_editor.access_denied",
    )


def serve_page(runtime, root: Path, requested_path: str) -> Response:
    """Serve a bundled single-page app file contained under *root*."""

    import mimetypes

    relative = requested_path or "index.html"
    if relative.endswith("/"):
        relative = f"{relative}index.html"
    try:
        candidate = ensure_contained(root / relative, root, "editor")
    except ConfigError as exc:
        raise HTTPException(status_code=404, detail="Not found.") from exc
    if candidate.is_dir():
        candidate = candidate / "index.html"
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Not found.")
    media_type, _ = mimetypes.guess_type(candidate.name)
    return render_html(candidate, runtime.config.base_path, media_type=media_type)


def json_error(status_code: int, code: str, message: str) -> JSONResponse:
    """Return a uniform JSON error envelope."""

    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "code": code, "message": message},
    )
