"""HTTP routes for reading and editing per-room prop layouts."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server.broadcast import broadcast_room_event
from server.routes.common import (
    enforce_authenticated_post,
    get_runtime,
    json_error,
    require_session,
)
from server.state.world_state import LayoutRevisionConflict


router = APIRouter()


class LayoutSaveRequest(BaseModel):
    """Room layout save request payload."""

    base_revision: int = Field(ge=0)
    patch: dict[str, object] = Field(default_factory=dict)


@router.get("/api/rooms/{room_id}/layout")
async def get_room_layout(request: Request, room_id: str) -> dict[str, object]:
    """Return the current layout for one room."""

    runtime = get_runtime(request)
    session = require_session(runtime, request)
    if room_id not in runtime.world.rooms:
        raise HTTPException(status_code=404, detail="Room not found.")
    account = runtime.profiles.get_account_by_id(session.account_id)
    return {"ok": True, "layout": runtime.layout.view(account, room_id)}


@router.post("/api/rooms/{room_id}/layout")
async def save_room_layout(
    request: Request,
    room_id: str,
    payload: LayoutSaveRequest,
) -> Response:
    """Apply a validated layout patch to one room."""

    runtime = get_runtime(request)
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    if room_id not in runtime.world.rooms:
        raise HTTPException(status_code=404, detail="Room not found.")
    account = runtime.profiles.get_account_by_id(session.account_id)
    try:
        update = runtime.layout.save(account, room_id, payload.base_revision, payload.patch)
    except LayoutRevisionConflict as exc:
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "code": "revision_conflict",
                "message": str(exc),
                "layout": runtime.layout.view(account, room_id),
            },
        )
    except ValueError as exc:
        return json_error(400, "layout_rejected", str(exc))
    await broadcast_room_event(runtime, room_id=room_id, event=update.event())
    return JSONResponse(content={"ok": True, "layout": runtime.layout.view(account, room_id)})


@router.post("/api/rooms/{room_id}/reset")
async def reset_room_layout(request: Request, room_id: str) -> Response:
    """Reset one room's layout to its authored definition."""

    runtime = get_runtime(request)
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    if room_id not in runtime.world.rooms:
        raise HTTPException(status_code=404, detail="Room not found.")
    account = runtime.profiles.get_account_by_id(session.account_id)
    try:
        reset = runtime.layout.reset(account, room_id)
    except ValueError as exc:
        return json_error(400, "reset_rejected", str(exc))
    runtime.dispensers.clear_room(reset.prop_instance_ids)
    await broadcast_room_event(runtime, room_id=room_id, event=reset.event())
    return JSONResponse(content={"ok": True, "layout": runtime.layout.view(account, room_id)})
