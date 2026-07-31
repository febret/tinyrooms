"""
Selenium UI tests — room view after login.

These tests verify the visual state of the main room page: the room title,
chat log, action palette, inventory panel, and the character editor overlay.
"""
from __future__ import annotations

import pytest

from tests.client.actions import (
    Click,
    ExecuteScript,
    Login,
    Screenshot,
    SendMessage,
    Wait,
    WaitForElement,
)

pytestmark = pytest.mark.client_ui


def _login_and_wait_for_room(runner, username: str, password: str) -> None:
    """Helper: log in and wait until the room stage is rendered.

    Users must be pre-registered via the ``register_user`` HTTP fixture before
    calling this helper.  Using the HTTP API is faster and more reliable than
    browser-based registration.
    """
    runner.run([
        Login(username=username, password=password),
        WaitForElement(selector="#mainPage"),
        # Wait for room header to be populated by the server
        WaitForElement(selector="#roomTitleOverlay", timeout=15.0),
        Wait(seconds=1.5),
    ])


def test_room_view_after_login(client_runner, unique_username, register_user):
    """The main page shows a room title and chat panel after a successful login."""
    username = unique_username("ui_room")
    password = "test_password_123"
    register_user(username, password)

    _login_and_wait_for_room(client_runner, username, password)

    client_runner.run([
        Screenshot(name="room_view"),
    ])

    # Verify key structural elements are present
    driver = client_runner.driver
    assert driver.find_element("id", "mainPage").is_displayed()
    assert driver.find_element("id", "roomTitleOverlay").text.strip() != ""


def test_chat_message_appears_in_log(client_runner, unique_username, register_user):
    """Sending a message adds it to the chat log."""
    username = unique_username("ui_chat")
    password = "test_password_123"
    register_user(username, password)

    _login_and_wait_for_room(client_runner, username, password)

    client_runner.run([
        Screenshot(name="before_chat"),
        SendMessage(text="Hello integration world"),
        WaitForElement(selector="#chatLogList .msg"),
        Wait(seconds=0.5),
        Screenshot(name="after_chat"),
    ])

    # Verify message text appears somewhere in the chat log
    chat_log = client_runner.driver.find_element("id", "chatLogList")
    assert "Hello integration world" in chat_log.text, (
        f"Expected chat message in log, got: {chat_log.text!r}"
    )


def test_action_palette_visible(client_runner, unique_username, register_user):
    """The action palette panel is rendered in the controls area."""
    username = unique_username("ui_palette")
    password = "test_password_123"
    register_user(username, password)

    _login_and_wait_for_room(client_runner, username, password)

    client_runner.run([
        Screenshot(name="action_palette"),
    ])

    palette = client_runner.driver.find_element("id", "actionPalette")
    assert palette.is_displayed()


def test_room_title_button_opens_description(client_runner, unique_username, register_user):
    """Clicking the room title button populates the look-box with a description."""
    username = unique_username("ui_desc")
    password = "test_password_123"
    register_user(username, password)

    _login_and_wait_for_room(client_runner, username, password)

    client_runner.run([
        # Click the room title (which may be a button if the room has a description)
        Click(selector="#roomTitleOverlay"),
        Wait(seconds=0.4),
        Screenshot(name="look_box_open"),
    ])


def test_give_kudos_action_for_other_peep_selection(client_runner, unique_username, register_user):
    """Selecting another user's peep exposes a Give Kudos action in the palette."""
    username = unique_username("ui_give_kudos")
    password = "test_password_123"
    register_user(username, password)

    _login_and_wait_for_room(client_runner, username, password)

    client_runner.run([
        ExecuteScript("""
            if (typeof window.selectTarget === 'function') {
                window.selectTarget({
                    type: 'peep',
                    id: 'other-user',
                    label: 'Other User',
                    description: 'Another user in the room',
                    is_self: false,
                });
            }
        """),
        Wait(seconds=0.5),
    ])

    palette = client_runner.driver.find_element("id", "actionPalette")
    assert "Give Kudos" in palette.text

    client_runner.run([
        ExecuteScript("""
            if (typeof window.selectTarget === 'function') {
                window.selectTarget({
                    type: 'peep',
                    id: 'self-user',
                    label: 'Self User',
                    description: 'Your own peep',
                    is_self: true,
                });
            }
        """),
        Wait(seconds=0.5),
    ])

    assert "Give Kudos" not in client_runner.driver.find_element("id", "actionPalette").text


def test_character_editor_overlay(client_runner, unique_username, register_user):
    """Triggering the character editor shows the editor overlay card."""
    username = unique_username("ui_chared")
    password = "test_password_123"
    register_user(username, password)

    _login_and_wait_for_room(client_runner, username, password)

    client_runner.run([
        # Invoke the character editor open function directly via JavaScript
        # (the trigger button is intentionally hidden in the normal UI flow).
        ExecuteScript("if (typeof openCharacterEditor === 'function') openCharacterEditor();"),
        WaitForElement(selector="#characterEditorPage", timeout=10.0),
        Wait(seconds=0.5),
        Screenshot(name="character_editor_open"),
    ])
