# Tinyrooms — Native Mobile Clients (Android + iOS) Plan

Status: implementation plan. This document proposes two thin native shells that
host the existing browser client in a first-party WebView, pointed by default at
`https://tinyrooms.febret.com/home`. Related docs:
[architecture.md](./architecture.md) (components and protocol),
[design.md](./design.md) (product/design intent),
[android.md](./android.md) (separate, self-hosted LAN-server Android plan),
[performance.md](./performance.md) (regression policy and budgets).

## 1. Goal and constraints

- Two thin native apps whose only job is to host the existing web client in a
  first-party WebView.
- Default server URL `https://tinyrooms.febret.com/home`; users may point at any
  instance and the choice is persisted.
- Minimal native code, minimal dependencies, no shared cross-platform framework
  (deliberate decision). Two small native codebases.
- No local Mac: the iOS app is built, signed, and tested on a cloud macOS CI
  runner.
- Must clear both stores. This drives two **server-side** workstreams that do
  not exist yet: account deletion and UGC safeguards.

### 1.1 Why a plain WebView works

The web client is pure ES modules plus Three.js with no build step. It derives
every network URL from `window.location.origin` (`app/js/socket.js:websocketUrl`)
and honors a URL prefix through `BasePathMiddleware`
(`server/base_path.py`), which injects `window.__TR_BASE__` consumed by
`app/js/base-path.js`. Loading the origin directly means:

- The server's `Origin` check (`server/security.py:validate_origin`) sees the
  site's own origin and passes.
- The `SameSite=Lax` session cookies set in `server/app.py:_set_session_cookies`
  are first-party and persist in the WebView cookie store.
- No CORS work, no cookie work, no per-request host plumbing.

The modern-browser floor is ES2020 syntax plus import maps
(`app/index.html`), i.e. Android System WebView 89+ and iOS 16.4+. The existing
`app/js/boot-guard.js` renders a diagnostic overlay on older engines.

## 2. Store-approval reality

