"""Read-only Card Database page and JSON API routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from server.routes.common import get_runtime, require_editor_access
from server.routes.world_editor import _serve_page


router = APIRouter()


@router.get("/card-database")
@router.get("/card-database/")
@router.get("/card-database/{requested_path:path}")
async def card_database_page(request: Request, requested_path: str = "") -> FileResponse:
    """Serve the Card Database single-page app behind feature and power gates."""

    runtime = get_runtime(request)
    require_editor_access(runtime, request, feature="card-database")
    root = runtime.config.repo_root / "card-database"
    return _serve_page(runtime, root, requested_path)


@router.get("/api/card-database")
async def card_database(request: Request) -> dict[str, object]:
    """Return the read-only card catalog payload."""

    runtime = get_runtime(request)
    require_editor_access(runtime, request, feature="card-database")
    return {"ok": True, "database": runtime.card_database_service().payload()}
