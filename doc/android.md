# Tinyrooms — Android Application

Status: implementation plan. Related docs:
[architecture.md](./architecture.md) (current components and protocol),
[design.md](./design.md) (product/design intent),
[db.md](./db.md) (profile and world schemas),
[performance.md](./performance.md) (regression policy and budgets).

This document specifies how to ship Tinyrooms as a single self-contained Android
application: a Python world server running on the device, an in-app client
rendering that world, and LAN multiplayer so nearby devices can join a
phone-hosted world. Fine-grained implementation choices inside the Android
shell are intentionally left to the build agent.

Source references below are given as `file:symbol` rather than line numbers, so
they stay valid as the tree evolves.

## 1. Overview

The application packages the existing game unchanged in spirit. The browser
client becomes a `WebView` pointed at a loopback server; the Python server is
cross-compiled for `arm64-v8a` with python-for-android and runs in-process.

| Layer | Technology | Change required |
| --- | --- | --- |
| Client | Vanilla ES modules + Three.js, served from the loopback server | **None.** Load it from a different origin and it works unchanged |
| Server | Starlette + Uvicorn, `websockets`, PyYAML, SQLite, Pillow | FastAPI -> Starlette; add `TRSERVER_LOCAL_PATH` |
| Transport | TLS on loopback **and** LAN, self-signed cert shipped in the APK | Bind `0.0.0.0`; pass `--certfile`/`--keyfile` |
| Discovery | `NsdManager` (mDNS) in the Android layer | New native code; no Python involved |
| Packaging | `python-for-android` + Gradle AAB | New build system |

### 1.1 What the LAN requirement forces

Supporting other devices changes four decisions that would otherwise be simple:

1. **TLS cannot be dropped.** Chromium throws `SecurityError` on `ws://` from a
   non-trustworthy origin, and `http://192.168.x.x` is not trustworthy — so
   plaintext also removes `getUserMedia`, which disables peer voice chat (the
   `getUserMedia` call in `app/js/voice.js`). `cryptography` is still removed,
   but for a different reason: only *generating* a certificate needed it
   (`run.py:ensure_self_signed_certificate`). Shipping a pre-built PEM and
   loading it through the existing `--certfile`/`--keyfile` branch in
   `run.py:main` uses stdlib `SSLContext.load_cert_chain` instead.
2. **The host process must survive backgrounding.** A host that switches apps
   would otherwise drop every connected player, so hosting runs in an Android
   foreground service with a partial wake lock.
3. **Cookie handling needs no work.** With TLS everywhere, the two
   `secure=True` flags in `server/app.py:_set_session_cookies` are already
   correct, and the hardcoded `https://` in
   `server/config.py:compute_allowed_origins` is already correct.
4. **Origin validation already permits LAN clients.**
   `server/security.py:_is_same_port_https_origin` checks scheme, credentials,
   path, and port but never the hostname, so with a wildcard bind an origin of
   `https://192.168.1.42:5000` is accepted today. This needs a regression test,
   not a code change.

## 2. Target architecture

```
Hosting phone                              Joining phone (xN)
+-------------------------------+         +------------------------------+
| Activity: native launcher     |         | Activity: native launcher   |
|  +-- "Host a world"           |         |  +-- NsdManager.discover... |
|  +-- "Join a world" -> list   |<-- mDNS-|  |   Molly's House   3 players|
|     Molly's House  3 players  |  5353   |  |   Sam's Flat     1 player  |
+-------------------------------+         +------------------------------+
| Foreground Service             |         | Foreground Service          |
|  +-- partial WakeLock         |         |  (idle: not hosting)        |
|  +-- NsdManager.register      |         +------------------------------+
|  +-- Python/Uvicorn thread    |         | WebView -> https://<ip>:<p>/|
|     bind 0.0.0.0:0 over TLS   |         |  onReceivedSslError: proceed |
| WebViewClient:                 |         +------------------------------+
|  onReceivedSslError -> proceed |
| WebView -> https://127.0.0.1   |         Session cookies are keyed by origin, so
+-----+-------------------------+         127.0.0.1 and 192.168.1.42 keep
      |                                     separate tr_session values.
      +-- JNI: bound port, ready signal, world metadata
```

