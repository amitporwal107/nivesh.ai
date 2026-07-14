# Functionality Verification Report — Lite Copilot surface + Goal/Risk onboarding

- **Branch:** feat/copilot-backtest
- **Date:** 2026-07-12
- **Author:** Claude (Full-Stack Developer)
- **Environment:** local Vite dev server with mocked APIs (the repo's Playwright
  harness — `auth/me` faked by `mockApi`, no real session token needed) + local
  typecheck/build. NOT verified on live staging (see "Inputs required").
- **Changed areas:** backend routes/services: **no** · frontend src: **yes**

## Summary
Two connected frontend changes toward the "lite" product journey
**Login → Connect → Goal → Risk → Copilot**, all additive/reversible:

1. **Lite Copilot surface (`/lite`)** — a URL-pattern-gated surface exposing
   ONLY the Copilot chat, no dashboard chrome. New `LiteLayout.tsx` (no Sidebar,
   ticker, mobile nav, or CopilotDock) + a `/lite` route mounting the existing
   self-contained `ChatPage`. The full app at every other route is untouched.

2. **Goal & Risk as OPTIONAL onboarding steps** — after Connect, onboarding
   enters a `profile` phase that reuses the shared `ProfileWizardModal` scoped to
   Risk + Goal only (new backward-compatible `lastStep` prop; default `2` keeps
   the 3 existing callers — Dashboard/Settings/Goals — unchanged). Both steps are
   **skippable** (never mandatory, per the explicit request), and finishing OR
   skipping/closing lands the user in the Copilot (`/lite`). Saves go to the real
   endpoints `POST /api/user/risk-profile` and `POST /api/goals` (no mock data).
   Additionally, already-onboarded users hitting `/onboarding` are now redirected
   to `/lite` (was `/dashboard`).

3. **`/lite` onboarding gate (`RequireOnboarded`)** — a signed-in but NOT-yet-
   onboarded user on `/lite` is routed to `/onboarding` first (which is where CAS
   upload + Gmail sync live), then back to `/lite`. Loop-safety: on the way back
   the flow marks onboarding complete (`POST /api/user/complete-onboarding`) and
   flips the cached `useMe` flag synchronously (also fixes a real-app stale-cache
   bounce, since `/onboarding` has no active `useMe` observer).

4. **Connect-step bug fixes** (from live-staging errors):
   - **Gmail import** showed *"Import failed: 200"* — the backend returns the real
     reason in `parse_error.{message,detail}` (HTTP 200, `ok:false`), but the UI
     only read a top-level `message`. Now surfaces the actual reason (and handles
     the "no CAS emails / 0 holdings" case).
   - **CAS upload** was wired to `POST /api/portfolio/upload` (CSV/Excel-only —
     **410s PDFs**). Rewired the onboarding UploadPanel to the in-house parser
     `POST /api/onboarding/upload-cas` (saves PAN → multipart file), with real
     422/415/413 error surfacing.
   - NOT fixed here (external): the Google OAuth 403 (app unverified / test-user)
     — Google Console action, no code change possible.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | /lite render | Visit `/lite` (authed via mock) → Copilot mounts | e2e | "New chat" control visible | PASS |
| TC-2 | /lite chrome-off | Visit `/lite` → no dashboard chrome | e2e | 0 × `nav[aria-label="Primary"]` (desktop Sidebar + mobile nav both absent) | PASS |
| TC-3 | /chat control | Same page at `/chat` still has chrome | e2e | 2 × `nav[aria-label="Primary"]`, Sidebar visible | PASS |
| TC-4 | Onboarding step | persona → connect → "Continue · Goals & Risk" opens the wizard, scoped to Risk + Goal, NO Snapshot | e2e | "Complete your profile" + "Risk profile" + "What's your risk tolerance?" visible; "Snapshot (optional)" count 0 | PASS |
| TC-5 | Optional / lands in Copilot | Skip Risk → skip Goal → finish → lands in Copilot | e2e | URL `…/v5/lite`, "New chat" visible | PASS |
| TC-6 | Already-onboarded redirect | Onboarded user hits `/onboarding` → redirected to Copilot | e2e | URL `…/v5/lite`, "New chat" visible | PASS |
| TC-7 | Onboarding gate | NOT-onboarded user hits `/lite` → routed to onboarding; CAS upload + Gmail sync visible | e2e | URL `…/v5/onboarding`; "Gmail CAS Import" + "CAS Upload · NSDL / CDSL" visible | PASS |
| TC-8 | No redirect loop | NOT-onboarded user goes through onboarding + skips → lands in `/lite` (stateful: `onboarded` flips on `complete-onboarding`) | e2e | URL `…/v5/lite`, "New chat" visible | PASS |
| TC-9 | Gmail error surfacing | auto-import returns 200 `{ok:false, parse_error}` → UI shows the reason | e2e | "The CAS statement couldn't be read." visible; no "Import failed: 200" | PASS |
| TC-10 | CAS upload endpoint | Upload PDF → posts to `/api/onboarding/upload-cas` (NOT `/api/portfolio/upload`), imports holdings | e2e | request URL contains `/api/onboarding/upload-cas`; "5 holdings imported" + continue visible | PASS |
| TC-11 | CAS upload error surfacing | upload-cas 422 `{detail}` → UI shows the detail | e2e | "Couldn't parse this CAS PDF…" visible | PASS |
| TC-12 | Compile | `tsc --noEmit` | type | Exit 0 | PASS |
| TC-13 | Buildable + no regression to wizard's 3 existing callers | `tsc -b && vite build` | build | Exit 0 | PASS |

