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

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | /lite render | Visit `/lite` (authed via mock) → Copilot mounts | e2e | "New chat" control visible | PASS |
| TC-2 | /lite chrome-off | Visit `/lite` → no dashboard chrome | e2e | 0 × `nav[aria-label="Primary"]` (desktop Sidebar + mobile nav both absent) | PASS |
| TC-3 | /chat control | Same page at `/chat` still has chrome | e2e | 2 × `nav[aria-label="Primary"]`, Sidebar visible | PASS |
| TC-4 | Onboarding step | persona → connect → "Continue · Goals & Risk" opens the wizard, scoped to Risk + Goal, NO Snapshot | e2e | "Complete your profile" + "Risk profile" + "What's your risk tolerance?" visible; "Snapshot (optional)" count 0 | PASS |
| TC-5 | Optional / lands in Copilot | Skip Risk → skip Goal → finish → lands in Copilot | e2e | URL `…/v5/lite`, "New chat" visible | PASS |
| TC-6 | Compile | `tsc --noEmit` | type | Exit 0 | PASS |
| TC-7 | Buildable + no regression to wizard's 3 existing callers | `tsc -b && vite build` | build | Exit 0 | PASS |

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
    Running 5 tests using 2 workers
      ✓ /lite hides the dashboard sidebar (no app chrome) (12.1s)
      ✓ /lite renders the Copilot (12.8s)
      ✓ Goal & Risk appear as onboarding steps — Risk + Goal only (no Snapshot) (3.5s)
      ✓ CONTROL: /chat renders the SAME Copilot WITH the sidebar (4.3s)
      ✓ Both steps are OPTIONAL — skipping through lands in the Copilot (/lite) (2.5s)
      5 passed (28.8s)
    ```
  - Result: PASS
- **Typecheck:** `npx tsc --noEmit` → `EXIT: 0` — PASS
- **Build:** `npm run build` (`tsc -b && vite build`) → `✓ built in 25.62s` / `EXIT: 0`
  (pre-existing chunk-size warning only) — PASS

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
