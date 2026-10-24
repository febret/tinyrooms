"""Mission-control UI API and fleet endpoints."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import shlex
import signal
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server.commands.admin import ALLOWED_ADMIN_COMMANDS
from server.config import ConfigError, normalize_base_path
from server.mission_control.auth import MC_CSRF_COOKIE, MC_SESSION_COOKIE, McSession
from server.mission_control.packages import RUNNING_VERSION_ID
from server.mission_control.registry import (
    EXTERNAL,
    SPAWNED,
    STATUS_RUNNING,
    STATUS_STARTING,
    STATUS_STOPPED,
    STATUS_UNREACHABLE,
)
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
    version: str | None = None
    worldstate_db: str | None = None
    users_path: str | None = None
    name: str | None = None
    host: str | None = None
    port: int | None = None
    features: str = ""
    admins: str = ""
    mods: str | None = None


class RenameInstancePayload(BaseModel):
    """Rename-instance payload."""

    name: str


class ChangeVersionPayload(BaseModel):
    """Instance version-change payload."""

    version: str | None = None


class EditUserPayload(BaseModel):
    """User edit payload."""

    fields: dict[str, object]


class RepairUserDestinationPayload(BaseModel):
    """Operator-selected replacement destination for one player."""

    instance_id: str


class RegisterPayload(BaseModel):
    """Instance registration payload (world -> mission control)."""

    instance_name: str
    instance_id: str | None = None
    endpoint: str
    client_url: str | None = None
    version: str | None = None
    protocol_version: int | None = None
    world: dict[str, object] = {}
    started_at: str | None = None
    base_path: str = ""


class HeartbeatPayload(BaseModel):
    """Instance heartbeat payload (world -> mission control)."""

    instance_id: str
    uptime_seconds: float = 0.0
    users_online: int = 0
    online_account_ids: list[str] = Field(default_factory=list)
    world_id: str | None = None


class DeregisterPayload(BaseModel):
    """Instance deregistration payload."""

    instance_id: str


class CleanupVersionsPayload(BaseModel):
    """Bulk version-cleanup payload."""

    dry_run: bool = False
    ids: list[str] | None = None


def _runtime(request: Request):
    return request.app.state.mc


def _with_route_warning(runtime: object, payload: dict[str, object]) -> dict[str, object]:
    """Attach a recent world-map failure to a lifecycle response."""

    warning = getattr(getattr(runtime, "supervisor", None), "route_warning", None)
    if warning:
        payload["warning"] = warning
    return payload


def _json_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "code": code, "message": message})


def _require_token(request: Request) -> None:
    runtime = _runtime(request)
    presented = request.headers.get("x-mc-token")
    if not presented or not hmac.compare_digest(runtime.config.token, presented):
        LOGGER.warning(json.dumps({"event": "mc.token_rejected", "path": request.url.path}))
        runtime.audit.record("unknown", "mc.token_rejected", result="denied", detail={"path": request.url.path})
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
    require_matching_csrf(session.csrf_token, request.headers.get("x-csrf-token"))


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


def _launch_keepalive(keepalive: Path) -> None:
    """Start a detached process that reruns the keepalive script after exit."""

    script = shlex.quote(str(keepalive))
    subprocess.Popen(
        ["/bin/bash", "-c", f"sleep 4; exec {script}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def _exit_soon() -> None:
    """Ask the running server to shut down gracefully."""

    os.kill(os.getpid(), signal.SIGTERM)


# --- Fleet channel (token authenticated) -------------------------------------


@router.post("/api/mc/register")
async def fleet_register(request: Request, payload: RegisterPayload) -> dict[str, object]:
    """Register a world-server instance and assign it an id."""

    _require_token(request)
    runtime = _runtime(request)
    try:
        base_path = normalize_base_path(payload.base_path)
    except ConfigError as exc:
        return _json_error(400, "base_path_invalid", str(exc))
    if runtime.config.same_origin_worlds and payload.instance_id:
        existing = runtime.registry.get(payload.instance_id)
        if existing is not None and existing.source == SPAWNED and existing.spawn_config:
            expected_base = normalize_base_path(str(existing.spawn_config.get("base_path") or ""))
            expected_url = str(existing.spawn_config.get("client_url") or "").rstrip("/")
            submitted_url = str(payload.client_url or "").rstrip("/")
            if base_path != expected_base or (submitted_url and submitted_url != expected_url):
                return _json_error(
                    409,
                    "reregister_mismatch",
                    "Restart this instance so Mission Control can update its same-origin route.",
                )
    data = payload.model_dump()
    data["base_path"] = base_path
    record = runtime.registry.register(data)
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
        online_account_ids=payload.online_account_ids,
        world_id=payload.world_id,
    )
    if record is None:
        return {"ok": False, "code": "unknown_instance", "message": "Instance is not registered."}
    if not record.registered_at:
        return {
            "ok": False,
            "code": "reregister_required",
            "message": "Instance was restored by Mission Control and must re-register.",
            "needs_registration": True,
        }
    return {"ok": True, "pending_commands": []}


@router.post("/api/mc/deregister")
async def fleet_deregister(request: Request, payload: DeregisterPayload) -> dict[str, object]:
    """Mark an instance as stopped on graceful shutdown."""

    _require_token(request)
    runtime = _runtime(request)
    runtime.registry.set_status(payload.instance_id, STATUS_STOPPED)
    try:
        runtime.world_map.update()
    except Exception:  # noqa: BLE001 - routing refreshes are best effort
        LOGGER.exception("world_map.update_failed")
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
    default_id = runtime.entry_settings.default_instance_id
    for server in servers:
        server["is_default"] = server["instance_id"] == default_id
    summary = {
        "total": len(servers),
        "running": sum(1 for item in servers if item["status"] == STATUS_RUNNING),
        "unreachable": sum(1 for item in servers if item["status"] == STATUS_UNREACHABLE),
        "external": sum(1 for item in servers if item["source"] == EXTERNAL),
    }
    return {"ok": True, "servers": servers, "summary": summary}


@router.post("/api/mission-control/servers")
async def start_server(request: Request, payload: StartInstancePayload) -> dict[str, object]:
    """Spawn a new world-server instance."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    try:
        version_path = runtime.packages.resolve_version(payload.version)
        world_path = runtime.packages.resolve_world(payload.version, payload.world)
    except ValueError as exc:
        return _json_error(400, "world_unavailable", str(exc))
    worldstate_path = Path(payload.worldstate_db).expanduser() if payload.worldstate_db else None
    if worldstate_path is not None and (not worldstate_path.is_file() or worldstate_path.is_dir()):
        return _json_error(400, "worldstate_invalid", "Worldstate DB must be an existing .sqlite3 file.")
    users_path = Path(payload.users_path).expanduser() if payload.users_path else None
    name = payload.name or payload.world
    spawned = runtime.supervisor.start(
        name=name,
        world_path=world_path,
        worldstate_path=worldstate_path,
        users_path=users_path,
        host=payload.host,
        port=payload.port,
        features=payload.features,
        admins=payload.admins,
        mods=payload.mods,
        version_path=version_path,
        version_id=payload.version or RUNNING_VERSION_ID,
    )
    return _with_route_warning(runtime, {"ok": True, "server": runtime.registry.snapshot(spawned)})


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
    detail["log_source"] = "process" if record.source == SPAWNED else "poll"
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
    if record.source == SPAWNED:
        runtime.supervisor.stop(instance_id)
    else:
        try:
            await _world_call(runtime, record.endpoint, "POST", "/api/mc/shutdown")
        except (httpx.HTTPError, ValueError) as exc:
            return _json_error(502, "unreachable", f"{type(exc).__name__}")
        runtime.registry.set_status(instance_id, STATUS_STOPPED)
        try:
            runtime.world_map.update()
        except Exception:  # noqa: BLE001 - routing refreshes are best effort
            LOGGER.exception("world_map.update_failed")
    runtime.audit.record("operator", "instance.stop", target=instance_id)
    return _with_route_warning(runtime, {"ok": True})


