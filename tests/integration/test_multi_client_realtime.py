import pytest


pytestmark = pytest.mark.integration


def _go_to_playroom(client):
    client.emit("message", {"text": ":go @way:to_gateway"})
    client.wait_for(
        "update_view",
        predicate=lambda payload: payload.get("view") == "header" and payload.get("room_id") == "playroom",
        timeout=8.0,
    )


def test_disconnect_removes_connected_user_and_broadcasts_removal(auth_socket_user, http_client):
    first = auth_socket_user(prefix="it_realtime_a")
    second = auth_socket_user(prefix="it_realtime_b")
    a = first["client"]
    b = second["client"]

    _go_to_playroom(a)
    _go_to_playroom(b)
    b.disconnect()

    remove_event = a.wait_for(
        "update_view",
        predicate=lambda p: p.get("view") == "room-object"
        and p.get("change") == "remove"
        and p.get("entity", {}).get("entity_type") == "peep"
        and p.get("entity", {}).get("entity_id") == second["username"],
        timeout=8.0,
    )
    assert remove_event["change"] == "remove"

    connected = http_client.get("/connected")
    assert connected.status_code == 200
    assert second["username"] not in connected.json()["connected"]


def test_logout_returns_ok(http_client):
    response = http_client.post("/logout")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
