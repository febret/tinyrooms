"""Static file and HTML routes for the game server."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import mimetypes

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse

from server.base_path import render_html
from server.config import ConfigError, ensure_contained
from server.routes.common import get_runtime
from server.routes.html_pages import render_fallback_activity

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
    return (runtime.config.propsets_path,)


def register_static_routes(app: FastAPI) -> None:
    """Register HTML and static asset routes on *app*."""

    @app.get("/")
    async def index(request: Request) -> Response:
        runtime = get_runtime(request)
        index_path = runtime.config.app_path / "index.html"
        if index_path.is_file():
            return render_html(index_path, runtime.config.base_path)
        return Response(
            "<!doctype html><html><body><h1>Tinyrooms backend ready</h1>"
            "<p>The backend is running. Add the frontend files under app\\index.html when available.</p>"
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

    @app.get("/assets/fx/{filename}")
    async def fx_asset(filename: str, request: Request) -> Response:
        runtime = get_runtime(request)
        candidate = _safe_path(runtime.config.fx_path, filename)
        if candidate.is_file():
            return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="Effect asset not found.")

    @app.get("/assets/{cardset}/{filename}")
    async def cardset_asset(cardset: str, filename: str, request: Request) -> Response:
        runtime = get_runtime(request)
        candidate = _safe_path(runtime.config.cardsets_path, f"{cardset}/{filename}")
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
        if world_id != runtime.world.id or bucket not in {"cards", "rooms", "props", "peeps"}:
            raise HTTPException(status_code=404, detail="World asset not found.")
        candidate = _safe_path(runtime.world.root_path, f"{bucket}/{filename}")
        if candidate.is_file():
            return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="World asset not found.")
