"""World Editor page and JSON API routes."""

from __future__ import annotations

from pathlib import Path
import mimetypes

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server.base_path import render_html
from server.behaviors.options import behavior_options
from server.broadcast import broadcast_room_event
from server.config import ConfigError, ensure_contained
from server.content.exit_props import exit_style_options
from server.content.surface_props import DEFAULT_SIGN_STYLE, sign_options, whiteboard_options
from server.content.text_props import text_options
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


class ResetRoomPayload(BaseModel):
    """Live-room reset request payload."""

    room_id: str


def _editor_root(runtime) -> Path:
    return runtime.config.client_path / "world-editor"


def _serve_page(runtime, root: Path, requested_path: str) -> Response:
    from server.routes.common import serve_page as _common_serve_page

    return _common_serve_page(runtime, root, requested_path)


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
            "render_kind": definition.render_kind,
            **({"default_sign_style": DEFAULT_SIGN_STYLE} if definition.render_kind == "sign" else {}),
            "source": definition.source,
            "source_kind": definition.source_kind,
            "decorative": definition.decorative,
            "scale": definition.scale,
            "editor_scale_min": definition.editor_scale_min,
            "editor_scale_max": definition.editor_scale_max,
            "resizable": definition.resizable,
            "tags": list(definition.tags),
            "price": definition.price,
            "locked": definition.locked,
            "behavior": definition.behavior,
            "activity": definition.activity,
            "content": list(definition.content),
            "cooldown": definition.cooldown,
            "recipes": list(definition.recipes),
            "one_per_room": definition.one_per_room,
            "default_actions": [
                [action.label, action.command, action.default]
                if action.default
                else [action.label, action.command]
                for action in definition.default_actions
            ],
        }
        for definition in world.props.values()
        if not definition.hidden
    ]
    cards = [
        {**runtime.cards.serialize_definition(definition), "source": definition.source}
        for definition in runtime.catalog.cards.values()
    ]
    return {
        "world_id": world.id,
        "props": sorted(props, key=lambda item: item["id"]),
        "cards": sorted(cards, key=lambda item: item["id"]),
        "card_database": runtime.card_database_service().payload(),
        "activities": sorted(world.activities),
        "recipes": sorted(world.recipes),
        "text_options": text_options(),
        "sign_options": sign_options(),
        "whiteboard_options": whiteboard_options(),
        "exit_style_options": exit_style_options(),
        "behaviors": behavior_options(world.root_path, runtime.config.repo_root),
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
async def world_editor_page(request: Request, requested_path: str = "") -> Response:
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
    info = service.saved_draft_info()
    return {
        "ok": True,
        "world_key": service.world_key,
        "published_revision": runtime.world_state.read_world_meta("published_revision"),
        "has_draft": info is not None,
        "draft_info": info.to_payload() if info is not None else None,
        "draft_matches_published": service.draft_matches_published(),
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
    return JSONResponse(
        content={
            "ok": True,
            "info": info.to_payload(),
            "draft": service.load_draft(),
            "has_draft": True,
            "draft_matches_published": service.draft_matches_published(),
        }
    )


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


@router.post("/api/world-editor/reset-room")
async def reset_live_room(request: Request, payload: ResetRoomPayload) -> JSONResponse:
    """Reset a live room to its current YAML definition and refresh clients."""

    runtime = get_runtime(request)
    account = require_editor_access(runtime, request, feature="world-editor")
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    if payload.room_id not in runtime.world.rooms:
        raise HTTPException(status_code=404, detail="Room not found.")
    try:
        reset = runtime.layout.reset(account, payload.room_id, authorized_override=True)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "code": "reset_rejected", "message": str(exc)},
        )
    runtime.dispensers.clear_room(reset.prop_instance_ids)
    await broadcast_room_event(runtime, room_id=payload.room_id, event=reset.event())
    return JSONResponse(content={"ok": True, "revision": reset.revision})


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
