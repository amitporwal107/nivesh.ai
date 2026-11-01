# Functionality Verification Report — Quick Hedge (Risk Desk › Portfolio hedge + Copilot chat)

- **Branch:** feat/quick-hedge (sparse worktree /home/deploy/nivesh-wt-quick-hedge, from origin/dev 25c61610; local commits, NOT pushed)
- **Date:** 2026-11-01
- **Author:** Claude (full-stack developer + QA)
- **Plan and decisions:** docs/RISK_AND_HEDGE_GAP_AND_PLAN_20261031.md §4-§5
- **Scope:** POST /api/portfolio/quick-hedge (flag `portfolio_hedge`), services/quick_hedge/*, the Copilot `portfolio_hedge` intent and answer, Risk Desk › Portfolio hedge.
- **Out of scope / not built:** placing a paper hedge (the "Portfolio Hedge" group; ledger decision open), R1/H1 of the plan.

## Test cases (authored up front)
Written before the code for the calculator (calc), then extended as real data exposed cases. Files in the worktree:

| File | Cases | Covers |
|---|---|---|
| backend/tests/test_quick_hedge_calc.py | 29 | round-down lots and the 100% cap, strike from tolerable loss (never wider), put spread (band, fallback to deepest traded strike), payoffs, scenario table tie-out, R² bands, missing inputs, no NaN |
| backend/tests/test_quick_hedge_inputs.py | 33 | classification (overseas/liquid/hybrid/gold named), merged duplicate rows, beta coverage rule, fit to Nifty (perfect, leveraged, unrelated, blend, short history, coverage), expiry choice, traded puts, cost-card charges |
| backend/tests/test_quick_hedge_service.py | 7 | answer shape and dates, % tolerance, missing tolerance, market down shows only the real cause, no beta stops before the fit, unmeasurable fit blocks placing |
| backend/tests/test_quick_hedge_route.py | 11 | fail-closed flag gate (default, allow-list, off), validation, account taken from the session |
| backend/tests/test_quick_hedge_chat.py | 47 | which questions are taken / left alone, what a question states, the payload (validated against the contract), assumptions said, flag gate in prepare() |
| frontend-v5/e2e/tests/copilot-app-desk-hedge.spec.ts | 11 (HG-1…HG-11) | flag off hides the view and its URL asks nothing; view offered last; figures are the server's; choice switching; inputs sent exactly; bad input refused; under one lot; poor fit blocks placing; market down / 403 wording; dates + disclosures; phone 390px no sideways scroll |

## Results — REAL output from this session

Backend (container nivesh/backend:staging, worktree mounted read-only):
```
$ pytest <every test file naming copilot_visual or INTENTS> tests/test_quick_hedge_{calc,inputs,service,route}.py tests/test_move_odds_routes.py
411 passed, 2 warnings in 43.14s
$ python -c "import server; ..."
routes mounted: 1
```
(The two guards a new intent trips were satisfied honestly: tests/test_suggestions.py INTENTS count 13→14 with a suggestion template `t_portfolio_hedge`; tests/test_copilot_visual.py::test_c2 needs a REAL staging capture, added below.)

Real-data run of the service (NOT mocked) — in-process inside nivesh-staging-app-backend through a throwaway overlay in /tmp (nothing deployed, read-only) against the staging test account's holdings and the live NIDP warehouse, 2026-10-31 22:2x IST:
```
elapsed_s: 4.0 | status: ok | reasons: []
value: 11351032 hedgeable: 5443891 (48%) positions: 67
excluded: {'hybrid': 3390267, 'debt': 42735, 'gold': 1483000, 'overseas': 786344, 'other': 123786, 'unclassified': 81009}
weighted beta: 0.62 (coverage 0.997 )
fit: {'r2': 0.871, 'correlation': 0.933, 'regression_beta': 0.956, 'observations': 252, 'coverage': 0.875, 'series_used': 29, 'window_start': '2025-10-21', 'window_end': '2026-10-30'}
confidence: high | Nifty explains most of this portfolio's moves.
exposure rs 3375222 | required lots 2.25 executed 2 | protected 88.8 % residual 11.2 %
   maximum long_put [('buy', 22150.0, 121.9)] | deductible 132224 | cost 15886 | -10% net -171585 vs -337522 | place_allowed True | notes []
   balanced long_put [('buy', 21300.0, 36.0)] | deductible 256673 | cost 4708 | -10% net -270640 vs -337522 | place_allowed True | notes []
   lowest_cost put_spread [('buy', 21300.0, 36.0), ('sell', 20850.0, 25.0)] | deductible 256673 | cost 1490 | -10% net -280745 vs -337522 | place_allowed True | notes ['band_ends_above_expected_fall']
```
The Copilot answer built from the same run: resolved `portfolio_hedge {'expected_fall_pct': 15.0}`, `contract problems: []`, blocks kpis, kpis, ranked, ranked, notice×3; stored as the REAL capture in frontend-v5/e2e/fixtures/contract-visual-answer.json (14 of 14 intents).

Real-data defects this run exposed, fixed with tests: duplicate holdings rows overwrote each other (fit coverage 52.3% → 87.5%, 21 → 29 series); overseas and liquid funds were "unclassified"; the put spread gave the wrong reason when no traded put sat as deep as the fear (now built to the deepest traded strike with a note); the unit-test fixture's chain was not monotonic; the service printed a redundant "missing spot" line after the real cause.

Frontend (container mcr.microsoft.com/playwright:v1.47.0-jammy, production build, every /api mocked — the repo's convention for /v5/app specs):
```
TSC_EXIT=0
BUILD_EXIT=0
preview http 200
npx playwright test --config pw.copilot-app.config.ts copilot-app-desk-hedge.spec.ts copilot-app-desk-risk-desk.spec.ts copilot-app-desk-risk-controls.spec.ts copilot-app-desk-risk-phase1.spec.ts
  58 passed (56.7s)
PW_EXIT=0
```
First run: 56 passed, 2 failed — both mistakes in my spec (expected "75.0%" where the screen shows "75%"; read the switcher before it rendered). Spec fixed, re-run above. The three existing Risk Desk specs (47 cases) pass unchanged.

## After merging dev 35a7931d (2026-11-01) — REAL output

Seven merge conflicts, all two features adding to the same list or the same end of file; both sides kept (details in the merge commit). Then:

CI allowlist reproduced locally (container nivesh/backend:staging, `pytest -q -rfE --continue-on-collection-errors` over the 292 files of .github/workflows/backend-tests.yml, which now lists the five quick_hedge files), merged branch vs plain dev 35a7931d:
```
MERGED   84 failed, 7764 passed, 34 skipped, 15 warnings, 4 errors in 217.68s
BASELINE 84 failed, 7635 passed, 34 skipped, 15 warnings, 4 errors in 211.84s
failing/erroring names: 88 on each side, IDENTICAL sets, 0 only-on-merged, 0 of them quick_hedge
```
(The 88 are this container's known baseline: no network for NSE fetches, files the CI runner has. The +129 passes are the 127 new Quick Hedge tests and 2 more parametrized suggestion-template cases.)

Frontend on the merged tree, whole suite (container mcr.microsoft.com/playwright:v1.47.0-jammy, production build, every /api mocked):
```
TSC_EXIT=0
BUILD_EXIT=0
  32 failed
  1285 passed (13.1m)
```
The 32 failures are IDENTICAL BY NAME to the 32 that fail on plain dev (all in copilot-app-desk-strategy-graphs.spec.ts, pre-existing, not touched by this branch); none elsewhere; the 11 hedge cases (HG-1…HG-11) all pass inside this run.

## Merge onto dev 4fd874d3 — re-verification (1 Nov, after PRs #432-#439 landed)
The branch conflicted with dev in 7 files (two features adding to the same lists and the same end-of-file spots); both sides were kept: copilot_visual `__init__.py` (AGENT_FOR), `payload.py` and `intents.py` (intent tuples), `builders.py` (BUILDERS), `readers.py` (docstring + readers), `tests/test_suggestions.py` (INTENTS 16 -> 17), `frontend-v5/e2e/fixtures/contract-visual-answer.json` (dev's 16 real captures + the real portfolio_hedge capture, 17). The five Quick Hedge suites were added to the CI allowlist (`.github/workflows/backend-tests.yml`).

Backend, the CI allowlist (292 files) run in the staging backend image on the merged tree and on plain dev 35a7931d, failures compared by name:
```
MERGED : 84 failed, 7764 passed, 34 skipped, 4 errors in 217.68s
DEV    : 84 failed, 7635 passed, 34 skipped, 4 errors in 211.84s
identical FAILED/ERROR names: YES (88 = 88) | Quick Hedge tests among them: 0
```
(+129 passed = 127 Quick Hedge tests + 2 suggestion-template cases. The 84 + 4 are the container environment's known baseline, e.g. tests that need network or files the CI runner has; they are identical on dev.)

Frontend, the WHOLE Playwright suite (every /api mocked, production build) on the merged tree:
```
TSC_EXIT=0
BUILD_EXIT=0
  32 failed
  1285 passed (13.1m)
```
The 32 failures are copilot-app-desk-strategy-graphs.spec.ts (SG-*), which fail with the same 32 names on pure dev e8ffd516 (compared name by name; none outside that spec). The 11 hedge cases (HG-1…HG-11) pass; the 47 existing Risk Desk cases pass.

## NOT verified (UNVERIFIED)
- The HTTP route on staging: POST /api/portfolio/quick-hedge with a session and the flag on. Needs the branch deployed (backend process restart) and a staging session token. Only the service and the chat builder ran against real data (in-process), and the route's gate/validation ran in unit tests.
- Playwright against the DEPLOYED staging app with the flag on (the UI spec is mocked, as the repo's UI specs are); the screen in a real browser; the LLM's wording of the chat explanation (it shares the staging 5-hour limit / Groq key).
- Charges against a real contract note (the desk cost card's F&O rates carry an UNVERIFIED effective date in the code).
- Anything about placing a paper hedge (not built).

## Verdict: BLOCKED — unit, contract, build and mocked-UI levels pass; the staging API and deployed-app checks have not run (not PASS).
