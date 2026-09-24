"""FastAPI assembly for the optional mission-control server."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
import json
import logging
import mimetypes
import time

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from server.config import ensure_contained
from server.mission_control import routes as mc_routes
from server.mission_control.audit import McAuditLog
from server.mission_control.auth import McSessionStore
from server.mission_control.config import MCConfig
from server.mission_control.packages import PackageManager
from server.mission_control.registry import InstanceRegistry
from server.mission_control.supervisor import Supervisor
from server.mission_control.users import UserManager
from server.profiles import ProfileRepository
from server.security import RateLimitError, RateLimiter, SecurityError
from server.state.migrations import DatabaseHub, ensure_profile_database
from server.version import BUILD_VERSION


LOGGER = logging.getLogger("tinyrooms.mc")


@dataclass
class McRuntime:
    """Shared mission-control runtime state."""

    config: MCConfig
    hub: DatabaseHub
    profiles: ProfileRepository
    audit: McAuditLog
    registry: InstanceRegistry
    supervisor: Supervisor
    packages: PackageManager
    users: UserManager
    sessions: McSessionStore
    limiter: RateLimiter
    http: httpx.AsyncClient
    started_at: float = field(default_factory=time.time)


def build_runtime(config: MCConfig) -> McRuntime:
    """Build the mission-control runtime graph."""

    ensure_profile_database(config.profiles_db_path)
    hub = DatabaseHub(config.profiles_db_path)
    profiles = ProfileRepository(hub)
    audit = McAuditLog()
    registry = InstanceRegistry(stale_after_seconds=config.heartbeat_seconds * 3)
    supervisor = Supervisor(config, registry, audit)
    packages = PackageManager(config, audit)
    users = UserManager(hub, profiles, audit)
    verify: object = True
    if config.insecure_tls:
        verify = False
        LOGGER.warning(json.dumps({"event": "mc.insecure_tls_enabled"}))
    elif config.ca_file is not None:
        verify = str(config.ca_file)
    http = httpx.AsyncClient(verify=verify, timeout=5.0)
    return McRuntime(
        config=config,
        hub=hub,
        profiles=profiles,
        audit=audit,
        registry=registry,
        supervisor=supervisor,
        packages=packages,
        users=users,
        sessions=McSessionStore(),
        limiter=RateLimiter(),
        http=http,
    )


async def _sweep_stale(runtime: McRuntime) -> None:
    interval = max(1.0, runtime.config.heartbeat_seconds)
    while True:
        await asyncio.sleep(interval)
        runtime.registry.evict_stale()


def _safe_ui_path(root: Path, requested: str) -> Path:
    try:
        return ensure_contained(root / requested, root, "ui")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="Not found.") from exc


def create_mc_app(config: MCConfig) -> FastAPI:
    """Create the mission-control FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = build_runtime(config)
        app.state.mc = runtime
        runtime.packages.refresh()
        sweeper = asyncio.create_task(_sweep_stale(runtime))
        try:
            yield
        finally:
            sweeper.cancel()
            try:
                await sweeper
            except asyncio.CancelledError:
                pass
            await runtime.http.aclose()
            runtime.hub.close()

    app = FastAPI(title="Tinyrooms Mission Control", version=BUILD_VERSION, lifespan=lifespan)

    @app.exception_handler(RateLimitError)
    async def rate_limit_error_handler(request: Request, exc: RateLimitError) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(status_code=429, content={"ok": False, "code": "rate_limited", "message": str(exc)})

    @app.exception_handler(SecurityError)
    async def security_error_handler(request: Request, exc: SecurityError) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(status_code=403, content={"ok": False, "code": "security_error", "message": str(exc)})

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "code": "http_error", "message": str(exc.detail)},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(status_code=400, content={"ok": False, "code": "invalid_request", "message": "Invalid request payload."})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
        LOGGER.exception("mission_control.error")
        return JSONResponse(status_code=500, content={"ok": False, "code": "server_error", "message": "Server error."})

    app.include_router(mc_routes.router)

    @app.get("/")
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/mission-control")

    @app.get("/mission-control")
    @app.get("/mission-control/")
    async def ui_index() -> Response:
        index_path = config.ui_path / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        return HTMLResponse("<!doctype html><html><body><h1>Mission Control</h1></body></html>")

    @app.get("/mission-control/{requested_path:path}")
    async def ui_files(requested_path: str) -> Response:
        candidate = _safe_ui_path(config.ui_path, requested_path)
        if candidate.is_file():
            media_type, _ = mimetypes.guess_type(candidate.name)
            return FileResponse(candidate, media_type=media_type)
        raise HTTPException(status_code=404, detail="UI file not found.")

    return app
