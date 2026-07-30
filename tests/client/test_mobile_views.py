"""
Temporary test to capture mobile viewport screenshots for the JRPG theme review.
Screenshots at 390x844 (iPhone 14) and 768x1024 (iPad).
"""
from __future__ import annotations
import pytest
from tests.client.actions import (
    Login, Screenshot, SetWindowSize, Wait, WaitForElement,
)

pytestmark = pytest.mark.client_ui


def _login_room(runner, username: str, password: str) -> None:
    runner.run([
        Login(username=username, password=password),
        WaitForElement(selector="#mainPage"),
        WaitForElement(selector="#roomTitleOverlay", timeout=15.0),
        Wait(seconds=1.5),
    ])


def test_mobile_phone_view(client_runner, unique_username, register_user):
    """Capture the main room at phone viewport (390x844)."""
    username = unique_username("ui_mob_phone")
    password = "test_password_123"
    register_user(username, password)
    _login_room(client_runner, username, password)
    client_runner.run([
        SetWindowSize(width=390, height=844),
        Wait(seconds=0.8),
        Screenshot(name="mobile_phone_room"),
    ])


def test_mobile_tablet_view(client_runner, unique_username, register_user):
    """Capture the main room at tablet viewport (768x1024)."""
    username = unique_username("ui_mob_tablet")
    password = "test_password_123"
    register_user(username, password)
    _login_room(client_runner, username, password)
    client_runner.run([
        SetWindowSize(width=768, height=1024),
        Wait(seconds=0.8),
        Screenshot(name="mobile_tablet_room"),
    ])


def test_mobile_login_view(client_runner):
    """Capture the login page at phone viewport."""
    client_runner.run([
        SetWindowSize(width=390, height=844),
        Wait(seconds=0.4),
        Screenshot(name="mobile_login_page"),
    ])
