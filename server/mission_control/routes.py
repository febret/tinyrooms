"""Mission-control UI API and fleet endpoints."""

from __future__ import annotations

import hmac
import json
import logging
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from server.commands.admin import ALLOWED_ADMIN_COMMANDS
from server.mission_control.auth import MC_CSRF_COOKIE, MC_SESSION_COOKIE, McSession
from server.mission_control.registry import STATUS_RUNNING, STATUS_UNREACHABLE
from server.security import RateLimitError, require_matching_csrf, validate_origin
from server.version import BUILD_VERSION


LOGGER = logging.getLogger("tinyrooms.mc")
router = APIRouter()
LOGIN_ATTEMPT_LIMIT = 10
LOGIN_ATTEMPT_WINDOW_SECONDS = 300


class LoginPayload(BaseModel):
    """Operator login payload."""

    passphrase: str


class StartInstancePayload(BaseModel):
    """Start-instance form payload."""

    world: str
    worldstate_db: str | None = None
    users_path: str | None = None
    name: str | None = None
    host: str = "127.0.0.1"
    port: int | None = None
    features: str = ""
    admins: str = ""
    mods: str | None = None


class EnablePayload(BaseModel):
    """Package enable/disable payload."""

    enabled: bool


class EditUserPayload(BaseModel):
    """User edit payload."""

    fields: dict[str, object]


class RegisterPayload(BaseModel):
    """Instance registration payload (world -> mission control)."""

    instance_name: str
    endpoint: str
    version: str | None = None
    protocol_version: int | None = None
    world: dict[str, object] = {}
    started_at: str | None = None


class HeartbeatPayload(BaseModel):
    """Instance heartbeat payload (world -> mission control)."""

    instance_id: str
    uptime_seconds: float = 0.0
    users_online: int = 0
    world_id: str | None = None


class DeregisterPayload(BaseModel):
    """Instance deregistration payload."""

    instance_id: str


def _runtime(request: Request):
    return request.app.state.mc


def _json_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "code": code, "message": message})


def _require_token(request: Request) -> None:
    runtime = _runtime(request)
    presented = request.headers.get("x-mc-token")
    if not presented or not hmac.compare_digest(runtime.config.token, presented):
        LOGGER.warning(json.dumps({"event": "mc.token_rejected", "path": request.url.path}))
        raise HTTPException(status_code=403, detail="Invalid mission-control token.")


def _require_operator(request: Request) -> McSession:
    runtime = _runtime(request)
    session = runtime.sessions.get(request.cookies.get(MC_SESSION_COOKIE))
    if session is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return session


def _enforce_post(request: Request, session: McSession) -> None:
    runtime = _runtime(request)
    validate_origin(request.headers.get("origin"), runtime.config)
    csrf_cookie = request.cookies.get(MC_CSRF_COOKIE)
    if csrf_cookie is None:
        raise HTTPException(status_code=403, detail="Missing CSRF cookie.")
    require_matching_csrf(session.csrf_token, request.headers.get("x-csrf-token"))
    require_matching_csrf(session.csrf_token, csrf_cookie)


def _client_key(request: Request) -> str:
    client = request.client
    return "unknown" if client is None else client.host


