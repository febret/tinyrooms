"""
Selenium UI tests — login and logout flow.

Each test passes a sequence of :mod:`tests.client.actions` to
``client_runner.run()`` and uses :class:`~tests.client.actions.Screenshot`
checkpoints to verify the visual state of the client page.

On the first run (or with ``--rebase-screenshots``) the screenshot is written
as the reference.  Subsequent runs compare the actual render against the
reference and fail when the RMS pixel difference exceeds 5 %.
"""
from __future__ import annotations

import pytest

from tests.client.actions import (
    Login,
    Logout,
    Register,
    Screenshot,
    Wait,
    WaitForElement,
    WaitForElementAbsent,
)

pytestmark = pytest.mark.client_ui


def test_login_page_initial_state(client_runner):
    """The login page is visible before any interaction."""
    client_runner.run([
        Wait(seconds=0.3),
        Screenshot(name="login_page_initial"),
    ])


def test_register_and_login(client_runner, unique_username):
    """Registering then logging in transitions to the main (room) page."""
    username = unique_username("ui_login")
    password = "test_password_123"

    client_runner.run([
        # Register via the in-page button
        Register(username=username, password=password),
        # Status text appears confirming registration
        WaitForElement(selector="#loginStatus"),
        Wait(seconds=0.3),
        Screenshot(name="after_register"),
        # Now log in
        Login(username=username, password=password),
        WaitForElement(selector="#mainPage"),
        Wait(seconds=1.0),
        Screenshot(name="after_login"),
    ])


def test_login_failure_shows_error(client_runner, unique_username):
    """Logging in with wrong credentials shows a failure message."""
    username = unique_username("ui_badusr")

    client_runner.run([
        # Attempt login with no such user
        Login(username=username, password="wrong_password"),
        WaitForElement(selector="#loginStatus"),
        Wait(seconds=0.3),
        Screenshot(name="login_failed"),
    ])

    # Verify the failure text is present in the DOM
    status_el = client_runner.driver.find_element("id", "loginStatus")
    assert "failed" in status_el.text.lower(), (
        f"Expected 'failed' in loginStatus text, got: {status_el.text!r}"
    )


def test_logout_returns_to_login_page(client_runner, unique_username, register_user):
    """Clicking logout hides the main page and shows the login page again."""
    username = unique_username("ui_logout")
    password = "test_password_123"
    register_user(username, password)

    client_runner.run([
        Login(username=username, password=password),
        WaitForElement(selector="#mainPage"),
        Wait(seconds=0.8),
        Screenshot(name="before_logout"),
        Logout(),
        WaitForElement(selector="#loginPage"),
        Wait(seconds=0.3),
        Screenshot(name="after_logout"),
    ])
