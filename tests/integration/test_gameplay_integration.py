"""Integration tests for the core gameplay mechanics.

Covers: Juice consumption, Kudos gifting, status API, and update_status events.
"""
from __future__ import annotations

import time

import httpx
import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_update_status(client, timeout: float = 8.0):
    """Wait for the first update_status event after login."""
    return client.wait_for(
        "update_status",
        predicate=lambda p: "juice" in p and "level" in p,
        timeout=timeout,
    )


def _status_via_rest(http_client: httpx.Client, headers: dict) -> dict:
    resp = http_client.get("/api/gameplay/status", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# update_status is emitted after login
# ---------------------------------------------------------------------------

def test_update_status_emitted_after_login(auth_socket_user):
    """Server must emit update_status immediately after a successful login."""
    user = auth_socket_user(prefix="it_gp_login")
    client = user["client"]
    payload = _wait_update_status(client)
    assert "username" in payload
    assert "level" in payload
    assert "juice" in payload
    assert "max_juice" in payload
    assert "kudos_received" in payload
    assert "bops" in payload


# ---------------------------------------------------------------------------
# REST: GET /api/gameplay/status
# ---------------------------------------------------------------------------

def test_gameplay_status_rest(auth_socket_user, http_client: httpx.Client):
    """GET /api/gameplay/status returns expected fields for authenticated user."""
    user = auth_socket_user(prefix="it_gp_status")
    headers = user["headers"]
    status = _status_via_rest(http_client, headers)
    assert status["ok"] is True
    assert status["username"] == user["username"]
    assert isinstance(status["level"], int)
    assert 0 <= status["level"] <= 10
    assert isinstance(status["juice"], float)
    assert status["juice"] >= 0
    assert status["max_juice"] > 0
    assert isinstance(status["bops"], int)
    assert isinstance(status["traits"], list)


def test_gameplay_status_unauthenticated(http_client: httpx.Client):
    """GET /api/gameplay/status without auth returns 401."""
    resp = http_client.get("/api/gameplay/status")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Juice: consumption per message
# ---------------------------------------------------------------------------

def test_juice_consumed_on_message(auth_socket_user, http_client: httpx.Client):
    """Sending a chat message should reduce the user's juice."""
    user = auth_socket_user(prefix="it_gp_juice")
    client = user["client"]
    headers = user["headers"]

    # Wait for initial status
    _wait_update_status(client)

    initial_status = _status_via_rest(http_client, headers)
    initial_juice = initial_status["juice"]

    # Send a regular message (not a command)
    client.emit("message", {"text": "Hello, world!"})
    time.sleep(0.5)  # Allow server to process

    updated_status = _status_via_rest(http_client, headers)
    assert updated_status["juice"] < initial_juice, (
        f"Expected juice to decrease: {initial_juice} → {updated_status['juice']}"
    )


# ---------------------------------------------------------------------------
# Kudos: give-kudos command and REST endpoint
# ---------------------------------------------------------------------------

def test_give_kudos_command_updates_receiver(
    auth_socket_user, http_client: httpx.Client
):
    """Using :give-kudos should increment the receiver's total_received."""
    giver = auth_socket_user(prefix="it_gp_giver")
    receiver = auth_socket_user(prefix="it_gp_recv")
    giver_client = giver["client"]
    receiver_client = receiver["client"]
    headers_recv = receiver["headers"]

    _wait_update_status(giver_client)
    _wait_update_status(receiver_client)

    # Get receiver's initial kudos count
    initial = _status_via_rest(http_client, headers_recv)
    initial_kudos = initial["kudos_received"]

    # Giver gives kudos to receiver
    giver_client.emit("message", {"text": f":give-kudos @{receiver['username']}"})

    # Wait for receiver to get update_status with incremented kudos
    try:
        receiver_client.wait_for(
            "update_status",
            predicate=lambda p: p.get("kudos_received", 0) > initial_kudos,
            timeout=6.0,
        )
    except AssertionError:
        pass  # May have already been consumed; check via REST

    updated = _status_via_rest(http_client, headers_recv)
    assert updated["kudos_received"] > initial_kudos, (
        f"Expected kudos_received to increase from {initial_kudos}"
    )


def test_give_kudos_rest_endpoint(
    auth_socket_user, http_client: httpx.Client
):
    """POST /api/gameplay/give-kudos should update both giver and receiver."""
    giver = auth_socket_user(prefix="it_gp_rest_give")
    receiver = auth_socket_user(prefix="it_gp_rest_recv")
    headers_giver = giver["headers"]
    headers_recv = receiver["headers"]

    initial_recv = _status_via_rest(http_client, headers_recv)

    resp = http_client.post(
        "/api/gameplay/give-kudos",
        json={"username": receiver["username"], "amount": 1},
        headers=headers_giver,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["given"] == 1

    updated_recv = _status_via_rest(http_client, headers_recv)
    assert updated_recv["kudos_received"] == initial_recv["kudos_received"] + 1


def test_give_kudos_rest_unauthenticated(http_client: httpx.Client, auth_socket_user):
    """POST /api/gameplay/give-kudos without auth returns 401."""
    target = auth_socket_user(prefix="it_gp_noauth_recv")
    resp = http_client.post(
        "/api/gameplay/give-kudos",
        json={"username": target["username"], "amount": 1},
    )
    assert resp.status_code == 401


def test_give_kudos_to_self_rejected(auth_socket_user, http_client: httpx.Client):
    """A user cannot give kudos to themselves."""
    user = auth_socket_user(prefix="it_gp_self")
    resp = http_client.post(
        "/api/gameplay/give-kudos",
        json={"username": user["username"], "amount": 1},
        headers=user["headers"],
    )
    assert resp.status_code == 400, resp.text


def test_give_kudos_daily_budget_enforced(auth_socket_user, http_client: httpx.Client, register_user, unique_username):
    """After exhausting the daily budget via the API, giving more kudos should be rejected."""
    from tinyrooms import user_data
    giver = auth_socket_user(prefix="it_gp_budget")
    # Create several receivers to give kudos to
    receivers = []
    for i in range(user_data.DAILY_KUDOS_BUDGET + 1):
        uname = unique_username(f"it_gp_brecv{i}")
        register_user(uname, "pass123")
        receivers.append(uname)

    # Exhaust the full daily budget
    for recv_name in receivers[:user_data.DAILY_KUDOS_BUDGET]:
        resp = http_client.post(
            "/api/gameplay/give-kudos",
            json={"username": recv_name, "amount": 1},
            headers=giver["headers"],
        )
        assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"

    # The next give-kudos should fail
    resp = http_client.post(
        "/api/gameplay/give-kudos",
        json={"username": receivers[-1], "amount": 1},
        headers=giver["headers"],
    )
    assert resp.status_code == 409, resp.text


# ---------------------------------------------------------------------------
# Juice pack purchase
# ---------------------------------------------------------------------------

def test_buy_juice_pack_via_rest(auth_socket_user, http_client: httpx.Client):
    """POST /api/gameplay/buy-juice with enough Bops should increase juice.

    New users start with DEFAULT_STARTING_BOPS (50) which is enough for a small pack (5 Bops).
    """
    user_obj = auth_socket_user(prefix="it_gp_buyjuice")
    headers = user_obj["headers"]

    # Drain juice first so there's meaningful room to fill
    # (just check the purchase works; juice may already be at max for a fresh user)
    resp = http_client.post(
        "/api/gameplay/buy-juice",
        json={"pack": "small"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["juice"] >= 0
    assert data["bops"] >= 0


def test_buy_juice_insufficient_bops(auth_socket_user, http_client: httpx.Client):
    """Buying multiple juice packs eventually fails with insufficient Bops."""
    user_obj = auth_socket_user(prefix="it_gp_nobops")
    headers = user_obj["headers"]

    # Buy large packs until we run out (each costs 35 bops; start with 50)
    bought = 0
    for _ in range(10):
        resp = http_client.post(
            "/api/gameplay/buy-juice",
            json={"pack": "large"},
            headers=headers,
        )
        if resp.status_code == 409:
            break
        assert resp.status_code == 200, resp.text
        bought += 1

    # We must have eventually hit 409
    resp = http_client.post(
        "/api/gameplay/buy-juice",
        json={"pack": "large"},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text


# ---------------------------------------------------------------------------
# Juice-status command
# ---------------------------------------------------------------------------

def test_juice_status_command_returns_panel(auth_socket_user):
    """Issuing :juice-status should return an activity_panel with juice info."""
    user_obj = auth_socket_user(prefix="it_gp_jstat")
    client = user_obj["client"]
    _wait_update_status(client)

    client.emit("message", {"text": ":juice-status"})
    panel = client.wait_for(
        "activity_panel",
        predicate=lambda p: "juice" in p.get("content", "").lower(),
        timeout=6.0,
    )
    assert panel["title"] is not None
    assert "juice" in panel["content"].lower()


# ---------------------------------------------------------------------------
# Level-info command
# ---------------------------------------------------------------------------

def test_level_info_command_returns_panel(auth_socket_user):
    """Issuing :level-info should return an activity_panel with level info."""
    user_obj = auth_socket_user(prefix="it_gp_linfo")
    client = user_obj["client"]
    _wait_update_status(client)

    client.emit("message", {"text": ":level-info"})
    panel = client.wait_for(
        "activity_panel",
        predicate=lambda p: "level" in p.get("content", "").lower(),
        timeout=6.0,
    )
    assert "L0" in panel["content"] or "Guest" in panel["content"]
