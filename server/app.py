"""FastAPI assembly and lifespan for the Tinyrooms Milestone 1 backend."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
import html
import json
import logging
import mimetypes
import sqlite3
import time
import uuid

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from server.accounts import AccountConflictError, AccountService, AuthenticationError, LoginResult
from server.behaviors.dispatcher import BehaviorDispatcher
from server.behaviors.events import BehaviorEvent, PeepRef
from server.behaviors.loader import BehaviorLoader
from server.behaviors.ticker import RoomTicker
from server.commands.core import build_registry, dispatch_command
from server.commands.outcomes import CommandContext, CommandError
from server.commands.parser import CommandParseError, parse_command
from server.commands.registry import CommandRegistry
from server.config import AppConfig, ConfigError, KNOWN_FEATURES, ensure_contained, load_config
from server.connections import ConnectionRegistry, LiveConnection
from server.content.activities import load_activity_definitions
from server.content.cards import CardCatalog, ContentError, load_card_catalog
from server.content.gameplay import GameplayContent, load_gameplay_content
from server.content.worlds import WorldDefinition, load_world_definition
from server.mods import ModDefinition, load_mods
from server.profiles import AccountRecord, ProfileRepository, SessionRecord
from server.protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    error_envelope,
    parse_client_message,
    presence_leave_event,
    result_envelope,
    room_event_envelope,
    room_snapshot_envelope,
    visible_rejection_event,
)
from server.security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    RateLimitError,
    SecurityError,
    require_matching_csrf,
    validate_origin,
)
from server.services.activities import ActivityService
from server.services.actions import ActionsService
from server.services.audit import AuditService
from server.services.auras import AuraService
from server.services.cards import CardService
from server.services.crafting import CraftingService
from server.services.dialogs import DialogService
from server.services.dispensers import DispenserService
from server.services.environment import EnvironmentService
from server.services.friends import FriendsService
from server.services.inventory import InventoryService
from server.services.memories import MemoryService
from server.services.ownership import OwnershipService
from server.services.powers import PowersService
from server.services.pricing import CardPricingService
from server.services.progression import ProgressionService
from server.services.room_layout import RoomLayoutService
from server.services.rooms import RoomService
from server.services.shop import ShopService
from server.services.stats import StatsService
from server.services.tasks import TaskService
from server.state.migrations import DatabaseHub, ensure_profile_database, ensure_world_database
from server.state.world_state import LayoutRevisionConflict, WorldStateRepository


LOGGER = logging.getLogger("tinyrooms.server")


def _log_event(event: str, **fields: object) -> None:
    """Write one structured log record without request bodies or credentials."""

    LOGGER.info(json.dumps({"event": event, **fields}, separators=(",", ":")))


class AuthRequest(BaseModel):
    """Create-account or login request payload."""

    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=8, max_length=256)
    passphrase: str | None = None


class StickerConfirmRequest(BaseModel):
    """Sticker confirmation request payload."""

    sticker: str


class ActivityBridgeRequest(BaseModel):
    """Activity bridge request payload."""

    type: str
    payload: dict[str, object] = Field(default_factory=dict)


class LayoutSaveRequest(BaseModel):
    """Room layout save request payload."""

    base_revision: int = Field(ge=0)
    patch: dict[str, object] = Field(default_factory=dict)


@dataclass(slots=True)
class RuntimeState:
    """Shared application runtime state."""

    config: AppConfig
    hub: DatabaseHub
    catalog: CardCatalog
    content: GameplayContent
    world: WorldDefinition
    profiles: ProfileRepository
    world_state: WorldStateRepository
    accounts: AccountService
    cards: CardService
    activities: ActivityService
    connections: ConnectionRegistry
    rooms: RoomService
    registry: CommandRegistry
    stats: StatsService
    inventory: InventoryService
    progression: ProgressionService
    actions: ActionsService
    friends: FriendsService
    shop: ShopService
    pricing: CardPricingService
    dialogs: DialogService
    tasks: TaskService
    memories: MemoryService
    powers: PowersService
    audit: AuditService
    ownership: OwnershipService
    environment: EnvironmentService
    layout: RoomLayoutService
    auras: AuraService
    mods: dict[str, object]
    mod_definitions: tuple[ModDefinition, ...]
    dispensers: DispenserService
    crafting: CraftingService
    behaviors: BehaviorDispatcher
    ticker: RoomTicker


def _client_source_key(request: Request) -> str:
    client = request.client
    return "unknown" if client is None else client.host


def _json_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "code": code, "message": message})


def _set_session_cookies(response: Response, *, token: str, csrf_token: str, expires_at: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        expires=expires_at,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=True,
        samesite="lax",
        expires=expires_at,
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _safe_path(root: Path, requested_path: str) -> Path:
    try:
        return ensure_contained(root / requested_path, root, "asset")
    except ConfigError as exc:
        raise HTTPException(status_code=404, detail="Not found.") from exc


def _activity_roots(runtime: RuntimeState) -> tuple[Path, ...]:
    """Return core and mod activity roots in search order."""

    return (runtime.config.activities_path, *(mod.activities_path for mod in runtime.mod_definitions))


def _propset_roots(runtime: RuntimeState) -> tuple[Path, ...]:
    """Return core propset roots in search order."""

    return (runtime.config.propsets_path,)


def _render_fallback_activity(kind: str) -> HTMLResponse:
    title = html.escape(kind.replace("-", " ").title())
    body = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family:sans-serif;padding:1rem">
  <h1>{title}</h1>
  <p>Milestone 1 fallback activity page for <code>{title}</code>.</p>
  <p>This route is ready for the real activity files under <code>activities\\{html.escape(kind)}</code>.</p>
</body>
</html>"""
    return HTMLResponse(body)


