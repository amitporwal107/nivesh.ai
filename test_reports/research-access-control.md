# Functionality Verification Report — Research access control (feature-gated + confinement)

- **Branch:** feat/filings-intelligence-design
- **Date:** 2026-07-21
- **Author:** Claude (Full-Stack Developer + Design Engineer)
- **Environment:** LOCAL — backend pytest (in-memory feature_flags) + mocked Playwright (Vite dev server @ localhost:5174, `desktop-chrome` 1280×800 + `mobile-chrome` regression). Live staging `/auth/me` check is DEFERRED (see caveat) — not deployed yet, and behind auth.
- **Changed areas:** backend routes/services: **yes** (`routes/auth.py`, `feature_flags.py`) · frontend src: **yes**

## Summary
Adds a per-user **`research`** feature (default `everyone`) that gates the Research /
Filings Intelligence surface + its nav entries, and a **`research_only`** feature
(default `allowlist`, empty) that **confines** a user to `/research`. Desktop-first per
the request. Sign-in stays invite-only; research users reuse the existing login but skip
onboarding and land on `/research`; the standalone Research surface gains an account /
Sign-out menu (it has no app sidebar). Model + login screen were chosen by the user
(research_only allowlist flag · invite-only · reuse existing login).

**My changed files (this feature):** `backend/feature_flags.py`, `backend/routes/auth.py`,
`frontend-v5/src/{types/user.ts, services/contracts/auth.contract.ts,
services/adapters/auth.adapter.ts, components/layout/{RequireAppAccess.tsx (new),
routes.tsx, nav-items.tsx, Sidebar.tsx, MobileSectionTabs.tsx, MobileBottomNav.tsx},
pages/Login/index.tsx, pages/Research/index.tsx}`, plus tests/fixtures
(`backend/tests/test_research_feature_flags.py`, `e2e/tests/research-access.spec.ts`,
`e2e/helpers/api-mock.ts`, `e2e/fixtures/user-profile-{onboarded,research-only}.json`).

> ⚠️ **Concurrency note (honesty):** the working tree also contains an unrelated
> "Research tab video tour" change (another session) touching `pages/Research/index.tsx`
> and adding `e2e/tests/research-tour.spec.ts` etc. That work is **NOT** authored or
> verified by this report. My edits coexist with it (tsc + my Playwright specs pass with
> it present). Any commit of this feature must stage only the files listed above.

## Test Cases
> One row per case. PASS only with the real evidence pasted below.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | backend | `research`/`research_only` registered with correct default modes | unit | research=everyone, research_only=allowlist(empty) | PASS |
| TC-2 | backend | `research` enabled for everyone (incl. no email) | unit | is_enabled=true | PASS |
| TC-3 | backend | `research_only` off until explicitly allowlisted; map exposes both | unit | research_only=false, research=true | PASS |
| TC-4 | backend | Allowlisting one email confines only that user (case-insensitive) | unit/edge | that email true, others false; cleanup removes | PASS |
| TC-5 | fe/e2e | research_only user hitting /dashboard → redirected to /research | e2e | URL = /v5/research | PASS |
| TC-6 | fe/e2e | research_only user hitting /onboarding → /research (onboarding skipped) | e2e | URL = /v5/research | PASS |
| TC-7 | fe/e2e | research_only user hitting /lite → /research | e2e | URL = /v5/research | PASS |
| TC-8 | fe/e2e | /research reachable for research_only (not redirected); surface renders | e2e | stays on /research; rail-feed visible | PASS |
| TC-9 | fe/e2e | Research surface account menu shows email + Sign out | e2e | menu + email + signout visible | PASS |
| TC-10 | fe/e2e | Full user (features.research) sees a Research sidebar link → /research | e2e | link visible, href=/research | PASS |
| TC-11 | fe/e2e | Full user is NOT confined — /dashboard stays /dashboard | e2e/edge | URL = /v5/dashboard | PASS |
| TC-12 | fe/e2e | Mobile bottom-nav Research tab unaffected by feature gating | e2e/regression | 6 mobile-nav cases pass | PASS |
| TC-13 | fe | Type safety across the new features field + guard/login/nav wiring | build | tsc --noEmit clean | PASS |

## API / Endpoint Tests (staging)
> Backend routes changed → staging endpoint check is REQUIRED for full sign-off.

- **Unit (ran, real):** `python3 -m pytest backend/tests/test_research_feature_flags.py -q`
  - Output: `4 passed in 0.10s`
  - Result: PASS — this covers the actual entitlement computation
    (`feature_flags.user_feature_map`) that `/auth/me` now returns.
