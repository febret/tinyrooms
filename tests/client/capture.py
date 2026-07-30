"""
Standalone capture script for generating UI screenshots for agent context.

Run this script directly to open the tinyrooms client, execute a set of
actions, and save the resulting screenshots to a specified output directory
without starting a full pytest session.

Usage
-----
python -m tests.client.capture \
    --server http://127.0.0.1:5000 \
    --username agent_user \
    --password agent_pass \
    --output /tmp/tinyrooms-shots

The script will:
1. Register *username* if it does not exist yet.
2. Log in and capture screenshots at key UI states.
3. Write PNG files to *output* directory.

Environment variables
---------------------
TR_BROWSER_VISIBLE
    Set to ``1`` to open a visible Chrome window.
TR_CHROMEDRIVER_PATH
    Path to a specific chromedriver binary.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Ensure the repo root is on sys.path when run as a script
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpx
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService

from tests.client.actions import (
    Login,
    Register,
    Screenshot,
    SendMessage,
    Wait,
    WaitForElement,
)
from tests.client.runner import ClientRunner


def _build_driver() -> webdriver.Chrome:
    opts = ChromeOptions()
    visible = os.environ.get("TR_BROWSER_VISIBLE", "").lower() in ("1", "true", "yes")
    if not visible:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,800")

    driver_path = os.environ.get("TR_CHROMEDRIVER_PATH")
    if driver_path:
        return webdriver.Chrome(service=ChromeService(driver_path), options=opts)
    try:
        from webdriver_manager.chrome import ChromeDriverManager

        return webdriver.Chrome(
            service=ChromeService(ChromeDriverManager().install()), options=opts
        )
    except Exception:
        return webdriver.Chrome(options=opts)


def _ensure_user(base_url: str, username: str, password: str) -> None:
    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        resp = client.post("/register", json={"username": username, "password": password})
        if resp.status_code not in (201, 409):
            print(f"Warning: unexpected register status {resp.status_code}: {resp.text}")


def capture(
    base_url: str,
    username: str,
    password: str,
    output_dir: Path,
) -> dict[str, Path]:
    """
    Capture a standard set of UI screenshots and return a mapping of
    name → saved PNG path.

    This function is the primary entry point for agent-driven capture.
    Customise the ``actions`` list below to match the UI states you need.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    _ensure_user(base_url, username, password)

    driver = _build_driver()
    try:
        runner = ClientRunner(
            driver=driver,
            base_url=base_url,
            screenshots_dir=output_dir,
            rebase=True,          # always write, never compare
            test_name="capture",
        )
        runner.open_client()

        # ----------------------------------------------------------------
        # Action sequence — edit this list to change what is captured
        # ----------------------------------------------------------------
        actions = [
            Screenshot(name="01_login_page"),
            Login(username=username, password=password),
            WaitForElement(selector="#mainPage"),
            WaitForElement(selector="#roomTitleOverlay", timeout=15.0),
            Wait(seconds=1.5),
            Screenshot(name="02_room_view"),
            SendMessage(text="Hello from the capture script"),
            WaitForElement(selector="#chatLogList .msg"),
            Wait(seconds=0.5),
            Screenshot(name="03_after_chat"),
        ]
        # ----------------------------------------------------------------

        runner.run(actions)

        saved: dict[str, Path] = {}
        for action in actions:
            if isinstance(action, Screenshot):
                path = output_dir / "capture" / f"{action.name}.png"
                if path.exists():
                    saved[action.name] = path
        return saved
    finally:
        driver.quit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture tinyrooms client screenshots for agent context."
    )
    parser.add_argument("--server", default="http://127.0.0.1:5000", help="Server base URL")
    parser.add_argument("--username", default="capture_agent", help="Username to use")
    parser.add_argument("--password", default="capture_password", help="Password to use")
    parser.add_argument("--output", default="screenshots_capture", help="Output directory")
    args = parser.parse_args()

    saved = capture(
        base_url=args.server,
        username=args.username,
        password=args.password,
        output_dir=Path(args.output),
    )
    print(f"Saved {len(saved)} screenshot(s):")
    for name, path in saved.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