## API / Endpoint Tests (staging)
> N/A — no backend routes/services changed. Frontend-only. The onboarding wizard
> reuses existing endpoints (`/api/user/risk-profile`, `/api/goals`) whose
> contracts are unchanged.

## UI / Playwright Tests
- **Specs:** `frontend-v5/e2e/tests/lite-copilot.spec.ts`,
  `frontend-v5/e2e/tests/onboarding-goal-risk.spec.ts`
  - Command: `npx playwright test e2e/tests/lite-copilot.spec.ts e2e/tests/onboarding-goal-risk.spec.ts --project=desktop-chrome --reporter=list`
  - Output (real, unedited):
    ```
    Running 11 tests using 2 workers
      ✓ /lite hides the dashboard sidebar (no app chrome) (6.9s)
      ✓ /lite renders the Copilot (6.9s)
      ✓ NOT-onboarded user on /lite is routed to onboarding (CAS upload / Gmail sync) (3.6s)
      ✓ CONTROL: /chat renders the SAME Copilot WITH the sidebar (4.2s)
      ✓ Goal & Risk appear as onboarding steps — Risk + Goal only (no Snapshot) (3.3s)
      ✓ Gmail import failure surfaces the REAL reason (not 'Import failed: 200') (3.2s)
      ✓ CAS upload posts to the in-house parser (/api/onboarding/upload-cas) and imports holdings (3.4s)
      ✓ CAS upload failure surfaces the real reason (422 detail) (3.0s)
      ✓ Already-onboarded users hitting /onboarding are redirected to the Copilot (/lite) (3.1s)
      ✓ NOT-onboarded user completes onboarding by skipping → lands in /lite, no loop (3.9s)
      ✓ Both steps are OPTIONAL — skipping through lands in the Copilot (/lite) (2.7s)
      11 passed (27.4s)
    ```
  - Result: PASS
- **Typecheck:** `npx tsc --noEmit` → `EXIT: 0` — PASS
- **Build:** `npm run build` (`tsc -b && vite build`) → `✓ built in 25.62s` / `EXIT: 0`
  (pre-existing chunk-size warning only) — PASS
- **Also verified on `origin/dev` codebase** (isolated worktree = dev + change):
  `tsc --noEmit` 0, `vite build` 0, `8 passed`. **Shipped to `origin/dev`** in
  two fast-forward commits — `fa508127` (/lite + onboarding) and `f69bc1da`
  (/lite onboarding gate). Both staging frontend deploy Actions **completed /
  success**; `/v5/lite` serves HTTP 200.

## Data Correctness (staging)
> N/A locally. The wizard's real save paths (`/api/user/risk-profile`,
> `/api/goals`) are exercised on the SKIP path here (no writes). Verifying an
> actual saved risk profile + goal row requires live staging (see below).

## Inputs required from user
- **Behind-auth staging verify** of `/v5/lite` + onboarding writing a real risk
  profile/goal needs a fresh **session_token** cookie. Not done this turn.
- **External blocker (NOT a code bug):** on live staging, Gmail sync fails at
  Google's consent screen — *"Error 403: access_denied — niveshcopilot.com has
  not completed the Google verification process; only developer-approved testers
  can access."* The app requests the **restricted** scope `gmail.readonly`; the
  OAuth client is in Testing/unverified status and `amit.porwal@gmail.com` is not
  an approved test user. Fix is in **Google Cloud Console** (add the account as a
  Test user, or submit the app for OAuth verification) — outside this repo; I
  have no Console access. The onboarding gate itself works (it routed the
  not-onboarded user into the Connect step, which is where the Google block hit).
- **CAS upload error** reported by the user is a **separate** path
  (`POST /api/onboarding/upload-cas`) — need the actual error + a session_token
  to reproduce and diagnose. Not investigated this turn.

## Verdict: PASS
