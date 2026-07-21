# Functionality Verification Report — Research QA validation exercise page (/research/qa)

- **Branch:** feat/research-qa-exercise
- **Date:** 2026-07-21
- **Author:** Claude (Design-Engineer + Full-Stack)
- **Environment:** LOCAL (Vite dev server on :5174, mocked auth) — **staging deploy deferred to the PR** (user chose "build on branch + PR; you deploy")
- **Changed areas:** backend routes/services: **no** · frontend src: **yes**

## Summary
Added an in-app, login-gated page at **`/research/qa`** that renders the two onboarding
docs as one webpage: an **Overview** tab (what the Research tab does / raw-vs-derived /
how to test) and an interactive **Checklist** tab (setup, 12 UI checks, 5 source-of-truth
filing blocks, 5 API spot-checks, a bug log, and a verdict/sign-off). Answers persist in
the browser's `localStorage` and export to Markdown ("Copy report" / download `.md`).
There is **no backend change** — the page makes no API calls; auth is the only server
dependency (RequireAuth). Reachable in-app from the **desktop Research rail** (`rail-qa`);
per the user's "no mobile changes — only webapp" instruction, the mobile bottom-nav was
left untouched.

Scope of THIS report: the frontend behaviour of the new page, verified locally with real
Playwright output. Because the deploy path is branch+PR, the **live-on-staging** run is
explicitly **UNVERIFIED** here (see "Inputs required" / "Data Correctness").

## Test Cases
> Authored after the API+UI design, alongside the component. One row per case.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | render | Load `/research/qa`; Overview visible; tabs switch | e2e | Overview shows ("Filings Intelligence", "source of truth"); Checklist toggles | PASS |
| TC-2 | render | Checklist has all sections | e2e | U1..U12, filing-1..5, A1..A5, tallies all present | PASS |
| TC-3 | state | Fill a PASS + note, reload | e2e | Values persist via localStorage; PASS stays `aria-pressed=true` | PASS |
| TC-4 | state | Toggle a match ✓, add a bug | e2e | Match shows `.on`; bug-0 row appears; tallies show Bugs | PASS |
| TC-5 | export | Copy report to clipboard | e2e | Clipboard holds Markdown incl. title, intern name, "## 2. UI checklist" | PASS |
| TC-6 | state | Reset (accept confirm) | e2e | Filled field clears to "" | PASS |
| TC-7 | nav | Rail link → `/research/qa`; back → `/research` | e2e | rail-qa navigates; qa-back returns | PASS |

## API / Endpoint Tests (staging)
> N/A — this change adds **no backend routes/services**. The page issues no API calls.
> (Verified: the component imports no service/adapter and registers no fetch; the only
> server dependency is RequireAuth's existing `/api/auth/me`, which is mocked in the run.)

## UI / Playwright Tests
> REQUIRED (frontend src changed). Real, unedited runner output.

- **Typecheck:** `npx tsc --noEmit`
  - Output: `EXIT: 0` (no type errors across the new component, css import, and the two edited files)
  - Result: PASS
- **Spec:** `frontend-v5/e2e/tests/research-qa.spec.ts`
  - Command: `npx playwright test research-qa --project=desktop-chrome --reporter=list`
  - Output (tail):
    ```
    Running 8 tests using 2 workers
      ✓  1 [auth-setup] › auth setup — inject dark-theme localStorage (12.2s)
      ✓  3 [desktop-chrome] › TC-1 loads with Overview, tabs switch (11.3s)
      ✓  2 [desktop-chrome] › TC-2 checklist covers UI, data, API, bug, verdict sections (11.6s)
      ✓  5 [desktop-chrome] › TC-4 match toggle + add bug update the page (9.3s)
      ✓  4 [desktop-chrome] › TC-3 answers persist across reload (localStorage) (16.5s)
      ✓  6 [desktop-chrome] › TC-5 copy report writes Markdown to the clipboard (9.1s)
      ✓  7 [desktop-chrome] › TC-6 reset clears answers (10.5s)
      ✓  8 [desktop-chrome] › TC-7 reachable from the Research rail; back link returns (9.5s)
      8 passed (1.1m)
    EXIT: 0
    ```
  - Result: PASS

## Data Correctness (staging)
> App test AND data test.

- This page holds **no server data** — its only "data" is the user's own entries, which
  round-trip through `localStorage` and into the exported Markdown. That round-trip is
  the data test, and it is covered by **TC-3** (persist) and **TC-5** (export reflects
  entered values). Result: PASS (local).
- **UNVERIFIED — staging:** the page is not yet deployed to staging (branch+PR path). Its
  live behaviour behind the real RequireAuth on `staging.niveshcopilot.com/v5/research/qa`
  has not been exercised this session. Verifying it needs the branch merged/deployed to
  `dev` (which redeploys app staging) + a staging login — deliberately deferred to you.

## Inputs required from user
- To deploy + verify on staging: a **push of this branch to `dev`** (your chosen path) and
  a **staging session token / test account** for a live pass. None were needed for the
  local verification above.

## Verdict: PASS
