# Functionality Verification Report — Android app: open on the Copilot, V5 native shell

- **Branch:** feat/android-v5-native-shell (from origin/dev 82580088)
- **Date:** 2026-10-31
- **Author:** Claude (Full Stack Developer + Design Engineer + QA)
- **Environment:** local production build of the web bundle (Vite preview, mocked API) + Android debug APK built in `nivesh/android-builder:local`; staging was the baseline for the comparison that found the gaps
- **Changed areas:** backend routes/services: no · frontend src: yes (`src/routes.tsx`) · Android native resources: yes

## Summary

The Android app (Capacitor APK) bundles the same web code as /v5/app (100 of 100 code chunks identical
to staging after normalising the base path), but two things differ from the /v5/app baseline and from the
owner's Android design system (`docs/Android design system files.zip`, V5 tokens):

1. **Launch screen.** The APK opened at `/`, the public marketing homepage, even for a signed-in user.
   On a native device `/` now redirects to `/app`; `RequireAuth` already sends a signed-out user to
   `/login`. The web homepage is unchanged.
2. **Native shell.** The APK still wore Capacitor's template: a white splash with the Capacitor logo,
   the Capacitor launcher icon, and stock AppCompat colours. It now uses the design system's dark surface
   `#06080F` (`nv_bg_0`) for the status bar, navigation bar, window and splash, and the V5 "न" mark
   (mint `#6AF0A8` → `#36C57E`, ink `#06120B`, as `.nv-mark` in `src/index.css`) for the launcher icon
   and splash. The palette sits in `values/` only (not `values-night/` as in the design system's XML),
   because the web app is dark by default and switches theme in-app, not with the system.

The previous spec case "TC-7 homepage still renders at / in the native build" asserted the old launch
behaviour (added 2026-10-21 as the smallest change at the time); it is replaced by TC-7/TC-8/TC-9 below.

Out of scope (need the owner's decision first): broker sign-in returning into the app, the live price
stream without the session cookie, a "new version" notice for the APK, and a status-bar colour that
follows the in-app light theme (needs the `@capacitor/status-bar` plugin).

## Test Cases

> Authored UP FRONT — before implementation. Spec IDs in brackets.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Launch | Native (androidBridge), signed in, open `/` [spec TC-7] | e2e | Lands on `/app`, the marketing homepage is not shown | PASS |
| TC-2 | Launch | Native, signed out (`/api/auth/me` 401), open `/` [spec TC-8] | e2e | Lands on `/login` with the email form | PASS |
| TC-3 | Launch | Web (no androidBridge), open `/` [spec TC-9] | e2e regression | Marketing homepage still renders, URL stays `/` | PASS |
| TC-4 | Sign-in | Existing cases [spec TC-3..TC-6]: web sign-in → `/dashboard`, native sign-in → `/app`, research-only → `/research`, login form unchanged | e2e regression | All pass unchanged | PASS |
| TC-5 | Types | `tsc --noEmit` on the worktree | build | No errors | PASS |
| TC-6 | Native build | `vite build` + `cap sync android` + `./gradlew assembleDebug` | build | APK builds | PASS |
| TC-7 | Native theme | `aapt2 dump resources` of the built APK | static | Status bar / navigation bar / window background = `#06080F`; launch splash background `#06080F`; mint primary | PASS |
| TC-8 | Native assets | Replaced splash and icon PNGs keep their pixel sizes; images show the mark | static/visual | 26 of 26 same size; dark splash with the mint "न" tile, mint icon | PASS |
| TC-9 | Device | Status bar colour, splash and icon on a real phone | device | — | UNVERIFIED (no device or emulator on this VM) |

## UI / Playwright Tests

- **Spec:** `frontend-v5/e2e/tests/login-native-destination.spec.ts` (project `unauthenticated`)
  - Command (Docker `mcr.microsoft.com/playwright:v1.60.0-jammy`, `--network none`):
    `VITE_USE_MOCK_API=false VITE_BASE=/v5/ npx vite build --outDir /tmp/cp-dist` →
    `VITE_BASE=/v5/ npx vite preview --outDir /tmp/cp-dist --port 5174 --strictPort &` →
    `npx playwright test e2e/tests/login-native-destination.spec.ts --project=unauthenticated --reporter=list`
  - Output:
    ```
    ✓  1 [unauthenticated] › …:59:1 › TC-4 web sign-in still lands on /dashboard (1.3s)
    ✓  2 [unauthenticated] › …:65:1 › TC-3 native sign-in lands on /app (one-screen Copilot) (1.6s)
    ✓  3 [unauthenticated] › …:72:1 › TC-5 research-only user still lands on /research (native) (999ms)
    ✓  4 [unauthenticated] › …:79:1 › TC-6 login screen is unchanged in the native build (777ms)
    ✓  5 [unauthenticated] › …:90:1 › TC-7 the native app opens on /app, not the marketing homepage (716ms)
    ✓  6 [unauthenticated] › …:98:1 › TC-8 a signed-out native launch goes to the login screen (780ms)
    ✓  7 [unauthenticated] › …:107:1 › TC-9 the web homepage still renders at / (607ms)
      7 passed (5.0s)
    ```
  - Note: the first attempt against the Vite dev server (`webServer`) failed all 7 cases on a blank page,
    the four untouched ones included; the dev server does not finish its first compile within the
    5 s assertions on this VM. Against the production build all 7 pass.
  - Result: PASS
- **Typecheck:** `npx tsc --noEmit -p tsconfig.json` → `tsc: 0 errors` — PASS

## Native build

- Command (Docker `nivesh/android-builder:local`, JDK 17, build-tools 34.0.0):
  `vite build` → `npx cap sync android` (`✔ update android`, `Sync finished in 0.33s`) →
  `./gradlew assembleDebug --no-daemon` → `app-debug.apk` 14,798,104 bytes (the sparse worktree has no
  tour videos, hence smaller than the published APK).
- `aapt2 dump badging`: `package: name='ai.nivesh.staging' versionCode='202610319' versionName='2026.10.31-shell'`,
  `application: label='Nivesh (Staging)' icon='res/mipmap-anydpi-v26/ic_launcher.xml'`.
- `aapt2 dump resources` (0x01010054 = windowBackground, 0x01010451 = statusBarColor, 0x01010452 = navigationBarColor):
  ```
  resource 0x7f0e0005 style/AppTheme
    colorAccent=@color/nv_mint  colorPrimary=@color/nv_mint  colorPrimaryDark=@color/nv_bg_0
  resource 0x7f0e0006 style/AppTheme.NoActionBar
    0x01010054=@color/nv_bg_0  0x010100d4=@null  0x01010451=@color/nv_bg_0  0x01010452=@color/nv_bg_0
  resource 0x7f0e0007 style/AppTheme.NoActionBarLaunch
    0x010100d4=@drawable/splash  windowSplashScreenBackground=@color/nv_bg_0
  color/nv_bg_0 #ff06080f · color/nv_mint #ff6af0a8 · color/nv_mint_2 #ff36c57e · color/ic_launcher_background #ff6af0a8
  res/mipmap-anydpi-v26/ic_launcher.xml background → drawable/nv_icon_background (res/drawable/nv_icon_background.xml)
  ```
- PNG sizes: `26 PNGs replaced, 26 keep their original pixel size`.
- Result: PASS (build and resources). How it looks on a phone: UNVERIFIED.

## Data Correctness (staging)

Not applicable: no data path changes. The launch redirect relies on `/api/auth/me`, which `RequireAuth`
already uses for every `/app` screen.

## Inputs required from user

- none

## UNVERIFIED

- On a real phone: status bar and navigation bar colour, the Android 12+ system splash (dark background +
  the new adaptive icon), and the launcher icon in the owner's launcher shape. Needs the APK installed on a
  device after merge (CI publishes it on every push to `dev`).

## Verdict: PASS