def _auth_response(runtime: RuntimeState, result: LoginResult, account: AccountRecord) -> Response:
    response = JSONResponse(
        {
            "ok": True,
            "csrf_token": result.csrf_token,
            "user": _serialize_account(runtime, account),
        }
    )
    _set_session_cookies(response, token=result.session_token, csrf_token=result.csrf_token, expires_at=result.expires_at)
    return response


def _serialize_account(runtime: RuntimeState, account: AccountRecord) -> dict[str, object]:
    user_profile = runtime.profiles.user_profile_for(account.id, runtime.world.id, runtime.world.entry_room_id)
    activity = runtime.activities.get(account.id)
    if not account.initial_sticker_complete:
        activity = runtime.activities.ensure_initial_sticker(account.id)
    snapshot = runtime.stats.view(account.id)
    level_definition = runtime.content.levels.get(account.level)
    skills = runtime.progression.skill_slots(account, user_profile)
    friends = runtime.friends.serialize(account.id)
    return {
        "id": account.id,
        "username": account.username_display,
        "sticker": account.sticker,
        "initial_sticker_complete": account.initial_sticker_complete,
        "owned_rooms": list(user_profile.owned_rooms),
        "level": account.level,
        "level_label": level_definition.label,
        "kudos": account.kudos,
        "kudos_to_next": level_definition.kudos_to_next,
        "max_equipped": level_definition.max_equipped,
        "bops": account.bops,
        "sticker_swap_cost": runtime.content.bops.sticker_swap_cost,
        "shared_energy": snapshot.energy,
        "counters": snapshot.payload(),
        "stats": snapshot.effective.stats,
        "statuses": list(snapshot.statuses),
        "status_definitions": {
            status_id: {
                "label": definition.label,
                "description": definition.description,
                "icon": definition.icon,
            }
            for status_id, definition in runtime.content.statuses.items()
        },
        "skills": [
            {"index": slot.index, "rank": slot.rank, "unlocked": slot.unlocked, "stack_id": slot.stack_id}
            for slot in skills
        ],
        "pinned_peeps": list(user_profile.pinned_peeps),
        "friends": friends.as_dict(),
        "packs": [preview.as_dict() for preview in runtime.shop.packs()],
        "show_activity_log": user_profile.show_activity_log,
        "world_id": runtime.world.id,
        "remembered_room": user_profile.remembered_room,
        "inventory": runtime.cards.list_inventory_payload(account.id),
        "core_cards": runtime.cards.serialize_core_cards(),
        "activity": runtime.activities.serialize(activity),
        "tasks": runtime.tasks.view_payload(account.id),
        "journal": runtime.memories.journal_payload(account.id),
        "powers": sorted(runtime.powers.effective(account)),
    }


def _get_runtime(request: Request) -> RuntimeState:
    return request.app.state.runtime


def _session_from_request(runtime: RuntimeState, request: Request) -> SessionRecord | None:
    return runtime.accounts.authenticate(request.cookies.get(SESSION_COOKIE))


