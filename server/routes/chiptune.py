"""Read-only proxy for the chiptune.app catalog API.

The chiptune.app JSON API sends no CORS headers, so the browser cannot call it
directly. This route forwards a small, validated set of read-only catalog
queries and normalizes the payload for the Tinyrooms mini player. The upstream
host is fixed; user input only ever reaches query parameters.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Request
import httpx

from server.routes.common import enforce_authenticated_post, get_runtime, require_session


router = APIRouter()

CHIPTUNE_BASE = "https://chiptune.app"
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
MAX_QUERY_LENGTH = 120
MAX_PATH_LENGTH = 300
REQUEST_TIMEOUT_SECONDS = 5.0

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    return _client


async def _fetch_json(path: str, params: dict[str, str]) -> object:
    """Fetch and decode a chiptune.app JSON response."""

    url = f"{CHIPTUNE_BASE}{path}"
    try:
        response = await _get_client().get(url, params=params)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="The chiptune.app catalog is unavailable.") from exc


def _limit(raw_value: str | None) -> int:
    try:
        value = int(raw_value or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        value = DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, value))


def _query(raw_value: str | None) -> str:
    text = (raw_value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="A search query is required.")
    if len(text) > MAX_QUERY_LENGTH:
        raise HTTPException(status_code=400, detail="That search query is too long.")
    return text


def _path(raw_value: str | None) -> str:
    text = (raw_value or "").strip().strip("/")
    if len(text) > MAX_PATH_LENGTH:
        raise HTTPException(status_code=400, detail="That catalog path is too long.")
    if ".." in text.split("/"):
        raise HTTPException(status_code=400, detail="That catalog path is not valid.")
    return text


def _song_id_from_url(url: object) -> str:
    if not isinstance(url, str):
        return ""
    query = parse_qs(urlsplit(url).query)
    values = query.get("play") or []
    return str(values[0]) if values else ""


def _basename(path: str) -> str:
    name = PurePosixPath(path).name
    return name.rsplit(".", 1)[0] if "." in name else name


def _search_items(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return []
    items: list[dict[str, object]] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("file") or entry.get("path") or "")
        song_id = str(entry.get("song_id") or "")
        if not song_id and not path:
            continue
        parent = PurePosixPath(path).parent
        items.append(
            {
                "id": song_id,
                "path": path,
                "title": str(entry.get("title") or _basename(path) or song_id),
                "subtitle": str(entry.get("artist") or ("" if str(parent) == "." else str(parent))),
                "kind": "file",
            }
        )
    return items


def _top_items(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return []
    items: list[dict[str, object]] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "")
        song_id = str(entry.get("song_id") or "")
        if not song_id and not path:
            continue
        subtitle_parts = [str(entry.get(key) or "").strip() for key in ("artist", "game", "system")]
        subtitle = " · ".join(part for part in subtitle_parts if part)
        items.append(
            {
                "id": song_id,
                "path": path,
                "title": str(entry.get("title") or _basename(path) or song_id),
                "subtitle": subtitle,
                "kind": "file",
            }
        )
    return items


def _browse_items(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        return []
    items: list[dict[str, object]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "").strip("/")
        if not path:
            continue
        is_directory = entry.get("type") == "directory"
        items.append(
            {
                "id": _song_id_from_url(entry.get("url")),
                "path": path,
                "title": _basename(path) if not is_directory else PurePosixPath(path).name,
                "subtitle": f"{int(entry.get('count') or 0)} tracks" if is_directory else "track",
                "kind": "directory" if is_directory else "file",
            }
        )
    return items


@router.get("/api/chiptune/search")
async def chiptune_search(request: Request, query: str = "", limit: str | None = None) -> dict[str, object]:
    """Search the chiptune.app catalog."""

    require_session(get_runtime(request), request)
    items = _search_items(await _fetch_json("/api/search", {"query": _query(query), "limit": str(_limit(limit))}))
    return {"ok": True, "items": items, "total": len(items)}


@router.get("/api/chiptune/top")
async def chiptune_top(request: Request, limit: str | None = None) -> dict[str, object]:
    """Return the most-played chiptune.app tracks."""

    require_session(get_runtime(request), request)
    items = _top_items(await _fetch_json("/api/top", {"metric": "plays", "limit": str(_limit(limit))}))
    return {"ok": True, "items": items, "total": len(items)}


@router.get("/api/chiptune/browse")
async def chiptune_browse(request: Request, path: str = "") -> dict[str, object]:
    """List a chiptune.app catalog directory."""

    require_session(get_runtime(request), request)
    items = _browse_items(await _fetch_json("/api/browse", {"path": _path(path)}))
    return {"ok": True, "items": items, "total": len(items)}


@router.get("/api/chiptune/starred")
async def chiptune_starred(request: Request) -> dict[str, object]:
    """Return the signed-in user's starred tracks."""

    runtime = get_runtime(request)
    session = require_session(runtime, request)
    return {"ok": True, "items": runtime.chiptune_stars.starred(session.account_id)}


@router.post("/api/chiptune/starred")
async def chiptune_set_starred(request: Request) -> dict[str, object]:
    """Star or unstar a track for the signed-in user."""

    runtime = get_runtime(request)
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="A JSON body is required.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="A JSON object is required.")
    starred = payload.get("starred", True)
    try:
        items = runtime.chiptune_stars.set_starred(
            session.account_id,
            payload.get("song"),
            payload.get("label", ""),
            starred=starred if isinstance(starred, bool) else True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "items": items}


@router.get("/api/chiptune/suggestions")
async def chiptune_suggestions(request: Request, limit: str | None = None) -> dict[str, object]:
    """Return top tracks plus tracks starred by other Tinyrooms users."""

    runtime = get_runtime(request)
    session = require_session(runtime, request)
    count = _limit(limit)
    try:
        top = _top_items(await _fetch_json("/api/top", {"metric": "plays", "limit": str(count)}))
    except HTTPException:
        top = []
    community = [
        {
            "id": entry["song"],
            "path": "",
            "title": entry["label"] or entry["song"],
            "subtitle": (
                f"Starred by {entry['stars']} "
                f"Tinyrooms {'player' if int(entry['stars']) == 1 else 'players'}"
            ),
            "kind": "file",
            "stars": entry["stars"],
        }
        for entry in runtime.chiptune_stars.starred_counts(session.account_id, count)
    ]
    return {"ok": True, "top": top, "community": community}
