"""Guest invite creation, landing page, and redemption routes."""

from __future__ import annotations

import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from server.base_path import render_html
from server.routes.common import (
    enforce_authenticated_post,
    get_runtime,
    require_session,
    set_session_cookies,
)
from server.security import (
    SESSION_COOKIE,
    RateLimiter,
    RateLimitError,
    validate_origin,
)
from server.services.guest_invites import FingerprintContext, GuestInviteError

router = APIRouter()
_create_limiter = RateLimiter()
_redeem_limiter = RateLimiter()


class RedeemRequest(BaseModel):
    """Guest link redemption payload from the landing page."""

    token: str = Field(min_length=1, max_length=256)
    device_id: str = Field(min_length=1, max_length=128)


def _source_key(request: Request) -> str:
    return "unknown" if request.client is None else request.client.host


def _public_base_url(runtime, request: Request) -> str:
    """Return the public source-world URL, including any base path."""

    config = runtime.config
    base = (config.client_url or f"{request.url.scheme}://{request.url.netloc}").rstrip("/")
    if config.base_path:
        path = urlsplit(base).path.rstrip("/")
        if not (path == config.base_path or path.endswith(config.base_path)):
            base = f"{base}{config.base_path}"
    return base


def _error(exc: GuestInviteError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "code": exc.code, "message": str(exc)},
    )


@router.post("/api/guest-invites")
async def create_guest_invite(request: Request) -> Response:
    """Create a source-world invite link for the signed-in member."""

    runtime = get_runtime(request)
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    account = runtime.profiles.get_account_by_id(session.account_id)
    if account is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        _create_limiter.check(
            f"guest-invite:{account.id}",
            limit=10,
            window_seconds=60,
            now_ts=time.time(),
        )
    except RateLimitError as exc:
        return JSONResponse(
            status_code=429,
            content={"ok": False, "code": "rate_limited", "message": str(exc)},
        )
    try:
        link = await runtime.guest_invites.create(
            account,
            public_base_url=_public_base_url(runtime, request),
        )
    except GuestInviteError as exc:
        return _error(exc)
    return JSONResponse({
        "ok": True,
        "invite": {
            "token": link.token,
            "url": link.url,
            "world_id": link.world_id,
            "instance_id": link.instance_id,
            "room_id": link.room_id,
            "room_label": link.room_label,
            "inviter_username": link.inviter_username,
            "expires_at": link.expires_at,
        },
    })


@router.get("/guest/{token}")
async def guest_invite_page(token: str, request: Request) -> Response:
    """Serve the same-origin page that redeems a guest link."""

    runtime = get_runtime(request)
    page = runtime.config.app_path / "guest-invite.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="Guest invite page not found.")
    return render_html(
        page,
        runtime.config.base_path,
        document_path=f"/guest/{token}",
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/api/guest-invites/redeem")
async def redeem_guest_invite(request: Request, payload: RedeemRequest) -> Response:
    """Admit an existing member or create/reuse a device-bound guest."""

    runtime = get_runtime(request)
    session = runtime.accounts.authenticate(request.cookies.get(SESSION_COOKIE))
    existing_account = None
    if session is not None:
        enforce_authenticated_post(runtime, request, session)
        existing_account = runtime.profiles.get_account_by_id(session.account_id)
    else:
        try:
            validate_origin(request.headers.get("origin"), runtime.config)
        except ValueError:
            raise HTTPException(status_code=403, detail="Invalid origin.")
    try:
        _redeem_limiter.check(
            f"guest-redeem:ip:{_source_key(request)}",
            limit=20,
            window_seconds=60,
            now_ts=time.time(),
        )
    except RateLimitError as exc:
        return JSONResponse(
            status_code=429,
            content={"ok": False, "code": "rate_limited", "message": str(exc)},
        )

    context = FingerprintContext(
        device_id=payload.device_id,
        user_agent=request.headers.get("user-agent", ""),
        accept_language=request.headers.get("accept-language", ""),
        client_host=_source_key(request),
    )
    try:
        result = await runtime.guest_invites.redeem(
            payload.token,
            context,
            existing_account=existing_account,
        )
    except GuestInviteError as exc:
        return _error(exc)

    response = JSONResponse({"ok": True, "redirect_url": result.redirect_url})
    set_session_cookies(
        response,
        token=result.session.token,
        csrf_token=result.session.csrf_token,
        expires_at=result.session.expires_at.isoformat(),
    )
    return response
