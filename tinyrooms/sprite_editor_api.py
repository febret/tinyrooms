"""Sprite-editor REST API — enabled only when --feature sprite-editor is active."""

from pathlib import Path
from typing import Any

import yaml
from flask import Blueprint, jsonify, request, send_from_directory

from . import sprites

blueprint = Blueprint("sprite_editor", __name__)

_IMAGE_EXTS = (".png", ".gif", ".webp")
_YAML_EXTS = (".yaml", ".yml")
_STATIC_FOLDER = Path(__file__).parent.parent / "app"


# ---------------------------------------------------------------------------
# Thin wrappers that lazily reach into server.py to avoid circular imports.
# By request time the module is fully loaded, so this is safe.
# ---------------------------------------------------------------------------

def _get_repo(force_reindex: bool = False) -> sprites.SpriteRepository:
    from . import server  # noqa: PLC0415
    return server._sprite_repo(force_reindex)


def _feature_enabled() -> bool:
    from . import server  # noqa: PLC0415
    return server.feature_enabled("sprite-editor")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _err(msg: str, code: int):
    return jsonify({"ok": False, "error": msg}), code


def _verr(exc: sprites.SpriteValidationError):
    return jsonify({"ok": False, "error": str(exc), "details": exc.errors}), 400


def _guard():
    """Return a 404 response when the feature is disabled, else None."""
    if not _feature_enabled():
        return _err("sprite-editor feature disabled", 404)
    return None


def _parse_set(scope: str, filename: str) -> tuple[str, str]:
    v_scope = scope.strip().lower()
    if v_scope not in {"server", "world"}:
        raise ValueError("scope must be 'server' or 'world'")
    v_filename = filename.strip()
    if not v_filename or "/" in v_filename or "\\" in v_filename or ".." in v_filename:
        raise ValueError("invalid filename")
    return v_scope, v_filename


def _yaml_path(scope: str, filename: str) -> Path:
    repo = _get_repo()
    root = repo.server_root_path if scope == "server" else repo.world_sprites_path
    return root / f"{filename}.yaml"


def _image_path(scope: str, filename: str) -> Path:
    repo = _get_repo()
    root = repo.server_root_path if scope == "server" else repo.world_sprites_path
    for ext in _IMAGE_EXTS:
        p = root / f"{filename}{ext}"
        if p.exists():
            return p
    raise ValueError("sprite image file not found")


