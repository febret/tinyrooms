"""Cutscene static assets and the launchable-catalog route."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from server.routes.common import get_runtime, require_session


router = APIRouter()


def cutscene_roots(runtime: object) -> tuple[Path, ...]:
    """Return core, world, and mod cutscene roots in search order."""

    return (
        runtime.config.cutscenes_path,
        runtime.config.world_path / "cutscenes",
        *(mod.cutscenes_path for mod in runtime.mod_definitions),
    )


@router.get("/cutscenes/{cutscene_name}/{requested_path:path}")
async def cutscene_files(cutscene_name: str, requested_path: str, request: Request) -> FileResponse:
    """Serve a cutscene module or one of its sibling assets."""

    runtime = get_runtime(request)
    for root in cutscene_roots(runtime):
        candidate = root / cutscene_name / requested_path
        try:
            contained = candidate.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        if not contained.parts or contained.parts[0] != cutscene_name:
            continue
        if candidate.is_file():
            media_type, _ = mimetypes.guess_type(candidate.name)
            return FileResponse(candidate, media_type=media_type)
    raise HTTPException(status_code=404, detail="Cutscene file not found.")


@router.get("/api/cutscenes")
async def cutscene_catalog(request: Request) -> dict[str, object]:
    """Return the cutscenes the signed-in account may launch from here."""

    runtime = get_runtime(request)
    session = require_session(runtime, request)
    profile = runtime.profiles.user_profile_for(
        session.account.id, runtime.world.id, runtime.world.entry_room_id
    )
    return {"ok": True, "cutscenes": runtime.cutscenes.visible_catalog(room_id=profile.remembered_room)}
