"""
ClientRunner: executes Action sequences against a live tinyrooms browser session.

Typical usage inside a pytest test::

    def test_login_screenshot(client_runner, unique_username, register_user):
        username = unique_username("ui_login")
        register_user(username, "password123")

        client_runner.run([
            Login(username=username, password="password123"),
            WaitForElement(selector="#mainPage"),
            Wait(seconds=0.5),
            Screenshot(name="logged_in"),
        ])

Agent capture usage (no reference comparison)::

    screenshots = client_runner.capture_screenshots([
        Login(username="agent_user", password="pass"),
        Wait(seconds=1.0),
        Screenshot(name="home"),
    ])
    png_bytes = screenshots["home"]  # raw PNG bytes ready for LLM vision input
"""
from __future__ import annotations

import io
import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.client.actions import (
    Action,
    Click,
    ExecuteScript,
    Login,
    Logout,
    Register,
    Screenshot,
    SendMessage,
    SetWindowSize,
    Wait,
    WaitForElement,
    WaitForElementAbsent,
)

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver


# Root-mean-square pixel diff allowed before a screenshot comparison fails.
# Expressed as a fraction of full-scale (0–1).  5 % handles minor
# anti-aliasing / font-rendering differences across platforms.
DEFAULT_DIFF_THRESHOLD = 0.05


class ScreenshotMismatchError(AssertionError):
    """Raised when a captured screenshot differs too much from its reference."""