@router.post("/api/mission-control/servers/{instance_id}/restart")
async def restart_server(request: Request, instance_id: str) -> dict[str, object]:
    """Restart a spawned child or cooperatively restart an external instance."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    record = runtime.registry.get(instance_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    if record.source == SPAWNED:
        restarted = runtime.supervisor.restart(instance_id)
        if restarted is None:
            return _json_error(502, "restart_unavailable", "Instance cannot be restarted automatically.")
        runtime.audit.record("operator", "instance.restart", target=instance_id)
        return _with_route_warning(runtime, {"ok": True, "server": runtime.registry.snapshot(restarted)})
    try:
        await _world_call(runtime, record.endpoint, "POST", "/api/mc/restart")
    except (httpx.HTTPError, ValueError) as exc:
        return _json_error(502, "unreachable", f"{type(exc).__name__}")
    runtime.audit.record("operator", "instance.restart", target=instance_id)
    return {"ok": True}


@router.post("/api/mission-control/servers/{instance_id}/start")
async def start_stopped_server(request: Request, instance_id: str) -> dict[str, object]:
    """Start a stopped spawned child without creating a new identity."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    record = runtime.registry.get(instance_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    if record.source != SPAWNED or record.spawn_config is None:
        return _json_error(400, "start_external", "Only spawned instances can be started by Mission Control.")
    if record.status in {STATUS_RUNNING, STATUS_STARTING}:
        return _json_error(409, "already_running", "Instance is already running.")
    started = runtime.supervisor.start_existing(instance_id)
    if started is None:
        return _json_error(409, "start_unavailable", "Instance is not stopped or cannot be started.")
    return _with_route_warning(runtime, {"ok": True, "server": runtime.registry.snapshot(started)})