def _require_session(runtime: RuntimeState, request: Request) -> SessionRecord:
    session = _session_from_request(runtime, request)
    if session is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return session


def _enforce_authenticated_post(runtime: RuntimeState, request: Request, session: SessionRecord) -> None:
    validate_origin(request.headers.get("origin"), runtime.config)
    csrf_cookie = request.cookies.get(CSRF_COOKIE)
    if csrf_cookie is None:
        raise HTTPException(status_code=403, detail="Missing CSRF cookie.")
    require_matching_csrf(session.csrf_token, request.headers.get("x-csrf-token"))
    require_matching_csrf(session.csrf_token, csrf_cookie)


async def _broadcast_room_event(
    runtime: RuntimeState,
    *,
    room_id: str,
    event: dict[str, object],
    exclude_account_id: str | None = None,
) -> None:
    for connection in await runtime.connections.list_room(room_id):
        if exclude_account_id is not None and connection.account_id == exclude_account_id:
            continue
        await connection.send(room_event_envelope(event))


async def _deliver_behavior_result(runtime: RuntimeState, result: object | None) -> None:
    """Broadcast room events and route private events produced by behaviors."""

    if result is None:
        return
    for pending in getattr(result, "room_broadcasts", []):
        await _broadcast_room_event(runtime, room_id=pending.room_id, event=pending.event)
    for event in getattr(result, "private_events", []):
        account_id = event.get("account_id")
        if not isinstance(account_id, str):
            continue
        target = await runtime.connections.get(account_id)
        if target is not None:
            await target.send(room_event_envelope(event))


async def _handle_replaced_connection(
    runtime: RuntimeState,
    replaced: LiveConnection,
    *,
    reason: str = "session_replaced",
    message: str = "Your session was replaced by a newer login.",
) -> None:
    if replaced.room_id is not None:
        runtime.auras.leave(replaced.account_id, replaced.room_id)
        await _broadcast_room_event(
            runtime,
            room_id=replaced.room_id,
            event=presence_leave_event(
                account_id=replaced.account_id,
                username=replaced.username,
                room_id=replaced.room_id,
                reason=reason,
            ),
            exclude_account_id=replaced.account_id,
        )
    await runtime.connections.send_session_replaced(replaced, message)


