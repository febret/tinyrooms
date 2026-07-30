"""
Pytest fixtures for Selenium-based tinyrooms client UI tests.

This conftest extends the server-level fixtures from ``tests/conftest.py``
(which provides a running tinyrooms server) with browser-level fixtures.

Fixtures provided
-----------------
rebase_screenshots : bool
    True when ``--rebase-screenshots`` is passed on the command line.
screenshots_dir : Path
    ``tests/client/screenshots/`` — root for reference and actual images.
browser : WebDriver
    Session-scoped Chrome WebDriver instance (headless by default).
client_runner : ClientRunner
    Function-scoped runner pre-navigated to the client login page.
    Depends on server_runtime from the parent conftest.

Environment variables
---------------------
TR_BROWSER_VISIBLE
    Set to ``1`` / ``true`` / ``yes`` to open a visible browser window
    (useful when debugging test failures locally).
TR_CHROMEDRIVER_PATH
    Optional path to a specific ``chromedriver`` binary.  When absent,
    ``webdriver-manager`` resolves the correct driver automatically.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService

from tests.client.runner import ClientRunner

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"


# ---------------------------------------------------------------------------
# CLI option
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--rebase-screenshots",
        action="store_true",
        default=False,
        help=(
            "Regenerate all reference screenshots instead of comparing them. "
            "Use this after intentional UI changes to accept the new appearance."
        ),
    )


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def rebase_screenshots(request: pytest.FixtureRequest) -> bool:
    """True when the test run was started with ``--rebase-screenshots``."""
    return bool(request.config.getoption("--rebase-screenshots", default=False))


@pytest.fixture(scope="session")
def screenshots_dir() -> Path:
    """Root directory for reference screenshots."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    return SCREENSHOTS_DIR


@pytest.fixture(scope="session")
def browser():
    """
    A single Chrome WebDriver instance shared across the entire client test session.

    The browser runs headless unless the ``TR_BROWSER_VISIBLE`` environment
    variable is set to a truthy value (``1``, ``true``, or ``yes``).
    """
    opts = ChromeOptions()
    visible = os.environ.get("TR_BROWSER_VISIBLE", "").lower() in ("1", "true", "yes")
    if not visible:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,800")
    # Suppress Chrome's "Chrome is being controlled by automated software" bar
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    driver_path = os.environ.get("TR_CHROMEDRIVER_PATH")
    if driver_path:
        service = ChromeService(executable_path=driver_path)
        driver = webdriver.Chrome(service=service, options=opts)
    else:
        # webdriver-manager resolves and caches the matching ChromeDriver binary
        try:
            from webdriver_manager.chrome import ChromeDriverManager

            service = ChromeService(executable_path=ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=opts)
        except Exception:
            # Fall back to relying on chromedriver being in PATH
            driver = webdriver.Chrome(options=opts)

    driver.set_window_size(1280, 800)
    yield driver
    driver.quit()


# ---------------------------------------------------------------------------
# Function-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client_runner(
    browser,
    server_runtime,
    rebase_screenshots: bool,
    screenshots_dir: Path,
    request: pytest.FixtureRequest,
) -> ClientRunner:
    """
    A :class:`~tests.client.runner.ClientRunner` pre-navigated to the client
    login page for the current test.

    The runner uses the ``server_runtime`` fixture (live tinyrooms server)
    and the session-wide ``browser`` WebDriver.  Screenshots are stored under
    ``tests/client/screenshots/<test_node_name>/``.

    Example::

        def test_login_ui(client_runner, unique_username, register_user):
            u = unique_username("ui")
            register_user(u, "pass")
            client_runner.run([
                Login(u, "pass"),
                Screenshot("logged_in"),
            ])
    """
    # Sanitise the test node name so it is safe as a directory name
    safe_name = request.node.name.replace("[", "_").replace("]", "").replace("/", "_")
    runner = ClientRunner(
        driver=browser,
        base_url=server_runtime.base_url,
        screenshots_dir=screenshots_dir,
        rebase=rebase_screenshots,
        test_name=safe_name,
    )
    runner.open_client()
    yield runner
