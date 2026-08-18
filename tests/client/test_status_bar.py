"""
Selenium UI tests — gameplay status bar.

Tests verify that:
- The four status bar elements are visible after login.
- Juice and Kudos indicators are populated with content.
- Connection, settings, and logout controls share one dropdown.
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
        Login(username=username, password=password),
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
        Login(username=username, password=password),
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
    """The juice indicator should show a populated progress bar after login."""
    username = unique_username("ui_gpjuice")
    password = "testpass123"
    register_user(username, password)

    client_runner.run([
        Login(username=username, password=password),
        WaitForElement(selector="#mainPage"),
        Wait(seconds=1.5),
    ])

    driver = client_runner.driver
    juice_progress = driver.find_element(By.ID, "statusJuiceProgress")
    assert juice_progress.is_displayed()
    assert float(juice_progress.get_attribute("max")) > 0
    assert float(juice_progress.get_attribute("value")) >= 0


def test_account_menu_contains_connection_settings_and_logout(
    client_runner, unique_username, register_user
):
    """The top-right menu should contain all connection and account controls."""
    username = unique_username("ui_account_menu")
    password = "testpass123"
    register_user(username, password)

    client_runner.run([
        Login(username=username, password=password),
        WaitForElement(selector="#mainPage"),
        Wait(seconds=1.5),
    ])

    driver = client_runner.driver
    assert not driver.find_elements(By.ID, "statusKudosProgress")

    toggle = driver.find_element(By.ID, "statusMenuToggle")
    toggle.click()

    dropdown = driver.find_element(By.ID, "statusMenuDropdown")
    assert dropdown.is_displayed()
    assert driver.find_element(By.ID, "connectionStatusText").text == "Connected"
    assert driver.find_element(By.ID, "statusConfig").is_displayed()
    assert driver.find_element(By.ID, "btnLogout").is_displayed()


def test_status_bar_fits_phone_portrait(client_runner, unique_username, register_user):
    """The status bar and its open menu should fit a phone portrait viewport."""
    username = unique_username("ui_status_portrait")
    password = "testpass123"
    register_user(username, password)

    client_runner.run([
        Login(username=username, password=password),
        WaitForElement(selector="#mainPage"),
        Wait(seconds=1.5),
    ])

    driver = client_runner.driver
    driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
        "width": 390,
        "height": 844,
        "deviceScaleFactor": 1,
        "mobile": True,
    })

    status_panel = driver.find_element(By.ID, "statusPanel")
    assert driver.execute_script("return window.innerWidth") == 390
    assert driver.execute_script(
        "return document.documentElement.scrollWidth <= "
        "document.documentElement.clientWidth"
    )
    assert driver.execute_script(
        "return arguments[0].scrollWidth <= arguments[0].clientWidth", status_panel
    )

    driver.find_element(By.ID, "statusMenuToggle").click()
    dropdown = driver.find_element(By.ID, "statusMenuDropdown")
    dropdown_bounds = driver.execute_script(
        "const rect = arguments[0].getBoundingClientRect(); "
        "return {left: rect.left, right: rect.right};",
        dropdown,
    )
    assert dropdown_bounds["left"] >= 0
    assert dropdown_bounds["right"] <= 390


def test_clicking_juice_opens_activity_panel(client_runner, unique_username, register_user):
    """Clicking the juice status button should emit a command that opens an activity panel."""
    username = unique_username("ui_gpjclick")
    password = "testpass123"
    register_user(username, password)

    client_runner.run([
        Login(username=username, password=password),
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
