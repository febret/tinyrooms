"""Admin Prop Editor page and JSON API routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from server.content.common import ContentError
from server.routes.common import (
    enforce_authenticated_post,
    get_runtime,
    require_admin_access,
    require_session,
)
from server.routes.world_editor import _serve_page
from server.services.prop_editor import PropEditorNotFound, PropEditorValidationError


router = APIRouter()


class SavePropPayload(BaseModel):
    """Prop save request payload."""

    kind: str
    source: str
    prop_id: str
    prop: dict[str, object] = Field(default_factory=dict)
    scale_adjust: float | None = None


class SaveEffectPayload(BaseModel):
    """Effect save request payload."""

    effect_id: str
    effect: dict[str, object] = Field(default_factory=dict)


def _editor_root(runtime) -> Path:
    return runtime.config.repo_root / "prop-editor"


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "code": code, "message": message})


@router.get("/prop-editor")
@router.get("/prop-editor/")
@router.get("/prop-editor/{requested_path:path}")
async def prop_editor_page(request: Request, requested_path: str = "") -> FileResponse:
    """Serve the Prop Editor single-page app behind feature and admin gates."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="prop-editor")
    return _serve_page(runtime, _editor_root(runtime), requested_path)


@router.get("/api/prop-editor/catalog")
async def prop_editor_catalog(request: Request) -> dict[str, object]:
    """Return every loaded prop plus effect, source, and enum metadata."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="prop-editor")
    return {"ok": True, "catalog": runtime.prop_editor_service().catalog(runtime.world)}


@router.get("/api/prop-editor/prop")
async def prop_editor_prop(request: Request, kind: str, source: str, prop_id: str) -> dict[str, object]:
    """Return the raw definition for one prop."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="prop-editor")
    service = runtime.prop_editor_service()
    try:
        payload = await run_in_threadpool(service.load_prop, runtime.world, kind, source, prop_id)
    except PropEditorNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PropEditorValidationError, ContentError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **payload}


@router.put("/api/prop-editor/prop")
async def prop_editor_save_prop(request: Request, payload: SavePropPayload) -> JSONResponse:
    """Validate, back up, and atomically write one prop definition."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="prop-editor")
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    service = runtime.prop_editor_service()
    async with runtime.mutation_lock:
        try:
            result = await run_in_threadpool(
                service.save_prop,
                runtime.world,
                payload.kind,
                payload.source,
                payload.prop_id,
                payload.prop,
                scale_adjust=payload.scale_adjust,
                actor_id=session.account_id,
            )
        except PropEditorNotFound as exc:
            return _error(404, "not_found", str(exc))
        except (PropEditorValidationError, ContentError) as exc:
            return _error(400, "invalid_prop", str(exc))
    return JSONResponse(content={"ok": True, **result})


@router.get("/api/prop-editor/effects")
async def prop_editor_effects(request: Request) -> dict[str, object]:
    """Return every effect definition plus editor enums."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="prop-editor")
    service = runtime.prop_editor_service()
    return {"ok": True, "effects": service.effects_catalog(), "enums": service.enums()}


@router.get("/api/prop-editor/effect")
async def prop_editor_effect(request: Request, effect_id: str) -> dict[str, object]:
    """Return the raw definition for one effect."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="prop-editor")
    service = runtime.prop_editor_service()
    try:
        payload = await run_in_threadpool(service.load_effect, effect_id)
    except PropEditorNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PropEditorValidationError, ContentError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **payload}


@router.put("/api/prop-editor/effect")
async def prop_editor_save_effect(request: Request, payload: SaveEffectPayload) -> JSONResponse:
    """Validate, back up, and atomically write one effect definition."""

    runtime = get_runtime(request)
    require_admin_access(runtime, request, feature="prop-editor")
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    service = runtime.prop_editor_service()
    async with runtime.mutation_lock:
        try:
            result = await run_in_threadpool(
                service.save_effect,
                payload.effect_id,
                payload.effect,
                actor_id=session.account_id,
            )
        except PropEditorNotFound as exc:
            return _error(404, "not_found", str(exc))
        except (PropEditorValidationError, ContentError) as exc:
            return _error(400, "invalid_effect", str(exc))
    return JSONResponse(content={"ok": True, **result})


@router.post("/api/prop-editor/reload")
async def prop_editor_reload(request: Request) -> dict[str, object]:
    """Rebuild the running world from the edited files and broadcast a reload."""

    runtime = get_runtime(request)
    account = require_admin_access(runtime, request, feature="prop-editor")
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    await runtime.reload_world()
    runtime.audit.safe_record(account.id, "prop_editor.reload", runtime.world.id, "ok")
    return {
        "ok": True,
        "world_id": runtime.world.id,
        "revision": runtime.world_state.read_world_meta("published_revision"),
    }
