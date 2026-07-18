import pytest


pytestmark = pytest.mark.integration


def test_request_activity_panel_contract(auth_socket_user):
    user = auth_socket_user(prefix="it_activity")
    client = user["client"]

    client.emit("request_activity_panel", {"mode": "equip"})
    panel = client.wait_for("activity_panel", predicate=lambda p: p.get("mode") == "equip", timeout=8.0)

    assert panel["title"] == "Equip"
    assert "TODO" in panel["content"]