async def _world_call(
    runtime,
    endpoint: str,
    method: str,
    path: str,
    *,
    json_body: dict[str, object] | None = None,
    timeout: float = 5.0,
) -> dict[str, object]:
    response = await runtime.http.request(
        method,
        f"{endpoint}{path}",
        json=json_body,
        headers={"X-MC-Token": runtime.config.token},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _set_mc_cookies(response: Response, *, token: str, csrf_token: str, expires_at: str) -> None:
    response.set_cookie(MC_SESSION_COOKIE, token, httponly=True, secure=True, samesite="lax", expires=expires_at, path="/")
    response.set_cookie(MC_CSRF_COOKIE, csrf_token, httponly=False, secure=True, samesite="lax", expires=expires_at, path="/")


def _clear_mc_cookies(response: Response) -> None:
    response.delete_cookie(MC_SESSION_COOKIE, path="/")
    response.delete_cookie(MC_CSRF_COOKIE, path="/")


# --- Fleet channel (token authenticated) -------------------------------------


@router.post("/api/mc/register")
async def fleet_register(request: Request, payload: RegisterPayload) -> dict[str, object]:
    """Register a world-server instance and assign it an id."""

    _require_token(request)
    runtime = _runtime(request)
    record = runtime.registry.register(payload.model_dump())
    runtime.registry.set_capabilities(record.instance_id, list(ALLOWED_ADMIN_COMMANDS))
    runtime.audit.record("world", "instance.register", target=record.instance_id, detail={"endpoint": record.endpoint})
    return {
        "ok": True,
        "instance_id": record.instance_id,
        "heartbeat_seconds": runtime.config.heartbeat_seconds,
        "capabilities": list(ALLOWED_ADMIN_COMMANDS),
    }


@router.post("/api/mc/heartbeat")
async def fleet_heartbeat(request: Request, payload: HeartbeatPayload) -> dict[str, object]:
    """Record an instance heartbeat."""

    _require_token(request)
    runtime = _runtime(request)
    record = runtime.registry.heartbeat(
        payload.instance_id,
        uptime_seconds=payload.uptime_seconds,
        users_online=payload.users_online,
        world_id=payload.world_id,
    )
    if record is None:
        return {"ok": False, "code": "unknown_instance", "message": "Instance is not registered."}
    return {"ok": True, "pending_commands": []}


@router.post("/api/mc/deregister")
async def fleet_deregister(request: Request, payload: DeregisterPayload) -> dict[str, object]:
    """Mark an instance as stopped on graceful shutdown."""

    _require_token(request)
    runtime = _runtime(request)
    runtime.registry.set_status(payload.instance_id, "stopped")
    return {"ok": True}


# --- UI authentication --------------------------------------------------------


@router.post("/api/mission-control/auth/login")
async def login(request: Request, payload: LoginPayload) -> Response:
    """Authenticate an operator with the shared passphrase."""

    runtime = _runtime(request)
    validate_origin(request.headers.get("origin"), runtime.config)
    try:
        runtime.limiter.check(
            _client_key(request),
            limit=LOGIN_ATTEMPT_LIMIT,
            window_seconds=LOGIN_ATTEMPT_WINDOW_SECONDS,
            now_ts=time.time(),
        )
    except RateLimitError:
        runtime.audit.record(_client_key(request), "auth.login", result="rate_limited")
        raise
    try:
        issued = runtime.sessions.login(payload.passphrase, runtime.config.passphrase)
    except PermissionError:
        runtime.audit.record(_client_key(request), "auth.login", result="denied")
        return _json_error(401, "invalid_passphrase", "Incorrect passphrase.")
    runtime.audit.record("operator", "auth.login", result="ok")
    response = JSONResponse({"ok": True, "operator": "operator", "csrf_token": issued.csrf_token})
    _set_mc_cookies(response, token=issued.token, csrf_token=issued.csrf_token, expires_at=issued.expires_at.isoformat())
    return response


@router.post("/api/mission-control/auth/logout")
async def logout(request: Request) -> Response:
    """End the operator session."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    runtime.sessions.logout(request.cookies.get(MC_SESSION_COOKIE))
    response = JSONResponse({"ok": True})
    _clear_mc_cookies(response)
    return response


@router.get("/api/mission-control/session")
async def session_status(request: Request) -> dict[str, object]:
    """Return the current operator session."""

    runtime = _runtime(request)
    session = runtime.sessions.get(request.cookies.get(MC_SESSION_COOKIE))
    if session is None:
        return {"ok": True, "logged_in": False, "version": BUILD_VERSION}
    return {"ok": True, "logged_in": True, "operator": session.operator, "version": BUILD_VERSION}


# --- Server Manager -----------------------------------------------------------


@router.get("/api/mission-control/servers")
async def list_servers(request: Request) -> dict[str, object]:
    """List known instances with a status summary."""

    _require_operator(request)
    runtime = _runtime(request)
    records = runtime.registry.list()
    servers = [runtime.registry.snapshot(record) for record in records]
    summary = {
        "total": len(servers),
        "running": sum(1 for item in servers if item["status"] == STATUS_RUNNING),
        "unreachable": sum(1 for item in servers if item["status"] == STATUS_UNREACHABLE),
        "external": sum(1 for item in servers if item["source"] == "external"),
    }
    return {"ok": True, "servers": servers, "summary": summary}


@router.post("/api/mission-control/servers")
async def start_server(request: Request, payload: StartInstancePayload) -> dict[str, object]:
    """Spawn a new world-server instance."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    record = runtime.packages.record("world", payload.world)
    if record is None or record.validation_status == "error" or not record.enabled:
        return _json_error(400, "world_unavailable", f"World '{payload.world}' is not available.")
    worldstate_path = Path(payload.worldstate_db).expanduser() if payload.worldstate_db else None
    if worldstate_path is not None and (not worldstate_path.is_file() or worldstate_path.is_dir()):
        return _json_error(400, "worldstate_invalid", "Worldstate DB must be an existing .sqlite3 file.")
    users_path = Path(payload.users_path).expanduser() if payload.users_path else None
    name = payload.name or payload.world
    spawned = runtime.supervisor.start(
        name=name,
        world_path=record.path,
        worldstate_path=worldstate_path,
        users_path=users_path,
        host=payload.host,
        port=payload.port,
        features=payload.features,
        admins=payload.admins,
        mods=payload.mods,
    )
    return {"ok": True, "server": runtime.registry.snapshot(spawned)}


@router.get("/api/mission-control/servers/{instance_id}")
async def server_detail(request: Request, instance_id: str) -> dict[str, object]:
    """Return an instance's detail and (best-effort) runtime stats."""

    _require_operator(request)
    runtime = _runtime(request)
    record = runtime.registry.get(instance_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    detail = runtime.registry.snapshot(record)
    detail["stats"] = record.stats_cache
    detail["log_source"] = "process" if record.source == "spawned" else "poll"
    if record.status == STATUS_RUNNING:
        try:
            stats = await _world_call(runtime, record.endpoint, "GET", "/api/mc/stats")
            runtime.registry.set_stats(instance_id, stats)
            detail["stats"] = stats
        except (httpx.HTTPError, ValueError) as exc:
            runtime.registry.set_status(instance_id, STATUS_UNREACHABLE)
            detail["status"] = STATUS_UNREACHABLE
            detail["error"] = f"{type(exc).__name__}"
    return {"ok": True, "server": detail}


@router.post("/api/mission-control/servers/{instance_id}/stop")
async def stop_server(request: Request, instance_id: str) -> dict[str, object]:
    """Stop a spawned child or cooperatively shut down an external instance."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    record = runtime.registry.get(instance_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    if record.source == "spawned":
        runtime.supervisor.stop(instance_id)
    else:
        await _world_call(runtime, record.endpoint, "POST", "/api/mc/shutdown", json_body={"actor": runtime.config.actor})
        runtime.registry.set_status(instance_id, "stopped")
    runtime.audit.record("operator", "instance.stop", target=instance_id)
    return {"ok": True}


@router.post("/api/mission-control/servers/{instance_id}/restart")
async def restart_server(request: Request, instance_id: str) -> dict[str, object]:
    """Restart a spawned child or cooperatively restart an external instance."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    record = runtime.registry.get(instance_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    if record.source == "spawned":
        restarted = runtime.supervisor.restart(instance_id)
        runtime.audit.record("operator", "instance.restart", target=instance_id)
        return {"ok": True, "server": None if restarted is None else runtime.registry.snapshot(restarted)}
    await _world_call(runtime, record.endpoint, "POST", "/api/mc/restart", json_body={"actor": runtime.config.actor})
    runtime.audit.record("operator", "instance.restart", target=instance_id)
    return {"ok": True}


@router.get("/api/mission-control/servers/{instance_id}/logs")
async def server_logs(request: Request, instance_id: str, limit: int = 200) -> dict[str, object]:
    """Return a log tail for an instance."""

    _require_operator(request)
    runtime = _runtime(request)
    record = runtime.registry.get(instance_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    if record.source == "spawned":
        return {"ok": True, "source": "process", "lines": runtime.registry.logs(instance_id, limit)}
    try:
        payload = await _world_call(runtime, record.endpoint, "GET", f"/api/mc/logs?limit={limit}")
        return {"ok": True, "source": "poll", "lines": payload.get("lines", [])}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "code": "unreachable", "message": f"{type(exc).__name__}"}


@router.post("/api/mission-control/servers/{instance_id}/command")
async def server_command(request: Request, instance_id: str, payload: dict[str, object]) -> dict[str, object]:
    """Validate and forward an admin command to an instance."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    record = runtime.registry.get(instance_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    command = str(payload.get("command", "")).strip()
    if not command:
        return _json_error(400, "command_empty", "Command must not be empty.")
    capabilities = record.capabilities or list(ALLOWED_ADMIN_COMMANDS)
    token = command.lstrip("\\.").split(maxsplit=1)[0].lower() if command else ""
    if token not in capabilities:
        return _json_error(400, "capability_unknown", f"'{token}' is not an available admin command.")
    try:
        result = await _world_call(
            runtime,
            record.endpoint,
            "POST",
            "/api/mc/command",
            json_body={"command": command, "actor": runtime.config.actor},
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _json_error(502, "unreachable", f"{type(exc).__name__}")
    runtime.audit.record("operator", "instance.command", target=instance_id, detail={"command": token})
    return {"ok": True, "result": result}


@router.post("/api/mission-control/servers/{instance_id}/resync")
async def resync_server(request: Request, instance_id: str) -> dict[str, object]:
    """Force one instance to reload profile data and notify its clients."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    record = runtime.registry.get(instance_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    try:
        result = await _world_call(
            runtime,
            record.endpoint,
            "POST",
            "/api/mc/resync",
            json_body={"actor": runtime.config.actor, "scope": "instance"},
        )
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "code": "unreachable", "message": f"{type(exc).__name__}", "instance_id": instance_id}
    runtime.audit.record("operator", "instance.resync", target=instance_id)
    return {"ok": True, "instance_id": instance_id, "result": result}


@router.post("/api/mission-control/resync")
async def resync_all(request: Request) -> dict[str, object]:
    """Force every running instance to reload profile data."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    results: list[dict[str, object]] = []
    for record in runtime.registry.list():
        if record.status != STATUS_RUNNING:
            continue
        try:
            payload = await _world_call(
                runtime,
                record.endpoint,
                "POST",
                "/api/mc/resync",
                json_body={"actor": runtime.config.actor, "scope": "all"},
            )
            results.append({"instance_id": record.instance_id, "ok": True, "result": payload})
        except (httpx.HTTPError, ValueError) as exc:
            results.append({"instance_id": record.instance_id, "ok": False, "message": type(exc).__name__})
    runtime.audit.record("operator", "fleet.resync", detail={"count": len(results)})
    return {"ok": True, "results": results}


# --- Package Manager ----------------------------------------------------------


@router.get("/api/mission-control/packages")
async def list_packages(request: Request) -> dict[str, object]:
    """Return the package inventory."""

    _require_operator(request)
    runtime = _runtime(request)
    return {"ok": True, "packages": runtime.packages.inventory()}


@router.post("/api/mission-control/packages")
async def upload_package(request: Request, kind: str) -> dict[str, object]:
    """Validate and install an uploaded package zip."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    data = await request.body()
    try:
        record = runtime.packages.install(kind, data, actor="operator")
    except ValueError as exc:
        return _json_error(400, "package_rejected", str(exc))
    return {"ok": True, "package": record.to_dict()}


@router.post("/api/mission-control/packages/{kind}/{package_id}/enable")
async def enable_package(request: Request, kind: str, package_id: str, payload: EnablePayload) -> dict[str, object]:
    """Enable or disable a package for this session."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    runtime.packages.set_enabled(kind, package_id, payload.enabled, actor="operator")
    return {"ok": True}


@router.delete("/api/mission-control/packages/{kind}/{package_id}")
async def delete_package(request: Request, kind: str, package_id: str) -> dict[str, object]:
    """Delete an installed package directory."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    try:
        runtime.packages.delete(kind, package_id, actor="operator")
    except ValueError as exc:
        return _json_error(400, "package_delete_failed", str(exc))
    return {"ok": True}


# --- User Manager -------------------------------------------------------------


@router.get("/api/mission-control/users")
async def list_users(request: Request, q: str | None = None, limit: int = 50) -> dict[str, object]:
    """Search or list accounts."""

    _require_operator(request)
    runtime = _runtime(request)
    return {"ok": True, "users": runtime.users.search(q, limit=max(1, min(limit, 200)))}


@router.get("/api/mission-control/users/{account_id}")
async def user_detail(request: Request, account_id: str) -> dict[str, object]:
    """Return an account and its related rows."""

    _require_operator(request)
    runtime = _runtime(request)
    detail = runtime.users.detail(account_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    return {"ok": True, "user": detail}


@router.patch("/api/mission-control/users/{account_id}")
async def edit_user(request: Request, account_id: str, payload: EditUserPayload) -> dict[str, object]:
    """Apply supported edits to an account."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    try:
        updated = runtime.users.edit("operator", account_id, payload.fields)
    except ValueError as exc:
        return _json_error(400, "user_edit_rejected", str(exc))
    return {"ok": True, "user": updated}


# --- Audit --------------------------------------------------------------------


@router.get("/api/mission-control/audit")
async def audit_entries(request: Request, limit: int = 100) -> dict[str, object]:
    """Return recent mission-control audit entries."""

    _require_operator(request)
    runtime = _runtime(request)
    return {"ok": True, "entries": runtime.audit.entries(max(1, min(limit, 500)))}
