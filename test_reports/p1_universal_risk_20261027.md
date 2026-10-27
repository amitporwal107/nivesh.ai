# Functionality Verification Report — Phase 1: Universal Risk Enforcement

- **Branch:** feat/p1-universal-risk (off origin/dev 6a3ec2e3; origin/dev e704c231 merged in)
- **Date:** 2026-10-27
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** unit and integration tests in throwaway containers (nivesh/backend:staging image, `--network none`);
  real MongoDB tests against a throwaway `mongo:7` container on a private network; READ-ONLY probes of the real staging
  book through a throwaway container with the branch mounted read-only. Nothing was deployed, flagged or written on
  staging.
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary

**One risk decision on every position-creating path.** `services/risk_gate/service.py` (policy `universal-risk-v1`)
grows the F&O gate into the single decision service, with `risk_governor.evaluate` as one of its checks. It is called
before anything is written on six paths: desk cash POST, desk strategy POST, journal create, journal ENTRY fill,
AI-trader signals and AI-trader confirm. No flag bypasses the core checks. `fno_risk_gate` now only adds the gate's fixed
F&O structure checks.

**What a decision does:**
- **Inputs:** resolved on the server, and fresh (`services/data_freshness.py`).
- **Estimated risk:** costs + a 1% gap stress (`est-risk-v1`).
- **Limits:** the per-account owner-default profile (0.5 / 3 / 10 / 25 / 2 / 4 / 10 / 1.5) with an audited setter.
- **Recorded:** in `risk_decisions`, fail-closed.
- **Reserved:** atomically on `paper_accounts` in one conditional update.

**The book** (`services/risk_book.py`) marks F&O structures on the bhavcopy `close_price`, so drawdown is known while
they are open.

**Also in this branch:**
- frontend reduce and block rendering, and a risk profile card;
- a reservation migration (dry run only);
- the route inventory and real-Mongo concurrency tests.

**Scope verified here:** everything except signed-in staging API calls. Those need a deploy and an owner session token;
see the Verdict.

## Test Cases

Authored in `test_reports/p1_universal_risk_TESTCASES.md`. That file states honestly that it was written after the
service was drafted, before the new suites. The IDs below refer to it.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| U-1 | inventory | every position-writing route calls the service | unit (AST) | no route missing | PASS |
| U-2 | inventory | the six paths found, nothing unexpected | unit (AST) | exactly P1–P6 | PASS |
| U-3 | mandatory | flag off: every path judged, recorded, reserved | api (fakes) | rows `source=risk_service` | PASS |
| U-4 | flag scope | the flag adds only the F&O structure checks | api | `futures_only` only with the flag | PASS |
| U-5 | live | order-path guard; `LIVE_EXECUTION_AVAILABLE` False | unit | pass | PASS |
| M-1…M-11 | matrix | 6 paths × 11 reasons: 409 (P5 ticket rejected), nothing written, nothing reserved, one decision row with code, version, correlation id | api | 63 refusals | PASS |
| baseline | matrix | valid inputs pass every path, recorded and reserved, invariants clean | api | 6 pass | PASS |
| D-1 | sizing | Example A at 0.5% of ₹6 lakh | unit | reduce, total ≤ ₹3,000 | PASS |
| D-2 | sizing | Example E at ₹2,500 | unit | `min_lot_exceeds_budget` | PASS |
| D-3 | sizing | Example F at ₹2,500 | unit | `min_lot_exceeds_budget` (₹4,500 + costs) | PASS |
| D-4…D-8 | estimate, lots, exposure vs risk, shape, replay | — | unit | as specified | PASS |
| F-1…F-12 | fail closed | each input missing or stale → its own code; options marked at close | unit | as specified | PASS |
| P-1…P-6 | profile | defaults, tighten, loosen 403, reason, concurrency | unit | as specified | PASS |
| P-7 | profile | GET/PUT `/api/risk/profile` on staging | api (staging) | 200 / 403 | **NOT RUN** (needs deploy + owner token) |
| R-1…R-7 | reservation | real Mongo: concurrency, full-decision race, retry, duplicate, cancel, close-once, restart | integration | as specified | PASS |
| R-8 | partial exits | not supported (stated) | — | — | N/A |
| G-1 | migration | dry run writes nothing | unit | zero writes | PASS |
| G-2 | migration | dry run read-only against staging | data | counts, plan | PASS (output below) |
| G-3 | migration | apply → rollback exact; re-apply idempotent | unit | as specified | PASS |
| UI-1…UI-3 | frontend | reduce offer, block reasons, profile card | e2e (mocked API) | 10 cases | PASS |
| UI-4 | frontend | tsc and build | build | clean | PASS |
| X-1 | regression | Phase 0 and every touched suite | unit / api | pass | PASS |
| X-2 | regression | full `backend/tests`: fails on branch, passes on origin/dev | full suite | empty list | PASS (output below) |
| S-1 | staging data | real book: equity, F&O marks, day/week P&L, drawdown, inputs resolve | data (read-only) | known | PASS (output below) |
| S-2 | staging API | signed-in desk POSTs answer reduce / block with decision rows | api (staging) | 409 / 201 | **NOT RUN** (needs deploy + owner token) |