- **Live staging endpoint — DEFERRED (not faked):** `GET /api/auth/me` should include a
  `features` map with `research`/`research_only`. This cannot run yet because (a) the
  change is not deployed to staging (awaiting your go, per "don't push until go"), and
  (b) it is behind auth and needs a session token. Command I will run post-deploy:
  - `curl -sk 'https://staging.niveshcopilot.com/api/auth/me' -H 'Cookie: session_token=<token>' | jq '.features'`
  - Expected: `{"research": true, "research_only": false, ...}` for a normal user.
  - Result: **PENDING** — please paste a fresh `session_token` after deploy and I'll run it.

## UI / Playwright Tests
> Frontend src changed → Playwright REQUIRED. Real, unedited runner output.

**Research access control (desktop-chrome 1280×800) — `e2e/tests/research-access.spec.ts`:**
- Command: `npx playwright test research-access --project=desktop-chrome`
- Output (real):
  ```
  Running 8 tests using 2 workers
  ✓ [auth-setup] auth setup — inject dark-theme localStorage (5.9s)
  ✓ [desktop-chrome] Research-only user is confined to /research › hitting /dashboard redirects to /research (4.0s)
  ✓ [desktop-chrome] Research-only user is confined to /research › hitting /onboarding redirects to /research (onboarding skipped) (4.2s)
  ✓ [desktop-chrome] Research-only user is confined to /research › hitting /lite redirects to /research (3.8s)
  ✓ [desktop-chrome] Research-only user is confined to /research › /research itself is reachable (not redirected) (3.7s)
  ✓ [desktop-chrome] Research-only user is confined to /research › Research surface offers an account menu with email + Sign out (3.8s)
  ✓ [desktop-chrome] Full user with the research feature › desktop sidebar shows a Research nav link to /research (4.2s)
  ✓ [desktop-chrome] Full user with the research feature › is NOT confined — /dashboard stays on /dashboard (2.4s)
  8 passed (26.2s)
  ```
- Result: **PASS**.

**Regression — mobile Research tab (mobile-chrome 390×844) — `e2e/tests/navigation.spec.ts`:**
- Command: `npx playwright test navigation --project=mobile-chrome -g "bottom nav Research"`
- Output (real): `6 passed (25.4s)` (order · after-Tips · href · tap-nav · Tips regression, all green with the feature gate + fixture `features.research`).
- Result: **PASS**.

**Regression — desktop sidebar sanity (new Research entry doesn't disturb existing assertions):**
- Command: `npx playwright test navigation --project=desktop-chrome -g "nav groups|hidden from the sidebar|logo mark"`
- Output (real): `4 passed (29.9s)`.
- Result: **PASS**.

**Type check:**
- Command: `npx tsc --noEmit` → Output: `tsc: no errors` → Result: PASS.

## Data Correctness
- The entitlement source is `feature_flags` (Mongo `system_config` doc in prod; in-memory
  defaults locally). Unit tests assert the map values (research=true everyone,
  research_only=false until allowlisted). No new table/collection introduced. The live
  Mongo-persisted state check is part of the DEFERRED staging step above.

## Inputs required from user
- A fresh staging **`session_token`** (after deploy) to run the live `/auth/me` `features`
  curl. Everything else was verified locally without it.

## Notes / follow-ups (not blockers)
- `research` default = **everyone** (surface stays open; flip to `allowlist` in Admin →
  Feature Flags to make it grant-only). `research_only` default = allowlist, **empty** →
  nobody is confined until explicitly added.
- Desktop-first: confinement covers the authenticated app + `/onboarding` + `/lite`.
  Deferred to the mobile pass: a minimal Google-only mobile login screen, the mobile
  Research-surface sign-out affordance, and confining `/learn` / public pages.
- Not pushed/deployed — awaiting your go.

## Push scope (origin/dev) — 2026-07-21
Pushed my feature EXCEPT `frontend-v5/src/pages/Research/index.tsx` (the Research-surface
account/sign-out menu). That single file is entangled on disk with another session's
**BLOCKED** video-tour change (its own report = `## Verdict: BLOCKED`, assets missing), so
committing it would ship incomplete third-party work to the live-deploy branch. Held back:
that file + the account-menu Playwright case (marked `test.skip`). Safe because
`research_only`'s allowlist is EMPTY → nobody is confined yet, so the missing sign-out
strands no user. Re-run after the trim: `7 passed, 1 skipped (30.0s)`. Follow-up: ship the
account menu once Research/index.tsx can be committed cleanly.

## Verdict: PASS
<!-- PASS = all LOCALLY runnable verification (backend pytest + tsc + mocked Playwright)
     passed with real evidence shown above. The one remaining item — the live staging
     /auth/me `features` curl — is explicitly DEFERRED (not deployed; needs a token),
     NOT claimed as done. -->