Key structural choices:

- **The session list is native, not web.** The client derives every request from
  `app/js/socket.js:websocketUrl` (i.e. `window.location.origin`), so a joining
  device only has to `loadUrl("https://<host-ip>:<port>/")` and the existing game
  boots against the remote host. There is no API-host setting, no CORS work, and
  **no new web UI**. The list of sessions is an Android screen shown before an
  origin exists.
- **mDNS lives entirely in the Android layer.** `NsdManager` advertises and
  discovers; the Python server only reports its bound port upward over JNI. The
  TXT record carries the world label, device name, player count, and join code.
- **Foreground service iff hosting.** Promote the service when the user chooses
  *Host a world*, or on the first inbound WebSocket connection. Demote when the
  last client leaves. A device that only joins still runs its own local server
  in-process, without a service, so it is cheap and dies with the app.

## 3. Scope decisions

| Decision | Choice | Rationale / rejected alternative |
| --- | --- | --- |
| Python packaging | python-for-android, custom recipes | Chaquopy rejected: prebuilt wheels but commercial. Pinning pydantic v1 rejected: see 4.1 |
| Worlds shipped | Tutorial only | No world import/export yet; would need a SAF/`Intent` bridge |
| Propsets | All six, unpruned | Prop Shop reads `/assets/propsets/` (`server/app.py:propset_asset`) independently of the Prop Editor |
| Prop Editor | Excluded | Not needed. Gate by omitting from `TRSERVER_FEATURES`; handlers already self-gate via `server/routes/common.py:require_editor_access` |
| World / Card / Prop editors | Excluded | The `server/services/world_editor.py` publish path mutates the checked-out world in place, which fails on a read-only bundle |
| Mission control | Excluded | Unmounted unless `TRSERVER_MC_ENDPOINT` is set (`server/app.py:create_app`); also drops the `httpx` dependency |
| Mods | `infinite-bedrooms` only | `worlds/tutorial/world.yaml` declares `requires_mods: [infinite-bedrooms]`; 139 KB |
| Network scope | LAN only | No internet STUN/TURN; WebRTC completes on host candidates |
| Target SDK | 36 (Android 16) | Local network access is open by default; avoids the `ACCESS_LOCAL_NETWORK` runtime permission and the `FLAG_SHOW_PICKER` flow entirely |
| Cert trust | `proceed()` on all cert errors | See 11 |
| Account creation | Host's join code is `TRSERVER_NEW_ACCOUNT_PASSPHRASE` | See 11 |

## 4. Code change inventory

### 4.1 Dependency surgery — remove both native blockers

`requirements.txt` ends up with **no Rust, no C extensions except Pillow**.

**Drop `cryptography`.** It appears only in the `run.py` imports /
`run.py:ensure_self_signed_certificate` and `tests/test_launcher.py`. Replace
with a PEM shipped in the APK; `run.py:main` already supports external cert
files.

**Drop FastAPI in favour of Starlette.** Pydantic v1 is not a viable escape
route: FastAPI 0.126.0 removed standalone pydantic v1, 0.128.0 removed the
`pydantic.v1` shim, and the shim lives inside pydantic 2.x which still loads
`pydantic-core` (Rust). Starlette 1.6 depends only on `anyio` and
`typing-extensions`.

Verified surface for the migration:

