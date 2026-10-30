"""Player authentication and exact-instance entry for mission control."""

from __future__ import annotations

from datetime import UTC, datetime
import hmac
import json
from pathlib import Path
import tempfile
import time
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from server.instance_policy import AccountLimitError, InstancePolicyStore
from server.mission_control.registry import SPAWNED, STATUS_RUNNING, InstanceRecord
from server.mission_control.routes import _client_key, _enforce_post, _require_operator, _require_token
from server.profiles import ProfileRepository, SessionRecord
from server.security import (
    CSRF_COOKIE, SESSION_COOKIE, RateLimitError, RateLimiter, normalize_username,
    require_matching_csrf, validate_origin, validate_password, verify_password,
)


router = APIRouter()


class EntryError(HTTPException):
    """An entry failure that carries a stable machine-readable code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        data: dict[str, object] | None = None,
    ) -> None:
        super().__init__(status_code, message)
        self.code = code
        self.data = data


def _instance_label(record: InstanceRecord) -> str:
    """Return a human-readable instance label for entry errors."""

    return f"'{record.name}' ({record.instance_id})"


class Credentials(BaseModel):
    """Player login credentials."""

    username: str
    password: str


class CreateCredentials(Credentials):
    """Invitation-gated player account creation."""

    passphrase: str


class RepairDestination(BaseModel):
    """Explicit player confirmation of a replacement same-world instance."""

    instance_id: str
    world_id: str | None = None


class PlayerAuthService:
    """Shared-database authentication with runtime-lifetime attempt limits."""

    def __init__(
        self,
        profiles: ProfileRepository,
        invitation: str,
        policy_store: InstancePolicyStore | None = None,
    ) -> None:
        self.profiles = profiles
        self._invitation = invitation
        self._policy_store = policy_store
        self.limiter = RateLimiter()

    @property
    def invitation(self) -> str:
        """Return the current invitation, preferring the shared policy file."""

        if self._policy_store is not None:
            return self._policy_store.load().invitation_code
        return self._invitation

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
        raise EntryError(409, "entry_instance_client_url",
                         f"Destination client URL for {_instance_label(record)} is invalid.")
    return value


async def _validate_running_destination(runtime, record: InstanceRecord) -> str:
    """Validate a running instance's identity and client URL, without host checks."""

    status = runtime.registry.snapshot(record)["status"]
    label = _instance_label(record)
    if not record.registered_at:
        if status == STATUS_RUNNING:
            raise EntryError(
                503,
                "entry_instance_not_registered",
                f"Instance {label} is running but has not re-registered since Mission Control restarted. "
                "It should reconnect within a few seconds; retry, or restart it in Server Manager.",
            )
        raise EntryError(
            503,
            "entry_instance_not_registered",
            f"Instance {label} is {status.replace('_', ' ')} and has not registered with Mission Control. "
            "Start or restart it in Server Manager.",
        )
    if status != STATUS_RUNNING:
        raise EntryError(
            503,
            "entry_instance_not_running",
            f"Instance {label} is {status.replace('_', ' ')}. Start it in Server Manager, then retry.",
        )
    if not record.world_id:
        raise EntryError(
            409,
            "entry_instance_no_world",
            f"Instance {label} has not reported a world identity. Restart it in Server Manager.",
        )
    if record.source == SPAWNED:
        users_path = (record.spawn_config or {}).get("users_path")
        if not users_path or Path(str(users_path)).resolve() != runtime.config.users_path.resolve():
            raise EntryError(
                409,
                "entry_instance_db_mismatch",
                f"Instance {label} does not use the shared player database.",
            )
    client_url = _format_client_url(record)
    try:
        response = await runtime.http.get(f"{record.endpoint.rstrip('/')}{record.base_path}/health", timeout=5.0)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise EntryError(
            503,
            "entry_instance_unreachable",
            f"Instance {label} is registered but could not be reached. Retry, or restart it in Server Manager.",
        ) from exc
    if not isinstance(data, dict) or data.get("world_id") != record.world_id or data.get("instance_id") != record.instance_id:
        raise EntryError(
            409,
            "entry_instance_identity",
            f"Instance {label} health response does not match its registration. Restart it in Server Manager.",
        )
    return client_url


def _is_runnable(runtime, record: InstanceRecord) -> bool:
    """Return whether an instance is registered and currently running."""

    return bool(record.registered_at) and runtime.registry.snapshot(record)["status"] == STATUS_RUNNING


async def _destination(request: Request, instance_id: str) -> tuple[InstanceRecord, str]:
    runtime = request.app.state.mc
    record = runtime.registry.get(instance_id)
    if record is None:
        raise EntryError(409, "entry_instance_missing",
                         f"The saved instance '{instance_id}' is no longer registered. Ask an operator to restore it.")
    client_url = await _validate_running_destination(runtime, record)
    if urlsplit(client_url).hostname != request.url.hostname:
        raise HTTPException(409, "Destination must use the same hostname as player entry so the login cookie can be shared across ports.")
    return record, client_url


