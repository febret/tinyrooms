"""World-side mission-control admin endpoints.

Mounted only when ``TRSERVER_MC_ENDPOINT`` is set. Every endpoint requires the
shared ``X-MC-Token``; these routes are never reachable by game clients.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import sys
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from server.broadcast import broadcast_room_event
from server.commands.admin import ALLOWED_ADMIN_COMMANDS
from server.commands.context import build_command_context
from server.commands.core import dispatch_command
from server.commands.outcomes import CommandError
from server.commands.parser import CommandParseError, parse_command
from server.connections import SyntheticConnection
from server.protocol import PROTOCOL_VERSION, profile_resync_envelope
from server.serialization import serialize_account
from server.version import BUILD_VERSION, schema_versions


LOGGER = logging.getLogger("tinyrooms.mc")
router = APIRouter(prefix="/api/mc")

MC_CAPABILITIES = tuple(f"admin.{name}" for name in ALLOWED_ADMIN_COMMANDS)


class CommandPayload(BaseModel):
    """Admin command dispatch payload."""

    command: str
    actor: str
    request_id: str | None = None


class ResyncPayload(BaseModel):
    """Profile resync payload."""

    actor: str = "mission-control"
    scope: str = "all"


def _runtime(request: Request):
    return request.app.state.runtime


def _require_token(request: Request) -> None:
    runtime = _runtime(request)
    expected = runtime.config.mc_token
    presented = request.headers.get("x-mc-token")
    if not expected or not presented or not hmac.compare_digest(expected, presented):
        LOGGER.warning(json.dumps({"event": "mc.token_rejected", "path": request.url.path}))
        raise HTTPException(status_code=403, detail="Invalid mission-control token.")


def _log_ring(request: Request):
    return getattr(request.app.state, "log_ring", None)


def _schedule_restart() -> None:
    """Re-exec the process shortly after responding (cooperative restart)."""

    def _restart() -> None:
        os.execv(sys.executable, [sys.executable, *sys.argv])

    threading.Timer(0.25, _restart).start()


def _schedule_exit() -> None:
    """Exit the process shortly after responding (cooperative shutdown)."""

    threading.Timer(0.25, lambda: os._exit(0)).start()


def _resolve_actor(runtime, actor: str):
    account = runtime.profiles.resolve_account(actor)
    if account is not None:
        return account
    for username in sorted(runtime.config.bootstrap_admins):
        account = runtime.profiles.get_account_by_username(username)
        if account is not None:
            return account
    return None


@router.get("/stats")
async def stats(request: Request) -> dict[str, object]:
    """Return runtime stats for the running world server."""

    _require_token(request)
    runtime = _runtime(request)
    users = [
        {
            "account_id": connection.account_id,
            "username": connection.username,
            "room_id": connection.room_id,
        }
        for connection in runtime.connections.list_all()
    ]
    return {
        "ok": True,
        "uptime": round(time.time() - runtime.started_at, 2),
        "users": users,
        "rooms": len(runtime.world.rooms),
        "world": {"id": runtime.world.id, "label": runtime.world.label},
        "version": {"build": BUILD_VERSION, "protocol": PROTOCOL_VERSION},
        "schema": schema_versions(),
        "counters": {
            "cards": len(runtime.catalog.cards),
            "packs": len(runtime.catalog.packs),
            "peeps": len(runtime.world.peeps),
            "props": len(runtime.world.props),
            "revision": runtime.profile_revision,
        },
    }


@router.get("/logs")
async def logs(request: Request, limit: int = 200) -> dict[str, object]:
    """Return the server-local recent log ring."""

    _require_token(request)
    ring = _log_ring(request)
    lines = [] if ring is None else ring.lines(max(1, min(limit, 1000)))
    return {"ok": True, "lines": lines}


@router.post("/command")
async def command(request: Request, payload: CommandPayload) -> JSONResponse:
    """Dispatch an admin command through the existing command pipeline."""

    _require_token(request)
    runtime = _runtime(request)
    account = _resolve_actor(runtime, payload.actor)
    if account is None:
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "code": "actor_unknown",
                "message": f"No account or bootstrap admin matches actor '{payload.actor}'.",
            },
        )
    room_id = runtime.rooms.current_room_for_account(account.id)
    connection = SyntheticConnection(
        account_id=account.id,
        username=account.username_display,
        room_id=room_id,
    )
    try:
        parsed = parse_command(payload.command)
        context = build_command_context(
            runtime,
            account=account,
            connection=connection,
            serialize_user=lambda target: serialize_account(runtime, target),
        )
        outcome = await dispatch_command(context, parsed)
    except (CommandParseError, CommandError, ValueError) as exc:
        return JSONResponse(
            status_code=200,
            content={"ok": False, "code": "command_rejected", "message": str(exc)},
        )
    for pending in outcome.room_broadcasts:
        await broadcast_room_event(runtime, room_id=pending.room_id, event=pending.event)
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "result": {
                "code": outcome.code,
                "message": outcome.message,
                "payload": outcome.payload,
                "events": outcome.private_events,
            },
        },
    )


@router.post("/restart")
async def restart(request: Request, payload: dict[str, object] | None = None) -> dict[str, object]:
    """Cooperatively restart the world server process."""

    _require_token(request)
    _schedule_restart()
    return {"ok": True}


@router.post("/shutdown")
async def shutdown(request: Request, payload: dict[str, object] | None = None) -> dict[str, object]:
    """Cooperatively stop the world server process."""

    _require_token(request)
    _schedule_exit()
    return {"ok": True}


@router.post("/resync")
async def resync(request: Request, payload: ResyncPayload) -> dict[str, object]:
    """Bump the profile revision and notify live clients to refresh."""

    _require_token(request)
    runtime = _runtime(request)
    runtime.profile_revision += 1
    notified = await runtime.connections.broadcast(profile_resync_envelope(runtime.profile_revision))
    return {"ok": True, "refreshed": 1, "notified_clients": notified}