| Current | Replacement | Volume |
| --- | --- | --- |
| `fastapi.HTTPException` | `starlette.exceptions.HTTPException` (FastAPI subclasses it) | 55 uses |
| `fastapi.Request` / `Response` / `WebSocket` / `WebSocketDisconnect` | `starlette.requests` / `.responses` / `.websockets` | 146 uses |
| `fastapi.responses` | `starlette.responses` | 9 files |
| `fastapi.concurrency.run_in_threadpool` | `starlette.concurrency.run_in_threadpool` | 2 uses |
| `fastapi.APIRouter` | `starlette.routing.Router` + `Route(...)` | 10 uses, ~40 routes |
| `fastapi.exceptions.RequestValidationError` | `starlette.exceptions.HTTPException` | 1 use (mission control only) |
| 14 `BaseModel` classes | `dataclass` + explicit length/range checks | 4 in `server/app.py` (`AuthRequest` and siblings), 2 in `server/mc_api.py`, 8 in `server/mission_control/routes.py` |

There are **zero** uses of `Depends`, `Body`, `Form`, `UploadFile`, or `Query`,
so there is no dependency-injection container to replace. `request.cookies`,
`request.app.state`, `request.client`, `websocket.receive_text`, and lifespan
all exist in Starlette.

Keep: `starlette`, `uvicorn`, `websockets` (pure-Python fallback, no
`_speedups`), `PyYAML` (only `yaml.safe_load` is used, never `CSafeLoader`),
`Pillow`, `tzdata`. Drop: `httpx` (mission control only), `cryptography`,
`fastapi`.

### 4.2 Configuration

- **Add `TRSERVER_LOCAL_PATH`.** `server/config.py:load_config` hardcodes
  `local_path = root / ".local"`, and `drafts_path` / `revisions_path` derive
  from it. Everything else is already relocatable via `TRSERVER_USERS_PATH`,
  `TRSERVER_WORLDSTATE_PATH`, `TRSERVER_CUSTOM_STICKERS_PATH`, and
  `TRSERVER_WORLD_PATH`.
- **Allow an ephemeral port.** The port range check in
  `server/config.py:load_config` rejects port 0. Either bind the socket in Java
  and hand it to Python, or widen the accepted range. The pre-bound-socket
  pattern already exists in `tools/browser_test_runtime.py`.
- **Set `TRSERVER_HOST=0.0.0.0`** so LAN clients can reach the host.
- **Set `TRSERVER_STUN_URLS=`** (empty) for LAN-only WebRTC.
  `server/config.py:parse_ice_urls` returns `()` for an empty string,
  `AppConfig.ice_servers` returns `[]`, and `app/js/voice.js:ensurePeer` does
  `new RTCPeerConnection({ iceServers })`, which completes on same-subnet host
  candidates.
- **Add a `TRSERVER_JOIN_CODE` alias** that populates `new_account_passphrase`
  (read in `server/config.py:load_config`) so the Android shell can pass a
  per-world code without duplicating the existing variable.
- **Register explicit MIME types** for `.glb`, `.gltf`, `.ktx2`, `.webp`,
  `.svg`, `.wasm`, and `.mjs`. Every asset route except `server/app.py:activity_asset`
  relies on Starlette's default guess, and Android's mime database is sparse — a
  wrong `Content-Type` on a `.glb` fails silently inside `GLTFLoader`.

### 4.3 Security fixes

- `server/accounts.py:create_account` compares the new-account passphrase with
  `!=`. `server/mission_control/auth.py:login` correctly uses
  `hmac.compare_digest`. Align it, since the value is now a short LAN code.
- Add a regression test asserting that a wildcard bind accepts an origin of
  `https://<lan-ip>:<port>`. The behaviour already works
  (`server/security.py:_is_same_port_https_origin`) but is untested and
  non-obvious.

### 4.4 Client changes

The game client needs no changes to *play* across the LAN. It needs five
targeted fixes for the WebView environment:

1. **Add a `webglcontextrestored` handler on the board.** The
   `webglcontextlost` listener in `app/js/board.js` is the only one in the
   codebase and there is no restore handler anywhere. When Chromium exceeds its
   live-context cap it force-loses the *oldest* context, which is always the
   board, and `app/js/board.js:contextLost` then declares the board permanently
   dead with "Reload to restore the board". A restore handler that rebuilds from
   the caches in `app/js/board-resources.js` converts a fatal error into a
   hiccup. Highest value per line of any item in this document.