@router.post("/api/mission-control/servers/{instance_id}/version")
async def change_server_version(
    request: Request,
    instance_id: str,
    payload: ChangeVersionPayload,
) -> dict[str, object]:
    """Switch a spawned instance to another installed version and apply it."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    record = runtime.registry.get(instance_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    if record.source != SPAWNED or record.spawn_config is None:
        return _json_error(400, "version_external", "Only spawned instances can change versions.")
    world_id = record.world_id or Path(str(record.spawn_config.get("world_path") or "")).name
    if not world_id:
        return _json_error(400, "world_unknown", "Instance has no saved world identity.")
    try:
        version_path = runtime.packages.resolve_version(payload.version)
        world_path = runtime.packages.resolve_world(payload.version, world_id)
    except ValueError as exc:
        return _json_error(400, "version_unavailable", str(exc))
    updated = runtime.supervisor.change_version(
        instance_id,
        version_id=payload.version or RUNNING_VERSION_ID,
        version_path=version_path,
        world_path=world_path,
    )
    if updated is None:
        return _json_error(409, "version_unavailable", "Instance version cannot be changed.")
    return {"ok": True, "server": runtime.registry.snapshot(updated)}


@router.post("/api/mission-control/servers/{instance_id}/rename")
async def rename_server(request: Request, instance_id: str, payload: RenameInstancePayload) -> dict[str, object]:
    """Rename a spawned instance."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    record = runtime.registry.get(instance_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    if record.source != SPAWNED:
        return _json_error(400, "rename_external", "Only spawned instances can be renamed.")
    name = payload.name.strip()
    if not name:
        return _json_error(400, "name_empty", "A new name is required.")
    renamed = runtime.supervisor.rename(instance_id, name)
    if renamed is None:
        return _json_error(502, "rename_unavailable", "Instance cannot be renamed.")
    runtime.audit.record("operator", "instance.rename", target=instance_id, detail={"name": name})
    return {"ok": True, "server": runtime.registry.snapshot(renamed)}


@router.get("/api/mission-control/servers/{instance_id}/destination-references")
async def destination_references(request: Request, instance_id: str) -> dict[str, object]:
    """Count players whose saved destination points at an instance."""

    _require_operator(request)
    runtime = _runtime(request)
    if runtime.registry.get(instance_id) is None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    return {"ok": True, "count": runtime.profiles.count_accounts_for_instance(instance_id)}


