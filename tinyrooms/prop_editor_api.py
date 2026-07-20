"""Prop-editor REST API — enabled only when --feature prop-editor is active."""

from pathlib import Path
from typing import Any

import yaml
from flask import Blueprint, jsonify, request, send_from_directory

from . import prop_sets

blueprint = Blueprint("prop_editor", __name__)

_IMAGE_EXTS = (".png", ".gif", ".webp")
_YAML_EXTS = (".yaml", ".yml")
_STATIC_FOLDER = Path(__file__).parent.parent / "app"


# ---------------------------------------------------------------------------
# Thin wrappers that lazily reach into server.py to avoid circular imports.
# ---------------------------------------------------------------------------

def _get_repo(force_reindex: bool = False) -> prop_sets.PropRepository:
    from . import server  # noqa: PLC0415
    return server._prop_repo(force_reindex)


def _feature_enabled() -> bool:
    from . import server  # noqa: PLC0415
    return server.feature_enabled("prop-editor")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _err(msg: str, code: int):
    return jsonify({"ok": False, "error": msg}), code


def _verr(exc: prop_sets.PropValidationError):
    return jsonify({"ok": False, "error": str(exc), "details": exc.errors}), 400


def _guard():
    """Return a 404 response when the feature is disabled, else None."""
    if not _feature_enabled():
        return _err("prop-editor feature disabled", 404)
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
    root = repo.server_root_path if scope == "server" else repo.world_props_path
    return root / f"{filename}.yaml"


def _image_path(scope: str, filename: str) -> Path:
    repo = _get_repo()
    root = repo.server_root_path if scope == "server" else repo.world_props_path
    for ext in _IMAGE_EXTS:
        p = root / f"{filename}{ext}"
        if p.exists():
            return p
    raise ValueError("prop image file not found")


def _load_doc(scope: str, filename: str) -> tuple[dict[str, Any], Path, Path]:
    """Return (raw_yaml_doc, yaml_path, image_path) for a set that already has a definition."""
    yp = _yaml_path(scope, filename)
    ip = _image_path(scope, filename)
    if not yp.exists():
        raise ValueError("prop definition does not exist")
    doc = yaml.safe_load(yp.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        raise ValueError("prop definition yaml must be a mapping")
    return doc, yp, ip


def _persist(yp: Path, ip: Path, doc: dict[str, Any]) -> None:
    normalized = prop_sets.validate_definition_document(doc, image_path=ip)
    prop_sets.write_definition_document(yp, normalized)


def _serialize_record(record: prop_sets.PropSetRecord) -> dict[str, Any]:
    ps = record.prop_set
    return {
        "scope": record.scope,
        "filename": record.filename,
        "has_image": record.has_image,
        "has_yaml": record.has_yaml,
        "image_url": f"/props/{record.scope}/{record.image_path.name}" if record.image_path else "",
        "yaml_error": record.load_error or "",
        "label": ps.label if ps else "",
        "description": ps.description if ps else "",
        "prop_count": len(ps.props) if ps else 0,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@blueprint.route("/prop-editor")
def prop_editor_page():
    if g := _guard():
        return g
    return send_from_directory(str(_STATIC_FOLDER), "prop-editor.html")


@blueprint.route("/api/prop-editor/reindex", methods=["POST"])
def reindex():
    if g := _guard():
        return g
    repo = _get_repo(force_reindex=True)
    return jsonify({"ok": True, "sets": len(repo.list_sets())})


@blueprint.route("/api/prop-editor/sets")
def list_sets():
    if g := _guard():
        return g
    repo = _get_repo(force_reindex=True)
    return jsonify({"ok": True, "sets": [_serialize_record(r) for r in repo.list_sets()]})


@blueprint.route("/api/prop-editor/sets/<scope>/<filename>")
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
        return _err("prop set not found", 404)
    definition = prop_sets.to_definition_dict(record.prop_set) if record.prop_set else None
    return jsonify({"ok": True, "set": _serialize_record(record), "definition": definition})


@blueprint.route("/api/prop-editor/sets/<scope>/<filename>/create-definition", methods=["POST"])
def create_definition(scope, filename):
    if g := _guard():
        return g
    try:
        scope, filename = _parse_set(scope, filename)
        ip = _image_path(scope, filename)
        yp = _yaml_path(scope, filename)
        if yp.exists():
            return _err("prop definition already exists", 409)
        body = request.json or {}
        prop_id = str(body.get("prop_id", "prop_1")).strip() or "prop_1"
        doc = {
            "label": str(body.get("label", "") or ""),
            "description": str(body.get("description", "") or ""),
            "image": ip.name,
            "props": {
                prop_id: {
                    "width": int(body.get("width", 32)),
                    "height": int(body.get("height", 32)),
                    "frames": [[0, 0]],
                }
            },
        }
        _persist(yp, ip, doc)
        _get_repo(force_reindex=True)
        return jsonify({"ok": True}), 201
    except prop_sets.PropValidationError as e:
        return _verr(e)
    except ValueError as e:
        return _err(str(e), 400)


@blueprint.route("/api/prop-editor/sets/<scope>/<filename>", methods=["PUT"])
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
    except prop_sets.PropValidationError as e:
        return _verr(e)
    except ValueError as e:
        return _err(str(e), 400)


@blueprint.route("/api/prop-editor/sets/<scope>/<filename>/props", methods=["POST"])
def create_prop(scope, filename):
    if g := _guard():
        return g
    try:
        scope, filename = _parse_set(scope, filename)
        body = request.json or {}
        prop_id = str(body.get("prop_id", "")).strip()
        if not prop_id:
            raise ValueError("prop_id is required")
        doc, yp, ip = _load_doc(scope, filename)
        props_doc = dict(doc.get("props", {}) or {})
        if prop_id in props_doc:
            return _err("prop already exists", 409)
        props_doc[prop_id] = {
            "width": int(body.get("width", 32)),
            "height": int(body.get("height", 32)),
            "frames": list(body.get("frames", [[0, 0]])),
        }
        if body.get("anim_speed") is not None:
            props_doc[prop_id]["anim_speed"] = float(body["anim_speed"])
        doc["props"] = props_doc
        _persist(yp, ip, doc)
        _get_repo(force_reindex=True)
        return jsonify({"ok": True}), 201
    except prop_sets.PropValidationError as e:
        return _verr(e)
    except ValueError as e:
        return _err(str(e), 400)


@blueprint.route("/api/prop-editor/sets/<scope>/<filename>/props/<prop_id>", methods=["DELETE"])
def delete_prop(scope, filename, prop_id):
    if g := _guard():
        return g
    try:
        scope, filename = _parse_set(scope, filename)
        doc, yp, ip = _load_doc(scope, filename)
        props_doc = dict(doc.get("props", {}) or {})
        if prop_id not in props_doc:
            return _err("prop not found", 404)
        if len(props_doc) <= 1:
            return _err("prop set must contain at least one prop", 400)
        del props_doc[prop_id]
        doc["props"] = props_doc
        _persist(yp, ip, doc)
        _get_repo(force_reindex=True)
        return jsonify({"ok": True})
    except prop_sets.PropValidationError as e:
        return _verr(e)
    except ValueError as e:
        return _err(str(e), 400)