2. **Debounce look-bar prop selection** (~150 ms) at the look-bar preview markup
   in `app/js/ui.js`. The `sync` in `app/js/prop-viewer.js` and the `sync` in
   `app/js/card-viewer.js` dispose and recreate a WebGL context on every
   URL/scale change, and `WebGLRenderer.dispose()` releases the slot
   asynchronously — so fast tap-through transiently exceeds the cap.
3. **Set `antialias: false` for the inspector stages** in
   `app/js/viewer-stage.js:createViewerStage`, keeping MSAA on the board only.
   The card and prop detail previews do not need it, and this is the largest
   per-context memory win. Expect small diffs in the card/prop detail visual
   baselines.
4. **Add a shared live-context budget** in `app/js/viewer-stage.js` that refuses
   past N and falls back to a static image, so pressure degrades predictably
   instead of killing the board.
5. **Handle the Prop Editor launcher in `app/js/ui.js`**, which calls
   `window.open`. WebView blocks it; use same-WebView navigation with a back
   stack, or hide the entry point when the feature is off. The route would return
   403 anyway.

Steady-state WebGL usage is already safe and must stay that way: 1 board (the
renderer in `app/js/board.js`), up to 3 inspector canvases (the card preview
canvas in `app/js/cards.js`, the look-bar preview markup in `app/js/ui.js`, and
the prop preview canvas in `app/js/views/prop-details-view.js`), and 1 shared
offscreen thumbnail renderer
(`app/js/editing/prop-thumbnails.js:ensureRenderer`) that all library and shop
grids go through via `app/js/editing/prop-library.js:thumbnailMarkup` and the
`IntersectionObserver` in `app/js/editing/prop-thumbnails.js`. **Never convert a
grid to per-item canvases.**

### 4.5 Android shell

- **Manifest permissions**: `INTERNET`, `ACCESS_NETWORK_STATE`, `WAKE_LOCK`,
  `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_DATA_SYNC`, `POST_NOTIFICATIONS`,
  `RECORD_AUDIO`.
- **`WebChromeClient`** mapping `PermissionRequest.RESOURCE_AUDIO_CAPTURE` onto
  the `RECORD_AUDIO` runtime permission. WebView denies `PermissionRequest` by
  default, which silently kills push-to-talk.
- **`onReceivedSslError` -> `handler.proceed()`** on every error, so there is no
  interstitial. This yields a working secure context, so `getUserMedia` and
  `navigator.clipboard` function.
- **`WindowCompat.setDecorFitsSystemWindows(window, false)`** so the existing
  `env(safe-area-inset-*)` rules and the viewport meta in `app/index.html`
  resolve to real values on notched devices.
- **`OnBackPressedCallback`** mirroring the Escape ladder in `app/js/ui.js`,
  then `webView.goBack()`, then finish.
- **`navigator.wakeLock` + `FLAG_KEEP_SCREEN_ON`.** The board only polls
  `document.hidden` (`app/js/board.js:pageIsHidden`).
- **Import maps need WebView 89+.** The import map in `app/index.html` already
  relies on them, and `app/js/boot-guard.js` renders a diagnostic overlay on
  older engines. Check `WebViewFeature.isFeatureSupported` at launch and fail
  with a clear message rather than a blank page.
- **No cleartext traffic.** With TLS on loopback and LAN, `usesCleartextTraffic`
  stays at its default of `false` and no network security config is needed.

### 4.6 Build and content pipeline

- **Extract content to `filesDir` on first launch**; point writable state
  (`users/`, `.local/`) at app-private storage and read-only content at the
  extracted bundle. Add an asset-pack manifest step that fails the build if
  `worlds/tutorial`, `data/cardsets`, `data/propsets/*/props.yaml`, or
  `mods/infinite-bedrooms` is missing.
- **Vendor Three.js during the APK build.** `app/vendor/three/` is gitignored,
  and the `vendor` script in `package.json` contains a Windows backslash
  (`tools\vendor_browser_deps.py`) that breaks the POSIX shell an Android build
  uses.