def _repair_candidates(
    runtime,
    request: Request,
    world_id: str,
    *,
    saved_instance_id: str | None = None,
    successor_instance_id: str | None = None,
) -> list[dict[str, object]]:
    """Return runnable same-world instances a player could explicitly choose."""

    candidates: list[dict[str, object]] = []
    for record in runtime.registry.list():
        if record.instance_id == saved_instance_id or record.world_id != world_id:
            continue
        if not record.registered_at:
            continue
        if runtime.registry.snapshot(record)["status"] != STATUS_RUNNING:
            continue
        try:
            client_url = _format_client_url(record)
        except HTTPException:
            continue
        if urlsplit(client_url).hostname != request.url.hostname:
            continue
        candidates.append(
            {
                "instance_id": record.instance_id,
                "world_id": record.world_id,
                "label": record.name,
                "client_url": client_url,
                "entry_room_id": record.entry_room_id,
                "replacement": record.instance_id == successor_instance_id,
            }
        )
    candidates.sort(
        key=lambda candidate: (
            not candidate["replacement"],
            str(candidate["label"]).casefold(),
            str(candidate["instance_id"]),
        )
    )
    return candidates


def _recovery_response(
    runtime,
    request: Request,
    profile,
    *,
    code: str,
    saved_instance_id: str | None,
) -> JSONResponse:
    """Return a recoverable destination error with explicit same-world choices."""

    world_id = profile.last_world_id
    retirement = runtime.retired.get(saved_instance_id)
    successor = retirement.get("successor_instance_id") if retirement else None
    if not isinstance(successor, str) or not successor:
        successor = None
    candidates = _repair_candidates(
        runtime,
        request,
        world_id,
        saved_instance_id=saved_instance_id,
        successor_instance_id=successor,
    )
    if candidates:
        if saved_instance_id:
            message = (
                f"The saved instance '{saved_instance_id}' is not available right now. "
                f"Choose another running instance of '{world_id}' to continue."
            )
        else:
            message = (
                f"Your saved world '{world_id}' has more than one running instance. "
                "Choose one to continue."
            )
    elif saved_instance_id:
        message = f"The saved instance '{saved_instance_id}' is no longer registered. Ask an operator to restore it."
    else:
        message = (
            f"Your saved world '{world_id}' does not identify a running instance. "
            "Ask an operator to restore your destination."
        )
    data: dict[str, object] = {
        "saved_instance_id": saved_instance_id,
        "world_id": world_id,
        "can_repair": bool(candidates),
        "candidates": candidates,
    }
    if retirement is not None:
        data["retired"] = True
        data["retired_at"] = retirement.get("retired_at")
    if successor is not None:
        data["successor_instance_id"] = successor
    return JSONResponse(
        status_code=409,
        content={"ok": False, "code": code, "message": message, **data},
        headers={"Cache-Control": "no-store"},
    )


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
        raise EntryError(409, "entry_instance_no_entry_room",
                         f"Instance {_instance_label(record)} has not reported its entry room. Restart it in Server Manager.")
    try:
        account = runtime.profiles.create_account(display, payload.password, record.world_id, record.entry_room_id)
    except AccountLimitError as exc:
        raise EntryError(
            409,
            "account_limit_reached",
            "This instance has reached its guest account limit.",
        ) from exc
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
    """Resolve the exact saved instance, offering same-world recovery when it is gone."""

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
            return _recovery_response(
                runtime,
                request,
                profile,
                code="entry_instance_ambiguous",
                saved_instance_id=None,
            )
        instance_id = matches[0].instance_id
    record = runtime.registry.get(instance_id)
    if record is None or not _is_runnable(runtime, record):
        return _recovery_response(
            runtime,
            request,
            profile,
            code="entry_instance_missing" if record is None else "entry_instance_not_running",
            saved_instance_id=instance_id,
        )
    try:
        record, client_url = await _destination(request, instance_id)
    except EntryError as exc:
        if exc.code in {
            "entry_instance_unreachable",
            "entry_instance_identity",
            "entry_instance_client_url",
        }:
            return _recovery_response(
                runtime,
                request,
                profile,
                code=exc.code,
                saved_instance_id=instance_id,
            )
        raise
    if record.world_id != profile.last_world_id:
        raise HTTPException(409, "Your saved instance now serves a different world. Ask an operator for help.")
    return JSONResponse({"ok": True, "instance_id": record.instance_id, "world_id": record.world_id,
                         "client_url": client_url}, headers={"Cache-Control": "no-store"})