## API / Endpoint Tests

### pytest: risk, desk, journal, AI-trader and Phase 0 suites on the final code

Includes the real-Mongo suite. A throwaway `mongo:7` on a private network: `docker network create p1-risk-mongo-net`,
`docker run -d --rm --name p1-risk-mongo --network p1-risk-mongo-net mongo:7` (db version v7.0.43), removed afterwards.

```
sudo docker run --rm --network p1-risk-mongo-net -v /home/deploy/nivesh-p1-risk:/work:ro -w /work/backend ... -e RISK_MONGO_URL=mongodb://p1-risk-mongo:27017 \
  nivesh/backend:staging python -m pytest tests/test_risk_service.py tests/test_risk_entry_paths.py tests/test_risk_route_inventory.py \
  tests/test_risk_reservation_mongo.py tests/test_risk_migration.py tests/test_order_path_guard.py tests/test_desk_trading.py \
  tests/test_desk_paper_safety.py tests/test_risk_gate_desk_journal.py tests/test_desk_strategy_trades.py tests/test_paper_fills_pnl.py \
  tests/test_fno_idea_paper_trade_contract.py tests/test_paper_account.py tests/test_risk_gate.py tests/test_desk_paper_sim.py \
  tests/test_ai_trader_execution.py tests/test_risk_gate_ai_trader.py tests/test_ai_trader.py tests/test_ai_trader_config_risk.py \
  tests/test_risk_routes.py tests/test_risk_replay.py tests/test_risk_controls.py tests/test_risk_equity.py tests/test_desk_exit_job.py \
  tests/test_paper_reconcile.py tests/test_honesty_safety_pass.py tests/test_exit_rules.py tests/test_paper_exit_rules.py \
  tests/test_backtest_exit_rules.py tests/test_prd_worked_examples.py -q -p no:cacheprovider
1249 passed, 5 warnings in 63.87s (0:01:03)
```

### Real MongoDB (R-1…R-7), verbatim

```
tests/test_risk_reservation_mongo.py::test_r1_concurrent_reservations_never_exceed_the_open_risk_cap PASSED
tests/test_risk_reservation_mongo.py::test_r3_r4_r5_retry_duplicate_symbol_and_cancel PASSED
tests/test_risk_reservation_mongo.py::test_r6_closing_a_trade_releases_its_reservation_exactly_once PASSED
tests/test_risk_reservation_mongo.py::test_r7_a_reservation_whose_process_died_before_the_insert_is_swept_after_the_grace PASSED
tests/test_risk_reservation_mongo.py::test_r2_concurrent_full_decisions_whose_sum_exceeds_the_cap_stay_within_it R-2: per-entry risk Rs 3806.08, accepted 7, lost at the atomic step 2, refused by their own decision 3, reserved Rs 26642.560000000005 of Rs 30,000
PASSED
========================= 5 passed, 1 warning in 3.66s =========================
```

R-1: 20 concurrent reservations of ₹5,000 against ₹30,000 admit exactly 6. The counters equal the sum of the entries.

**R-2 found a defect, now fixed.** The orphan sweep judged a reservation's age on the decision's injectable clock instead
of the real clock that stamped it. A decision clock ahead of it read in-flight reservations as orphans, and 9 were
admitted against a cap of 7. The sweep now uses the real clock (commit 3f61a8ca).