def create_runtime(config: AppConfig) -> RuntimeState:
    """Create the loaded runtime state."""

    profile_db_path = config.users_path / "profiles.sqlite3"
    ensure_profile_database(profile_db_path)
    ensure_world_database(config.worldstate_path)
    hub = DatabaseHub(profile_db_path, config.worldstate_path)
    catalog = load_card_catalog(config.cardsets_path, config.world_path)
    content = load_gameplay_content(config.repo_root / "data" / "core")
    mods = load_mods(config)
    core_activities = load_activity_definitions(
        config.repo_root / "data" / "core" / "activities.yaml",
        source="core",
        known_features=KNOWN_FEATURES,
    )
    activities_catalog = {**core_activities, **mods.activity_definitions}
    world = load_world_definition(
        config.world_path,
        set(catalog.cards),
        core_activities=activities_catalog,
        known_features=KNOWN_FEATURES,
        propsets_root=config.propsets_path,
        mod_props=mods.mod_props(),
        enabled_mods=mods.ids,
    )
    profiles = ProfileRepository(hub)
    world_state = WorldStateRepository(hub)
    accounts = AccountService(config, profiles, world.id, world.entry_room_id)
    activities = ActivityService(config)
    connections = ConnectionRegistry()
    equipped_caps = {level: definition.max_equipped for level, definition in content.levels.levels.items()}
    pricing = CardPricingService(hub, profiles, catalog, content, world.id)
    cards = CardService(hub, profiles, world_state, catalog, world.id, equipped_caps, pricing)
    stats = StatsService(hub, profiles, catalog, content, world.id)
    inventory = InventoryService(hub, profiles, stats, catalog, content.levels, world.id)
    progression = ProgressionService(hub, profiles, stats, catalog, content, world.id)
    memories = MemoryService(hub, profiles, world.id, config.timezone)
    tasks = TaskService(
        hub,
        profiles,
        stats,
        progression,
        content,
        world.id,
        world.tasks,
        config.timezone,
        memories=memories,
    )
    actions = ActionsService(hub, profiles, stats, catalog, world.id)
    friends = FriendsService(hub, profiles, is_online=connections.is_online)
    shop = ShopService(hub, profiles, catalog, content, world.id)
    audit = AuditService(hub, world.id)
    powers = PowersService(hub, profiles, world, config.bootstrap_admins, audit)
    ownership = OwnershipService(hub, profiles, world_state, world, has_power=powers.has_power)
    environment = EnvironmentService(hub, world, world_state)
    layout = RoomLayoutService(hub, world, world_state, ownership, environment)
    auras = AuraService(hub, stats, world)
    dispensers = DispenserService(hub, profiles, catalog, world, equipped_caps=equipped_caps)
    crafting = CraftingService(hub, profiles, inventory, stats, catalog, content, world, world.recipes)
    registry = build_registry()
    for spec in mods.command_specs():
        registry.register(
            spec["name"],
            spec["summary"],
            spec["handler"],
            usage=spec["usage"],
            power=spec["power"],
            help=spec["help"],
            toast=spec["toast"],
            log=spec["log"],
        )
    rooms = RoomService(
        hub=hub,
        profiles=profiles,
        world_state=world_state,
        connections=connections,
        card_service=cards,
        activities=activities,
        world=world,
        stats=stats,
        command_verbs=frozenset(f".{spec.name}" for spec in registry.list()),
        environment=environment,
        auras=auras,
        layout=layout,
    )
    dialogs = DialogService(
        hub=hub,
        profiles=profiles,
        stats=stats,
        catalog=catalog,
        progression=progression,
        world=world,
        tasks=tasks,
    )
    scripts = BehaviorLoader().load_world(world)
    behaviors = BehaviorDispatcher(
        hub=hub,
        profiles=profiles,
        stats=stats,
        progression=progression,
        activities=activities,
        catalog=catalog,
        dialogs=dialogs,
        connections=connections,
        scripts=scripts,
        world=world,
        tasks=tasks,
        environment=environment,
    )
    dialogs.attach_dispatcher(behaviors)
    rooms.attach_dispatcher(behaviors)
    rooms.attach_dialogs(dialogs)
    runtime_holder: dict[str, RuntimeState] = {}

    async def _deliver_tick_result(result: object) -> None:
        runtime = runtime_holder.get("runtime")
        if runtime is not None:
            await _deliver_behavior_result(runtime, result)

    ticker = RoomTicker(
        dispatcher=behaviors,
        world=world,
        connections=connections,
        environment=environment,
        auras=auras,
        on_result=_deliver_tick_result,
        interval=config.tick_seconds,
    )
    runtime = RuntimeState(
        config=config,
        hub=hub,
        catalog=catalog,
        content=content,
        world=world,
        profiles=profiles,
        world_state=world_state,
        accounts=accounts,
        cards=cards,
        activities=activities,
        connections=connections,
        rooms=rooms,
        registry=registry,
        stats=stats,
        inventory=inventory,
        progression=progression,
        actions=actions,
        friends=friends,
        shop=shop,
        pricing=pricing,
        dialogs=dialogs,
        tasks=tasks,
        memories=memories,
        powers=powers,
        audit=audit,
        ownership=ownership,
        environment=environment,
        layout=layout,
        auras=auras,
        mods={},
        mod_definitions=mods.definitions,
        dispensers=dispensers,
        crafting=crafting,
        behaviors=behaviors,
        ticker=ticker,
    )
    for mod_id, factory in mods.state_factories():
        runtime.mods[mod_id] = factory(runtime)
    for state in runtime.mods.values():
        prepare = getattr(state, "prepare", None)
        if prepare is not None:
            prepare()
    world_state.initialize_world(world)
    rooms.attach_mod_states(runtime.mods.values())
    runtime_holder["runtime"] = runtime
    return runtime