@router.delete("/api/mission-control/servers/{instance_id}")
async def delete_server(
    request: Request,
    instance_id: str,
    successor_instance_id: str | None = None,
    reassign_players: bool = False,
) -> dict[str, object]:
    """Stop and remove an instance, recording an optional successor destination."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    record = runtime.registry.get(instance_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    successor = None
    if successor_instance_id:
        successor = runtime.registry.get(successor_instance_id)
        if successor is None or successor.instance_id == instance_id:
            return _json_error(400, "successor_invalid", "Successor instance must be a different registered instance.")
        if not record.world_id or successor.world_id != record.world_id:
            return _json_error(400, "successor_world_mismatch", "Successor instance must serve the same world.")
        if not successor.registered_at or runtime.registry.snapshot(successor)["status"] != STATUS_RUNNING:
            return _json_error(400, "successor_unavailable", "Successor instance must be running and registered.")
    if record.source == SPAWNED:
        runtime.supervisor.delete(instance_id)
    else:
        try:
            await _world_call(runtime, record.endpoint, "POST", "/api/mc/shutdown")
        except (httpx.HTTPError, ValueError):
            pass
        runtime.registry.remove(instance_id)
    runtime.retired.record(
        record,
        successor_instance_id=successor.instance_id if successor is not None else None,
        actor="operator",
    )
    reassigned = 0
    if successor is not None and reassign_players:
        reassigned = runtime.profiles.reassign_last_instance(
            record.instance_id,
            successor.instance_id,
            str(record.world_id),
        )
    runtime.audit.record(
        "operator",
        "instance.delete",
        target=instance_id,
        detail={
            "successor_instance_id": successor.instance_id if successor is not None else None,
            "reassigned": reassigned,
        },
    )
    return _with_route_warning(runtime, {
        "ok": True,
        "successor_instance_id": successor.instance_id if successor is not None else None,
        "reassigned": reassigned,
    })


@router.post("/api/mission-control/reboot")
async def reboot(request: Request) -> dict[str, object]:
    """Stop all spawned instances, then hand off to the keepalive to restart MC."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    keepalive = runtime.config.keepalive_path
    if keepalive is None:
        return _json_error(400, "reboot_unconfigured", "TRSERVER_MC_KEEPALIVE is not configured.")
    resuming = runtime.supervisor.prepare_reboot()
    runtime.audit.record("operator", "mc.reboot", detail={"resuming": resuming})
    _launch_keepalive(keepalive)
    threading.Timer(0.5, _exit_soon).start()
    return {"ok": True, "resuming": resuming, "keepalive": str(keepalive)}


@router.get("/api/mission-control/servers/{instance_id}/logs")
async def server_logs(request: Request, instance_id: str, limit: int = 200) -> dict[str, object]:
    """Return a log tail for an instance."""

    _require_operator(request)
    runtime = _runtime(request)
    record = runtime.registry.get(instance_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    if record.source == SPAWNED:
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
            json_body={"command": command},
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
            json_body={"scope": "instance"},
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
                json_body={"scope": "all"},
            )
            results.append({"instance_id": record.instance_id, "ok": True, "result": payload})
        except (httpx.HTTPError, ValueError) as exc:
            results.append({"instance_id": record.instance_id, "ok": False, "message": type(exc).__name__})
    runtime.audit.record("operator", "fleet.resync", detail={"count": len(results)})
    return {"ok": True, "results": results}


# --- Package Manager ----------------------------------------------------------


@router.get("/api/mission-control/packages")
async def list_packages(request: Request) -> dict[str, object]:
    """Return the shared-content inventory and server versions."""

    _require_operator(request)
    runtime = _runtime(request)
    return {"ok": True, "packages": runtime.packages.inventory()}


@router.get("/api/mission-control/worlds")
async def list_worlds(request: Request, version: str | None = None) -> dict[str, object]:
    """Return worlds available to a server version (shared plus bundled)."""

    _require_operator(request)
    runtime = _runtime(request)
    try:
        worlds = runtime.packages.worlds_for(version)
    except ValueError as exc:
        return _json_error(400, "version_unavailable", str(exc))
    return {"ok": True, "worlds": worlds}


@router.delete("/api/mission-control/versions/{version_id}")
async def delete_version(request: Request, version_id: str) -> dict[str, object]:
    """Delete an unused installed server version and its release artifact."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    try:
        runtime.packages.delete_version(version_id, actor="operator")
    except ValueError as exc:
        return _json_error(400, "version_delete_failed", str(exc))
    return {"ok": True}


@router.post("/api/mission-control/versions/cleanup")
async def cleanup_versions(request: Request, payload: CleanupVersionsPayload) -> dict[str, object]:
    """Preview or delete unused version checkouts and orphan release tarballs."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    if payload.dry_run:
        candidates = await asyncio.to_thread(runtime.packages.cleanup_candidates)
        return {"ok": True, "candidates": candidates}
    result = await asyncio.to_thread(runtime.packages.cleanup_versions, payload.ids, actor="operator")
    return {"ok": True, **result}