- **Texture post-processor.** See section 5.
- **CI must run on Linux.** python-for-android only cross-compiles from Linux.

## 5. Asset pipeline

Measured across all 232 GLB files: **77.5% of the payload is embedded texture,
not geometry**, and all 455 textures are 512x512 PNG at ~7.3 bpp. None use Draco
or meshopt today.

| Stage | GLB payload | Full content |
| --- | --- | --- |
| As-is | 181 MB | 186.9 MB |
| Draco/meshopt on geometry only | ~163 MB | ~169 MB |
| **+ PNG to WebP q80-85 on all 455 textures** | **~50-55 MB** | **~92-97 MB** |
| + KTX2/ETC1S instead of WebP | ~35-40 MB | ~80 MB, more client work |

Draco alone is nearly pointless here: a 60% geometry win saves 18 MB of 181.
Downscaling is not available at all because every texture is already 512x512.
**PNG to WebP is the change that matters**, and it needs no client change
because `GLTFLoader` decodes WebP natively.

KTX2/Basis is the better Android answer — it transcodes to ASTC/ETC2 on the GPU,
cutting both download size and VRAM, which also relieves the per-context memory
pressure in 4.4. It requires `KHR_texture_basisu`, a `KTX2Loader`, and the Basis
transcoder binary. Defer to a second pass.

`data/propsets/*/bake.json` records the generation prompts and seeds that
produced each GLB, with **absolute `C:/...` output paths** baked in. The models
are generated artifacts from a tool not in this repository, so re-encoding must
be a post-processor that rewrites the GLB container in place, leaving geometry,
materials, and animations byte-for-byte. A bad pass must be revertable, so keep
it as an isolated commit — texture conversion is lossy and will produce visual
baseline diffs that need design review, not a silent re-record.

Resulting application size: ~92-97 MB content plus ~40-50 MB of cross-compiled
Python and Pillow, for **~135-150 MB** in a single Play base module. No Play
Asset Delivery and no asset packs are required.

## 6. Gates

Two gates must both pass before feature work begins. **Execution starts with
Gate 2** (see 6.4).

### 6.1 Gate 1 — python-for-android bring-up (blocking)

Build an APK containing Python 3.11 for `arm64-v8a` with recipes for
`starlette`, `uvicorn`, `websockets`, `PyYAML`, and `Pillow`, serving a single
`{"ok": true}` response over TLS from a WebView.

Must also assert, in that same build:

- `hashlib.scrypt` works (`server/security.py:hash_password` / `verify_password`).
  It needs OpenSSL 1.1+; p4a bundles OpenSSL 3.x, but a failure here would
  silently break all account creation. Fallback: PBKDF2-HMAC-SHA256 with a
  versioned hash prefix so existing hashes still verify.
- `sqlite3` with `journal_mode=WAL` and `busy_timeout` works
  (`server/state/migrations.py:_connect`).
- `zoneinfo` resolves via the `tzdata` wheel.
- Uvicorn runs on a background thread. `uvicorn.Server.capture_signals` in 0.52
  no-ops off the main thread, so this is safe, but
  `BoundedShutdownServer.handle_exit` will never fire — drive shutdown with
  `server.should_exit = True` and a join-with-timeout from the service instead.

Failure here invalidates the whole approach.

### 6.2 Gate 2 — LAN spike on real hardware (blocking, execute first)

De-risk the multiplayer feature using a **placeholder** server. Build a minimal
APK containing only the launcher screen, `NsdManager` advertise + discover, a
`WebViewClient` that calls `proceed()`, and a foreground service with a wake
lock. Point it at `python -m http.server` on a laptop.

This validates every unknown in the LAN design *before* the p4a server exists:

1. Does `NsdManager` advertise and resolve across two real handsets?
2. Does the foreground service survive screen lock and app switching, and does it
   survive past Doze's grace period?