@router.post("/api/entry/repair")
async def repair(request: Request, payload: RepairDestination) -> Response:
    """Explicitly rebind a player to another running instance of their saved world."""

    runtime = request.app.state.mc
    session = _session(request)
    validate_origin(request.headers.get("origin"), runtime.config)
    require_matching_csrf(session.csrf_token, request.headers.get("x-csrf-token"))
    require_matching_csrf(session.csrf_token, request.cookies.get(CSRF_COOKIE))

    profile = runtime.profiles.get_user_profile(session.account_id)
    if profile is None:
        raise HTTPException(409, "Your player profile is missing. Ask an operator for help.")
    saved_instance_id = profile.last_instance_id
    saved = runtime.registry.get(saved_instance_id) if saved_instance_id else None
    if saved is not None:
        try:
            await _validate_running_destination(runtime, saved)
        except EntryError:
            pass
        else:
            raise EntryError(
                409,
                "entry_instance_healthy",
                "Your saved instance is available. Reload player entry to continue.",
            )
    if payload.world_id is not None and payload.world_id != profile.last_world_id:
        raise EntryError(
            409,
            "entry_instance_world_mismatch",
            "You can only repair your saved world destination.",
        )
    record, client_url = await _destination(request, payload.instance_id)
    if record.world_id != profile.last_world_id:
        raise EntryError(
            409,
            "entry_instance_world_mismatch",
            "That instance serves a different world. Ask an operator for help.",
        )
    runtime.profiles.remember_instance(session.account_id, record.instance_id)
    runtime.audit.record(
        f"account:{session.account_id}",
        "player.destination.repair",
        target=record.instance_id,
        detail={"world_id": record.world_id, "previous_instance_id": saved_instance_id},
    )
    return JSONResponse(
        {
            "ok": True,
            "instance_id": record.instance_id,
            "world_id": record.world_id,
            "client_url": client_url,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/mission-control/instances/{instance_id}/default")
async def set_default(request: Request, instance_id: str) -> dict[str, object]:
    """Persist the operator's default after validating the registered destination."""

    session = _require_operator(request)
    _enforce_post(request, session)
    record, _ = await _destination(request, instance_id)
    if not record.entry_room_id:
        raise EntryError(409, "entry_instance_no_entry_room",
                         f"Instance {_instance_label(record)} has not reported its entry room. Restart it in Server Manager.")
    runtime = request.app.state.mc
    runtime.entry_settings.set_default(instance_id)
    runtime.audit.record("operator", "instance.default", target=instance_id)
    return {"ok": True, "default_instance_id": instance_id}


def _world_image_url(record: InstanceRecord) -> str:
    """Return the destination-served world image URL, when one is authored."""

    if not record.world_image or not record.client_url:
        return ""
    return urljoin(f"{record.client_url.rstrip('/')}/", "assets/world-image")


@router.get("/api/mc/worlds")
async def fleet_worlds(request: Request) -> Response:
    """List running worlds for the in-game Multiverse view.

    Token-authenticated fleet endpoint. Instances are grouped by world so the
    caller can choose a destination that shares its browser hostname.
    """

    _require_token(request)
    runtime = request.app.state.mc
    grouped: dict[str, dict[str, object]] = {}
    for record in runtime.registry.list():
        if not record.world_id or not record.registered_at:
            continue
        if runtime.registry.snapshot(record)["status"] != STATUS_RUNNING:
            continue
        world = grouped.setdefault(
            record.world_id,
            {
                "id": record.world_id,
                "label": record.world_label or record.world_id,
                "description": record.world_description,
                "image": record.world_image,
                "online_account_ids": set(),
                "reported_users_online": 0,
                "instances": [],
            },
        )
        if not world["description"] and record.world_description:
            world["description"] = record.world_description
        if not world["image"] and record.world_image:
            world["image"] = record.world_image
        world["online_account_ids"].update(record.online_account_ids)
        world["reported_users_online"] = int(world["reported_users_online"]) + record.users_online
        world["instances"].append(
            {
                "instance_id": record.instance_id,
                "client_url": record.client_url,
                "entry_room_id": record.entry_room_id,
                "image_url": _world_image_url(record),
            }
        )
    worlds: list[dict[str, object]] = []
    for world in grouped.values():
        online_ids = sorted(world.pop("online_account_ids"))
        reported = int(world.pop("reported_users_online"))
        world["online_account_ids"] = online_ids
        world["users_online"] = len(online_ids) if online_ids else reported
        worlds.append(world)
    worlds.sort(key=lambda item: (str(item["label"]).casefold(), str(item["id"])))
    return JSONResponse(
        status_code=200,
        content={"ok": True, "worlds": worlds},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/mc/instances/{world_id}/destination")
async def fleet_world_destination(
    request: Request,
    world_id: str,
    host: str | None = None,
) -> Response:
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
    if host:
        record = next(
            (
                candidate
                for candidate in running
                if urlsplit(candidate.client_url or "").hostname == host
            ),
            record,
        )
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
