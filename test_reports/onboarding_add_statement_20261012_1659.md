# Onboarding: "Upload a statement" must reach the upload step for an onboarded user

Date: 2026-10-12 · Area: `frontend-v5/src/pages/Onboarding`, upload links in Dashboard and Portfolio.

## Problem

Every in-app upload action navigates to `/onboarding`. That page redirected to `/lite`
whenever the account had `onboarding_completed = true`, ignoring `?tab=upload`. An
onboarded account with 0 holdings (seen on staging after a failed CAS import) had no way
back to the upload step.

## Change

`/onboarding?tab=upload|gmail|otp` is treated as an explicit request to add a statement:
no redirect, skip the persona step, preselect the method. Returning from the Gmail consent
screen is exempt from the redirect too. The Dashboard and Portfolio empty-state buttons
now pass the `tab` parameter.

## Test cases

| # | Case | Expected |
|---|---|---|
| TC1 | Onboarded user opens `/onboarding` with no intent | Redirect to `/lite` (unchanged) |
| TC2 | Onboarded user opens `/onboarding?tab=upload` | Stays; connect step shown; file input present |
| TC3 | Onboarded user opens `/onboarding?tab=gmail` | Stays; connect step shown |
| TC4 | Not-onboarded user opens `/onboarding` | Stays on the persona step (unchanged) |

## Playwright output

Runner: `frontend-v5/e2e/tools/onboarding-add-statement-check.py` (Playwright 1.49, Chromium).

**MOCK — not real data.** Every `/api/**` call is intercepted and answered from the repo
fixture `frontend-v5/e2e/fixtures/user-profile-charting.json`. This exercises the page's
routing logic only; it does not prove backend behaviour or a real upload.

Before (deployed staging frontend, old code):
```
TC1 onboarded, /onboarding (no intent)                     → url=/v5/lite                     connect_step=False file_input=0
TC2 onboarded, /onboarding?tab=upload                      → url=/v5/lite                     connect_step=False file_input=0
TC3 onboarded, /onboarding?tab=gmail                       → url=/v5/lite                     connect_step=False file_input=0
TC4 NOT onboarded, /onboarding (persona step first)        → url=/v5/onboarding               connect_step=False file_input=0
RESULT: 2 FAILED
```

After (image built from the patched tree; `tsc -b && vite build` exit 0):
```
TC1 onboarded, /onboarding (no intent)                     → url=/v5/lite                     connect_step=False file_input=0
TC2 onboarded, /onboarding?tab=upload                      → url=/v5/onboarding?tab=upload    connect_step=True file_input=1
TC3 onboarded, /onboarding?tab=gmail                       → url=/v5/onboarding?tab=gmail     connect_step=True file_input=0
TC4 NOT onboarded, /onboarding (persona step first)        → url=/v5/onboarding               connect_step=False file_input=0
RESULT: ALL PASS
```

## Staging API

No backend route or service changed. The page reads `GET /api/onboarding/state`; on staging
the edge log shows it answering 200 for the signed-in account.

## Not verified

- A real upload by a signed-in user on staging (needs a real session and statement).
- The repo's own `npx playwright test` suite was not run; Node is not installed on this host.

## Verdict: PASS
