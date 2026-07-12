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
| TC-9 | Compile | `tsc --noEmit` | type | Exit 0 | PASS |
| TC-10 | Buildable + no regression to wizard's 3 existing callers | `tsc -b && vite build` | build | Exit 0 | PASS |

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
    Running 8 tests using 2 workers
      ✓ /lite hides the dashboard sidebar (no app chrome) (6.7s)
      ✓ /lite renders the Copilot (7.0s)
      ✓ NOT-onboarded user on /lite is routed to onboarding (CAS upload / Gmail sync) (3.2s)
      ✓ CONTROL: /chat renders the SAME Copilot WITH the sidebar (4.0s)
      ✓ Goal & Risk appear as onboarding steps — Risk + Goal only (no Snapshot) (3.0s)
      ✓ Already-onboarded users hitting /onboarding are redirected to the Copilot (/lite) (3.1s)
      ✓ NOT-onboarded user completes onboarding by skipping → lands in /lite, no loop (4.0s)
      ✓ Both steps are OPTIONAL — skipping through lands in the Copilot (/lite) (3.4s)
      8 passed (21.7s)
    ```
  - Result: PASS
- **Typecheck:** `npx tsc --noEmit` → `EXIT: 0` — PASS
- **Build:** `npm run build` (`tsc -b && vite build`) → `✓ built in 25.62s` / `EXIT: 0`
  (pre-existing chunk-size warning only) — PASS
- **Also verified on `origin/dev` codebase** (isolated worktree = dev + this
  change): `tsc --noEmit` exit 0, `vite build` exit 0, same 6 Playwright tests
  `6 passed (22.7s)`. Pushed as branch `feat/lite-copilot-onboarding` (1 commit,
  fast-forwards `dev`).

## Data Correctness (staging)
> N/A locally. The wizard's real save paths (`/api/user/risk-profile`,
> `/api/goals`) are exercised on the SKIP path here (no writes). Verifying an
> actual saved risk profile + goal row requires live staging (see below).

## Inputs required from user
- To verify on **live staging** (`staging.niveshcopilot.com/v5/lite` and the
  onboarding flow writing a real risk profile + goal) I'd need a fresh
  **session_token** cookie AND the change deployed there (app staging tracks the
  `dev` branch — a live deploy). Not done this turn.

## Verdict: PASS
