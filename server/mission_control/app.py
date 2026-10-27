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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from server.base_path import BasePathMiddleware, render_html
from server.config import ensure_contained
from server.instance_policy import InstancePolicyStore
from server.mission_control import routes as mc_routes
from server.mission_control.audit import McAuditLog
from server.mission_control.auth import McSessionStore
from server.mission_control.config import MCConfig
from server.mission_control.entry import EntrySettings, PlayerAuthService, router as entry_router
from server.mission_control.packages import PackageManager
from server.mission_control.registry import InstanceRegistry
from server.mission_control.retired import RetiredInstanceStore
from server.mission_control.server_info import ServerInfoService
from server.mission_control.showcase import EntryShowcase, router as showcase_router
from server.mission_control.supervisor import Supervisor
from server.mission_control.users import UserManager
from server.mission_control.vibes import VibesManager
from server.mission_control.world_map import WorldMapManager
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
    policy_store: InstancePolicyStore
    audit: McAuditLog
    registry: InstanceRegistry
    retired: RetiredInstanceStore
    supervisor: Supervisor
    world_map: WorldMapManager
    packages: PackageManager
    server_info: ServerInfoService
    users: UserManager
    vibes: VibesManager
    sessions: McSessionStore
    limiter: RateLimiter
    http: httpx.AsyncClient
    player_auth: PlayerAuthService
    entry_settings: EntrySettings
    entry_showcase: EntryShowcase
    started_at: float = field(default_factory=time.time)


def build_runtime(config: MCConfig) -> McRuntime:
    """Build the mission-control runtime graph."""

    ensure_profile_database(config.profiles_db_path)
    hub = DatabaseHub(config.profiles_db_path)
    policy_store = InstancePolicyStore(
        config.instance_policy_path or (config.users_path / "instance-policy.json"),
        fallback_invitation=config.new_account_passphrase,
    )
    profiles = ProfileRepository(hub, policy_store=policy_store)
    audit = McAuditLog()
    registry = InstanceRegistry(stale_after_seconds=config.heartbeat_seconds * 3)
    retired = RetiredInstanceStore(config.instances_path)
    world_map = WorldMapManager(config, registry)
    supervisor = Supervisor(
        config, registry, audit, on_change=world_map.update, policy_store=policy_store
    )
    packages = PackageManager(config, registry, audit)
    server_info = ServerInfoService(config)

    def _card_catalog_for(world_id: str | None) -> object | None:
        """Load the running build's card catalog for one world (or globals)."""

        from server.content.cards import load_card_catalog

        try:
            version_root = packages.resolve_version(None)
            cardsets_root = version_root / "data" / "cardsets"
            extra = (
                (config.shared_cardsets_root,)
                if config.shared_cardsets_root.is_dir()
                else ()
            )
            world_path = (
                packages.resolve_world(None, world_id) if world_id else version_root
            )
            return load_card_catalog(cardsets_root, world_path, extra_cardsets_roots=extra)
        except Exception:  # noqa: BLE001 - validation fails closed below
            return None

    users = UserManager(hub, profiles, audit, card_catalog_for=_card_catalog_for)
    vibes = VibesManager(hub, profiles, registry, audit)
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
        policy_store=policy_store,
        audit=audit,
        registry=registry,
        retired=retired,
        supervisor=supervisor,
        world_map=world_map,
        packages=packages,
        server_info=server_info,
        users=users,
        vibes=vibes,
        sessions=McSessionStore(),
        limiter=RateLimiter(),
        http=http,
        player_auth=PlayerAuthService(
            profiles, config.new_account_passphrase, policy_store=policy_store
        ),
        entry_settings=EntrySettings(config.instances_path),
        entry_showcase=EntryShowcase(config),
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
        try:
            resumed = runtime.supervisor.resume_pending()
            if resumed:
                LOGGER.info(json.dumps({"event": "mc.resume", "instances": resumed}))
        except Exception:  # noqa: BLE001 - never block startup on resume
            LOGGER.exception("mc.resume_failed")
        try:
            runtime.world_map.update()
        except Exception:  # noqa: BLE001 - paths degrade, management remains available
            LOGGER.exception("world_map.startup_failed")
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
        content = {"ok": False, "code": getattr(exc, "code", "http_error"), "message": str(exc.detail)}
        extra = getattr(exc, "data", None)
        if isinstance(extra, dict):
            content.update(
                {key: value for key, value in extra.items() if key not in {"ok", "code", "message"}}
            )
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(status_code=400, content={"ok": False, "code": "invalid_request", "message": "Invalid request payload."})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
        LOGGER.exception("mission_control.error")
        return JSONResponse(status_code=500, content={"ok": False, "code": "server_error", "message": "Server error."})

    app.include_router(mc_routes.router)
    app.include_router(entry_router)
    app.include_router(showcase_router)

    @app.get("/mission-control/vendor/three/{requested_path:path}")
    async def three_vendor(requested_path: str) -> Response:
        root = config.client_path / "app" / "vendor" / "three"
        candidate = _safe_ui_path(root, requested_path)
        if candidate.is_file() and candidate.suffix == ".js":
            return FileResponse(
                candidate,
                media_type="text/javascript",
                headers={"Cache-Control": "public, max-age=604800"},
            )
        raise HTTPException(status_code=404, detail="Vendor file not found.")

    @app.get("/")
    async def root() -> Response:
        return render_html(config.ui_path / "entry.html", config.base_path)

    @app.get("/manifest.webmanifest")
    async def manifest() -> Response:
        candidate = config.ui_path / "manifest.webmanifest"
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="Web app manifest not found.")
        return FileResponse(candidate, media_type="application/manifest+json",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/icons/{filename}")
    async def icon(filename: str) -> Response:
        if filename not in {
            "apple-touch-icon-180.png", "icon-192.png", "icon-512.png", "icon-maskable-512.png",
        }:
            raise HTTPException(status_code=404, detail="App icon not found.")
        candidate = config.ui_path / "icons" / filename
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="App icon not found.")
        return FileResponse(candidate, media_type="image/png",
                            headers={"Cache-Control": "public, max-age=604800"})

    @app.get("/sw.js")
    async def service_worker() -> Response:
        candidate = config.ui_path / "sw.js"
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="Service worker not found.")
        return FileResponse(candidate, media_type="text/javascript",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/mission-control")
    @app.get("/mission-control/")
    async def ui_index() -> Response:
        index_path = config.ui_path / "index.html"
        if index_path.is_file():
            return render_html(index_path, config.base_path)
        return HTMLResponse("<!doctype html><html><body><h1>Mission Control</h1></body></html>")

    @app.get("/mission-control/{requested_path:path}")
    async def ui_files(requested_path: str) -> Response:
        candidate = _safe_ui_path(config.ui_path, requested_path)
        if candidate.is_file():
            media_type, _ = mimetypes.guess_type(candidate.name)
            return render_html(candidate, config.base_path, media_type=media_type)
        raise HTTPException(status_code=404, detail="UI file not found.")

    return BasePathMiddleware(app, config.base_path)
