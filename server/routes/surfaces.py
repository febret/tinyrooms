"""HTTP routes for authoring built-in prop surfaces."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server.broadcast import broadcast_room_event
from server.routes.common import (
    enforce_authenticated_post,
    get_runtime,
    json_error,
    require_session,
)
from server.services.prop_surfaces import surface_kind


router = APIRouter()


class SignSaveRequest(BaseModel):
    """Sign text save request payload."""

    text: str


@router.post("/api/rooms/{room_id}/signs/{instance_id}")
async def save_sign_text(
    request: Request,
    room_id: str,
    instance_id: str,
    payload: SignSaveRequest,
) -> object:
    """Save one sign's text for a room occupant."""

    runtime = get_runtime(request)
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    if room_id not in runtime.world.rooms:
        raise HTTPException(status_code=404, detail="Room not found.")
    connection = await runtime.connections.get(session.account_id)
    if connection is None or connection.room_id != room_id:
        return json_error(403, "sign_rejected", "You must be in the room to edit this sign.")
    try:
        prop = runtime.rooms.require_prop_target(room_id, instance_id)
    except ValueError as exc:
        return json_error(400, "sign_rejected", str(exc))
    definition = runtime.world.props[prop.prop_id]
    if surface_kind(definition.render_kind) != "sign":
        return json_error(400, "sign_rejected", "That prop is not a sign.")
    try:
        surface = runtime.surfaces.save_sign(
            room_id,
            instance_id,
            session.account_id,
            {"text": payload.text},
        )
    except ValueError as exc:
        return json_error(400, "sign_rejected", str(exc))
    await broadcast_room_event(
        runtime,
        room_id=room_id,
        event={
            "type": "room.prop.surface",
            "room_id": room_id,
            "prop_id": instance_id,
            "surface": surface.serialize(),
        },
    )
    return {"ok": True, "surface": surface.serialize()}
