# Functionality Verification Report — Phase 4 research hardening (4.1 CI, payoff costs, 4.2 universe + reproducibility, 4.4 scope, RS63 readiness)

- **Branch:** feat/p4-research-hardening (off origin/dev ce923426; origin/dev 87a90bca, #363 Phase 1, merged in), worktree
  /home/deploy/nivesh-p4-hardening
- **Date:** 2026-10-27
- **Author:** Claude (full-stack developer + QA + domain analyst)
- **Environment:**
  - unit, contract and route tests in the staging backend image (`nivesh/backend:staging`, `--network none`);
  - the CI job's exact command in a clean `python:3.11-slim` container;
  - Playwright on a local production build with a mocked API;
  - staging data read-only only: warehouse SELECTs, DaaS GETs, app-Postgres SELECT, Mongo counts.
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary

Commits (oldest first):

| Commit | What |
|---|---|
| `1114ff66` | payoff-v2: the payoff engine prices costs with the desk cost card |
| `04e87ff0` | merge of origin/dev (#363 Phase 1) |
| `fdce5bed` | liquid-eq-v1, the point-in-time universe, as the default |
| `445193bc` | run provenance, and old runs readable |
| `5bff7e3d` | RS63 readiness check |
| `c2352e65` | universe lookback from the price history, and NSE ETF list exclusion (found by the data test) |
| `49a2c3e3` | UI: the universe default and a survivorship warning driven by the run's basis |
| `340ee3d3` | docs: 4.4 scope and the point-in-time universe / index-history decision |
| `59e6716a` | CI workflow |

Test cases were authored first in `test_reports/p4_research_hardening_TESTCASES.md`. The freshness contract is out of
scope here; it waits for Phase 1.

## Test Cases

| ID | Scenario | Type | Result |
|----|----------|------|--------|
| TC-CI-1 | triggers dev+main, pins, no secrets | static | PASS |
| TC-CI-2 | exact CI command, clean python:3.11-slim, repo requirements | integration | PASS (exit 0, 276 s wall) |
| TC-CI-3 | regression changes an expected number → job fails | negative control | PASS (exit 1) |
| TC-CI-4 | allowlist holds the named suites + this PR's | static | PASS |
| TC-CI-5 | excluded suites listed with reasons | report | PASS (in the PR body) |
| TC-PC-1…9 | payoff-v2 components, CaR, block, overrides, compatibility, parity with paper trades (25 random structures), pre-expiry, segments, worthless | unit / property | PASS (34) |
| TC-PC-10 | consumers: ideas, regime-fit, strategy_levels, F&O candidates, TradePlan, PRD examples, contracts | regression | PASS; every changed number re-derived |
| TC-LU-1…10 | liquid-eq-v1 conditions, point in time, survivorship, missing session, ETF list, DSL, DaaS + SQL providers, failures, labels, defaults | unit / e2e-in-process | PASS (20 incl. the fixture contract) |
| TC-LU-11 | staging: engine rule = independent SQL | data, read-only | PASS (4 dates identical) |
| TC-LU-12 | UI: default liquid card; index warning from the run; switch clears it; fixture = engine texts | e2e (mocked) + contract | PASS |
| TC-RP-1…3 | provenance on a run; persist_run; old runs through the normaliser; GET /runs | unit / route | PASS (8) |
| TC-RP-4 | the 3 stored staging runs read through run_provenance | data, read-only | PASS |
| TC-DOC-1/2 | scope doc; index-history decision | review | PASS (citations re-read in this branch) |
| TC-RS-1 | readiness counter | unit | PASS (9) |
| TC-RS-2 | staging now | data, read-only | PASS: NOT_READY, 0 of 60 |
| TC-SAFE-1 | test_order_path_guard | regression | PASS |
| TC-REG-1 | full suite branch vs dev: "fails on branch, passes on dev" | regression | PASS (0) |

## API / Endpoint Tests

**Not run against staging.** This task forbids push, PR and merge, and staging runs `dev`. The endpoints changed:
- `POST /api/strategy-builder/strategies/{id}/backtest`: adds `provenance`; `metrics` gain `universe_*`;
- `GET /api/strategy-builder/runs/{id}`: adds `provenance`;
- `GET /api/strategy-builder/universe-catalog`: first card is the liquid universe; cards carry `universe`;
- `POST /api/desk/strategy/payoff` and every plan, idea and levels route: `payoff-v2` costs.

They are exercised in-process (FastAPI TestClient) by the route tests below. UNVERIFIED on staging; the plan is in the PR
body.

What WAS checked on staging (read-only): the two DaaS endpoints the liquid universe depends on exist and serve what it
reads. They were called from inside `nivesh-staging-app-backend` with the platform's own client:
```
GET /prices/eod?on=2026-10-23&series=EQ: 2706 rows, next_offset None, columns ['as_of_date', 'close_price', 'deliv_pct', 'high_price', 'isin', 'low_price', 'open_price', 'prev_close', 'series', 'symbol', 'trades', 'turnover', 'volume'], 0.58s
GET /prices/eod?on=2025-12-29&series=EQ: 2378 rows, next_offset None, columns [...same...], 0.41s
GET /features/scan-snapshot: HTTP 200, 2493 rows, is_etf true 332, reference_as_of 2026-10-26, 1.01s
GET /features/calendar: 203 dates 2025-12-29..2026-10-26, 0.07s
```
At about 0.5 s a session with 8 in parallel, a one-year liquid-universe backtest adds about 290 reads, roughly 20 s.
That is an estimate, not measured end to end.

**pytest — new and touched suites** (staging image, `--network none`):
```
tests/test_payoff_cost_card.py                                    34 passed in 0.60s
payoff consumers (payoff, PRD examples, plan, ideas, levels, regime-fit x2, F&O candidates, templates route, trade plan)
                                                                  339 passed, 3 warnings in 34.83s
remaining consumers (ai_watchlist, chartink x2, desk_trading, paper safety, F&O idea contract, paper fills, evidence,
  trade-plan contract, strategy trades, paper exit rules, lifecycle routes, symbol lookup, watchlist chain)
                                                                  607 passed, 2 failed → the 2 contract fixtures regenerated → 36 passed (contract files)
Phase 1 risk suites (tests/test_risk*.py, 12 files) + payoff + PRD + plan + both contracts + order-path guard, on the merge
                                                                  536 passed, 5 skipped, 3 warnings in 42.74s
strategy engine (liquid universe, provenance, screen→strategy, market data, engine, sizing, adjusted, exit rules, screen,
  copilot backtest, AI trader x2, config, order-path guard)       397 passed, 3 warnings in 21.62s
tests/test_liquid_universe.py (final)                             20 passed (52 with provenance, market data, screen→strategy)
tests/test_backtest_provenance.py                                 8 passed
tests/test_rs63_readiness.py                                      9 passed
```
The 5 skipped are `test_risk_reservation_mongo.py`, which needs a real Mongo.

**Phase 1 double counting (#363).** `services/risk_gate` never calls the payoff engine:
```
$ grep -rn "compute_payoff\|strategy_plan.payoff\|from services.strategy_plan import" services/risk_gate/
services/risk_gate/inputs.py:172:        from services.strategy_plan import regime_fit      (the regime read only)
```
A structure's risk request carries its legs only (`wiring.structure_request`). `estimate.py` computes its own gross
maximum loss (`gate.structure_capital_at_risk`) and adds its own desk-card costs, so payoff-v2's net figures cannot be
added twice.

### Changed numbers in existing tests, one by one
Each is re-derived component by component in the test's comment. The PR body has the same table.

| Test | payoff-v1 | payoff-v2 | Reason |
|---|---|---|---|
| test_strategy_payoff cash | entry 80.75, net@1300 8,334.25 | 228.62, 8,047.92 | equity delivery STT 0.1% ×2, exch, SEBI, stamp, GST |
| … long future | entry 323.75, net 16,843.75 | 353.34, 16,483.82 | futures STT 0.05% sell, exch, stamp, GST |
| … long call | net@1200 −10,025; CaR 10,045 | −10,033.10; 10,056.70 | option charges; worthless exit 20 + GST 3.60 |
| … bull call spread / scenarios | entry 47.25; 6,894.00 / −5,547.25 | 67.59; 6,812.82 / −5,567.59 | STT on sale premium and on intrinsic at expiry, exch, stamp, GST |
| … request costs | 8,133.75 | 7,957.39 | overrides replace slippage and brokerage only |
| … pre-expiry | slip + ₹20 | card formula (tolerance 0.04) | per-component paisa rounding |
| PRD Example F | CaR 4,500 / 4,588.75 | 4,517.45 / 4,620.60 | statutory charges at zero slippage/brokerage; gross 4,500 still asserted |
| test_strategy_plan cash net R:R | 1.90 | 1.72 | now the sizing's card: net risk 9,159.32 = `risk_at_stop_net_inr` |
| 4 suites: version | payoff-v1 | payoff-v2 | the bump |
| fixtures contract-trade-plan-paper.json, desk-strategy-levels-banknifty.json | — | regenerated from the backend's builders | payoff figures; the cash plan id hashes calculation_version |

### CI (TC-CI-1 … 5)

The exact workflow steps were run on the final tree by
`/tmp/claude-1002/-home-deploy-nivesh-ai/ed913e2a-3741-4fc5-b4b0-5ab7c9f24ea5/scratchpad/ci/ci-proof.sh`. It reads the
steps and env from the YAML, runs them in a fresh `python:3.11-slim` container with network but no services and the
tree mounted read-only, and uses `bash -eo pipefail`:
```
allowlisted files run: 244
Python 3.11.17
Resolved 252 packages in 3.41s
== install seconds 22
6441 passed, 27 skipped, 15 warnings in 241.57s (0:04:01)
== test seconds 250
== wall seconds (container start to end) 276
exit 0
```
- This run overlapped a full-suite run on the same 4-vCPU VM, so the times are pessimistic. GitHub runner timing is
  UNVERIFIED until the PR exists.
- `python:3.11-slim` was used because it is the base of both repo backend Dockerfiles.
- The first clean full run selected the allowlist: 324 files, 236 clean. Later additions: 4 Phase 1 risk suites merged
  after that run, and this PR's 4 new files.

Negative control (TC-CI-3): a copy of the tree at ce923426 with PRD Example A's expected quantity changed from 77 to
78, run with the workflow's pytest command. That test and its number are unchanged on this branch:
```
E       assert (True and 77 == 78)
FAILED tests/test_prd_worked_examples.py::test_tc60_example_a_on_the_desk_calculator_is_77_not_85
1 failed, 43 passed, 2 warnings in 6.75s
exit 1
```
Static checks: `grep -c 'secrets\.' .github/workflows/backend-tests.yml` → 0. Triggers: `pull_request: branches: [dev,
main]` and `workflow_dispatch`.

## UI / Playwright Tests

- **Specs:**
  - `copilot-app-backtest-universe` (new, TC-LU-12);
  - the specs that read the two regenerated contract fixtures: `copilot-app-desk-top10`, `copilot-app-ai-watchlist`,
    `copilot-app-desk-strategy-top`;
  - the specs that mount the strategy builder: `copilot-app-trader`, `copilot-app-screens`;
  - `copilot-app-desk-lab`, the payoff screens.
- **Command:** `run-fe.sh /home/deploy/nivesh-p4-hardening <log> <7 specs>`. It runs tsc, a vite production build,
  vite preview, then `npx playwright test --config pw.copilot-app.config.ts`, on a mocked API with no network.
- **Output (final tree):**
```
== tsc
tsc: clean
== build
✓ built in 37.10s
== playwright
  ✓   15 [copilot-app] › e2e/tests/copilot-app-backtest-universe.spec.ts:69:3 › Backtest universe — survivorship status › the liquid point-in-time universe is first and chosen by default, and its run says it is point in time
  ✓   16 [copilot-app] › e2e/tests/copilot-app-backtest-universe.spec.ts:88:3 › Backtest universe — survivorship status › an index universe's run shows the engine's survivorship warning; switching to the liquid universe clears it
  ...
  2 skipped
  226 passed (4.1m)
exit 0
```
- The 2 skipped are the desk-lab screenshot tests (`set SHOTS_DIR`).
- The mocked backtest replies come from `e2e/fixtures/strategy-backtest-universe.json`, whose universe texts
  `test_tc_lu12_the_e2e_fixture_matches_the_engine` asserts are the engine's own. The mock therefore cannot drift from
  the backend.
- Result: PASS, on a mocked API.

## Data Correctness (staging, read-only)

**TC-LU-11: liquid-eq-v1, the engine's rule vs an independent SQL version.**
- Rows were exported with `\copy (SELECT … FROM nidp.prices_eod WHERE series='EQ' AND as_of_date IN <30 sessions ending
  at d>)`, plus NSE's ETF list from `security_reference_daily`.
- `liquid_universe.membership` was run offline on those rows. The SQL version was written separately (window CTE,
  `percentile_cont(0.5)`, `DISTINCT ON`).
```
2025-06-02: sessions read 30 (2025-04-21..2025-06-02), EQ symbols priced on 2025-06-02: 2090, python members 688, sql members 688, identical True, only_python [], only_sql [], sessions_without_prices []
2025-12-29: sessions read 30 (2025-11-17..2025-12-29), EQ symbols priced on 2025-12-29: 2378, python members 623, sql members 623, identical True, only_python [], only_sql [], sessions_without_prices []
2026-04-15: sessions read 30 (2026-02-26..2026-04-15), EQ symbols priced on 2026-04-15: 2456, python members 734, sql members 734, identical True, only_python [], only_sql [], sessions_without_prices []
2026-10-23: sessions read 30 (2026-09-09..2026-10-23), EQ symbols priced on 2026-10-23: 2706, python members 780, sql members 780, identical True, only_python [], only_sql [], sessions_without_prices []
```
Survivorship (2025-06-02):
```
 on_date    | members | not_priced_eq_on_2026_10_26 | not_in_latest_nifty500
 2025-06-02 |     688 |                          22 |                    245
 gone: CIGNITITEC, DHANI, E2E, GANESHHOUC, GSPL, GUJGASLTD, HEG, HFCL, ICICIPRULI, INFIBEAM, ITDCEM, IWEL, JBCHEPHARM, LTIM, MANGCHEFER, MOREPENLAB, PEL, RELINFRA, SEQUENT, SGLTL, SWANENERGY, TATAMOTORS
```

This test found two defects, both fixed in `c2352e65`:
1. **ETFs got through.** The first version excluded ETFs by name only. NSE's list flags 10 members on 2025-06-02 and 19
   on 2026-10-23 that the name rule missed (GOLD1, GOLDCASE, LIQUIDCASE, MON100, SETFNIF50, …). Every one had feature
   rows on 2026-10-23, so a strategy could have bought them. The list now excludes them.
2. **An empty start of window.** The feature calendar starts 2025-12-29, but prices go back to 2024-04-01. A lookback
   taken from the feature calendar would have left a window's first 19 dates empty. The lookback now comes from the price
   history.

Calendars (read-only):
```
prices_eod EQ:          2024-04-01 | 2026-10-26 | 634 sessions
stock_features_daily:   2025-12-29 | 2026-10-26 | 203 dates
```

**TC-RP-4: stored staging runs.**
- The rows were read with a SELECT from `strategy_runs` joined to `strategy_versions` inside the app backend container.
- They were then read offline through this branch's `run_provenance`.
```
bb3d0a32 2026-04-20..2026-10-20 | universe latest_snapshot | spec_sha256 471507de32f1 (derived at read time from the ) | not_recorded ['data_watermark', 'code_version', 'rule_version.exit_rules_version', 'cost_model', 'entry_timing'] | complete False
b2f50576 2026-06-01..2026-09-18 | universe latest_snapshot | spec_sha256 279918c82036 (derived at read time from the ) | not_recorded [...same five...] | complete False
9e64e0ef 2026-04-21..2026-10-21 | universe latest_snapshot | spec_sha256 37d44a3db164 (derived at read time from the ) | not_recorded [...same five...] | complete False
```
All three are readable. They are labelled `latest_snapshot` (survivorship bias), and what they never recorded is named.

**TC-RS-2: RS63 readiness now.** The script's own `--print-sql` SELECTs were exported through `nidp-psql.sh`:
```
RS63 confirmation readiness: NOT_READY (as of 2026-10-27)
  calendar 2024-04-01..2026-10-26 (634 sessions); signal dates after 2026-10-09: 10
  complete 10-session outcomes: 0 (known regime 0: up 0, down 0; unknown 0)
  awaiting their outcome: 10
  ...
exit=1
```

**4.4 facts re-checked:**
```
to_regclass('nidp.intraday_bars'), to_regclass('nidp.intraday_ingest_log') → NULL, NULL
nidp tables matching intraday|minute|tick → 0
Mongo count_documents: kite_live_minute 156, kite_live_intraday 33, kite_live_close 2
index_constituents: Nifty 50/100/200/500 → 4 snapshots each (2026-10-12, -13, -20, -22)
```

## Full backend suite, branch vs plain origin/dev (TC-REG-1)

Method:
- Both trees run `python -m pytest tests -q --continue-on-collection-errors --junitxml=…` in `nivesh/backend:staging`
  with `--network none`.
- The branch tree is a `git archive` of HEAD `59e6716a`; dev is a `git archive` of origin/dev `87a90bca`.
- The comparison is per test id, from the JUnit files.
```
dev:    580 failed, 6631 passed, 584 skipped, 41 warnings, 166 errors in 449.05s (0:07:29)
branch: 580 failed, 6702 passed, 584 skipped, 42 warnings, 166 errors in 466.97s (0:07:46)
dev tests 7961 {'passed': 6631, 'failed': 746, 'skipped': 584}
branch tests 8032 {'passed': 6702, 'failed': 746, 'skipped': 584}
fails on branch, passes on dev: 0
fails on dev, passes on branch: 0
new on branch: 74 | new failing: 0
on dev only (renamed/removed): 3
```
- New: test_payoff_cost_card 34, test_liquid_universe 20, test_rs63_readiness 9, test_backtest_provenance 8, and 3
  `test_portfolio_import_preview` ids.
- The 3 "dev only" ids are the same parametrised test. Its ids embed freshly zipped bytes, so they differ on every run;
  it is not a removal.
- The 746 failures and errors are identical on both sides. They are pre-existing in this sandbox: no Mongo or Postgres,
  missing env files and fixtures.
- **The "fails on branch, passes on dev" list is empty. PASS.**

## Inputs required from user
- None for this report.
- To finish on staging, the branch must be merged to `dev` (the owner's action); then run the plan in the PR body.
- Owner decisions raised:
  - installing the RS63 monthly cron;
  - importing NSE's index history;
  - whether the CI allowlist should become an exclusion list, so that new suites run without being added.

## Verdict: NOT PASS YET — every local, contract, CI-proof, UI and read-only data test above passed; the staging API run of the new code awaits deployment (UNVERIFIED), and the CI job has not yet run on GitHub
