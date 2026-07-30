"""
Action DSL for the tinyrooms Selenium client test framework.

Actions are plain dataclasses describing steps to perform in the browser.
Pass a list of Action instances to ``ClientRunner.run()`` or
``ClientRunner.capture_screenshots()`` to execute them.

Usage example::

    from tests.client.actions import Login, Register, SendMessage, Screenshot, Wait

    actions = [
        Register(username="testuser", password="testpass"),
        Login(username="testuser", password="testpass"),
        Wait(seconds=1.0),
        Screenshot(name="after_login"),
        SendMessage(text="Hello world"),
        Wait(seconds=0.5),
        Screenshot(name="after_message"),
    ]
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Action types
# ---------------------------------------------------------------------------


@dataclass
class Login:
    """Fill in the login form with *username* / *password* and click Login.

    Waits until the main page becomes visible or a login-failure message appears.
    """
    username: str
    password: str


@dataclass
class Register:
    """Fill in the registration form and click Register (local).

    Waits until the status text changes (success or error).
    """
    username: str
    password: str


@dataclass
class Logout:
    """Click the logout button and wait for the login page to reappear."""


@dataclass
class SendMessage:
    """Type *text* into the chat input box and click Send."""
    text: str


@dataclass
class Click:
    """Click the first DOM element matching the CSS *selector*."""
    selector: str


@dataclass
class WaitForElement:
    """Block until a DOM element matching *selector* is visible.

    Raises ``TimeoutException`` if the element does not appear within
    *timeout* seconds.
    """
    selector: str
    timeout: float = 10.0


@dataclass
class WaitForElementAbsent:
    """Block until a DOM element matching *selector* is invisible or removed.

    Raises ``TimeoutException`` if the element is still visible after
    *timeout* seconds.
    """
    selector: str
    timeout: float = 10.0


@dataclass
class Wait:
    """Pause execution for *seconds* seconds (wall-clock sleep)."""
    seconds: float = 0.5


@dataclass
class SetWindowSize:
    """Resize the browser viewport to *width* × *height* pixels."""
    width: int = 1280
    height: int = 800


@dataclass
class Screenshot:
    """
    Capture the current browser window at this point in the action list.

    *name* identifies the screenshot within the test.  When the test suite
    runs normally the screenshot is compared against a saved reference image.
    When the suite is run with ``--rebase-screenshots`` the screenshot is
    written as the new reference instead.

    Screenshots are stored under::

        tests/client/screenshots/<test_name>/<name>.png

    A test failure is raised when the root-mean-square pixel difference
    between the captured image and the reference exceeds the configured
    threshold (default 5 %).
    """
    name: str


@dataclass
class ExecuteScript:
    """Execute arbitrary JavaScript *script* in the browser context.

    The script is passed directly to ``driver.execute_script()``.  Use
    ``return`` inside the script to capture a return value (available via
    ``ClientRunner.last_script_result`` after the action executes).
    """
    script: str
    args: list = field(default_factory=list)


# Convenience type alias for type hints
Action = (
    Login
    | Register
    | Logout
    | SendMessage
    | Click
    | WaitForElement
    | WaitForElementAbsent
    | Wait
    | SetWindowSize
    | Screenshot
    | ExecuteScript
)
