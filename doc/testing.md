# Tinyrooms Integration Testing

tinyrooms now includes an integration-first pytest suite that validates behavior through real HTTP and Socket.IO traffic against a live server process.

## Scope

The suite covers:

- HTTP smoke/auth boundaries
- socket connect/login/message flows
- initial room sync contract (`update_view` header/stage/object/exits)
- room navigation and multi-client realtime synchronization
- room interaction permissions (`room_move_entity`, `room_edit_prop`)
- disconnect and logout behavior
- character editor REST profile/sprite-selection/main-image contract
- sprite schema/resolver unit tests
- sprite-editor REST API lifecycle contract

## Test Layout

```text
tests/
  conftest.py
  integration/
    test_http_smoke.py
    test_auth_and_login_flow.py
    test_room_sync_and_navigation.py
    test_room_interactions_permissions.py
    test_multi_client_realtime.py
    test_activity_panel_and_actions.py
    test_char_editor_api.py
    test_sprite_editor_api.py
  test_sprites.py
```

## Isolation Strategy

The test harness copies the repository into a temporary workspace per session and starts `trserver.py` from that copied root.

- This keeps local `data/*.duckdb` and `data/users/*` state untouched.
- A lightweight test stub replaces `tools/make-image` inside the copied workspace so char-editor and object-editor contract tests run quickly without ML runtime dependencies.
- The copied world config sets the `playroom` owner to a dedicated integration owner account for deterministic permission tests.

## Running Tests

Run all integration tests:

```powershell
python -m pytest
```

Only char editor contract tests:

```powershell
python -m pytest -m char_editor
```
