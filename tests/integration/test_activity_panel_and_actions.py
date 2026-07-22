import pytest


pytestmark = pytest.mark.integration


def test_equip_command_activity_panel_contract(auth_socket_user):
    user = auth_socket_user(prefix="it_activity")
    client = user["client"]

    client.emit("message", {"text": ":equip"})
    panel = client.wait_for("activity_panel", predicate=lambda p: p.get("mode") == "equip", timeout=8.0)

    assert panel["title"] == "Equip"
    assert "TODO" not in panel["content"]


def test_look_and_use_commands_cover_targets(auth_socket_user):
    user = auth_socket_user(prefix="it_actions_targets")
    client = user["client"]

    # Look with no target should show room description.
    client.emit("message", {"text": ":look"})
    room_panel = client.wait_for("activity_panel", predicate=lambda p: p.get("mode") == "look", timeout=8.0)
    assert room_panel["title"]
    assert room_panel["content"]

    # Look at peep target (plain @<id> form used by the client).
    client.emit("message", {"text": ":look @greeter_npc"})
    peep_panel = client.wait_for("activity_panel", predicate=lambda p: p.get("mode") == "look", timeout=8.0)
    assert "greeter" in peep_panel["title"].lower() or "greeter" in peep_panel["content"].lower()

    # Move to playroom and fetch one object + one prop target id.
    client.emit("message", {"text": ":go @way:to_gateway"})
    client.wait_for("update_view", predicate=lambda p: p.get("view") == "header" and p.get("room_id") == "playroom", timeout=8.0)
    room_stage = client.wait_for("update_view", predicate=lambda p: p.get("view") == "room-stage", timeout=8.0)
    assert room_stage.get("props")
    prop_id = room_stage["props"][0]["prop_instance_id"]

    room_object = client.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-object" and p.get("change") == "upsert" and p.get("entity", {}).get("entity_type") == "object",
        timeout=8.0,
    )
    object_id = room_object["entity"]["entity_id"]

    client.emit("message", {"text": f":look @obj:{object_id}"})
    object_panel = client.wait_for("activity_panel", predicate=lambda p: p.get("mode") == "look", timeout=8.0)
    assert "test statue" in object_panel["title"].lower() or "test statue" in object_panel["content"].lower()

    client.emit("message", {"text": f":look @prop:{prop_id}"})
    prop_panel = client.wait_for("activity_panel", predicate=lambda p: p.get("mode") == "look", timeout=8.0)
    assert prop_panel["title"]
    assert prop_panel["content"]

    # Use target should route through :use command implementation.
    client.emit("message", {"text": f":use @obj:{object_id}"})
    use_message = client.wait_for("message", predicate=lambda p: "You use @obj:" in (p.get("text") or ""), timeout=8.0)
    assert object_id in use_message["text"]


def test_look_and_use_commands_report_target_errors(auth_socket_user):
    user = auth_socket_user(prefix="it_actions_errors")
    client = user["client"]

    client.emit("message", {"text": ":use"})
    missing_target = client.wait_for("message", predicate=lambda p: "Use what?" in (p.get("text") or ""), timeout=8.0)
    assert "Use what?" in missing_target["text"]

    client.emit("message", {"text": ":look @obj:does-not-exist"})
    bad_target = client.wait_for("error", predicate=lambda p: "not found" in (p.get("error") or ""), timeout=8.0)
    assert "look:" in bad_target["error"]
