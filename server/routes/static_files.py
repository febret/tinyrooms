"""Static file and HTML routes for the game server."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import mimetypes
import re

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse

from server.base_path import render_html
from server.config import ConfigError, ensure_contained
from server.routes.common import get_runtime
from server.routes.html_pages import render_fallback_activity
from server.security import SESSION_COOKIE

if TYPE_CHECKING:
    from server.app import RuntimeState


def _safe_path(root: Path, requested_path: str) -> Path:
    try:
        return ensure_contained(root / requested_path, root, "asset")
    except ConfigError as exc:
        raise HTTPException(status_code=404, detail="Not found.") from exc


def _activity_roots(runtime: RuntimeState) -> tuple[Path, ...]:
    return (runtime.config.activities_path, *(mod.activities_path for mod in runtime.mod_definitions))


def _propset_roots(runtime: RuntimeState) -> tuple[Path, ...]:
    shared = runtime.config.shared_propsets_path
    if shared is None:
        return (runtime.config.propsets_path,)
    return (shared, runtime.config.propsets_path)


def _cardset_roots(runtime: RuntimeState) -> tuple[Path, ...]:
    shared = runtime.config.shared_cardsets_path
    if shared is None:
        return (runtime.config.cardsets_path,)
    return (shared, runtime.config.cardsets_path)


_UI_ICON_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*\.svg$")


def _ui_icon_roots(runtime: RuntimeState) -> tuple[Path, ...]:
    """Return UI icon override roots from highest to lowest priority.

    The active world wins, then enabled mods in reverse load order, then the
    core defaults. A world or mod provides an icon by dropping
    ``ui/<key>.svg`` into its own directory.
    """

    roots = [runtime.world.root_path / "ui"]
    roots.extend(mod.path / "ui" for mod in reversed(runtime.mod_definitions))
    roots.append(runtime.config.repo_root / "data" / "ui" / "icons")
    return tuple(roots)


def resolve_ui_icon(runtime: RuntimeState, filename: str) -> Path | None:
    """Return the winning file for a UI icon name, or None when unknown."""

    if not _UI_ICON_PATTERN.match(filename):
        return None
    for root in _ui_icon_roots(runtime):
        candidate = _safe_path(root, filename)
        if candidate.is_file():
            return candidate
    return None


def register_static_routes(app: FastAPI) -> None:
    """Register HTML and static asset routes on *app*."""

    @app.get("/")
    async def index(request: Request) -> Response:
        runtime = get_runtime(request)
        if runtime.config.entry_url:
            session = runtime.accounts.authenticate(request.cookies.get(SESSION_COOKIE))
            profile = runtime.profiles.get_user_profile(session.account_id) if session else None
            if (profile is None or profile.last_world_id != runtime.world.id
                    or profile.last_instance_id not in {None, runtime.config.mc_instance_id}):
                return RedirectResponse(runtime.config.entry_url, headers={"Cache-Control": "no-store"})
        index_path = runtime.config.app_path / "index.html"
        if index_path.is_file():
            return render_html(index_path, runtime.config.base_path)
        return Response(
            "<!doctype html><html><body><h1>Tinyrooms backend ready</h1>"
            "<p>The backend is running. Add the frontend files under client/app/index.html when available.</p>"
            "</body></html>",
            media_type="text/html",
        )

    @app.get("/app/{requested_path:path}")
    async def app_files(requested_path: str, request: Request) -> Response:
        runtime = get_runtime(request)
        candidate = _safe_path(runtime.config.app_path, requested_path)
        if candidate.is_file():
            return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="App file not found.")

    @app.get("/activities/{activity_name}/")
    async def activity_index(activity_name: str, request: Request) -> Response:
        runtime = get_runtime(request)
        for root in _activity_roots(runtime):
            candidate = _safe_path(root, f"{activity_name}/index.html")
            if candidate.is_file():
                return render_html(
                    candidate,
                    runtime.config.base_path,
                    document_path=f"/activities/{activity_name}/",
                )
        return render_fallback_activity(activity_name)

    @app.get("/activities/{filename}")
    async def shared_activity_file(filename: str, request: Request) -> Response:
        runtime = get_runtime(request)
        if filename not in {"shared.css", "shared.js"}:
            raise HTTPException(status_code=404, detail="Activity file not found.")
        candidate = _safe_path(runtime.config.activities_path, filename)
        return FileResponse(candidate)

    @app.get("/activities/{activity_name}/{requested_path:path}")
    async def activity_files(activity_name: str, requested_path: str, request: Request) -> Response:
        runtime = get_runtime(request)
        for root in _activity_roots(runtime):
            candidate = _safe_path(root, f"{activity_name}/{requested_path}")
            if candidate.is_file():
                media_type, _ = mimetypes.guess_type(candidate.name)
                return render_html(
                    candidate,
                    runtime.config.base_path,
                    media_type=media_type,
                    document_path=f"/activities/{activity_name}/{requested_path}",
                )
        raise HTTPException(status_code=404, detail="Activity file not found.")

    @app.get("/assets/stickers/{filename}")
    async def sticker_asset(filename: str, request: Request) -> Response:
        runtime = get_runtime(request)
        for root in (runtime.config.stickers_path, runtime.config.custom_stickers_path):
            candidate = _safe_path(root, filename)
            if candidate.is_file():
                return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="Sticker asset not found.")

    @app.get("/assets/world-image")
    async def world_image(request: Request) -> Response:
        runtime = get_runtime(request)
        if runtime.world.image_path is None or not runtime.world.image_path.is_file():
            raise HTTPException(status_code=404, detail="World image not found.")
        return FileResponse(runtime.world.image_path, headers={"Cache-Control": "public, max-age=60"})

    @app.get("/assets/world/{world_id}/world.css")
    async def world_stylesheet(world_id: str, request: Request) -> Response:
        runtime = get_runtime(request)
        if world_id != runtime.world.id or runtime.world.stylesheet_path is None:
            raise HTTPException(status_code=404, detail="World stylesheet not found.")
        if not runtime.world.stylesheet_path.is_file():
            raise HTTPException(status_code=404, detail="World stylesheet not found.")
        return FileResponse(
            runtime.world.stylesheet_path,
            media_type="text/css",
            headers={"Cache-Control": "public, max-age=60"},
        )

    @app.get("/assets/fx/{filename}")
    async def fx_asset(filename: str, request: Request) -> Response:
        runtime = get_runtime(request)
        candidate = _safe_path(runtime.config.fx_path, filename)
        if candidate.is_file():
            return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="Effect asset not found.")

    @app.get("/assets/ui/{filename}")
    async def ui_icon_asset(filename: str, request: Request) -> Response:
        runtime = get_runtime(request)
        candidate = resolve_ui_icon(runtime, filename)
        if candidate is None:
            raise HTTPException(status_code=404, detail="UI icon not found.")
        return FileResponse(
            candidate,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=60"},
        )

    @app.get("/assets/sounds/{filename}")
    async def sound_asset(filename: str, request: Request) -> Response:
        runtime = get_runtime(request)
        if not filename.lower().endswith(".wav"):
            raise HTTPException(status_code=404, detail="Sound asset not found.")
        candidate = _safe_path(runtime.config.sounds_path, filename)
        if candidate.is_file():
            return FileResponse(candidate, headers={"Cache-Control": "public, max-age=3600"})
        raise HTTPException(status_code=404, detail="Sound asset not found.")

    @app.get("/assets/{cardset}/{filename}")
    async def cardset_asset(cardset: str, filename: str, request: Request) -> Response:
        runtime = get_runtime(request)
        for root in _cardset_roots(runtime):
            candidate = _safe_path(root, f"{cardset}/{filename}")
            if candidate.is_file():
                return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="Cardset asset not found.")

    @app.get("/assets/propsets/{propset}/{filename}")
    async def propset_asset(propset: str, filename: str, request: Request) -> Response:
        runtime = get_runtime(request)
        for root in _propset_roots(runtime):
            candidate = _safe_path(root, f"{propset}/{filename}")
            if candidate.is_file():
                return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="Propset asset not found.")

    @app.get("/assets/mods/{mod_id}/props/{filename}")
    async def mod_prop_asset(mod_id: str, filename: str, request: Request) -> Response:
        runtime = get_runtime(request)
        for mod in runtime.mod_definitions:
            if mod.id != mod_id:
                continue
            candidate = _safe_path(mod.props_path, filename)
            if candidate.is_file():
                return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="Mod prop asset not found.")

    @app.get("/assets/world/{world_id}/{bucket}/{filename}")
    async def world_asset(world_id: str, bucket: str, filename: str, request: Request) -> Response:
        runtime = get_runtime(request)
        if world_id != runtime.world.id or bucket not in {"cards", "rooms", "props", "peeps", "keys"}:
            raise HTTPException(status_code=404, detail="World asset not found.")
        if bucket == "keys" and (filename == "bake.json" or not filename.lower().endswith(".png")):
            raise HTTPException(status_code=404, detail="World asset not found.")
        candidate = _safe_path(runtime.world.root_path, f"{bucket}/{filename}")
        if candidate.is_file():
            return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="World asset not found.")