| Requirement | Applies? | Current state | Action |
| --- | --- | --- | --- |
| Account deletion (in-app + external web resource) | Yes — the app creates accounts | Missing | Add endpoint + pages ([§6.1](#61-account-deletion-and-privacy)) |
| UGC policy: report + block + moderation contact | Yes — room chat and custom stickers are user-generated | Partial: `moderator`/mute/kick powers exist (`server/services/powers.py`), but no user-facing report/block | Add minimal report/block ([§6.2](#62-ugc-safeguards)) |
| Privacy policy, in-app and store link | Yes | Missing | Add `/privacy` page ([§6.1](#61-account-deletion-and-privacy)) |
| Real-money purchases / IAP | No — Bops are earned only (`server/services/shop.py`, `server/services/prop_shop.py`); no payment code exists | — | None |
| Sign in with Apple | No — username/password only | — | None |
| Apple 4.2 Minimum Functionality | Yes — the top risk for a WebView shell | Shell is thin by design | Accepted; mitigation ladder in [§8](#8-phased-delivery) |
| Google Play "Webview Spam / Limited Functionality" | Low — the policy permits a webview of the owner's own site; the risk is a bare frame | — | Native menu, offline handling, and settings keep it from being a bare frame |
| Cleartext traffic | No — public HTTPS everywhere | — | `usesCleartextTraffic=false`; ATS default |

> [!WARNING]
> With "absolute minimum" native functionality there is a genuine risk that
> Apple rejects the first submission under App Review Guideline 4.2. The plan is
> structured so a rejection can be rescued cheaply (biometric app-lock, then
> push) without reworking the shell.

## 3. Repository layout

```
clients/
  README.md                     # shared behavior contract, build/run instructions
  android/                      # Kotlin, Gradle Kotlin DSL, version catalog
    settings.gradle.kts
    build.gradle.kts
    gradle.properties
    app/
      build.gradle.kts
      src/main/AndroidManifest.xml
      src/main/java/com/febret/tinyrooms/
        MainActivity.kt          # Activity + WebView + toolbar + overlay states
        ShellWebViewClient.kt    # navigation policy, errors, SSL policy
        ShellChromeClient.kt     # mic permission bridge, window.open
        AppSettings.kt           # SharedPreferences-backed settings
        ServerChooserActivity.kt # first-run + settings screen
        UrlPolicy.kt             # same-host vs external classification
      src/debug/                 # WebView debugging + self-signed cert bypass
      src/main/res/              # icons, strings, theme
  ios/
    project.yml                  # XcodeGen spec (no .pbxproj committed)
    Tinyrooms/
      TinyroomsApp.swift
      WebViewContainer.swift      # UIViewRepresentable
      WebViewModel.swift          # WKNavigationDelegate + WKUIDelegate
      AppSettings.swift
      SettingsView.swift          # first-run + settings sheet
      UrlPolicy.swift
      Info.plist
      Assets.xcassets
    TinyroomsUITests/
.github/workflows/android.yml    # ubuntu: build/test APK/AAB, optional Play upload
.github/workflows/ios.yml        # macos-14: xcodegen + xcodebuild + TestFlight
doc/mobile-clients-plan.md       # this document
```

`clients/README.md` holds the shared shell contract: a state machine
`Setup -> Loading -> Ready` with `Offline`/`Error` overlays, a settings model
`{ serverUrl, keepAwake, allowSelfSigned }` (`allowSelfSigned` is debug-only),
the default `serverUrl`, and one native overflow menu with `Reload`,
`Server...`, `Open in browser`, `Privacy`, `Delete account`, `Sign out`, and
`About`.

## 4. Android shell (Kotlin)

- `minSdk 26`, `targetSdk 36`, JDK 17, a single `app` module, AndroidX only
  (Core, AppCompat, Material, WebKit). Package `com.febret.tinyrooms`.
- `MainActivity` renders a slim native `MaterialToolbar` (overflow menu provides
  native chrome), a full-screen `WebView`, and a native `FrameLayout` overlay for
  offline and error states (never the browser error page).
- `ShellWebViewClient`:
  - `shouldOverrideUrlLoading`: same host as `serverUrl` stays in the WebView;
    other `http`/`https`/`mailto`/`tel` open via `Intent.ACTION_VIEW`.
  - `onReceivedError` (main frame) transitions to `Offline`; `onPageFinished`
    transitions to `Ready`.
  - `onReceivedSslError`: cancel by default; `handler.proceed()` only in debug
    builds when `allowSelfSigned` is enabled, for local development.
- `ShellChromeClient`:
  - `onPermissionRequest` maps `RESOURCE_AUDIO_CAPTURE` to a runtime
    `RECORD_AUDIO` request, then grants or denies. WebView denies permission
    requests by default, which would silently break push-to-talk.
  - `setSupportMultipleWindows(false)` so `window.open` navigates in place.
- `AppSettings`:
  - `CookieManager.setAcceptCookie(true)`; cookies persist in the app's WebView
    data store. Call `flush()` in `onPause` for durability.
  - `webView.keepScreenOn = true` while the activity is resumed.
- Back navigation: `OnBackPressedCallback` dispatches a synthetic `Escape` via
  `evaluateJavascript` (driving the game's Escape ladder in `app/js/ui.js`), then
  `webView.goBack()` when possible, otherwise double-back-to-exit.
- `AndroidManifest.xml`: `INTERNET`, `ACCESS_NETWORK_STATE`, `RECORD_AUDIO`,
  `MODIFY_AUDIO_SETTINGS`; `android:usesCleartextTraffic="false"`;
  `android:configChanges="orientation|screenSize|keyboardHidden|uiMode"` to
  survive rotation; edge-to-edge via
  `WindowCompat.setDecorFitsSystemWindows(window, false)` so the existing
  `env(safe-area-inset-*)` rules and the viewport meta resolve on notched
  devices.
- Debug tooling: `WebView.setWebContentsDebuggingEnabled(true)`; an optional
  WebView-version check (`WebViewCompat.getCurrentWebViewPackage`) warning below
  Chromium 89.

## 5. iOS shell (Swift / SwiftUI)

- Minimum iOS 16.4, matching the import-map floor recorded in `AGENTS.md`.
- SwiftUI `@main` app with `WebViewContainer: UIViewRepresentable` wrapping
  `WKWebView`:
  - `WKWebsiteDataStore.default()` for persistent cookies.
  - `allowsInlineMediaPlayback = true`, JavaScript enabled, no ATS exceptions.
- `WebViewModel` implements `WKNavigationDelegate`, `WKUIDelegate`, and script
  messaging:
  - Same-host versus external policy identical to Android; external URLs open
    through `UIApplication.shared.open`.
  - `requestMediaCapturePermissionFor` (iOS 15+) grants capture after
    `AVAudioSession` record permission is obtained.
  - `alert`/`confirm`/`prompt` panels implemented (the app uses its own DOM
    dialogs in `app/js/dialogs.js`, but this is cheap insurance).
  - `createWebViewWith` loads `window.open` targets in the same WebView.
- `Info.plist`: `NSMicrophoneUsageDescription`,
  `ITSAppUsesNonExemptEncryption=false`, supported orientations, launch screen.
- No hardware back button: a native toolbar `Back` dispatches a synthetic
  `Escape`. `UIApplication.shared.isIdleTimerDisabled = true` keeps the screen
  awake while active.
- `project.yml` drives XcodeGen so no `.pbxproj` is committed or hand-merged.

## 6. Server work (store-approval blockers)

### 6.1 Account deletion and privacy

- `POST /api/auth/delete` — authenticated, requires `Origin` plus
  `X-CSRF-Token`, and password re-entry. Purge order:
  1. Account-owned **world-database** rows: bedroom door and `world.room_states`
     (`mods/infinite-bedrooms/`), room ownership, room-layout locks, memories
     (`server/services/memories.py`), prop unlocks, and pack purchases.
  2. The profile account row; the `accounts` foreign keys already
     `ON DELETE CASCADE` (`server/state/migrations.py`).
  3. Revoke sessions, push `session.replaced`, clear cookies.
- `/privacy` — static HTML served by the world server; linked from the native
  menu and used as the store privacy-policy URL. Include moderation contact
  information for the UGC policies.
- `/delete-account` — a public (no login) web resource for the store
  "Delete account URL" form field, satisfying users who already uninstalled.
- The native `Delete account` menu item loads `/delete-account` (or calls the
  endpoint after native confirmation), providing the required in-app path.

### 6.2 UGC safeguards

Both stores require apps with user-generated content and chat to provide
filtering, reporting, blocking, and moderator contact.

- Report: an endpoint or command to flag a chat message or a user; persist to a
  moderation table; surface through the existing admin console
  (`server/commands/admin.py`) and audit log.
- Block: a per-account block list; the server filters blocked accounts from chat
  presence and events.
- Keep the implementation deliberately small: one table, two endpoints, one
  admin listing, and published contact details on `/privacy`.

## 7. Local testing plan (Android tablet focus)

### 7.1 Build and install loop

1. `./gradlew installDebug` over USB, or `adb install -r app-debug.apk`;
   confirm with `adb devices`.
2. Validate the happy path against the production default
   (`https://tinyrooms.febret.com/home`) first.
3. Local-server iteration:
   - Run `python run.py --host 0.0.0.0` on the development PC.
   - Use `adb reverse tcp:5000 tcp:5000` and set the app server URL to
     `https://127.0.0.1:5000` with the debug self-signed bypass enabled.
   - For a second physical device on Wi-Fi, use the LAN IP. A wildcard bind
     already accepts same-port HTTPS origins
     (`server/security.py:_is_same_port_https_origin`).
4. Debug JavaScript with desktop Chrome at `chrome://inspect`; read native logs
   with `adb logcat -s Tinyrooms:V chromium:V`.

### 7.2 Manual smoke checklist (on the tablet)

- First run shows the server chooser with the default pre-filled.
- Create account, complete the mandatory Sticker Designer, enter the world.
- Navigate rooms, chat, pick up and drop cards, open an activity, play a
  cutscene.
- Voice: the mic prompt appears; push-to-talk works with a second client; a deny
  degrades cleanly.
- Rotation and backgrounding keep the session; force-stop then relaunch stays
  logged in (cookie persistence).
- Airplane mode shows the native offline overlay; Retry recovers after
  reconnect.
- External links open the system browser; back gestures work; the screen stays
  awake in a room.
- Delete account -> confirm -> logged out and login fails afterwards.
- Optional: the old-WebView warning path.

### 7.3 Automation

- Maestro flows cover launch, first-run chooser, settings, open-external,
  offline toggle, and the delete-account link. Maestro runs on the tablet and,
  from the CI Mac, on the iOS simulator.
- Server: add `unittest` cases for the delete and report endpoints (auth, CSRF,
  cascade correctness) and keep the existing suites green
  (`python -m unittest discover -s tests`, `npm test`).
- The web visual baselines are unchanged and remain authoritative. Do not add
  mobile pixel baselines initially, because device rendering varies; capture
  tablet screenshots as review artifacts only.

### 7.4 iOS without a Mac

- `.github/workflows/ios.yml` on `macos-14`: `xcodegen generate`, then
  `xcodebuild build test` on a simulator, then Fastlane uploads to TestFlight
  using an App Store Connect API key (`.p8`).
- Requires Apple Developer Program membership and CI secrets (API key plus
  issuer and key id). Manual iPhone testing happens through TestFlight;
  otherwise use simulator screenshots from CI.

## 8. Phased delivery

| Phase | Work | Exit criteria |
| --- | --- | --- |
| P0 | Server: delete endpoint, `/privacy`, `/delete-account`, UGC report/block, tests | Existing suites green; new tests pass |
| P1 | Android shell: settings, WebView, mic, offline, back, keep-awake, external links, debug tooling | Happy path plus smoke checklist pass on tablet |
| P2 | Android internal-testing release and Maestro smoke | Play internal-track build installed on tablet |
| P3 | iOS shell, XcodeGen, macOS CI, TestFlight | CI build/test green; TestFlight build installs |
| P4 | Store metadata, privacy and data-safety forms, screenshots, review notes, submission | Submitted to both stores |

### 8.1 4.2 rescue ladder (only if Apple rejects)

1. Biometric app-lock (`BiometricPrompt` on Android, Face ID / Touch ID on iOS):
   roughly one file per platform and no server work.
2. Push notifications (APNs plus FCM, a server use case, and permission
   prompts) if still rejected.

## 9. Risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Apple 4.2 minimum functionality rejection | High | Accepted with eyes open; rescue ladder in [§8](#8-phased-delivery) |
| UGC and chat moderation requirement | High | [§6.2](#62-ugc-safeguards) is store-blocking; do it in P0 |
| Account deletion spanning two SQLite databases | Medium | Explicit purge order plus cascade tests ([§6.1](#61-account-deletion-and-privacy)) |
| WebRTC voice needs TURN off-LAN | Medium | Add TURN to `TRSERVER_STUN_URLS`; otherwise voice is LAN-only |
| WebGL context loss kills the board (`app/js/board.js` handles `webglcontextlost` but not `webglcontextrestored`) | Medium | Optional upstream client fix; otherwise offer a reload prompt |
| No-Mac iOS iteration is slow | Medium | CI artifacts plus TestFlight; simulator tests in CI |
| Self-signed certificates on local dev | Low | Debug-only bypass, never in release |
| `/home` origin allowlist | Low | Confirm `TRSERVER_PUBLIC_ORIGIN` includes `https://tinyrooms.febret.com` on the production instance |

## 10. Open items

1. Confirm the production instance sets
   `TRSERVER_PUBLIC_ORIGIN=https://tinyrooms.febret.com`, which the WebSocket and
   POST `Origin` checks require.
2. UGC scope: implement minimal report and block, or restrict chat to friends
   and document that choice. The default plan implements report and block.
3. Decide which compliance pages live on the game server versus a separate static
   host.
4. Confirm Google Play and Apple Developer accounts exist, since CI signing and
   the store URLs depend on them.