@router.post("/api/mission-control/nginx/refresh")
async def refresh_nginx(request: Request) -> dict[str, object]:
    """Regenerate the nginx world map from running instances and reload nginx."""

    from server.mission_control.world_map import WorldMapError

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    if not runtime.world_map.enabled:
        return _json_error(400, "nginx_unconfigured", "Nginx world-map management is not configured.")
    try:
        result = await asyncio.to_thread(runtime.world_map.update, True)
    except WorldMapError as exc:
        return _json_error(502, "nginx_refresh_failed", str(exc))
    except Exception as exc:  # noqa: BLE001 - surface refresh failures without crashing
        return _json_error(502, "nginx_refresh_failed", f"{type(exc).__name__}: {exc}")
    runtime.audit.record(
        "operator",
        "nginx.refresh",
        detail={"routed": result["routed"], "changed": result["changed"]},
    )
    return {"ok": True, **result}


# --- Server Info --------------------------------------------------------------


@router.get("/api/mission-control/server")
async def server_info(request: Request) -> dict[str, object]:
    """Return host, CPU, memory, process, disk, and config information."""

    _require_operator(request)
    runtime = _runtime(request)
    return {"ok": True, **await asyncio.to_thread(runtime.server_info.snapshot)}


@router.get("/api/mission-control/server/storage")
async def server_storage(request: Request, refresh: int = 0) -> dict[str, object]:
    """Return the install storage breakdown by top-level directory."""

    _require_operator(request)
    runtime = _runtime(request)
    result = await asyncio.to_thread(runtime.server_info.storage, force=bool(refresh))
    return {"ok": True, **result}


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


@router.get("/api/mission-control/users/{account_id}/destination")
async def user_destination(request: Request, account_id: str) -> dict[str, object]:
    """Show a player's saved destination and valid same-world replacements."""

    _require_operator(request)
    runtime = _runtime(request)
    profile = runtime.profiles.get_user_profile(account_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Player profile not found.")
    from server.mission_control.entry import _repair_candidates

    saved_instance_id = profile.last_instance_id
    record = runtime.registry.get(saved_instance_id) if saved_instance_id else None
    retirement = runtime.retired.get(saved_instance_id)
    successor = retirement.get("successor_instance_id") if retirement else None
    candidates = _repair_candidates(
        runtime,
        request,
        profile.last_world_id,
        saved_instance_id=saved_instance_id,
        successor_instance_id=successor if isinstance(successor, str) else None,
    )
    return {
        "ok": True,
        "world_id": profile.last_world_id,
        "saved_instance_id": saved_instance_id,
        "status": runtime.registry.snapshot(record)["status"] if record is not None else None,
        "retired": retirement is not None,
        "successor_instance_id": successor if isinstance(successor, str) else None,
        "candidates": candidates,
    }


@router.post("/api/mission-control/users/{account_id}/destination")
async def repair_user_destination(
    request: Request,
    account_id: str,
    payload: RepairUserDestinationPayload,
) -> dict[str, object]:
    """Point one player's saved destination at another running same-world instance."""

    runtime = _runtime(request)
    session = _require_operator(request)
    _enforce_post(request, session)
    profile = runtime.profiles.get_user_profile(account_id)
    if profile is None:
        return _json_error(404, "profile_missing", "Player profile not found.")
    record = runtime.registry.get(payload.instance_id)
    if record is None:
        return _json_error(404, "destination_missing", "Destination instance is not registered.")
    if record.world_id != profile.last_world_id:
        return _json_error(400, "destination_world_mismatch", "Destination must serve the player's saved world.")
    from server.mission_control.entry import _validate_running_destination

    try:
        client_url = await _validate_running_destination(runtime, record)
    except HTTPException as exc:
        return _json_error(
            exc.status_code,
            str(getattr(exc, "code", "destination_invalid")),
            str(exc.detail),
        )
    if urlsplit(client_url).hostname != request.url.hostname:
        return _json_error(400, "destination_host_mismatch", "Destination must use the player entry hostname.")
    runtime.profiles.remember_instance(account_id, record.instance_id)
    runtime.audit.record(
        "operator",
        "user.destination",
        target=account_id,
        detail={"instance_id": record.instance_id, "world_id": record.world_id},
    )
    return {
        "ok": True,
        "instance_id": record.instance_id,
        "world_id": record.world_id,
        "client_url": client_url,
    }


# --- Audit --------------------------------------------------------------------


@router.get("/api/mission-control/audit")
async def audit_entries(request: Request, limit: int = 100) -> dict[str, object]:
    """Return recent mission-control audit entries."""

    _require_operator(request)
    runtime = _runtime(request)
    return {"ok": True, "entries": runtime.audit.entries(max(1, min(limit, 500)))}
