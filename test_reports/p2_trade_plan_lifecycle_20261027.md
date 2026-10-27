# Functionality Verification Report — Phase 2.1 + 2.2: canonical TradePlan, unified lifecycle, F&O roll, stored premium stop

- **Branch:** `feat/p2-trade-plan-lifecycle` (off origin/dev `6a3ec2e3`, then merged with origin/dev `e704c231`, which
  brought feat/p2-exits-backtest #361), worktree `/home/deploy/nivesh-p2-plan`; final runs on the merge commit `3a0bd120`
- **Date:** 2026-10-27
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** local containers (`nivesh/backend:staging` image, `--network none`; PostgreSQL 16 throwaway container for
  migration 025; Playwright 1.60 against a production build with mocked APIs) + READ-ONLY staging data checks. Nothing was
  deployed, pushed or written on staging.
- **Changed areas:** backend routes/services: yes · frontend src: yes
- **Status: IN PROGRESS** — everything below is verified locally; the staging endpoint checks need the branch deployed,
  which this brief does not allow (see `test_reports/OVERRIDE_p2_trade_plan_lifecycle.md`).

## Summary

One canonical **TradePlan** (`services/strategy_plan/trade_plan.py`, `trade-plan-v1`, content-hashed `plan_id`, insert-once
Mongo `trade_plans`, versioned and revalidated) built from the plan builder's candidates, with the AI scanner as the setup
source and its stop method stored as data (N13); scanner signals versioned in `positional_signals_history` (N17, migration
025); one direction per instrument per day on `/top`; every surface (ideas, /top, /plan, the AI watchlist job; Top 10,
watchlist, F&O rows, Builder) carries the plan by id and the paper route records only the plan's levels (`plan_ref`).
The **lifecycle** (`services/trade_lifecycle.py`) on `desk_paper_trades` and `ai_trader_tickets`: state + append-only events
written in the same conditional update as the status. The **F&O roll** (option C) at the roll session's bhavcopy
`close_price`. **2.6** storage of the strategy_levels premium stop / T1 / T2 on strategy trades, under the names the
exits branch's `desk_strategy_trades.premium_plan` reads (`kind, entry, planned_stop, target_1, target_2, unit_shares,
version, greek_review {entry_delta_per_unit, view}`); after the merge that seam is live and tested both ways.

## Test Cases

Authored first: `test_reports/p2_trade_plan_lifecycle_TESTCASES.md`. Evidence for each below.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TP-1 | TradePlan | same inputs → same id; created_at not hashed | unit | identical id | PASS (`test_the_same_inputs_give_the_same_plan_id…`) |
| TP-2 | TradePlan | any level change → new id | unit | different id | PASS (3 cases) |
| TP-3 | N13 | ICICIBANK 26 Oct real features | unit | atr 1.5, no "2 x ATR" | PASS (trade_planner + plan) |
| TP-4 | N13 | tighter swing-low stop | unit | structural | PASS |
| TP-5 | TradePlan | targets in R | unit | 2.0 / 3.0, match prices | PASS |
| TP-6 | TradePlan | order type from the setup | unit | stop_trigger / limit_pullback / at_close | PASS (5 cases) |
| TP-7 | TradePlan | desk-cost-v2 at the stop | unit | equals round_trip_breakdown | PASS |
| TP-8 | TradePlan | proposed vs derived status | unit | proposed; derived from trades | PASS |
| TP-9 | Store | insert-once, owners grow | unit | no second write | PASS |
| TP-10 | Store | next version, revalidated; invalid → REJECTED | unit | v2 supersedes v1; v3 not tradeable | PASS |
| TP-11 | Options plan | strategy_levels exit plan | unit | equals the engine's answer | PASS |
| TP-12 | N13 | bearish stock idea on a bullish cash setup | unit + e2e | flagged, not tradeable | PASS (CT fixture + UI-3) |
| TP-13 | N17 | re-run versioned (real PostgreSQL 16) | integration | history row, revision 2; identical re-run none | PASS |
| TP-14 | N17 | migration not applied | unit | old upsert + ERROR | PASS |
| LC-1 | Lifecycle | transition table | unit | allowed / refused | PASS (22 cases) |
| LC-2 | Lifecycle | event fields | unit | every field present | PASS |
| LC-3 | Lifecycle | at_once create | api | E→T→O | PASS |
| LC-4 | Lifecycle | conditional fill on read, once | api | T, O written once | PASS |
| LC-5 | Lifecycle | stop on read, repeat, later close; stale-copy close | api | one EXIT_PENDING→CLOSED | PASS |
| LC-6 | Lifecycle | entry not reached | api | ELIGIBLE→CLOSED | PASS |
| LC-7 | Lifecycle | strategy create / close | api | same update; repeat writes none | PASS |
| LC-8 | Lifecycle | refused open | api | REJECTED on risk_decisions (+ plan) | PASS |
| LC-9 | Lifecycle | replay / restart | unit | broken chain reported | PASS |
| LC-10 | Lifecycle | AI Trader tickets | unit + suite | each status change one event | PASS (unit + 463 AI-trader tests) |
| LC-11 | Lifecycle | legacy trade closes | api | derived history first | PASS |
| LC-12 | Plan status | derived from trades | api | proposed → open | PASS |
| LC-13 | Backfill | dry run default; apply idempotent; staging dry run | unit + staging (read-only) | counts, 0 written | PASS |
| PR-1…5 | Paper POST | plan_ref accepted / mismatch / unknown / not eligible / strategy | api | 201 / 409 / 404 / 409 / 201+409 | PASS |
| CT-1 | Contract | one plan_id across ideas, Top 10, watchlist, Builder, paper (cash); board, stored row, paper (F&O) | contract | byte-identical levels | PASS |
| CT-2 | Contract | the browser's bodies through the real route | contract | 201; fixture plans = backend's | PASS |
| RL-1…8 | Roll | close + open at D's close; not ready; strike gone; double click; links; risk; expiry day; not due | api | as specified | PASS (11 tests) |
| OP-1 | 2.6 | premium stop stored at entry, read by the exits work | api | exit_plan.options stored; `premium_plan()` reads the same numbers | PASS (`test_the_stored_premium_plan_is_read_by_the_exit_rules`) |
| UI-1…4 | Frontend | rows record plan levels + plan_ref; conflict badge; roll confirmation | e2e | as specified | PASS (7 new cases) |
| RG-1 | Regression | full backend/tests vs origin/dev | suite | no "fails on branch, passes on dev" | PASS (0) |
| RG-2 | Regression | test_order_path_guard | unit | pass | PASS |

## API / Endpoint Tests

**Staging: NOT RUN (UNVERIFIED).** The branch is not deployed (the brief is read-only towards staging), so
`GET /api/desk/trade-plans/{id}`, the `plan_ref` paper POST, `GET/POST /api/desk/paper-trades/{id}/roll` and the plan fields
of `/api/desk/strategy/plan|ideas|top` have not been called on staging. The routes were exercised through FastAPI's
TestClient with the real routers, validators, simulators and account (in-memory Mongo; data platform faked per test).

- **pytest (new and directly affected tests, real PostgreSQL for TP-13):**
  - Command: `sudo docker run --rm --network p2plan-pg -v /home/deploy/nivesh-p2-plan:/work:ro -w /work/backend … -e PG_TEST_DSN=postgresql://postgres:…@p2plan-pg-db:5432/sigtest nivesh/backend:staging python -m pytest tests/test_trade_lifecycle.py tests/test_trade_plan.py tests/test_trade_lifecycle_routes.py tests/test_trade_plan_contract.py tests/test_fno_roll.py tests/test_backfill_trade_lifecycle.py tests/test_positional_signal_history.py tests/test_order_path_guard.py -v -p no:cacheprovider`
  - Output (last line, before the merge): `======================= 114 passed, 3 warnings in 23.48s =======================`
  - On the merge (`3a0bd120`), the same files plus the exits branch's `test_paper_exit_rules.py`,
    `test_desk_strategy_trades.py` and `test_chartink_strategy.py`, with `PG_TEST_DSN` set (nothing skipped):
    `305 passed, 3 warnings in 20.26s`
  - Result: PASS
- **pytest (the desk / plan / AI Trader neighbourhood):** `… tests/test_trade_lifecycle_routes.py tests/test_trade_lifecycle.py tests/test_trade_plan.py tests/test_desk_trading.py tests/test_desk_paper_sim.py tests/test_desk_strategy_trades.py tests/test_desk_paper_safety.py tests/test_fno_idea_paper_trade_contract.py tests/test_desk_exit_job.py tests/test_paper_account.py tests/test_risk_gate_desk_journal.py tests/test_ai_trader.py tests/test_ai_trader_execution.py tests/test_risk_gate_ai_trader.py tests/test_strategy_plan.py tests/test_order_path_guard.py`
  - Output: `583 passed, 3 warnings in 53.99s`; plan / ideas / top / watchlist suites: `474 passed, 2 warnings in 21.88s`
  - Result: PASS

## UI / Playwright Tests

Runner: `scratchpad/run-fe.sh <tree> <log> <specs>` (tsc, production build, `vite preview`, Playwright 1.60, every `/api`
mocked, `--network none`), `PWEXTRA=--workers=2`, on a snapshot of the merge commit `3a0bd120`:

- Specs: `copilot-app-desk-top10`, `copilot-app-ai-watchlist`, `copilot-app-desk-portfolio-fno`, `copilot-app-desk-strategy-top`,
  `copilot-app-desk-strategy-builder`, `copilot-app-desk-strategy-ideas`, `copilot-app-desk-scanner`, `copilot-app-desk-lab`,
  `copilot-app-desk`
- Output:
  ```
  == tsc
  tsc: clean
  == build
  ✓ built in 36.85s
    16 skipped
    367 passed (6.8m)
  ```
  The 16 skipped are all screenshot-only cases ("screenshots desktop/mobile", "shot <state> 1440/390"), which the specs
  skip unless screenshots are asked for.
- The new cases:
  ```
  ✓ copilot-app-desk-top10.spec.ts:695  Top 10 — trade plans (Phase 2.1) › UI-1 a stock row shows its plan (entry, stop method, targets in R) and records exactly the plan's levels with plan_ref
  ✓ copilot-app-desk-top10.spec.ts:714  › UI-1b a plan its own rules reject cannot be added and the row says why
  ✓ copilot-app-desk-top10.spec.ts:727  › UI-3 an F&O row cites its plan; a bearish stock idea on a bullish cash setup says so and cannot be recorded
  ✓ copilot-app-ai-watchlist.spec.ts:342  › UI-2 a stored cash row records the stored plan's levels with plan_ref; a day stored before plans keeps the scanner's
  ✓ copilot-app-desk-portfolio-fno.spec.ts:1920  F&O roll › UI-4 the confirmation shows both legs and their prices, and Roll posts once
  ✓ copilot-app-desk-portfolio-fno.spec.ts:1938  › UI-4b a roll the route refuses shows its reason and offers no Roll button
  ✓ copilot-app-desk-portfolio-fno.spec.ts:1949  › UI-4c the trade record offers the same roll
  ```
  The UI bodies are compared with `e2e/fixtures/contract-trade-plan-paper.json`, which the backend contract test sends
  through the real route (CT-2): mocked UI, paired with the real-route test of the exact body.
- Result: PASS (mocked API). Earlier, before the merge, one 4-worker run showed 4 unrelated timeouts (a holdings panel still
  "Reading holdings…", two 30 s test timeouts); all four pass alone on both the branch and plain origin/dev, and the
  2-worker runs before and after the merge had 0 failures.

## Data Correctness (staging, READ-ONLY)

1. **N13 — how the stored scanner stops were set** (`positional_signals` ⨝ `stock_technical_features` for the latest
   signal date, SELECT only through the staging backend's own pool, classified with the branch's `trade_planner.stop_meta`):
   ```
   latest signal_date 2026-10-26 | signals 682
   stop method counts: {('atr', 1.5): 62, ('structural', None): 620}
      ('ICICIBANK', '2026-10-26', 'EARLY_BREAKOUT', 1413.21, 1374.89, 'atr', 1.5, 1.5, 1291.0)
      ('SGMART', '2026-10-26', 'ACCUMULATION', 717.15, 706.5, 'structural', None, 0.272, 710.05)
      ('FEDERALBNK', '2026-10-26', 'ACCUMULATION', 316.89, 312.18, 'structural', None, 0.482, 313.75)
      ('KOTAKBANK', '2026-10-26', 'EARLY_BREAKOUT', 453.55, 438.57, 'atr', 1.5, 1.5, 394.7)
   ```
   Every stop is identified (0 unknown); the old plan label "2 x ATR" matched none. PASS.
2. **Lifecycle backfill dry run** (the branch's `scripts/backfill_trade_lifecycle.py` piped into the staging backend's
   Python, `apply=False`, `find()` only; 2026-10-27 07:56 IST):
   ```
   desk_paper_trades: total 12, to_backfill 12, by_state {CLOSED: 7, POSITION_OPEN: 4, TRADE_ELIGIBLE: 1},
     by_status {cash:closed:stop 4, cash:open 4, cash:closed:manual 2, strategy:closed:manual 1, strategy:open 1},
     events 48, problems [], written 0
   ai_trader_tickets: total 0, written 0
   ```
   PASS (the chains replay with no problem). NOT applied: `--apply` needs the owner's go-ahead.
3. **Migration 025 + the versioned upsert** against a real PostgreSQL 16 (throwaway container, the repo's own DDL): TP-13
   above. Not applied on staging.

## Regression (RG-1)

Command: `scratchpad/p2plan_run_full.sh <tree> <name>` = `python -m pytest tests -q -p no:cacheprovider
--continue-on-collection-errors -rfE --junitxml=…` in the `nivesh/backend:staging` image, `--network none`, on a snapshot of
plain origin/dev `e704c231` and of the merge `3a0bd120`; the two JUnit files compared test by test
(`scratchpad/p2plan_draft/compare.py`):

```
origin/dev e704c231: 580 failed, 6422 passed, 578 skipped, 39 warnings, 166 errors in 473.68s (0:07:53)
merge      3a0bd120: 580 failed, 6528 passed, 579 skipped, 40 warnings, 166 errors in 487.62s (0:08:07)
fails on branch, passes on dev: 0
passes on branch, failed on dev: 0
new on branch: 108 | new failing: 0
on dev only (not collected on branch): 1
  gone tests.test_portfolio_import_preview::test_unsafe_or_unreadable_files_are_refused_before_any_parse[bomb.xlsx-PK… passed
```

The 580 failures and 166 errors are the same set on both trees: suites that need a live backend URL
(`REACT_APP_BACKEND_URL`), files outside the image, or a database. The one "dev only" id is a test parametrized with
bytes generated at collection (a zip bomb), so its id differs per run; it is collected and passes on the branch under its
own id. Result: PASS (the list is empty).

## What is UNVERIFIED, and why

- Staging endpoint calls for the new / changed routes, the UI on staging, migration 025 on staging, and the backfill apply:
  the branch is not deployed and the brief is read-only towards staging. Plan: the PR body's staging steps 1-6.
- "Failed exits are retried safely and surfaced operationally" (2.2): exits are evaluated by the exits work (now on dev,
  which names the exits it could not write in the job's log summary); this branch makes every close write its events in
  the same conditional update, re-read and retried when the state moved, and logs an ERROR when a document's state cannot
  close. No separate retry queue or alert was built here.
- The behaviour changes the merge made live, now covered by tests: a strategy paper trade recorded through the route gets
  strategy_levels' premium plan at entry, so the exits work can close it at its premium stop or target 1 on its marks (two
  of the exits branch's tests were updated to expect that).
- The plan store writes on the strategy read routes (insert-once, bounded by distinct content); its volume on staging has
  not been measured.

## Inputs required from user

- Owner go-ahead to apply the lifecycle backfill on staging (dry-run counts above) and migration 025.

## Verdict: BLOCKED
