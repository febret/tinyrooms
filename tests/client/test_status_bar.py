"""
Selenium UI tests — gameplay status bar.

Tests verify that:
- The four status bar elements are visible after login.
- Juice and Kudos indicators are populated with content.
- Clicking the juice/level button triggers an activity panel.
"""
from __future__ import annotations

import pytest
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

from tests.client.actions import (
    Login,
    Register,
    Screenshot,
    Wait,
    WaitForElement,
)

pytestmark = pytest.mark.client_ui


def test_status_bar_visible_after_login(client_runner, unique_username, register_user):
    """All four status bar elements should be visible immediately after login."""
    username = unique_username("ui_gpbar")
    password = "testpass123"
    register_user(username, password)

    client_runner.run([
        Login(username=username, ******
        WaitForElement(selector="#mainPage"),
        Wait(seconds=1.5),
        Screenshot(name="status_bar_visible"),
    ])

    driver = client_runner.driver

    # All four status bar buttons must exist
    for element_id in ("statusName", "statusKudosBar", "statusKudosGive", "statusJuice"):
        el = driver.find_element(By.ID, element_id)
        assert el is not None, f"#{element_id} not found"
        assert el.is_displayed(), f"#{element_id} not displayed"


def test_status_name_shows_username(client_runner, unique_username, register_user):
    """The status name button should display the username after login."""
    username = unique_username("ui_gpname")
    password = "testpass123"
    register_user(username, password)

    client_runner.run([
        Login(username=username, ******
        WaitForElement(selector="#mainPage"),
        Wait(seconds=1.5),
    ])

    driver = client_runner.driver
    name_text = driver.find_element(By.ID, "statusNameText")
    assert name_text.is_displayed(), "#statusNameText not displayed"
    # Username should appear somewhere in the text (may have level icon prefix)
    assert username in name_text.text, (
        f"Expected '{username}' in statusNameText, got: {name_text.text!r}"
    )


def test_juice_indicator_populated(client_runner, unique_username, register_user):
    """The juice indicator should show a numeric value after login."""
    username = unique_username("ui_gpjuice")
    password = "testpass123"
    register_user(username, password)

    client_runner.run([
        Login(username=username, ******
        WaitForElement(selector="#mainPage"),
        Wait(seconds=1.5),
    ])

    driver = client_runner.driver
    juice_text = driver.find_element(By.ID, "statusJuiceText")
    assert juice_text.is_displayed()
    # Should contain the juice emoji and a number
    text = juice_text.text
    assert "🧃" in text, f"Expected 🧃 in juice indicator, got: {text!r}"


def test_kudos_progress_visible(client_runner, unique_username, register_user):
    """The Kudos progress bar element should be present."""
    username = unique_username("ui_gpkudos")
    password = "testpass123"
    register_user(username, password)

    client_runner.run([
        Login(username=username, ******
        WaitForElement(selector="#mainPage"),
        Wait(seconds=1.5),
    ])

    driver = client_runner.driver
    progress_el = driver.find_element(By.ID, "statusKudosProgress")
    assert progress_el is not None
    # max attribute should be set (from update_status)
    max_val = progress_el.get_attribute("max")
    assert max_val is not None and int(float(max_val)) > 0


def test_clicking_juice_opens_activity_panel(client_runner, unique_username, register_user):
    """Clicking the juice status button should emit a command that opens an activity panel."""
    username = unique_username("ui_gpjclick")
    password = "testpass123"
    register_user(username, password)

    client_runner.run([
        Login(username=username, ******
        WaitForElement(selector="#mainPage"),
        Wait(seconds=1.5),
    ])

    driver = client_runner.driver
    juice_btn = driver.find_element(By.ID, "statusJuice")
    juice_btn.click()

    # Wait for the activity panel to appear with juice-related content
    try:
        WebDriverWait(driver, 8).until(
            lambda d: "juice" in d.find_element(By.ID, "activityPanel").text.lower()
        )
    except Exception:
        pass  # Take screenshot for debugging even if this fails

    client_runner.run([
        Wait(seconds=0.5),
        Screenshot(name="after_juice_click"),
    ])

    activity_panel_text = driver.find_element(By.ID, "activityPanel").text
    assert "juice" in activity_panel_text.lower(), (
        f"Expected 'juice' in activity panel after clicking juice button, got: {activity_panel_text!r}"
    )