### Full `backend/tests`: branch vs plain origin/dev (X-2)

Both trees ran the whole suite in the same image, `--network none`. The many failures common to both are environment
failures (no network, no Postgres), not regressions. Results, before the final rerun:
```
branch (merge d579dfb6): 580 failed, 6521 passed, 583 skipped, 46 warnings, 166 errors in 480.95s
origin/dev e704c231:     628 failed, 6171 passed, 578 skipped, 45 warnings, 169 errors in 441.39s
branch {'fail': 746, 'pass': 6521, 'skip': 583} dev {'fail': 797, 'pass': 6171, 'skip': 578}
FAILS ON BRANCH, PASSES ON DEV: 0
fail on branch, absent on dev: []
pass on branch, fail on dev: 42
```
The final rerun on the last commit is in the next section.

### Staging API (signed-in)

**NOT RUN.** The branch is not deployed (the brief allows no deploy), and the signed-in checks need an owner session
token. The plan is in the PR body ("Staging verification plan").

## UI / Playwright Tests

`run-fe.sh` runs tsc, the production build, vite preview and Playwright with mocked APIs and no network.

```
bash .../scratchpad/run-fe.sh /home/deploy/nivesh-p1-risk .../p1/fe_final.log e2e/tests/copilot-app-desk-risk-phase1.spec.ts \
  e2e/tests/copilot-app-desk-risk-controls.spec.ts e2e/tests/copilot-app-desk-top10.spec.ts e2e/tests/copilot-app-ai-watchlist.spec.ts \
  e2e/tests/copilot-app-desk-scanner.spec.ts
== tsc
tsc: clean
== build
✓ built in 31.80s
== playwright
  158 passed (2.6m)
exit 0
```

**Two earlier runs failed, and both causes are fixed or explained:**
- **Machine load.** One run overlapped two full backend suites on the same machine. Seven tests hit 5-second expectation
  timeouts; six passed when rerun alone.
- **A real merge interaction.** In my new spec, dev's #361 added `max_hold_sessions` to the Top 10 body. The spec now
  checks the fields it is about.

All API responses in these specs are mocked. The screens were not run against the real backend.

## Data Correctness (staging, read-only)

### G-2: migration dry run against staging

2026-10-27 03:08 UTC. A throwaway container, the branch mounted `:ro`, on the staging network with the backend's
Mongo/DaaS settings passed through the environment (never printed). The script calls find / find_one only.
```
risk-reservation-migration-v1 DRY RUN — read only, nothing written
counts: {"accounts": 1, "open_desk_trades": 5, "open_journal_trades": 0, "already_reserved": 0, "to_reserve": 5, "risk_unknown": 0, "accounts_affected": 1}
  a5530afb a797d230 desk_paper_trades structure BANKNIFTY  qty=None entry=None stop=54555.15 risk_rs=4281.99 exposure_rs=12000.0 sector=None paper_reserved_rs=12000.0 -> to_reserve (migr-a797d230-...)
  a5530afb ffa3904e desk_paper_trades cash      ICICIBANK  qty=89 entry=1400.2 stop=1363.26 risk_rs=4663.93 exposure_rs=124617.8 sector=Financial Services paper_reserved_rs=124617.8 -> to_reserve
  a5530afb 37681c72 desk_paper_trades cash      ICICIBANK  qty=89 entry=1400.2 stop=1363.26 risk_rs=4663.93 exposure_rs=124617.8 sector=Financial Services paper_reserved_rs=124617.8 -> to_reserve
  a5530afb d8f6820f desk_paper_trades cash      PNB        qty=1000 entry=110.46 stop=108.82 risk_rs=3129.09 exposure_rs=110460.0 sector=Financial Services paper_reserved_rs=110460.0 -> to_reserve
  a5530afb 71ccca30 desk_paper_trades cash      RELIANCE   qty=1 entry=1201.8 stop=1200.6 risk_rs=64.29 exposure_rs=1201.8 sector=Oil Gas & Consumable Fuels paper_reserved_rs=1201.8 -> to_reserve
account {"user": "a5530afb", "account_exists": true, "cash_rs": 984547.28, "counters_before": {"risk_rs": 0.0, "exposure_rs": 0.0, "positions": 0}, "counters_after": {"risk_rs": 16803.23, "exposure_rs": 372897.4, "positions": 5}, "sector_rs_after": {"unknown": 12000.0, "Financial Services": 359695.6, "Oil Gas & Consumable Fuels": 1201.8}, "existing_invariants": [], "over_owner_default_caps": ["sector Financial Services 359,695.60 > 25.0% of cash"], "unfunded_trades": []}
```
The dry run predates the index-underlying fix. With it, BANKNIFTY maps to Financial Services (index-sectors-v1).
`--apply` was NOT run.

