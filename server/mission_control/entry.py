"""Player authentication and exact-instance entry for mission control."""

from __future__ import annotations

from datetime import UTC, datetime
import hmac
import json
from pathlib import Path
import tempfile
import time
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from server.mission_control.registry import SPAWNED, STATUS_RUNNING, InstanceRecord
from server.mission_control.routes import _client_key, _enforce_post, _require_operator, _require_token
from server.profiles import ProfileRepository, SessionRecord
from server.security import (
    CSRF_COOKIE, SESSION_COOKIE, RateLimitError, RateLimiter, normalize_username,
    require_matching_csrf, validate_origin, validate_password, verify_password,
)


router = APIRouter()


class Credentials(BaseModel):
    """Player login credentials."""

    username: str
    password: str


class CreateCredentials(Credentials):
    """Invitation-gated player account creation."""

    passphrase: str


class PlayerAuthService:
    """Shared-database authentication with runtime-lifetime attempt limits."""

    def __init__(self, profiles: ProfileRepository, invitation: str) -> None:
        self.profiles = profiles
        self.invitation = invitation
        self.limiter = RateLimiter()

    def validate(self, credentials: Credentials, source: str, *, creating: bool = False) -> str:
        """Apply the same input validation and limits as world account services."""

        action = "create" if creating else "login"
        self.limiter.check(f"{action}:ip:{source}", limit=5 if creating else 10,
                           window_seconds=60, now_ts=time.time())
        display, key = normalize_username(credentials.username)
        self.limiter.check(f"{action}:user:{key}", limit=3 if creating else 6,
                           window_seconds=60, now_ts=time.time())
        validate_password(credentials.password)
        return display

    def authenticate(self, token: str | None) -> SessionRecord | None:
        """Resolve an active shared session, rejecting and revoking expired tokens."""

        if not token:
            return None
        session = self.profiles.get_session_by_token(token)
        if session is None:
            return None
        if datetime.fromisoformat(session.expires_at).astimezone(UTC) <= datetime.now(UTC):
            self.profiles.revoke_session(token)
            return None
        self.profiles.touch_session(token)
        return session


class EntrySettings:
    """Atomically persisted operator-selected destination for new accounts."""

    def __init__(self, instances_path: Path) -> None:
        self.path = instances_path / "entry.json"

    @property
    def default_instance_id(self) -> str | None:
        """Read the persisted default without silently replacing invalid settings."""

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        value = data.get("default_instance_id")
        if value is not None and not isinstance(value, str):
            raise ValueError("Invalid default instance settings.")
        return value

    def set_default(self, instance_id: str) -> None:
        """Replace settings atomically, preserving the old file on write failure."""

        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix="entry-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({"default_instance_id": instance_id}, handle)
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _session(request: Request) -> SessionRecord:
    session = request.app.state.mc.player_auth.authenticate(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise HTTPException(401, "Player authentication required.")
    return session


def _issue(runtime, account_id: str) -> Response:
    issued, _ = runtime.profiles.issue_session(account_id)
    response = JSONResponse({"ok": True, "logged_in": True, "csrf_token": issued.csrf_token})
    response.headers["Cache-Control"] = "no-store"
    for name, value, http_only in ((SESSION_COOKIE, issued.token, True), (CSRF_COOKIE, issued.csrf_token, False)):
        response.set_cookie(name, value, httponly=http_only, secure=True, samesite="lax",
                            expires=issued.expires_at, path="/")
    return response


def _format_client_url(record: InstanceRecord) -> str:
    value = record.client_url or ""
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname and parsed.port != 0
                 and parsed.username is None and parsed.password is None
                 and not parsed.query and not parsed.fragment and "?" not in value and "#" not in value
                 and not any(character.isspace() or character == "\\" for character in value))
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(409, "Destination client_url must be an HTTPS URL without credentials, query, or fragment.")
    return value


async def _validate_running_destination(runtime, record: InstanceRecord) -> str:
    """Validate a running instance's identity and client URL, without host checks."""

    if runtime.registry.snapshot(record)["status"] != STATUS_RUNNING or not record.registered_at:
        raise HTTPException(503, "The selected instance is unavailable. Please retry when it is running.")
    if not record.world_id:
        raise HTTPException(409, "The selected instance has not registered a world identity.")
    if record.source == SPAWNED:
        users_path = (record.spawn_config or {}).get("users_path")
        if not users_path or Path(str(users_path)).resolve() != runtime.config.users_path.resolve():
            raise HTTPException(409, "The selected instance does not use the shared player database.")
    client_url = _format_client_url(record)
    try:
        response = await runtime.http.get(f"{record.endpoint.rstrip('/')}{record.base_path}/health", timeout=5.0)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "The selected instance could not be reached. Please retry.") from exc
    if not isinstance(data, dict) or data.get("world_id") != record.world_id or data.get("instance_id") != record.instance_id:
        raise HTTPException(409, "The selected instance health identity does not match its registration.")
    return client_url


async def _destination(request: Request, instance_id: str) -> tuple[InstanceRecord, str]:
    runtime = request.app.state.mc
    record = runtime.registry.get(instance_id)
    if record is None:
        raise HTTPException(409, "The saved instance is no longer registered. Ask an operator to restore it.")
    client_url = await _validate_running_destination(runtime, record)
    if urlsplit(client_url).hostname != request.url.hostname:
        raise HTTPException(409, "Destination must use the same hostname as player entry so the login cookie can be shared across ports.")
    return record, client_url


@router.get("/api/entry/session")
async def session_status(request: Request) -> Response:
    """Report player authentication without loading or changing world state."""

    session = request.app.state.mc.player_auth.authenticate(request.cookies.get(SESSION_COOKIE))
    data = {"ok": True, "logged_in": session is not None}
    if session is not None:
        data.update(username=session.account.username_display, csrf_token=session.csrf_token)
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


