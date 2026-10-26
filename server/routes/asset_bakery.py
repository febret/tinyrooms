"""Admin Asset Bakery page and JSON API routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from server.routes.common import (
    enforce_authenticated_post,
    get_runtime,
    require_admin_access,
    require_session,
)
from server.routes.world_editor import _serve_page
from server.services.asset_bakery import (
    AssetBakeryError,
    get_job,
    job_payload,
    list_jobs,
    preview_url_for,
    resolve_output_local,
)

router = APIRouter()


class SaveBakeryFilePayload(BaseModel):
    """Bake file save request payload."""

    file_id: str
    tasks: list[dict[str, object]] = Field(default_factory=list)
    simplify: dict[str, object] | None = None


class ReseedPayload(BaseModel):
    """Reseed request payload."""

    file_id: str
    dry_run: bool = False


class BakePayload(BaseModel):
    """Background bake request payload."""

    file_id: str
    filters: list[str] = Field(default_factory=list)
    force: bool = False
    dry_run: bool = False
    reseed: bool = False


class PostprocessPayload(BaseModel):
    """Image postprocess request payload."""

    file_id: str
    label: str
    operation: str
    params: dict[str, object] = Field(default_factory=dict)


def _editor_root(runtime) -> Path:
    return runtime.config.client_path / "asset-bakery"


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "code": code, "message": message})


@router.get("/asset-bakery")
@router.get("/asset-bakery/")
@router.get("/asset-bakery/{requested_path:path}")
async def asset_bakery_page(request: Request, requested_path: str = "") -> Response:
    """Serve the Asset Bakery single-page app behind feature and admin gates."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="asset-bakery", audit_action="asset_bakery.access_denied")
    return _serve_page(runtime, _editor_root(runtime), requested_path)


@router.get("/api/asset-bakery/files")
async def asset_bakery_files(request: Request) -> dict[str, object]:
    """List every bake.json file available to the server."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="asset-bakery", audit_action="asset_bakery.access_denied")
    catalog = await run_in_threadpool(runtime.asset_bakery_service().catalog)
    return {"ok": True, **catalog}


@router.get("/api/asset-bakery/file")
async def asset_bakery_file(request: Request, file_id: str) -> dict[str, object]:
    """Load one bake.json file with editable tasks and output previews."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="asset-bakery", audit_action="asset_bakery.access_denied")
    try:
        payload = await run_in_threadpool(runtime.asset_bakery_service().load_file, file_id)
    except AssetBakeryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, **payload}


@router.put("/api/asset-bakery/file")
async def asset_bakery_save_file(request: Request, payload: SaveBakeryFilePayload) -> JSONResponse:
    """Validate and atomically rewrite one bake.json file."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="asset-bakery", audit_action="asset_bakery.access_denied")
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    service = runtime.asset_bakery_service()
    async with runtime.mutation_lock:
        try:
            result = await run_in_threadpool(
                service.save_file,
                payload.file_id,
                payload.tasks,
                payload.simplify or {},
                actor_id=session.account_id,
            )
        except AssetBakeryError as exc:
            return _error(400, "invalid_bake_file", str(exc))
    return JSONResponse(content={"ok": True, **result})


@router.post("/api/asset-bakery/reseed")
async def asset_bakery_reseed(request: Request, payload: ReseedPayload) -> JSONResponse:
    """Assign fresh random seeds to every pinned seed in a bake file."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="asset-bakery", audit_action="asset_bakery.access_denied")
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    service = runtime.asset_bakery_service()
    async with runtime.mutation_lock:
        try:
            result = await run_in_threadpool(
                service.reseed_file,
                payload.file_id,
                actor_id=session.account_id,
                dry_run=payload.dry_run,
            )
        except AssetBakeryError as exc:
            return _error(400, "reseed_failed", str(exc))
    return JSONResponse(content={"ok": True, **result})


@router.post("/api/asset-bakery/bake")
async def asset_bakery_bake(request: Request, payload: BakePayload) -> JSONResponse:
    """Queue a background bake of one file or a filtered subset of tasks."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="asset-bakery", audit_action="asset_bakery.access_denied")
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    service = runtime.asset_bakery_service()
    try:
        job = await run_in_threadpool(
            service.start_bake,
            payload.file_id,
            actor_id=session.account_id,
            filters=list(payload.filters),
            force=payload.force,
            dry_run=payload.dry_run,
            reseed=payload.reseed,
        )
    except AssetBakeryError as exc:
        return _error(400, "bake_failed", str(exc))
    return JSONResponse(content={"ok": True, "job": job_payload(job)})


@router.get("/api/asset-bakery/jobs")
async def asset_bakery_jobs(request: Request) -> dict[str, object]:
    """List recent background bake jobs."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="asset-bakery", audit_action="asset_bakery.access_denied")
    return {"ok": True, "jobs": [job_payload(job) for job in list_jobs()]}


@router.get("/api/asset-bakery/jobs/{job_id}")
async def asset_bakery_job(request: Request, job_id: str) -> dict[str, object]:
    """Return one background bake job with its captured log tail."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="asset-bakery", audit_action="asset_bakery.access_denied")
    try:
        job = get_job(job_id)
    except AssetBakeryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "job": job_payload(job)}


@router.post("/api/asset-bakery/postprocess")
async def asset_bakery_postprocess(request: Request, payload: PostprocessPayload) -> JSONResponse:
    """Apply a basic image edit to a baked task output."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="asset-bakery", audit_action="asset_bakery.access_denied")
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    service = runtime.asset_bakery_service()
    async with runtime.mutation_lock:
        try:
            result = await run_in_threadpool(
                service.postprocess,
                payload.file_id,
                payload.label,
                payload.operation,
                dict(payload.params),
                actor_id=session.account_id,
            )
        except AssetBakeryError as exc:
            return _error(400, "postprocess_failed", str(exc))
        except ValueError as exc:
            return _error(400, "postprocess_failed", str(exc))
    return JSONResponse(content={"ok": True, **result})


@router.get("/api/asset-bakery/output")
async def asset_bakery_output(request: Request, file_id: str, label: str) -> Response:
    """Serve a baked task output for preview, mapping it inside the repo."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="asset-bakery", audit_action="asset_bakery.access_denied")
    service = runtime.asset_bakery_service()
    try:
        payload = await run_in_threadpool(service.load_file, file_id)
    except AssetBakeryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    task = next((entry for entry in payload["tasks"] if str(entry.get("label")) == label), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Unknown task.")
    local = resolve_output_local(runtime.config, str(task.get("output") or ""))
    if local is None or not local.is_file():
        raise HTTPException(status_code=404, detail="Output not found.")
    preview = preview_url_for(runtime.config, str(task.get("output") or ""))
    if preview.startswith("/app/"):
        return FileResponse(local)
    if preview.startswith("/assets/"):
        return FileResponse(local)
    raise HTTPException(status_code=404, detail="Output is outside the served assets.")