3. Does `proceed()` produce a working secure context, and do `Secure` cookies
   set by a proceeded HTTPS response persist across a WebView restart?
4. Does a WebSocket survive the host phone's screen going off and the process
   being frozen?

**Run this on physical devices.** Doze, mDNS multicast, and vendor background
limits are unrepresentative in an emulator, and an emulator will produce a false
pass.

Also capture the failure modes of hostile networks: APs with IGMP snooping or
client isolation break mDNS discovery. Keep a manual "enter address" fallback in
the launcher as a result.

### 6.3 Gate outcomes

Both gates pass before P0 work starts. If Gate 2 fails, the LAN feature is
dropped and the application ships as single-device — no other work is wasted,
since the WebView shell, foreground service, and cert handling are all still
required.

### 6.4 Execution order

**Start with Gate 2**, then Gate 1, then P0.

Gate 2 comes first because it is cheaper (two days, and the placeholder server
needs no p4a work) and because it tests the assumption most likely to kill the
LAN feature outright. Gate 1 remains a hard prerequisite for everything
downstream, but if Gate 2 fails you want to know before spending weeks on
python-for-android recipes.

## 7. Phase plan

### P0 — Server refactors (desktop, suite green before any Android work)

| # | Task | Notes |
| --- | --- | --- |
| P0.1 | FastAPI to Starlette | 4.1. Pure refactor, no behaviour change |
| P0.2 | Add `TRSERVER_LOCAL_PATH` | 4.2 |
| P0.3 | `hmac.compare_digest` for the passphrase | `server/accounts.py:create_account` |
| P0.4 | LAN origin regression test | Documents existing behaviour |
| P0.5 | `webglcontextrestored` on the board | 4.4 item 1; also a desktop improvement |

### P1 — Android application shell

| # | Task |
| --- | --- |
| P1.1 | Gradle project, p4a integration, `arm64-v8a`, `INTERNET` permission |
| P1.2 | Content extraction to `filesDir` + asset-pack manifest step |
| P1.3 | Python service on a background thread, ephemeral pre-bound socket, JNI port handoff |
| P1.4 | WebView Activity: load `/`, wait for the ready signal |
| P1.5 | Ship the self-signed PEM; wire `--certfile` / `--keyfile` |
| P1.6 | `onReceivedSslError` proceed; microphone permission bridge |
| P1.7 | Edge-to-edge insets, wake lock, back gesture, WebView-version check |

### P2 — Hosting and discovery

| # | Task |
| --- | --- |
| P2.1 | Foreground service + notification + partial wake lock; promote/demote rules |
| P2.2 | `NsdManager.registerService` with world label, device name, player count, join code |
| P2.3 | `NsdManager.discoverServices` and the native session list |
| P2.4 | Join code generation wired to `TRSERVER_JOIN_CODE` |
| P2.5 | `TRSERVER_HOST=0.0.0.0`, `TRSERVER_STUN_URLS=` |
| P2.6 | Prefill the signup username from the device name (see 11) |
| P2.7 | Manual "enter address" fallback |

### P3 — Client polish for the WebView environment

| # | Task |
| --- | --- |
| P3.1 | Debounce look-bar selection |
| P3.2 | `antialias: false` for inspector stages (baseline review required) |
| P3.3 | Shared live-context budget with static fallback |
| P3.4 | `window.open` handling; hide the Prop Editor launcher when the feature is off |
| P3.5 | Multiplayer pass: two devices, create accounts, move props, chat, presence, voice |

### P4 — Assets and distribution

| # | Task |
| --- | --- |
| P4.1 | Texture post-processor (PNG to WebP), isolated commit |
| P4.2 | CI size assertion so the payload cannot silently re-inflate |
| P4.3 | AAB signing and release build |
| P4.4 | `adb` on-device smoke suite |
| P4.5 | Optional KTX2/Basis pass |

## 8. Testing strategy

The existing Playwright harness spawns a Python subprocess per test
(`tools/browser_test_runtime.py`) and runs under SwiftShader. **Neither
exercises the Android environment**, and in particular the SwiftShader config
will never surface the WebGL context-limit failure in 4.4.

