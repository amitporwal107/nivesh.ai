# Functionality Verification Report — Mobile bottom-nav "Research" tab

- **Branch:** feat/filings-intelligence-design
- **Date:** 2026-07-21
- **Author:** Claude (Design Engineer + Full-Stack Developer)
- **Environment:** local mocked Playwright (Vite dev server @ localhost:5174, `mobile-chrome` / Pixel 7 390×844). No backend/staging call needed — this is a pure client-side nav-config change, fully covered by the repo's mocked mobile-nav test layer.
- **Changed areas:** backend routes/services: **no** · frontend src: **yes**

## Summary
Added a **Research** tab to the mobile app's bottom navigation (`MobileBottomNav`), inserted
directly **after "Tips"**, pointing to the existing `/research` route (the "Filings Intelligence"
surface). Personal-investor bottom bar is now: **Home · Portfolio · Tips · Research · Chat**.
Only the personal (`PERSONAL_TABS`) bar was touched; the advisor bar (`ADVISOR_TABS`, which has
no "Tips" tab) is unchanged. Icon: `FileSearch` (lucide). `/research` renders outside `AppLayout`,
so entering it is a one-way portal (return via device/browser back) — documented inline in the code.

Change is confined to two files:
- `frontend-v5/src/components/layout/MobileBottomNav.tsx` — import `FileSearch`, add the tab entry.
- `frontend-v5/e2e/tests/navigation.spec.ts` — 5 new mobile-nav test cases (authored up front).

## Test Cases
> Authored UP FRONT — after UI design, before implementation. Verified red→green:
> all 4 assertions that require the new tab FAILED on the pre-change code, then PASSED after.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | mobile nav | Bottom bar renders `Home · Portfolio · Tips · Research · Chat` in that order (personal user, 390×844) | e2e | Exact ordered label list | PASS |
| TC-2 | mobile nav | "Research" sits immediately after "Tips" | e2e | `index(Research) === index(Tips)+1` | PASS |
| TC-3 | mobile nav | "Research" tab links to `/research` | e2e | `href` ends `/research` | PASS |
| TC-4 | mobile nav | Tapping "Research" navigates to `/research` | e2e | URL ends `/research` | PASS |
| TC-5 | regression | Existing "Tips" tab still links to `/recommendations` | e2e/edge | `href` ends `/recommendations` | PASS |

## UI / Playwright Tests
> Frontend src changed → Playwright REQUIRED. Real, unedited runner output below.

**Pre-implementation (RED) — proves the tests actually detect the change:**
- Command: `npx playwright test navigation --project=mobile-chrome -g "bottom nav Research"`
- Output (real):
  ```
  4 failed
    [mobile-chrome] › navigation.spec.ts › bottom nav Research tab › bottom nav shows Home · Portfolio · Tips · Research · Chat in order
    [mobile-chrome] › navigation.spec.ts › bottom nav Research tab › "Research" sits immediately after "Tips"
    [mobile-chrome] › navigation.spec.ts › bottom nav Research tab › "Research" tab links to /research
    [mobile-chrome] › navigation.spec.ts › bottom nav Research tab › tapping "Research" navigates to /research
  2 passed (57.8s)
  ```
  (The 4 Research assertions time out waiting for a non-existent "Research" link; the TC-5 regression already passes.)
- Result: RED as expected.

**Post-implementation (GREEN):**
- Command: `npx playwright test navigation --project=mobile-chrome -g "bottom nav Research"`
- Output (real):
  ```
  Running 6 tests using 2 workers
  ✓ [auth-setup] › auth.setup.ts:23:1 › auth setup — inject dark-theme localStorage (8.1s)
  ✓ [mobile-chrome] › navigation.spec.ts:115:5 › bottom nav Research tab › "Research" sits immediately after "Tips" (8.8s)
  ✓ [mobile-chrome] › navigation.spec.ts:103:5 › bottom nav Research tab › bottom nav shows Home · Portfolio · Tips · Research · Chat in order (9.1s)
  ✓ [mobile-chrome] › navigation.spec.ts:135:5 › bottom nav Research tab › tapping "Research" navigates to /research (8.4s)
  ✓ [mobile-chrome] › navigation.spec.ts:126:5 › bottom nav Research tab › "Research" tab links to /research (8.6s)
  ✓ [mobile-chrome] › navigation.spec.ts:143:5 › bottom nav Research tab › existing "Tips" tab still links to /recommendations (regression) (3.6s)
  6 passed (44.8s)
  ```
- Result: **PASS** (all 5 new cases + auth-setup).

**Full navigation spec on mobile-chrome (regression sweep):**
- Command: `npx playwright test navigation --project=mobile-chrome`
- Output (real): `20 passed`, `4 failed (1.8m)`.
- The 4 failures are all in the pre-existing **"Desktop sidebar navigation"** block
  (`sidebar link "Concentration"`, `"Diversification"`, `active link is highlighted`,
  `sidebar shows user name from fixture`) — NOT touched by this change.
- **Proof they are pre-existing / independent of my change:** with my edits `git stash`ed
  (baseline), the identical 4 fail:
  ```
  4 failed
    [mobile-chrome] › Desktop sidebar navigation (≥1024px) › sidebar link "Concentration" navigates to /v5/concentration
    [mobile-chrome] › Desktop sidebar navigation (≥1024px) › sidebar link "Diversification" navigates to /v5/diversification
    [mobile-chrome] › Desktop sidebar navigation (≥1024px) › active link is highlighted
    [mobile-chrome] › Desktop sidebar navigation (≥1024px) › sidebar shows user name from fixture
  1 passed (36.1s)
  ```
  Root cause is stale fixtures/labels ("Concentration"/"Diversification" are now "AI Insights";
  the mocked profile name is "Test Onboarded User", not "Amit Porwal"). Out of scope here.

## Type check
- Command: `npx tsc --noEmit`
- Output (real): `tsc: no errors`
- Result: PASS — the new `FileSearch` import and tab entry are type-safe.

## Data Correctness
> No data path changed. This is a client-side navigation-config change; `/research` and its
> data endpoints (`/api/filings/*`, `stocks_insights`) are pre-existing and unmodified.
- Result: N/A (no DB/feed read or write introduced).

## Inputs required from user
- none (mocked local Playwright needs no session token; no staging/behind-auth surface was changed).

## Notes / follow-ups (not blockers)
- Personal bar is now 5 tabs (still within the standard bottom-nav max; `flex-1` splits evenly).
- Advisor bottom bar (`ADVISOR_TABS`) intentionally NOT given a Research tab — the request was
  "after Tips" and the advisor bar has no Tips tab. Easy to add on request.
- `/research` also has no desktop Sidebar entry today (reachable via this new mobile tab or direct
  URL). Adding it to `nav-items.tsx` would surface it on desktop too — deferred, out of scope.

## Verdict: PASS
