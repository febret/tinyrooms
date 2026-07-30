# Tinyrooms Client UI Testing

The `tests/client/` package provides a Selenium-based visual testing framework for
the tinyrooms browser client.  It serves two purposes:

1. **Integration testing** — automated screenshot comparisons that catch visual
   regressions in the client UI.
2. **Agent context generation** — a standalone capture script that agents can call
   to populate their visual context with current screenshots of the UI.

Both modes execute the same *action DSL*, producing a consistent picture of what the
client looks like at each step.

---

## Quick start

### Prerequisites

- Google Chrome (or Chromium) installed on the test machine.
- `chromedriver` matching your Chrome version.  The framework uses
  [`webdriver-manager`](https://github.com/SergeyPirogov/webdriver_manager) to
  resolve the correct binary automatically; alternatively set
  `TR_CHROMEDRIVER_PATH` to a specific path.
- All Python dependencies installed:
  ```powershell
  pip install -r requirements.txt
  ```

### Run all client UI tests

```powershell
python -m pytest -m client_ui
```

This starts a real tinyrooms server (reusing the session-scoped server from the
integration suite), opens a headless Chrome browser, and executes each test.

### Run only client UI tests, verbosely

```powershell
python -m pytest -m client_ui -v
```

### Run with a visible browser window (for debugging)

```powershell
$env:TR_BROWSER_VISIBLE = "1"
python -m pytest -m client_ui -v
```

---

## Reference screenshots

Each `Screenshot` action in a test is compared against a **reference image** stored at:

```
tests/client/screenshots/<test_name>/<screenshot_name>.png
```

On the **first run** (when no reference exists) the framework writes the captured
image as the reference automatically.

On subsequent runs the captured image is compared pixel-by-pixel against the
reference.  If the root-mean-square difference exceeds 5 % (configurable via
`ClientRunner.diff_threshold`) the test fails with a message pointing to both the
reference and the actual files.

### Rebasing (accepting new appearances)

After intentional UI changes, re-generate all reference screenshots in one command:

```powershell
python -m pytest -m client_ui --rebase-screenshots
```

This overwrites every reference with the current render without performing any
comparisons.  Commit the updated PNG files to version control to lock in the new
baseline.

---

## Test layout

```
tests/client/
  __init__.py
  actions.py           # Action DSL — dataclasses describing browser steps
  runner.py            # ClientRunner — executes actions, compares screenshots
  conftest.py          # pytest fixtures (browser, client_runner, etc.)
  capture.py           # Standalone capture script for agent context generation
  test_login_flow.py   # Login / logout visual tests
  test_room_view.py    # In-room UI visual tests
  screenshots/         # Reference PNG images (committed to version control)
    <test_name>/
      <screenshot_name>.png        # reference
      <screenshot_name>.actual.png # written on failure, deleted on pass
```

---

## Action DSL reference

All actions live in `tests.client.actions`.  Import them like so:

```python
from tests.client.actions import Login, Register, SendMessage, Screenshot, Wait
```

| Action | Description |
|---|---|
| `Login(username, password)` | Fill in the login form and click Login.  Waits until the main page appears or a failure message is shown. |
| `Register(username, password)` | Click the Register button with the supplied credentials. |
| `Logout()` | Click the logout button and wait for the login page to reappear. |
| `SendMessage(text)` | Type *text* into the chat input and click Send. |
| `Click(selector)` | Click the first element matching the CSS *selector*. |
| `WaitForElement(selector, timeout=10)` | Block until an element is visible. |
| `WaitForElementAbsent(selector, timeout=10)` | Block until an element is invisible or removed. |
| `Wait(seconds=0.5)` | Pause for a fixed duration (wall-clock sleep). |
| `SetWindowSize(width=1280, height=800)` | Resize the browser viewport. |
| `Screenshot(name)` | Capture the current window; compare or save as reference. |
| `ExecuteScript(script, args=[])` | Run arbitrary JavaScript in the browser. |

---

## Writing a new test

```python
import pytest
from tests.client.actions import Login, Register, Screenshot, Wait, WaitForElement

pytestmark = pytest.mark.client_ui


def test_my_feature(client_runner, unique_username, register_user):
    username = unique_username("ui_myfeature")
    password = "test_password_123"
    register_user(username, password)

    client_runner.run([
        Login(username=username, password=password),
        WaitForElement(selector="#mainPage"),
        Wait(seconds=1.0),
        Screenshot(name="my_feature_state"),
    ])
```

The `client_runner`, `unique_username`, and `register_user` fixtures are all
provided by the conftest hierarchy — no additional boilerplate needed.

---

## Fixtures

### `client_runner`

Function-scoped.  Provides a `ClientRunner` already navigated to the login page.

Depends on:
- `server_runtime` (from `tests/conftest.py`) — a running tinyrooms server.
- `browser` (session-scoped Chrome WebDriver).
- `rebase_screenshots` — whether to write references instead of comparing.
- `screenshots_dir` — `tests/client/screenshots/`.

### `browser`

Session-scoped headless Chrome.  All tests in a session share one browser window to
keep overhead low.  Set `TR_BROWSER_VISIBLE=1` for a visible window.

### `rebase_screenshots`

Session-scoped bool — `True` when `--rebase-screenshots` is passed.

### `screenshots_dir`

Session-scoped `Path` pointing to `tests/client/screenshots/`.

---

## Agent context generation

The `tests.client.capture` module provides a standalone way to generate screenshots
for injection into an LLM agent context.

### From the command line

Start a tinyrooms server first, then:

```powershell
python -m tests.client.capture \
    --server http://127.0.0.1:5000 \
    --username agent_user \
    --password agent_pass \
    --output /tmp/tinyrooms-shots
```

Saved files are printed to stdout.

### From Python (inside an agent)

```python
from pathlib import Path
from tests.client.capture import capture

shots = capture(
    base_url="http://127.0.0.1:5000",
    username="agent_user",
    password="agent_pass",
    output_dir=Path("/tmp/shots"),
)
# shots["02_room_view"] is a Path to the PNG file
```

### From a pytest test (no comparison)

Use `ClientRunner.capture_screenshots()` instead of `run()`:

```python
def test_capture_for_agent(client_runner, unique_username, register_user):
    username = unique_username("agent")
    register_user(username, "pass")

    shots = client_runner.capture_screenshots([
        Login(username, "pass"),
        Wait(1.0),
        Screenshot("room"),
        SendMessage("Hello!"),
        Wait(0.5),
        Screenshot("after_chat"),
    ])
    # shots["room"] is raw PNG bytes — pass to vision model
    assert "room" in shots
```

`capture_screenshots` executes all actions but **never** compares to references and
never fails due to visual differences.

---

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `TR_BROWSER_VISIBLE` | `""` | Set to `1`/`true`/`yes` to show a visible Chrome window. |
| `TR_CHROMEDRIVER_PATH` | `""` | Path to a specific `chromedriver` binary; skips webdriver-manager. |

---

## Configuring diff tolerance

The default RMS pixel tolerance is **5 %**.  To tighten or relax it for a specific
test, create the runner manually:

```python
from tests.client.runner import ClientRunner

def test_strict(browser, server_runtime, screenshots_dir, rebase_screenshots):
    runner = ClientRunner(
        driver=browser,
        base_url=server_runtime.base_url,
        screenshots_dir=screenshots_dir,
        rebase=rebase_screenshots,
        test_name="my_strict_test",
        diff_threshold=0.01,   # 1 % tolerance
    )
    runner.open_client()
    runner.run([...])
```