### S-1: the real book and inputs through the service

Read-only. The database proxy raises on any write, and `gather` + `decide` are called without `enter`, so nothing is
recorded and nothing is reserved. The requests are hypothetical.

```
user a5530afb equity {"equity_rs": 984665.12, "cash_rs": 984547.28, "net_unrealised_rs": 117.84, "unknown_reasons": [], "marks_as_of": "2026-10-26", "fno_marks_as_of": null, "fno_marks_ok": true}
peak {'peak_rs': 1000000.0, 'starting_capital_rs': 1000000.0, 'stored': False} drawdown_pct 1.5335
day {"start": "2026-10-27", "pnl_rs": -51.08, "unknown_reasons": [], "start_equity_rs": 984716.2}
week {"start": "2026-10-26", "pnl_rs": 1514.54, "unknown_reasons": [], "start_equity_rs": 983150.58}
open {"positions": 5, "risk_rs": 16803.23, "legacy_risk_rs": 16803.23, "exposure_rs": 372897.4, "sector_rs": {"Financial Services": 371695.6, "Oil Gas & Consumable Fuels": 1201.8}, "unclassified_exposure_rs": 0.0, "held_symbols": ["ICICIBANK", "PNB", "RELIANCE"]}

[HAL cash 20 @4775 stop 4600 target 5200] outcome=reduce requested=20 approved=10
  reasons: [('BEAR_REGIME', 'reduce', 'BEAR', None)]
  estimate: {'gross': 1750.0, 'costs': 198.5, 'gap_stress': 460.0, 'total': 2408.5}
  freshness: {'last_close': True, 'sector': True, 'market': True, 'equity': True} market 2026-10-23 BEAR 16.86
[ICICIBANK cash (already held)] outcome=block requested=50 approved=0
  reasons: [('ALREADY_HELD', 'reject', 'ICICIBANK', None), ('BEAR_REGIME', 'reduce', 'BEAR', None), ('SECTOR_LIMIT', 'reduce', 0, 25.0), ('sector_exceeded', 'block', 1403.0, 0)]
[RELIANCE cash 200 (position cap)] outcome=block requested=200 approved=0
  reasons: [('per_trade_risk_exceeded', 'reduce', 9512.52, 4923.33), ('ALREADY_HELD', 'reject', 'RELIANCE', None), ('BEAR_REGIME', 'reduce', 'BEAR', None), ('POSITION_SIZE', 'reduce', 81, 10.0)]
```
(The first block is the earlier run of this probe; the decisions are from the rerun with Postgres passed through.)

**Index underlyings (staging probe, after the fix):**
```
BANKNIFTY last_close 54366.7 2026-10-26 bars 28 adv None err None | sector Financial Services None
NIFTY last_close 22753.2 2026-10-26 bars 28 adv None err None | sector Broad market index None
ICICIBANK last_close 1403.0 2026-10-26 bars 28 adv 16942573790.06 err None | sector Financial Services None
```

**Staging backend's own regime read** (`docker exec`, read-only):
```
{'available': True, 'label': 'Bearish', 'as_of': '2026-10-23', 'trend': 'down', 'india_vix': 16.86, 'reason': None}
```

**Before the fix, the probe found a real gap.** Index underlyings had no `prices_eod` bars and no sector, so every index
F&O idea would have been refused. Fixed in e2820f46: the close comes from the NSE index's EOD, and the sector from a
named mapping.

## Inputs required from user

- An owner session token, and a staging deploy, for the signed-in API checks (P-7, S-2).
- A go-ahead for the migration `--apply` (with a snapshot), per study §9.2.

## Verdict: BLOCKED
Every automated case passed with real output above. The signed-in staging API checks (P-7, S-2) were not run: the
branch is not deployed and they need an owner session token. `test_reports/OVERRIDE_p1_universal_risk.md` records this.
