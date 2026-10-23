"""Cutscene catalog page and admin preview API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from server.base_path import with_base
from server.content.cards import card_asset_url
from server.content.cutscenes import MAX_PARAM_STRING, MAX_PARAMS, RESERVED_PARAM_KEYS
from server.content.worlds import prop_model_url
from server.routes.common import (
    enforce_authenticated_post,
    get_runtime,
    require_power_access,
    require_session,
)
from server.routes.world_editor import _serve_page


router = APIRouter()

CATALOG_FEATURE = "cutscene-catalog"
CATALOG_POWERS = frozenset({"admin", "game-master"})
CATALOG_AUDIT_ACTION = "cutscene_catalog.access_denied"


def _require_catalog_access(runtime, request: Request):
    """Gate catalog access to admin and game-master accounts."""

    return require_power_access(
        runtime,
        request,
        feature=CATALOG_FEATURE,
        powers=CATALOG_POWERS,
        audit_action=CATALOG_AUDIT_ACTION,
    )


def _catalog_root(runtime) -> object:
    return runtime.config.client_path / "cutscene-catalog"


def _resolve_room(runtime, room_id: str | None):
    """Return the requested room, defaulting to the world entry room."""

    world = runtime.world
    if not room_id:
        return world.rooms[world.entry_room_id]
    room = world.rooms.get(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    return room


def _validate_preview_params(raw: object) -> dict[str, object]:
    """Validate catalog preview overrides against command launch limits."""

    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Params must be a mapping.")
    if len(raw) > MAX_PARAMS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_PARAMS} params are allowed.")
    overrides: dict[str, object] = {}
    for key, value in raw.items():
        name = str(key).strip()
        if not name:
            raise HTTPException(status_code=400, detail="Param names must be non-empty.")
        if name in RESERVED_PARAM_KEYS:
            raise HTTPException(status_code=400, detail=f"Param '{name}' is reserved.")
        if isinstance(value, bool) or isinstance(value, (int, float)):
            overrides[name] = value
        elif isinstance(value, str):
            if len(value) > MAX_PARAM_STRING:
                raise HTTPException(status_code=400, detail=f"Param '{name}' is too long.")
            overrides[name] = value
        else:
            raise HTTPException(status_code=400, detail=f"Param '{name}' must be a scalar.")
    return overrides


def _room_choices(runtime) -> list[dict[str, object]]:
    """Return every room in load order with labels for the room picker."""

    return [
        {"id": room.id, "label": room.label}
        for room in sorted(runtime.world.rooms.values(), key=lambda entry: entry.label.lower())
    ]


def _prop_choices(runtime, room) -> list[dict[str, object]]:
    """Return model-backed prop instances in a room for placeholder pickers."""

    choices = []
    for instance in room.props.values():
        definition = runtime.world.props.get(instance.prop_id)
        if definition is None:
            continue
        model_url = prop_model_url(runtime.world.id, definition, definition.active_state)
        if model_url is None:
            continue
        choices.append(
            {
                "id": instance.id,
                "label": definition.label or definition.id,
                "prop_id": definition.id,
                "model_url": model_url,
                "scale": instance.scale * definition.scale,
            }
        )
    choices.sort(key=lambda entry: str(entry["label"]).lower())
    return choices


async def _user_choices(runtime, account, room) -> list[dict[str, object]]:
    """Return live occupants of a room with sticker art for user pickers."""

    connections = await runtime.connections.list_room(room.id)
    choices = []
    for connection in connections:
        member = runtime.profiles.get_account_by_id(connection.account_id)
        if member is None:
            continue
        choices.append(
            {
                "id": member.id,
                "name": member.username_display,
                "self": member.id == account.id,
                "image_url": f"/assets/stickers/{member.sticker}" if member.sticker else "",
            }
        )
    choices.sort(key=lambda entry: (not entry["self"], str(entry["name"]).lower()))
    return choices


def _peep_choices(runtime) -> list[dict[str, object]]:
    """Return every authored NPC peep for peep placeholder pickers."""

    choices = [
        {
            "id": peep.id,
            "label": peep.label or peep.id,
            "room_id": peep.room_id,
            "image_url": f"/assets/world/{runtime.world.id}/peeps/{peep.image_name}",
        }
        for peep in runtime.world.peeps.values()
    ]
    choices.sort(key=lambda entry: str(entry["label"]).lower())
    return choices


def _sticker_choices(runtime) -> list[dict[str, object]]:
    """Return every servable sticker for sticker placeholder pickers."""

    choices = [
        {"name": name, "image_url": f"/assets/stickers/{name}"}
        for name in runtime.accounts.list_stickers()
    ]
    choices.sort(key=lambda entry: entry["name"])
    return choices


def _card_choices(runtime) -> list[dict[str, object]]:
    """Return every loaded card definition for card placeholder pickers."""

    choices = [
        {
            "id": definition.id,
            "label": definition.label,
            "rarity": definition.rarity,
            "type": definition.type,
            "source": definition.source,
            "image_url": card_asset_url(
                runtime.world.id,
                definition.source,
                definition.image_name,
                missing=definition.image_missing,
            ),
        }
        for definition in runtime.catalog.cards.values()
    ]
    choices.sort(key=lambda entry: str(entry["label"]).lower())
    return choices


def _cutscene_entry(runtime, account, definition, room_id: str) -> dict[str, object]:
    """Serialize one definition with placeholders and gate status."""

    has_power = lambda power: runtime.powers.has_power(account.id, power)
    cues = [
        {
            "at": cue.at,
            "say": cue.say,
            "speaker": cue.speaker,
            "style": cue.style,
            "sound": cue.sound,
        }
        for cue in definition.text
    ]
    return {
        "id": definition.id,
        "title": definition.title,
        "aliases": list(definition.aliases),
        "frame": definition.frame,
        "audience": definition.audience,
        "room_bound": definition.room_bound,
        "rooms": list(definition.rooms),
        "origin": definition.source,
        "hidden": definition.hidden,
        "skip": definition.skip,
        "duration": definition.duration_ms,
        "energy_cost": definition.energy_cost,
        "power": definition.power,
        "feature": definition.required_feature,
        "script_url": with_base(runtime.config.base_path, definition.script_url),
        "params": dict(definition.params),
        "placeholders": runtime.cutscenes.definition_placeholders(definition),
        "gates": runtime.cutscenes.gate_status(
            definition, room_id=room_id, has_power=has_power
        ),
        "text": cues,
        "sounds": dict(definition.sounds),
    }


@router.get("/cutscene-catalog")
@router.get("/cutscene-catalog/")
@router.get("/cutscene-catalog/{requested_path:path}")
async def cutscene_catalog_page(request: Request, requested_path: str = "") -> Response:
    """Serve the cutscene catalog single-page app behind feature and role gates."""

    runtime = get_runtime(request)
    _require_catalog_access(runtime, request)
    return _serve_page(runtime, _catalog_root(runtime), requested_path)


@router.get("/api/cutscene-catalog")
async def cutscene_catalog_data(request: Request, room_id: str | None = None) -> dict[str, object]:
    """Return every cutscene definition plus placeholder picker choices."""

    runtime = get_runtime(request)
    account = _require_catalog_access(runtime, request)
    room = _resolve_room(runtime, room_id)
    definitions = sorted(
        runtime.cutscenes.definitions().values(), key=lambda entry: entry.title.lower()
    )
    cutscenes = [
        _cutscene_entry(runtime, account, definition, room.id) for definition in definitions
    ]
    world_css_url = (
        with_base(runtime.config.base_path, f"/assets/world/{runtime.world.id}/world.css")
        if runtime.world.stylesheet_path is not None
        else ""
    )
    return {
        "ok": True,
        "world": {
            "id": runtime.world.id,
            "label": runtime.world.label,
            "entry_room_id": runtime.world.entry_room_id,
            "world_css_url": world_css_url,
        },
        "room_id": room.id,
        "rooms": _room_choices(runtime),
        "cutscenes": cutscenes,
        "choices": {
            "props": _prop_choices(runtime, room),
            "users": await _user_choices(runtime, account, room),
            "peeps": _peep_choices(runtime),
            "stickers": _sticker_choices(runtime),
            "cards": _card_choices(runtime),
        },
    }


@router.post("/api/cutscene-catalog/preview")
async def cutscene_catalog_preview(request: Request) -> dict[str, object]:
    """Build a local-only cutscene play payload for testing placeholders."""

    runtime = get_runtime(request)
    account = _require_catalog_access(runtime, request)
    session = require_session(runtime, request)
    enforce_authenticated_post(runtime, request, session)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Request body must be JSON.") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be an object.")
    definition_id = body.get("id")
    if not isinstance(definition_id, str) or not definition_id.strip():
        raise HTTPException(status_code=400, detail="A cutscene id is required.")
    room_value = body.get("room_id")
    if room_value is not None and (not isinstance(room_value, str) or not room_value.strip()):
        raise HTTPException(status_code=400, detail="room_id must be a room id.")
    room = _resolve_room(runtime, room_value if isinstance(room_value, str) else None)
    overrides = _validate_preview_params(body.get("params", {}))
    try:
        definition = runtime.cutscenes.resolve(definition_id.strip())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    occupants = [
        connection.account_id for connection in await runtime.connections.list_room(room.id)
    ]
    launch = runtime.cutscenes.launch(
        definition=definition,
        account=account,
        room_id=room.id,
        audience="private",
        origin="catalog",
        params=overrides,
        occupants=occupants,
        record_view=False,
    )
    return {"ok": True, "event": launch.event}
