"""World Editor page and JSON API routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from server.config import ConfigError, ensure_contained
from server.content.worlds import BOARD_IMAGE_STYLES, POWER_NAMES, prop_model_url
from server.routes.common import (
    enforce_authenticated_post,
    get_runtime,
    require_editor_access,
    require_session,
)
from server.services.world_editor import (
    DraftValidationError,
    PublishConfirmationRequired,
    PublishValidationError,
)


IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})

router = APIRouter()


class DraftPayload(BaseModel):
    """Draft save/validate request payload."""

    draft: dict[str, object] = Field(default_factory=dict)


class PublishPayload(BaseModel):
    """Publish request payload."""

    draft: dict[str, object] = Field(default_factory=dict)
    confirm: bool = False


def _editor_root(runtime) -> Path:
    return runtime.config.repo_root / "world-editor"


def _serve_page(runtime, root: Path, requested_path: str) -> FileResponse:
    relative = requested_path or "index.html"
    if relative.endswith("/"):
        relative = f"{relative}index.html"
    try:
        candidate = ensure_contained(root / relative, root, "editor")
    except ConfigError as exc:
        raise HTTPException(status_code=404, detail="Not found.") from exc
    if candidate.is_dir():
        candidate = candidate / "index.html"
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(candidate)


def _image_names(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []
    return sorted(
        entry.name
        for entry in directory.iterdir()
        if entry.is_file() and entry.suffix.lower() in IMAGE_SUFFIXES
    )


def _catalog_payload(runtime) -> dict[str, object]:
    world = runtime.world
    props = [
        {
            "id": definition.id,
            "label": definition.label,
            "description": definition.description,
            "model_url": prop_model_url(world.id, definition),
            "source": definition.source,
            "source_kind": definition.source_kind,
            "decorative": definition.decorative,
            "editable": definition.editable,
            "scale": definition.scale,
            "editor_scale_min": definition.editor_scale_min,
            "editor_scale_max": definition.editor_scale_max,
            "tags": list(definition.tags),
            "price": definition.price,
            "locked": definition.locked,
        }
        for definition in world.props.values()
    ]
    cards = [
        runtime.cards.serialize_definition(definition)
        for definition in runtime.catalog.cards.values()
    ]
    return {
        "world_id": world.id,
        "props": sorted(props, key=lambda item: item["id"]),
        "cards": sorted(cards, key=lambda item: item["id"]),
        "activities": sorted(world.activities),
        "recipes": sorted(world.recipes),
        "board_images": _image_names(world.root_path / "rooms"),
        "peep_images": _image_names(world.root_path / "peeps"),
        "board_image_styles": sorted(BOARD_IMAGE_STYLES),
        "powers": list(POWER_NAMES),
    }


def _issue_payloads(issues: list) -> list[dict[str, str]]:
    return [issue.to_payload() for issue in issues]


@router.get("/world-editor")
@router.get("/world-editor/")
@router.get("/world-editor/{requested_path:path}")
async def world_editor_page(request: Request, requested_path: str = "") -> FileResponse:
    """Serve the World Editor single-page app behind feature and power gates."""

    runtime = get_runtime(request)
    require_editor_access(runtime, request, feature="world-editor")
    return _serve_page(runtime, _editor_root(runtime), requested_path)


@router.get("/api/world-editor/draft")
async def get_draft(request: Request) -> dict[str, object]:
    """Return the saved draft, or one built from the published files."""

    runtime = get_runtime(request)
    require_editor_access(runtime, request, feature="world-editor")
    service = runtime.editor_service()
    return {
        "ok": True,
        "world_key": service.world_key,
        "published_revision": runtime.world_state.read_world_meta("published_revision"),
        "draft": service.load_draft(),
        "catalog": _catalog_payload(runtime),
    }


@router.put("/api/world-editor/draft")
async def save_draft(request: Request, payload: DraftPayload) -> JSONResponse:
    """Structurally validate and persist a draft without touching the world."""

    runtime = get_runtime(request)
    require_editor_access(runtime, request, feature="world-editor")
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    service = runtime.editor_service()
    try:
        info = service.save_draft(payload.draft)
    except DraftValidationError as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "code": "draft_invalid", "errors": _issue_payloads(exc.issues)},
        )
    return JSONResponse(content={"ok": True, "info": info.to_payload(), "draft": service.load_draft()})


@router.post("/api/world-editor/discard")
async def discard_draft(request: Request) -> dict[str, object]:
    """Delete the saved draft so the next load rebuilds from published files."""

    runtime = get_runtime(request)
    require_editor_access(runtime, request, feature="world-editor")
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    service = runtime.editor_service()
    discarded = service.discard_draft()
    return {"ok": True, "discarded": discarded, "draft": service.load_draft()}


@router.post("/api/world-editor/validate")
async def validate_draft(request: Request, payload: DraftPayload) -> dict[str, object]:
    """Validate a draft against the real content loaders."""

    runtime = get_runtime(request)
    require_editor_access(runtime, request, feature="world-editor")
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    report = runtime.editor_service().validate(payload.draft)
    return {"ok": True, "report": report.to_payload()}


@router.post("/api/world-editor/publish")
async def publish_draft(request: Request, payload: PublishPayload) -> JSONResponse:
    """Validate, confirm, publish, and reconcile the running world."""

    runtime = get_runtime(request)
    require_editor_access(runtime, request, feature="world-editor")
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    service = runtime.editor_service()
    async with runtime.mutation_lock:
        try:
            result = await run_in_threadpool(
                service.publish,
                payload.draft,
                actor_account_id=session.account_id,
                confirm=payload.confirm,
            )
        except PublishConfirmationRequired as exc:
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "code": "confirmation_required",
                    "message": str(exc),
                    "rooms": exc.rooms,
                    "changes": [change.to_payload() for change in exc.changes],
                },
            )
        except PublishValidationError as exc:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "code": "validation_failed", "errors": _issue_payloads(exc.errors)},
            )
        except DraftValidationError as exc:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "code": "draft_invalid", "errors": _issue_payloads(exc.issues)},
            )
        await runtime._apply_world_reload()
    return JSONResponse(content={"ok": True, "result": result.to_payload()})