- Keep `npm test` and `python -m unittest discover -s tests` as the desktop
  regression gate. P0 must land with them fully green.
- Add a physical-device smoke suite driven over `adb`: install, launch, create an
  account, walk the tutorial world, screenshot, and scrape `logcat`.
- Add a two-device test for P3.5. It cannot be automated without a lab, so
  document it as a manual release checklist item.
- `server/logging_ring.py` is memory-only, so nothing survives a crash or an ANR
  kill. Add file logging for the Android build or accept that a killed host
  leaves no trace.
- Re-check `tests/test_ui_presentation.py` — the under-1200-line rule and the
  no-fragile-CSS-assertions rule — against any new CSS.
- Visual baselines must be reviewed, not re-recorded to mask content changes.
  Expect diffs from P3.2 and P4.1.

## 9. Risk register

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Doze kills the host's world | High | Gate 2 on hardware; foreground service + wake lock; P2.1 |
| mDNS broken by AP IGMP snooping or client isolation | High | Gate 2 on hardware; manual address fallback (P2.7) |
| p4a recipe bring-up fails | High | Gate 1 blocks everything downstream |
| WebGL force-loss kills the board permanently | Medium | 4.4 items 1-4; invisible in SwiftShader, so P3.5 must run on hardware |
| `proceed()` breaks cookie persistence | Medium | Gate 2 item 3 |
| Loopback event-loop throughput with N clients | Medium | All database work is synchronous behind `DatabaseHub._lock` in `server/state/migrations.py`. Fine for 4-6 players; a real ceiling beyond that |
| Host device thermal load and battery | Medium | Host runs a server *and* a WebGL client. Show a "hosting" indicator, recommend the host charge, and justify the wake lock for Play review |
| Texture conversion degrades art | Low | Isolated commit, design review of baseline diffs, revertible |
| `ACCESS_LOCAL_NETWORK` on Android 17 | Low (deferred) | Deliberate. Target SDK 36 keeps local access open; revisit before the next major Play requirement |
| Play review rejects the wake lock or foreground service | Low | Declare `FOREGROUND_SERVICE_DATA_SYNC`; document the game-server justification |

## 10. Open decisions

1. **The Sticker Designer gate blocks entry.** `initial_sticker_complete` is
   required at the world-entry check and at the WebSocket handshake in
   `server/app.py` (close code 4403). Every joining player must design a sticker
   before playing, which is a poor start for four people on a couch. Options: a
   one-tap preset path, a host-side waiver, or a LAN-only feature flag. Recommend
   the preset path, since the gate exists to give players an identity rather than
   to force drawing. **Unresolved.**
2. **Maximum players per world.** No cap exists today. The global `RLock`
   around all database work is the practical ceiling and has not been measured
   on mobile hardware.
3. **Whether a joining device also hosts.** The current design allows it (its own
   world appears in the list alongside others). Confirm this is wanted.

## 11. Accepted trade-offs

- **No host authentication.** `proceed()` on all certificate errors means any
  device on the same Wi-Fi could man-in-the-middle a session. Acceptable for a
  LAN game with no secrets beyond game state, but it is a deliberate decision,
  not an oversight. A join code in the mDNS TXT record would not change this,
  because TXT records are readable by every device on the network.
- **The join code is convenience, not security.** Broadcasting
  `TRSERVER_NEW_ACCOUNT_PASSPHRASE` in an mDNS TXT record makes account creation
  roughly equivalent to open registration on that LAN. It removes setup friction
  and nothing more.
- **A static private key ships in the APK** and is therefore extractable. It
  must never be reused for anything else.
- **Single live session per account.** `server/app.py:login` silently replaces
  the previous connection when the same account logs in twice, so usernames must
  be effectively unique per device. P2.6 mitigates by prefilling from the device
  name.
- **LAN only.** No relay, no internet discovery, no TURN.