def _load_doc(scope: str, filename: str) -> tuple[dict[str, Any], Path, Path]:
    """Return (raw_yaml_doc, yaml_path, image_path) for a set that already has a definition."""
    yp = _yaml_path(scope, filename)
    ip = _image_path(scope, filename)
    if not yp.exists():
        raise ValueError("sprite definition does not exist")
    doc = yaml.safe_load(yp.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        raise ValueError("sprite definition yaml must be a mapping")
    return doc, yp, ip


def _persist(yp: Path, ip: Path, doc: dict[str, Any]) -> None:
    normalized = sprites.validate_definition_document(doc, image_path=ip)
    sprites.write_definition_document(yp, normalized)


def _serialize_record(record: sprites.SpriteSetRecord) -> dict[str, Any]:
    ss = record.sprite_set
    return {
        "scope": record.scope,
        "filename": record.filename,
        "has_image": record.has_image,
        "has_yaml": record.has_yaml,
        "image_url": f"/sprites/{record.scope}/{record.image_path.name}" if record.image_path else "",
        "yaml_error": record.load_error or "",
        "label": ss.label if ss else "",
        "description": ss.description if ss else "",
        "sprite_count": len(ss.sprites) if ss else 0,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@blueprint.route("/sprite-editor")
def sprite_editor_page():
    if g := _guard():
        return g
    return send_from_directory(str(_STATIC_FOLDER), "sprite-editor.html")


@blueprint.route("/api/sprite-editor/reindex", methods=["POST"])
def reindex():
    if g := _guard():
        return g
    repo = _get_repo(force_reindex=True)
    return jsonify({"ok": True, "sets": len(repo.list_sets())})


@blueprint.route("/api/sprite-editor/sets")
def list_sets():
    if g := _guard():
        return g
    repo = _get_repo(force_reindex=True)
    return jsonify({"ok": True, "sets": [_serialize_record(r) for r in repo.list_sets()]})


@blueprint.route("/api/sprite-editor/sets/<scope>/<filename>")
def get_set(scope, filename):
    if g := _guard():
        return g
    try:
        scope, filename = _parse_set(scope, filename)
    except ValueError as e:
        return _err(str(e), 400)
    repo = _get_repo(force_reindex=True)
    record = repo.get(scope, filename)
    if record is None or not record.has_image:
        return _err("sprite set not found", 404)
    definition = sprites.to_definition_dict(record.sprite_set) if record.sprite_set else None
    return jsonify({"ok": True, "set": _serialize_record(record), "definition": definition})


@blueprint.route("/api/sprite-editor/sets/<scope>/<filename>/create-definition", methods=["POST"])
def create_definition(scope, filename):
    if g := _guard():
        return g
    try:
        scope, filename = _parse_set(scope, filename)
        ip = _image_path(scope, filename)
        yp = _yaml_path(scope, filename)
        if yp.exists():
            return _err("sprite definition already exists", 409)
        body = request.json or {}
        sprite_id = str(body.get("sprite_id", "sprite_1")).strip() or "sprite_1"
        doc = {
            "label": str(body.get("label", "") or ""),
            "description": str(body.get("description", "") or ""),
            "frame_width": int(body.get("frame_width", 32)),
            "frame_height": int(body.get("frame_height", 32)),
            "background_color": body.get("background_color"),
            "sprites": {sprite_id: {"default_frame": str(body.get("default_frame", "0x0")), "anims": {}}},
        }
        _persist(yp, ip, doc)
        _get_repo(force_reindex=True)
        return jsonify({"ok": True}), 201
    except sprites.SpriteValidationError as e:
        return _verr(e)
    except ValueError as e:
        return _err(str(e), 400)


@blueprint.route("/api/sprite-editor/sets/<scope>/<filename>", methods=["PUT"])
def update_set(scope, filename):
    if g := _guard():
        return g
    try:
        scope, filename = _parse_set(scope, filename)
        body = request.json or {}
        definition = body.get("definition")
        if not isinstance(definition, dict):
            raise ValueError("definition must be an object")
        _, yp, ip = _load_doc(scope, filename)
        _persist(yp, ip, definition)
        _get_repo(force_reindex=True)
        return jsonify({"ok": True})
    except sprites.SpriteValidationError as e:
        return _verr(e)
    except ValueError as e:
        return _err(str(e), 400)


@blueprint.route("/api/sprite-editor/sets/<scope>/<filename>/sprites", methods=["POST"])
def create_sprite(scope, filename):
    if g := _guard():
        return g
    try:
        scope, filename = _parse_set(scope, filename)
        body = request.json or {}
        sprite_id = str(body.get("sprite_id", "")).strip()
        if not sprite_id:
            raise ValueError("sprite_id is required")
        doc, yp, ip = _load_doc(scope, filename)
        sprites_doc = dict(doc.get("sprites", {}) or {})
        if sprite_id in sprites_doc:
            return _err("sprite already exists", 409)
        sprites_doc[sprite_id] = {"default_frame": str(body.get("default_frame", "0x0")), "anims": {}}
        doc["sprites"] = sprites_doc
        _persist(yp, ip, doc)
        _get_repo(force_reindex=True)
        return jsonify({"ok": True}), 201
    except sprites.SpriteValidationError as e:
        return _verr(e)
    except ValueError as e:
        return _err(str(e), 400)


@blueprint.route("/api/sprite-editor/sets/<scope>/<filename>/sprites/<sprite_id>", methods=["DELETE"])
def delete_sprite(scope, filename, sprite_id):
    if g := _guard():
        return g
    try:
        scope, filename = _parse_set(scope, filename)
        doc, yp, ip = _load_doc(scope, filename)
        sprites_doc = dict(doc.get("sprites", {}) or {})
        if sprite_id not in sprites_doc:
            return _err("sprite not found", 404)
        if len(sprites_doc) <= 1:
            return _err("sprite set must contain at least one sprite", 400)
        del sprites_doc[sprite_id]
        doc["sprites"] = sprites_doc
        _persist(yp, ip, doc)
        _get_repo(force_reindex=True)
        return jsonify({"ok": True})
    except sprites.SpriteValidationError as e:
        return _verr(e)
    except ValueError as e:
        return _err(str(e), 400)


@blueprint.route("/api/sprite-editor/sets/<scope>/<filename>/sprites/<sprite_id>/anims", methods=["POST"])
def create_anim(scope, filename, sprite_id):
    if g := _guard():
        return g
    try:
        scope, filename = _parse_set(scope, filename)
        body = request.json or {}
        anim_id = str(body.get("anim_id", "")).strip()
        if not anim_id:
            raise ValueError("anim_id is required")
        doc, yp, ip = _load_doc(scope, filename)
        sprites_doc = dict(doc.get("sprites", {}) or {})
        sprite_doc = dict(sprites_doc.get(sprite_id) or {})
        if not sprite_doc:
            return _err("sprite not found", 404)
        anims_doc = dict(sprite_doc.get("anims", {}) or {})
        if anim_id in anims_doc:
            return _err("animation already exists", 409)
        anims_doc[anim_id] = {
            "speed": body.get("speed", 0.5),
            "type": body.get("type", "loop"),
            "frames": list(body.get("frames", ["0x0"])),
        }
        sprite_doc["anims"] = anims_doc
        sprites_doc[sprite_id] = sprite_doc
        doc["sprites"] = sprites_doc
        _persist(yp, ip, doc)
        _get_repo(force_reindex=True)
        return jsonify({"ok": True}), 201
    except sprites.SpriteValidationError as e:
        return _verr(e)
    except ValueError as e:
        return _err(str(e), 400)


@blueprint.route("/api/sprite-editor/sets/<scope>/<filename>/sprites/<sprite_id>/anims/<anim_id>", methods=["PUT"])
def update_anim(scope, filename, sprite_id, anim_id):
    if g := _guard():
        return g
    try:
        scope, filename = _parse_set(scope, filename)
        body = request.json or {}
        doc, yp, ip = _load_doc(scope, filename)
        sprites_doc = dict(doc.get("sprites", {}) or {})
        sprite_doc = dict(sprites_doc.get(sprite_id) or {})
        if not sprite_doc:
            return _err("sprite not found", 404)
        anims_doc = dict(sprite_doc.get("anims", {}) or {})
        if anim_id not in anims_doc:
            return _err("animation not found", 404)
        prev = anims_doc[anim_id]
        anims_doc[anim_id] = {
            "speed": body.get("speed", prev.get("speed", 0.5)),
            "type": body.get("type", prev.get("type", "loop")),
            "frames": body.get("frames", prev.get("frames", ["0x0"])),
        }
        sprite_doc["anims"] = anims_doc
        sprites_doc[sprite_id] = sprite_doc
        doc["sprites"] = sprites_doc
        _persist(yp, ip, doc)
        _get_repo(force_reindex=True)
        return jsonify({"ok": True})
    except sprites.SpriteValidationError as e:
        return _verr(e)
    except ValueError as e:
        return _err(str(e), 400)


@blueprint.route("/api/sprite-editor/sets/<scope>/<filename>/sprites/<sprite_id>/anims/<anim_id>", methods=["DELETE"])
def delete_anim(scope, filename, sprite_id, anim_id):
    if g := _guard():
        return g
    try:
        scope, filename = _parse_set(scope, filename)
        doc, yp, ip = _load_doc(scope, filename)
        sprites_doc = dict(doc.get("sprites", {}) or {})
        sprite_doc = dict(sprites_doc.get(sprite_id) or {})
        if not sprite_doc:
            return _err("sprite not found", 404)
        anims_doc = dict(sprite_doc.get("anims", {}) or {})
        if anim_id not in anims_doc:
            return _err("animation not found", 404)
        del anims_doc[anim_id]
        sprite_doc["anims"] = anims_doc
        sprites_doc[sprite_id] = sprite_doc
        doc["sprites"] = sprites_doc
        _persist(yp, ip, doc)
        _get_repo(force_reindex=True)
        return jsonify({"ok": True})
    except sprites.SpriteValidationError as e:
        return _verr(e)
    except ValueError as e:
        return _err(str(e), 400)