class ClientRunner:
    """
    Execute an Action list against a live tinyrooms client in a Selenium browser.

    Parameters
    ----------
    driver:
        An already-opened Selenium WebDriver instance.
    base_url:
        The HTTP origin of the running tinyrooms server
        (e.g. ``"http://127.0.0.1:5000"``).
    screenshots_dir:
        Root directory for reference and actual screenshots.
    rebase:
        When *True*, every :class:`~tests.client.actions.Screenshot` action
        writes (or overwrites) the reference image instead of comparing.
    test_name:
        Used as a sub-directory name under *screenshots_dir* so that
        screenshots from different tests don't collide.
    diff_threshold:
        Maximum allowed RMS pixel difference fraction (default 0.05 = 5 %).
    """

    def __init__(
        self,
        driver: "WebDriver",
        base_url: str,
        screenshots_dir: Path,
        rebase: bool,
        test_name: str,
        diff_threshold: float = DEFAULT_DIFF_THRESHOLD,
    ) -> None:
        self.driver = driver
        self.base_url = base_url
        self.screenshots_dir = screenshots_dir
        self.rebase = rebase
        self.test_name = test_name
        self.diff_threshold = diff_threshold
        self.last_script_result: object = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_client(self) -> None:
        """Navigate the browser to the tinyrooms client login page.

        Clears all cookies and localStorage for the server origin before
        loading the page so that a previous test's saved credentials do not
        trigger the auto-login handler.
        """
        target = f"{self.base_url}/"

        # Load the origin page so we can operate on its storage / cookies.
        # If we're already on the origin this is a no-op navigation.
        current_url = self.driver.current_url
        if not current_url.startswith(self.base_url):
            self.driver.get(target)

        # Clear all cookies (credentials are stored as cookies in tinyrooms).
        self.driver.delete_all_cookies()
        # Clear localStorage as well (chat messages, input state, etc.).
        try:
            self.driver.execute_script(
                "window.localStorage.clear(); window.sessionStorage.clear();"
            )
        except Exception:
            pass

        # Navigate with a clean slate — auto-login cannot fire without cookies.
        self.driver.get(target)
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "loginPage"))
        )
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "loginPage"))
        )

    def run(self, actions: list[Action]) -> None:
        """Execute *actions* sequentially, comparing screenshots to references."""
        for action in actions:
            self._execute(action, capture_only=False)

    def capture_screenshots(self, actions: list[Action]) -> dict[str, bytes]:
        """
        Execute *actions* and return every :class:`~tests.client.actions.Screenshot`
        as raw PNG bytes keyed by name.

        Unlike :meth:`run`, screenshots are **not** compared to references — this
        mode is intended for autonomous agents that need visual context of the UI.

        Example::

            shots = runner.capture_screenshots([
                Login("alice", "pass"),
                Wait(1.0),
                Screenshot("home"),
                SendMessage("Hello!"),
                Wait(0.5),
                Screenshot("after_chat"),
            ])
            # shots["home"] and shots["after_chat"] are PNG bytes
        """
        results: dict[str, bytes] = {}
        for action in actions:
            if isinstance(action, Screenshot):
                results[action.name] = self.driver.get_screenshot_as_png()
            else:
                self._execute(action, capture_only=True)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute(self, action: Action, *, capture_only: bool) -> None:
        if isinstance(action, Login):
            self._do_login(action)
        elif isinstance(action, Register):
            self._do_register(action)
        elif isinstance(action, Logout):
            self._do_logout()
        elif isinstance(action, SendMessage):
            self._do_send_message(action)
        elif isinstance(action, Click):
            self._do_click(action)
        elif isinstance(action, WaitForElement):
            self._do_wait_for_element(action)
        elif isinstance(action, WaitForElementAbsent):
            self._do_wait_for_element_absent(action)
        elif isinstance(action, Wait):
            time.sleep(action.seconds)
        elif isinstance(action, SetWindowSize):
            self.driver.set_window_size(action.width, action.height)
        elif isinstance(action, Screenshot):
            if not capture_only:
                self._do_screenshot(action)
        elif isinstance(action, ExecuteScript):
            self.last_script_result = self.driver.execute_script(
                action.script, *action.args
            )
        else:
            raise ValueError(f"Unknown action type: {type(action).__name__!r}")

    # --- concrete action implementations ---

    def _set_input_value(self, element, value: str) -> None:
        """Set an input value via JavaScript to bypass Chrome autofill protection."""
        self.driver.execute_script(
            "arguments[0].value = ''; arguments[0].dispatchEvent(new Event('input', {bubbles:true}));",
            element,
        )
        element.send_keys(value)

    def _do_login(self, action: Login) -> None:
        WebDriverWait(self.driver, 15).until(
            EC.element_to_be_clickable((By.ID, "username"))
        )
        self._set_input_value(self.driver.find_element(By.ID, "username"), action.username)
        self._set_input_value(self.driver.find_element(By.ID, "password"), action.password)
        self.driver.find_element(By.ID, "btnLogin").click()
        # Wait for main page or failure message
        WebDriverWait(self.driver, 15).until(
            lambda d: (
                d.find_element(By.ID, "mainPage").is_displayed()
                or "failed" in d.find_element(By.ID, "loginStatus").text.lower()
            )
        )

    def _do_register(self, action: Register) -> None:
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.ID, "username"))
        )
        self._set_input_value(self.driver.find_element(By.ID, "username"), action.username)
        self._set_input_value(self.driver.find_element(By.ID, "password"), action.password)
        self.driver.find_element(By.ID, "btnRegister").click()
        # Wait for status text to appear
        WebDriverWait(self.driver, 10).until(
            lambda d: d.find_element(By.ID, "loginStatus").text.strip() != ""
        )

    def _do_logout(self) -> None:
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.ID, "statusMenuToggle"))
        )
        self.driver.find_element(By.ID, "statusMenuToggle").click()
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.ID, "btnLogout"))
        )
        self.driver.find_element(By.ID, "btnLogout").click()
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "loginPage"))
        )

    def _do_send_message(self, action: SendMessage) -> None:
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "msgInput"))
        )
        msg_input = self.driver.find_element(By.ID, "msgInput")
        msg_input.clear()
        msg_input.send_keys(action.text)
        self.driver.find_element(By.ID, "sendBtn").click()

    def _do_click(self, action: Click) -> None:
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, action.selector))
        )
        element = self.driver.find_element(By.CSS_SELECTOR, action.selector)
        try:
            element.click()
        except Exception:
            # Fall back to JavaScript click for elements that are present but
            # not interactable via standard Selenium click (e.g. hidden parents).
            self.driver.execute_script("arguments[0].click();", element)

    def _do_wait_for_element(self, action: WaitForElement) -> None:
        WebDriverWait(self.driver, action.timeout).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, action.selector))
        )

    def _do_wait_for_element_absent(self, action: WaitForElementAbsent) -> None:
        WebDriverWait(self.driver, action.timeout).until(
            EC.invisibility_of_element_located((By.CSS_SELECTOR, action.selector))
        )

    # --- screenshot handling ---

    def _do_screenshot(self, action: Screenshot) -> None:
        """Capture screenshot and compare to reference (or save if rebasing)."""
        test_dir = self.screenshots_dir / self.test_name
        test_dir.mkdir(parents=True, exist_ok=True)

        ref_path = test_dir / f"{action.name}.png"
        actual_path = test_dir / f"{action.name}.actual.png"

        png_data = self.driver.get_screenshot_as_png()
        actual_image = Image.open(io.BytesIO(png_data)).convert("RGB")

        if self.rebase or not ref_path.exists():
            actual_image.save(ref_path, "PNG")
            # Remove stale actual if it exists
            if actual_path.exists():
                actual_path.unlink()
            return

        ref_image = Image.open(ref_path).convert("RGB")

        # Resize actual to match reference if viewport changed
        if actual_image.size != ref_image.size:
            actual_image = actual_image.resize(ref_image.size, Image.LANCZOS)

        actual_image.save(actual_path, "PNG")

        diff = _rms_diff(ref_image, actual_image)
        if diff > self.diff_threshold:
            raise ScreenshotMismatchError(
                f"Screenshot '{action.name}' in test '{self.test_name}' differs from "
                f"reference by {diff:.1%} (threshold {self.diff_threshold:.1%}).\n"
                f"  Reference : {ref_path}\n"
                f"  Actual    : {actual_path}\n"
                "Re-run with --rebase-screenshots to accept the new appearance."
            )
        # Clean up stale actual on pass
        if actual_path.exists():
            actual_path.unlink()


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _rms_diff(img_a: Image.Image, img_b: Image.Image) -> float:
    """Return the RMS pixel difference between two images, normalised to [0, 1]."""
    arr_a = np.asarray(img_a, dtype=np.float32)
    arr_b = np.asarray(img_b, dtype=np.float32)
    rms = float(np.sqrt(np.mean((arr_a - arr_b) ** 2)))
    return rms / 255.0