def create_app(config: AppConfig | None = None) -> FastAPI:
    """Create the FastAPI application."""

    loaded_config = config or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = create_runtime(loaded_config)
        app.state.runtime = runtime
        runtime.ticker.start()
        try:
            yield
        finally:
            runtime.ticker.stop()
            runtime.hub.close()

    app = FastAPI(title="Tinyrooms Server", version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        started_at = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        _log_event(
            "http.request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        return response

    @app.exception_handler(ContentError)
    async def content_error_handler(request: Request, exc: ContentError) -> JSONResponse:  # noqa: ARG001
        return _json_error(500, "content_error", str(exc))

    @app.exception_handler(AuthenticationError)
    async def auth_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:  # noqa: ARG001
        return _json_error(401, "auth_error", str(exc))

    @app.exception_handler(AccountConflictError)
    async def account_conflict_handler(request: Request, exc: AccountConflictError) -> JSONResponse:  # noqa: ARG001
        return _json_error(409, "account_conflict", str(exc))

    @app.exception_handler(RateLimitError)
    async def rate_limit_error_handler(request: Request, exc: RateLimitError) -> JSONResponse:  # noqa: ARG001
        return _json_error(429, "rate_limited", str(exc))

    @app.exception_handler(SecurityError)
    async def security_error_handler(request: Request, exc: SecurityError) -> JSONResponse:  # noqa: ARG001
        return _json_error(403, "security_error", str(exc))

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"ok": True, "protocol_version": PROTOCOL_VERSION}

    @app.get("/api/stickers")
    async def list_stickers(request: Request) -> dict[str, object]:
        runtime = _get_runtime(request)
        return {
            "ok": True,
            "stickers": [
                {"name": sticker_name, "image_url": f"/assets/stickers/{sticker_name}"}
                for sticker_name in runtime.accounts.list_stickers()
            ],
        }

    @app.get("/api/session")
    async def session_status(request: Request) -> dict[str, object]:
        runtime = _get_runtime(request)
        session = _session_from_request(runtime, request)
        if session is None:
            return {"ok": True, "logged_in": False}
        account = runtime.profiles.get_account_by_id(session.account_id)
        if account is None:
            return {"ok": True, "logged_in": False}
        return {
            "ok": True,
            "logged_in": True,
            "csrf_token": session.csrf_token,
            "user": _serialize_account(runtime, account),
        }

    @app.post("/api/auth/create")
    async def create_account(request: Request, payload: AuthRequest) -> Response:
        runtime = _get_runtime(request)
        validate_origin(request.headers.get("origin"), runtime.config)
        result = runtime.accounts.create_account(
            payload.username,
            payload.password,
            payload.passphrase or "",
            _client_source_key(request),
        )
        return _auth_response(runtime, result, result.account)

    @app.post("/api/auth/login")
    async def login(request: Request, payload: AuthRequest) -> Response:
        runtime = _get_runtime(request)
        validate_origin(request.headers.get("origin"), runtime.config)
        result = runtime.accounts.login(payload.username, payload.password, _client_source_key(request))
        account = runtime.profiles.get_account_by_id(result.account.id)
        replaced = await runtime.connections.get(account.id)
        if replaced is not None:
            await _handle_replaced_connection(runtime, replaced)
        return _auth_response(runtime, result, account)

    @app.post("/api/auth/logout")
    async def logout(request: Request) -> Response:
        runtime = _get_runtime(request)
        session = _require_session(runtime, request)
        _enforce_authenticated_post(runtime, request, session)
        runtime.activities.close(session.account_id)
        runtime.accounts.logout(request.cookies.get(SESSION_COOKIE))
        active = await runtime.connections.get(session.account_id)
        if active is not None:
            await _handle_replaced_connection(
                runtime,
                active,
                reason="signed_out",
                message="You signed out.",
            )
        response = JSONResponse({"ok": True})
        _clear_session_cookies(response)
        return response

    @app.post("/api/stickers/confirm")
    async def confirm_sticker(request: Request, payload: StickerConfirmRequest) -> dict[str, object]:
        runtime = _get_runtime(request)
        session = _require_session(runtime, request)
        _enforce_authenticated_post(runtime, request, session)
        account = runtime.accounts.confirm_initial_sticker(session.account_id, payload.sticker)
        runtime.activities.close(session.account_id)
        return {"ok": True, "user": _serialize_account(runtime, account)}

    @app.get("/api/bootstrap")
    async def bootstrap(request: Request) -> dict[str, object]:
        runtime = _get_runtime(request)
        session = _require_session(runtime, request)
        account = runtime.profiles.get_account_by_id(session.account_id)
        payload = _serialize_account(runtime, account)
        payload["can_enter_world"] = bool(account.initial_sticker_complete)
        return {"ok": True, "user": payload}

    @app.get("/api/rooms/{room_id}/layout")
    async def get_room_layout(request: Request, room_id: str) -> dict[str, object]:
        runtime = _get_runtime(request)
        session = _require_session(runtime, request)
        if room_id not in runtime.world.rooms:
            raise HTTPException(status_code=404, detail="Room not found.")
        account = runtime.profiles.get_account_by_id(session.account_id)
        return {"ok": True, "layout": runtime.layout.view(account, room_id)}

    @app.post("/api/rooms/{room_id}/layout")
    async def save_room_layout(request: Request, room_id: str, payload: LayoutSaveRequest) -> Response:
        runtime = _get_runtime(request)
        session = _require_session(runtime, request)
        _enforce_authenticated_post(runtime, request, session)
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
            return _json_error(400, "layout_rejected", str(exc))
        await _broadcast_room_event(runtime, room_id=room_id, event=update.event())
        return JSONResponse(content={"ok": True, "layout": runtime.layout.view(account, room_id)})

    @app.get("/api/activities/current")
    async def current_activity(request: Request) -> dict[str, object]:
        runtime = _get_runtime(request)
        session = _require_session(runtime, request)
        account = runtime.profiles.get_account_by_id(session.account_id)
        activity = runtime.activities.get(account.id)
        if not account.initial_sticker_complete:
            activity = runtime.activities.ensure_initial_sticker(account.id)
        return {"ok": True, "activity": runtime.activities.serialize(activity)}

    @app.get("/api/activities/{activity_id}")
    async def get_activity(request: Request, activity_id: str) -> dict[str, object]:
        runtime = _get_runtime(request)
        session = _require_session(runtime, request)
        activity = runtime.activities.get(session.account_id)
        if activity is None or activity.id != activity_id:
            raise HTTPException(status_code=404, detail="Activity not found.")
        return {"ok": True, "activity": runtime.activities.serialize(activity)}

    @app.post("/api/activities/{activity_id}/bridge")
    async def activity_bridge(request: Request, activity_id: str, payload: ActivityBridgeRequest) -> dict[str, object]:
        runtime = _get_runtime(request)
        session = _require_session(runtime, request)
        _enforce_authenticated_post(runtime, request, session)
        activity = runtime.activities.get(session.account_id)
        if activity is None or activity.id != activity_id:
            raise HTTPException(status_code=404, detail="Activity not found.")
        if payload.type not in {"activity.ready", "activity.attention", "activity.cancel", "activity.complete"}:
            raise HTTPException(status_code=400, detail="Unsupported activity bridge message type.")
        if payload.type == "activity.attention":
            updated = runtime.activities.mark_attention(session.account_id)
            return {"ok": True, "activity": runtime.activities.serialize(updated)}
        if payload.type in {"activity.cancel", "activity.complete"}:
            closed = runtime.activities.close(session.account_id)
            return {
                "ok": True,
                "activity": None,
                "closed": runtime.activities.serialize(closed),
                "reason": "cancelled" if payload.type == "activity.cancel" else "completed",
            }
        return {"ok": True, "activity": runtime.activities.serialize(activity)}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        runtime = websocket.app.state.runtime
        try:
            validate_origin(websocket.headers.get("origin"), runtime.config)
        except ValueError:
            await websocket.close(code=4403)
            return
        token = websocket.cookies.get(SESSION_COOKIE)
        session = runtime.accounts.authenticate(token)
        if session is None:
            await websocket.close(code=4401)
            return
        account = runtime.profiles.get_account_by_id(session.account_id)
        if account is None or not account.initial_sticker_complete:
            await websocket.close(code=4403)
            return
        await websocket.accept()
        _log_event(
            "websocket.connected",
            account_id=account.id,
            generation=session.generation,
        )
        connection = LiveConnection(
            websocket=websocket,
            account_id=account.id,
            username=account.username_display,
            generation=session.generation,
        )
        await connection.start()
        replaced = await runtime.connections.register(connection)
        if replaced is not None:
            await _handle_replaced_connection(runtime, replaced)
        room_id = runtime.rooms.current_room_for_account(account.id)
        await runtime.connections.set_room(account.id, room_id)
        runtime.auras.enter(account.id, room_id)
        snapshot = await runtime.rooms.build_snapshot(account, room_id)
        await connection.send(room_snapshot_envelope(snapshot))
        await _broadcast_room_event(
            runtime,
            room_id=room_id,
            event={
                "type": "presence.enter",
                "room_id": room_id,
                "account_id": account.id,
                "username": account.username_display,
            },
            exclude_account_id=account.id,
        )
        enter_result = await runtime.behaviors.dispatch(
            BehaviorEvent(
                type="enter",
                actor=PeepRef(kind="user", peep_id=None, account_id=account.id),
                target=None,
                room_id=room_id,
                action=None,
                data={"source_room_id": None},
            )
        )
        await _deliver_behavior_result(runtime, enter_result)
        try:
            while True:
                raw_text = await websocket.receive_text()
                try:
                    envelope_type, client_payload = parse_client_message(raw_text)
                except ProtocolError as exc:
                    await connection.send(error_envelope("protocol_error", str(exc)))
                    continue
                current_session = runtime.accounts.authenticate(token)
                current_account = runtime.profiles.get_account_by_id(account.id)
                if current_session is None or current_account is None:
                    await connection.send(
                        error_envelope(
                            "session_missing",
                            "Your session is no longer active.",
                        )
                    )
                    await runtime.connections.unregister(account.id, connection)
                    await connection.close()
                    return
                if (
                    current_session.generation != connection.generation
                    or not runtime.profiles.session_generation_matches(
                        account.id,
                        connection.generation,
                    )
                ):
                    await connection.send(error_envelope("session_replaced", "Your session was replaced."))
                    await runtime.connections.unregister(account.id, connection)
                    await connection.close()
                    return
                if envelope_type == "snapshot.request":
                    refreshed_snapshot = await runtime.rooms.build_snapshot(current_account, connection.room_id or room_id)
                    await connection.send(room_snapshot_envelope(refreshed_snapshot))
                    continue
                request_id = client_payload.request_id
                try:
                    parsed_command = parse_command(client_payload.command)
                    _log_event(
                        "command.received",
                        request_id=request_id,
                        account_id=account.id,
                        command=parsed_command.name,
                    )
                    context = CommandContext(
                        account=current_account,
                        connection=connection,
                        profiles=runtime.profiles,
                        world_state=runtime.world_state,
                        rooms=runtime.rooms,
                        cards=runtime.cards,
                        activities=runtime.activities,
                        registry=runtime.registry,
                        stats=runtime.stats,
                        inventory=runtime.inventory,
                        progression=runtime.progression,
                        actions=runtime.actions,
                        friends=runtime.friends,
                        shop=runtime.shop,
                        pricing=runtime.pricing,
                        content=runtime.content,
                        world=runtime.world,
                        valid_stickers=frozenset(runtime.accounts.list_stickers()),
                        serialize_user=lambda account: _serialize_account(runtime, account),
                        behaviors=runtime.behaviors,
                        dialogs=runtime.dialogs,
                        tasks=runtime.tasks,
                        memories=runtime.memories,
                        powers=runtime.powers,
                        ownership=runtime.ownership,
                        environment=runtime.environment,
                        audit=runtime.audit,
                        connections=runtime.connections,
                        mods=runtime.mods,
                        dispensers=runtime.dispensers,
                        crafting=runtime.crafting,
                        recipes=runtime.world.recipes,
                    )
                    outcome = await dispatch_command(context, parsed_command)
                except (CommandParseError, CommandError, ValueError, sqlite3.IntegrityError) as exc:
                    await connection.send(
                        result_envelope(
                            request_id,
                            ok=False,
                            code="command_rejected",
                            message=str(exc),
                            events=[visible_rejection_event("command_rejected", str(exc))],
                        )
                    )
                    continue
                await connection.send(
                    result_envelope(
                        request_id,
                        ok=True,
                        code=outcome.code,
                        message=outcome.message,
                        payload=outcome.payload,
                        events=outcome.private_events,
                        toast=outcome.toast,
                        log=outcome.log,
                    )
                )
                if outcome.snapshot is not None:
                    await connection.send(room_snapshot_envelope(outcome.snapshot))
                for pending in outcome.room_broadcasts:
                    exclude = connection.account_id if pending.event.get("type") == "presence.enter" else None
                    await _broadcast_room_event(
                        runtime,
                        room_id=pending.room_id,
                        event=pending.event,
                        exclude_account_id=exclude,
                    )
        except WebSocketDisconnect:
            active = await runtime.connections.get(account.id)
            if active is connection and connection.room_id is not None:
                runtime.auras.leave(account.id, connection.room_id)
                await _broadcast_room_event(
                    runtime,
                    room_id=connection.room_id,
                    event=presence_leave_event(
                        account_id=account.id,
                        username=account.username_display,
                        room_id=connection.room_id,
                    ),
                    exclude_account_id=account.id,
                )
                runtime.activities.close(account.id)
                runtime.dialogs.end(account.id, "disconnected")
                leave_result = await runtime.behaviors.dispatch(
                    BehaviorEvent(
                        type="leave",
                        actor=PeepRef(kind="user", peep_id=None, account_id=account.id),
                        target=None,
                        room_id=connection.room_id,
                        action=None,
                        data={"destination_room_id": None},
                    )
                )
                await _deliver_behavior_result(runtime, leave_result)
            await runtime.connections.unregister(account.id, connection)
            _log_event(
                "websocket.disconnected",
                account_id=account.id,
                generation=connection.generation,
            )

    @app.get("/")
    async def index(request: Request) -> Response:
        runtime = _get_runtime(request)
        index_path = runtime.config.app_path / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        return HTMLResponse(
            "<!doctype html><html><body><h1>Tinyrooms backend ready</h1>"
            "<p>The backend is running. Add the frontend files under app\\index.html when available.</p>"
            "</body></html>"
        )

    @app.get("/app/{requested_path:path}")
    async def app_files(requested_path: str, request: Request) -> Response:
        runtime = _get_runtime(request)
        candidate = _safe_path(runtime.config.app_path, requested_path)
        if candidate.is_file():
            return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="App file not found.")

    @app.get("/activities/{activity_name}/")
    async def activity_index(activity_name: str, request: Request) -> Response:
        runtime = _get_runtime(request)
        for root in _activity_roots(runtime):
            candidate = _safe_path(root / activity_name, "index.html")
            if candidate.is_file():
                return FileResponse(candidate)
        return _render_fallback_activity(activity_name)

    @app.get("/activities/{filename}")
    async def shared_activity_file(filename: str, request: Request) -> Response:
        runtime = _get_runtime(request)
        if filename not in {"shared.css", "shared.js"}:
            raise HTTPException(status_code=404, detail="Activity file not found.")
        candidate = _safe_path(runtime.config.activities_path, filename)
        return FileResponse(candidate)

    @app.get("/activities/{activity_name}/{requested_path:path}")
    async def activity_files(activity_name: str, requested_path: str, request: Request) -> Response:
        runtime = _get_runtime(request)
        for root in _activity_roots(runtime):
            candidate = _safe_path(root / activity_name, requested_path)
            if candidate.is_file():
                media_type, _ = mimetypes.guess_type(candidate.name)
                return FileResponse(candidate, media_type=media_type)
        raise HTTPException(status_code=404, detail="Activity file not found.")

    @app.get("/assets/stickers/{filename}")
    async def sticker_asset(filename: str, request: Request) -> Response:
        runtime = _get_runtime(request)
        candidate = _safe_path(runtime.config.stickers_path, filename)
        if candidate.is_file():
            return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="Sticker asset not found.")

    @app.get("/assets/{cardset}/{filename}")
    async def cardset_asset(cardset: str, filename: str, request: Request) -> Response:
        runtime = _get_runtime(request)
        candidate = _safe_path(runtime.config.cardsets_path / cardset, filename)
        if candidate.is_file():
            return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="Cardset asset not found.")

    @app.get("/assets/propsets/{propset}/{filename}")
    async def propset_asset(propset: str, filename: str, request: Request) -> Response:
        runtime = _get_runtime(request)
        for root in _propset_roots(runtime):
            candidate = _safe_path(root / propset, filename)
            if candidate.is_file():
                return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="Propset asset not found.")

    @app.get("/assets/mods/{mod_id}/props/{filename}")
    async def mod_prop_asset(mod_id: str, filename: str, request: Request) -> Response:
        runtime = _get_runtime(request)
        for mod in runtime.mod_definitions:
            if mod.id != mod_id:
                continue
            candidate = _safe_path(mod.props_path, filename)
            if candidate.is_file():
                return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="Mod prop asset not found.")

    @app.get("/assets/world/{world_id}/{bucket}/{filename}")
    async def world_asset(world_id: str, bucket: str, filename: str, request: Request) -> Response:
        runtime = _get_runtime(request)
        if world_id != runtime.world.id or bucket not in {"cards", "rooms", "props", "peeps"}:
            raise HTTPException(status_code=404, detail="World asset not found.")
        candidate = _safe_path(runtime.world.root_path / bucket, filename)
        if candidate.is_file():
            return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="World asset not found.")

    return app
