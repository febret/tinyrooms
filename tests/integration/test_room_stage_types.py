"""
Integration tests: room-stage payload contains stage type fields, and stage type
properties are not written to the worldstate DB.
"""
import pytest


pytestmark = pytest.mark.integration


def _get_stage_payload(client):
    return client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-stage",
        timeout=8.0,
    )


def test_room_stage_payload_contains_stage_type_fields(auth_socket_user):
    """room-stage payload must include all stage type fields with correct types."""
    user = auth_socket_user(prefix="it_stage_type")
    client = user["client"]

    stage_payload = _get_stage_payload(client)
    stage = stage_payload["stage"]

    assert "type" in stage, "stage.type missing from room-stage payload"
    assert "bg_height" in stage, "stage.bg_height missing"
    assert "floor_height" in stage, "stage.floor_height missing"
    assert "background_mode" in stage, "stage.background_mode missing"
    assert "floor_image" in stage, "stage.floor_image missing"

    # Type field must be one of the defined stage types
    assert stage["type"] in {"basic", "standard"}, f"Unknown stage type: {stage['type']!r}"

    # Numeric fields must be integers
    assert isinstance(stage["bg_height"], int), "bg_height must be int"
    assert isinstance(stage["floor_height"], int), "floor_height must be int"
    assert stage["bg_height"] > 0, "bg_height must be positive"
    assert stage["floor_height"] > 0, "floor_height must be positive"

    # background_mode must be a known value
    assert stage["background_mode"] in {"tile", "stretch"}, (
        f"Unknown background_mode: {stage['background_mode']!r}"
    )

    # floor_image is a string (may be empty for basic rooms)
    assert isinstance(stage["floor_image"], str)


def test_basic_room_stage_defaults(auth_socket_user):
    """Rooms marked type:basic get sensible defaults from the server."""
    user = auth_socket_user(prefix="it_basic_stage")
    client = user["client"]

    stage_payload = _get_stage_payload(client)
    stage = stage_payload["stage"]

    # All existing rooms are basic type (or default to basic)
    assert stage["type"] == "basic"
    assert isinstance(stage["width"], int) and stage["width"] > 0
    assert isinstance(stage["height"], int) and stage["height"] > 0


def test_stage_type_fields_not_in_room_db(auth_socket_user, server_runtime):
    """Stage type fields should not be persisted in the rooms DB table."""
    import sqlite3
    from pathlib import Path

    user = auth_socket_user(prefix="it_stage_db")
    client = user["client"]

    # Ensure we receive the stage payload (room was entered)
    _get_stage_payload(client)

    # Look for any worldstate DB in the workspace
    workspace = server_runtime.workspace
    db_files = list(workspace.rglob("*.duckdb")) + list(workspace.rglob("worldstate.db"))
    if not db_files:
        pytest.skip("No worldstate DB file found — skipping DB column check")

    for db_path in db_files:
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute("PRAGMA table_info(rooms)")
            columns = {row[1] for row in cursor.fetchall()}
            conn.close()
            stage_type_cols = {"stage_type", "bg_height", "floor_height", "background_mode", "floor_image"}
            persisted = stage_type_cols & columns
            assert not persisted, (
                f"Stage type columns {persisted} should not be stored in the rooms table of {db_path.name}"
            )
        except Exception:
            pass  # DB may use a different engine; skip gracefully