@router.post("/api/entry/login")
async def login(request: Request, payload: Credentials) -> Response:
    """Verify an existing player's password against the shared database."""

    runtime = request.app.state.mc
    validate_origin(request.headers.get("origin"), runtime.config)
    try:
        runtime.player_auth.validate(payload, _client_key(request))
    except RateLimitError:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    account = runtime.profiles.get_account_by_username(payload.username)
    if account is None or not verify_password(payload.password, account.password_hash):
        raise HTTPException(401, "Incorrect username or password.")
    return _issue(runtime, account.id)


@router.post("/api/entry/create")
async def create(request: Request, payload: CreateCredentials) -> Response:
    """Create a player in the current default instance and remember it immediately."""

    runtime = request.app.state.mc
    validate_origin(request.headers.get("origin"), runtime.config)
    try:
        display = runtime.player_auth.validate(payload, _client_key(request), creating=True)
    except RateLimitError:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not hmac.compare_digest(payload.passphrase.encode(), runtime.player_auth.invitation.encode()):
        raise HTTPException(403, "The new-account passphrase is incorrect.")
    default_id = runtime.entry_settings.default_instance_id
    if not default_id:
        raise HTTPException(409, "No default instance has been selected. Ask an operator to select one in Server Manager.")
    record, _ = await _destination(request, default_id)
    if not record.entry_room_id:
        raise HTTPException(409, "The default instance has not registered its entry room.")
    try:
        account = runtime.profiles.create_account(display, payload.password, record.world_id, record.entry_room_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    runtime.profiles.remember_instance(account.id, record.instance_id)
    return _issue(runtime, account.id)


@router.post("/api/entry/logout")
async def logout(request: Request) -> Response:
    """Revoke a player session with Origin and double-submit CSRF protection."""

    runtime = request.app.state.mc
    session = _session(request)
    validate_origin(request.headers.get("origin"), runtime.config)
    require_matching_csrf(session.csrf_token, request.headers.get("x-csrf-token"))
    require_matching_csrf(session.csrf_token, request.cookies.get(CSRF_COOKIE))
    runtime.profiles.revoke_session(request.cookies[SESSION_COOKIE])
    response = JSONResponse({"ok": True})
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=True, samesite="lax")
    return response


@router.get("/api/entry/resolve")
async def resolve(request: Request) -> Response:
    """Resolve the saved instance, with unique-world matching only for legacy profiles."""

    runtime = request.app.state.mc
    session = _session(request)
    profile = runtime.profiles.get_user_profile(session.account_id)
    if profile is None:
        raise HTTPException(409, "Your player profile is missing. Ask an operator for help.")
    instance_id = profile.profile.get("last_instance_id")
    if instance_id is not None and (not isinstance(instance_id, str) or not instance_id.strip()):
        raise HTTPException(409, "Your saved instance identity is invalid. Ask an operator for help.")
    if not instance_id:
        matches = [record for record in runtime.registry.list() if record.world_id == profile.last_world_id]
        if len(matches) != 1:
            raise HTTPException(409, "Your saved world does not identify a unique instance. Ask an operator to restore your destination.")
        instance_id = matches[0].instance_id
    record, client_url = await _destination(request, instance_id)
    if record.world_id != profile.last_world_id:
        raise HTTPException(409, "Your saved instance now serves a different world. Ask an operator for help.")
    return JSONResponse({"ok": True, "instance_id": record.instance_id, "world_id": record.world_id,
                         "client_url": client_url}, headers={"Cache-Control": "no-store"})


@router.post("/api/mission-control/instances/{instance_id}/default")
async def set_default(request: Request, instance_id: str) -> dict[str, object]:
    """Persist the operator's default after validating the registered destination."""

    session = _require_operator(request)
    _enforce_post(request, session)
    record, _ = await _destination(request, instance_id)
    if not record.entry_room_id:
        raise HTTPException(409, "The default instance has not registered its entry room.")
    runtime = request.app.state.mc
    runtime.entry_settings.set_default(instance_id)
    runtime.audit.record("operator", "instance.default", target=instance_id)
    return {"ok": True, "default_instance_id": instance_id}


@router.get("/api/mc/instances/{world_id}/destination")
async def fleet_world_destination(request: Request, world_id: str) -> Response:
    """Resolve a running instance serving *world_id* for cross-world travel.

    Token-authenticated fleet endpoint: a participating world asks mission
    control which instance currently serves a target world so the browser can be
    redirected there. The caller still enforces same-host client URLs.
    """

    _require_token(request)
    runtime = request.app.state.mc
    candidates = [record for record in runtime.registry.list() if record.world_id == world_id]
    if not candidates:
        return JSONResponse(status_code=404, content={
            "ok": False, "code": "world_not_found",
            "message": f"No instance is registered for world '{world_id}'.",
        })
    running = [
        record for record in candidates
        if runtime.registry.snapshot(record)["status"] == STATUS_RUNNING and record.registered_at
    ]
    if not running:
        return JSONResponse(status_code=503, content={
            "ok": False, "code": "world_unavailable",
            "message": f"World '{world_id}' is not currently running.",
        })
    record = running[0]
    try:
        client_url = await _validate_running_destination(runtime, record)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={
            "ok": False, "code": "destination_invalid", "message": str(exc.detail),
        })
    return JSONResponse(status_code=200, content={
        "ok": True,
        "instance_id": record.instance_id,
        "world_id": record.world_id,
        "client_url": client_url,
        "entry_room_id": record.entry_room_id,
    }, headers={"Cache-Control": "no-store"})
