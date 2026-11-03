# Functionality Verification Report — Paper-trade exits + backtest integrity (Phase 2.3–2.6, 4.1, 4.5)

- **Branch:** feat/p2-exits-backtest (off origin/dev 6a3ec2e3), worktree /home/deploy/nivesh-p2-exits
- **Date:** 2026-10-27
- **Author:** Claude (full-stack developer + QA)
- **Environment:** unit/contract tests in the staging backend image (`nivesh/backend:staging`, `--network none`); Playwright on a
  local production build with mocked API; **read-only** staging data (Mongo `find`, data-platform GETs, warehouse SELECT)
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary

One pure exit step, `services/exit_rules.step` (exit-rules-v1), is now used by the DSL backtest, the cash paper simulator and the
F&O strategy trades' underlying levels.

Order inside a session:
1. The gap rule on the open, against the stop as of the previous close.
2. A pending trend exit at the open.
3. The intrabar touch of the same stop, then the target. Both in one bar → the stop.
4. Expiry, then time in sessions.
5. After the bar only: Wilder ATR_t, the high-water mark from the high, and stop = max(stop, hw − k·ATR_t). The stop never
   loosens and is versioned.

ATR trailing and the EMA trend exit are opt-in research rules (D4), off by default.

Other changes:
- Every surface that opens a share paper trade sends `max_hold_sessions`.
- The AI Trader passes `max_hold_days` and `trailing_atr_mult` (N15).
- Options are marked at `close_price`, never `settle_price`.
- Premium stop and T1 are evaluated on the whole structure when stored. The Greek review is a flag.
- The exit job survives and reports a failed close.
- The backtest:
  - fills gaps at the open;
  - counts sessions and records TRAILING_STOP;
  - offers next-open entry;
  - charges the desk-cost-v2 card;
  - reports the PRD §12 diagnostics, a slippage sweep, the code version and a data watermark.

PRD Examples A–H are golden tests (Phase 4.1).

Commits:
- `464c3058` exit step
- `e80606d9` backtest
- `dbefba26` desk / F&O / job / AI Trader
- `15c1230b` UI
- `24025426` A–H + CI proposal
- `c32ca09a` job log line

## Test Cases
Authored up front in `test_reports/p2_exits_backtest_TESTCASES.md`.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1..4 | exit step | stop touch; gap → open; target touch/jump → target; both → stop | unit | as designed | PASS |
| TC-5 | exit step | time counted in sessions | unit | close of session N | PASS |
| TC-6/7/9 | exit step | Example H 1,040; same bar 1,080/1,035 no exit; trailing_stop vs stop | unit | as designed | PASS |
| TC-8 | exit step | stop never loosens, long and short (50 random paths) | property | monotone, versions increase | PASS |
| TC-10 | exit step | disabled opt-in rules (25 paths) | property | identical exits | PASS |
| TC-11 | exit step | Wilder ATR to t; zero/missing ATR never used, flagged | unit/edge | as designed | PASS |
| TC-12 | exit step | close < EMA → next open; time wins; gap beats trend | unit | as designed | PASS |
| TC-13 | exit step | short-side mirror | unit | as designed | PASS |
| TC-14 | exit step | invalid levels; bar without range; missing open | edge | refused / IncompleteBar / flagged | PASS |
| TC-20 | backtest | gap through stop | unit | STOPLOSS at the open (90, was 95) | PASS |
| TC-21 | backtest | trail exit, same-bar, missing ATR | unit | TRAILING_STOP 104.86; no same-bar exit; no 2 % stand-in | PASS |
| TC-22 | backtest | time | unit | 3 sessions (13 Jan), not 3 calendar days (12 Jan) | PASS |
| TC-23 | backtest | next-open entry; default labelled | unit | entry at next open 102; `signal_close` default | PASS |
| TC-24 | backtest | expectancy ₹/R per trade & session, payoff, Sharpe/Sortino, exposure, turnover, capital, signals, sweep | unit | hand-computed values | PASS |
| TC-25 | backtest | desk-cost-v2 charges (₹35.36 buy / ₹34.89 sell on 99 × ~100); flat selectable | unit | as designed | PASS |
| TC-26 | backtest | persist_run writes snapshot_as_of, code_version, trade metadata; watermark failure recorded | unit | as designed | PASS |
| TC-27 | parity | backtest vs paper, 20 paths × {no trail, k 1.5, k 2} | property | same reason, session, price, stop history | PASS |
| TC-30 | paper | existing desk suites unchanged | regression | unchanged | PASS |
| TC-31 | paper | opt-in trail: history, trailing_stop, warm-up read, invalid config | unit | as designed | PASS |
| TC-32 | paper | rules off (None / {} / absent) | property | identical simulation | PASS |
| TC-33 | paper | versioned stop write; stale reader conflict; double apply | unit/failure | one write, one close, one release | PASS |
| TC-34 | exit job | a close write fails | failure | others closed; `exits_failed` + id in job_runs (partial); retry closes once | PASS |
| TC-35 | exit job | new reasons counted | unit | no KeyError | PASS |
| TC-40 | F&O | marks at close, never settle; no close → no mark (flagged) | unit | as designed | PASS |
| TC-41/42 | F&O | premium stop / T1 on the whole structure; underlying stop wins | unit | exit_basis premium / underlying | PASS |
| TC-43 | F&O | no stored plan / a futures leg → today's rules | unit | no premium exit | PASS |
| TC-44 | F&O | Greek review | unit | flag + event, no exit | PASS |
| TC-50 | AI Trader | body carries time + trail; desk validator accepts; cap 250 | unit/contract | as designed | PASS |
| TC-60 | 4.1 | A–H gross; cost-inclusive A 77, B 145, C 292, E 0, G 64; C/D refused; F rejected; H 1,040 | golden | as designed | PASS |
| TC-61 | 4.1 | missing prices, invalid stops, zero/stale ATR, min lot, partial fills, monotone, gap parity | edge | as designed | PASS |
| TC-70 | UI + contract | bodies send `max_hold_sessions`; backend accepts the exact bodies | e2e + contract | as designed | PASS |
| TC-71/72 | UI | record: reasons, stop history, rule labels; strategy premium plan, close marks | e2e | as designed | PASS |
| TC-80 | staging | replay the stored trades, live rules vs new step | data, read-only | agree or explained | PASS (12/12 agree) |
| TC-81 | safety | tests/test_order_path_guard.py | regression | passes | PASS |
| TC-82 | regression | full backend suite, branch vs origin/dev | regression | "fails on branch, passes on dev" empty | see below |

## API / Endpoint Tests

**Not run against staging.** The branch is not deployed: this task forbids push, PR and merge, and staging runs `dev`. The
endpoints touched are:
- `GET /api/desk/paper-trades` and `GET /api/desk/paper-trades/{id}`: new response fields;
- `POST /api/desk/paper-trades`: optional `exit_rules`.

They are exercised through the existing route tests (FastAPI TestClient) in
`tests/test_desk_trading.py` / `test_desk_strategy_trades.py` / `test_desk_exit_job.py`, plus the new contract tests. UNVERIFIED on
staging: the plan is in the PR body (staging verification plan).

**pytest — every new and touched file, at HEAD 24025426:**
```
python -m pytest tests/test_exit_rules.py tests/test_backtest_exit_rules.py tests/test_paper_exit_rules.py tests/test_prd_worked_examples.py tests/test_strategy_backtest_sizing.py tests/test_strategy_backtest_adjusted.py tests/test_strategy_engine.py tests/test_desk_trading.py tests/test_desk_paper_sim.py tests/test_paper_fills_pnl.py tests/test_desk_strategy_trades.py tests/test_desk_exit_job.py tests/test_ai_trader_execution.py tests/test_ai_trader_strategy.py tests/test_order_path_guard.py -q -p no:cacheprovider
769 passed, 3 warnings in 27.57s
```
After the last commit (c32ca09a, a log line in the job script): `tests/test_desk_exit_job.py` → `25 passed, 2 warnings in 6.56s`.

**Full backend suite, branch vs plain origin/dev:**

Method:
- Both trees run `python -m pytest tests -q --continue-on-collection-errors --junitxml=...` in the same image, with
  `--network none`.
- The branch was at 24025426. c32ca09a only adds a log line, and `test_desk_exit_job.py` was rerun after it.
- The dev tree is a full `git archive 6a3ec2e3`.
- A first dev baseline archived only `backend/`. It was missing `research/` and `frontend-v5/e2e/fixtures/`, which made 52
  tests fail on dev only, so it was discarded and rerun from the full tree.

The comparison is per test id, from the JUnit files:
```
branch: 580 failed, 6422 passed, 578 skipped, 39 warnings, 166 errors in 408.56s (0:06:48)
dev:    580 failed, 6153 passed, 578 skipped, 42 warnings, 166 errors in 435.35s (0:07:15)
dev tests 7477 {'passed': 6153, 'failed': 746, 'skipped': 578}
branch tests 7746 {'passed': 6422, 'failed': 746, 'skipped': 578}
fails on branch, passes on dev: 0
fails on dev, passes on branch: 0
new on branch: 272 | new failing: 0
on dev only (renamed/removed): 3     ← one parametrised test (test_portfolio_import_preview) whose ids embed freshly zipped bytes; not a removal
```
- The 746 failures and errors are identical on both sides. They are pre-existing in this sandbox: no Mongo or Postgres,
  missing env files, and fixtures.
- **The "fails on branch, passes on dev" list is empty.** Result: PASS.

### Changed numbers in existing tests, one by one

Each change below is the intended effect of a named rule change.

1. **`test_strategy_backtest_sizing.py`, 12 tests — no number changed.**
   - Rule change: the backtest's default cost model is now the desk cost card (`desk-cost-v2`).
   - Before the fix, 8 of these tests failed on the default: with the card, STT, stamp duty and GST are added to the flat ₹20.
   - The file's `run()` helper now names `cost_model=bt.COST_FLAT`, the model its hand arithmetic is written in, so every
     expected number is unchanged.
   - The card's own arithmetic is pinned in TC-25.
2. **`test_desk_strategy_trades.py`, 9 tests.**
   - Rule change: an option is marked at its close, never its settle price. The fixture deliberately has settle = close + 1,
     so a settle-first regression fails.
   - The marks move from 50/20 to 49/19, from 110/60 to 109/59, and from 30/20 to 29/19. Per-leg P&L moves by ₹250 per
     leg. Gross P&L is unchanged: the +1 cancels across the spread's two legs.
   - Exit-side costs move by cents:

     | Figure | Old | New |
     |---|---|---|
     | Costs, open spread | 147.99 | 147.14 |
     | Costs, target close | 193.80 | 192.97 |
     | Net, target close | 6,056.20 | 6,057.03 |
     | Net, manual close | −1,383.51 | −1,382.69 |

   - Each figure is re-derived component by component in its comment.
   - The long-put fixture rows had a settle and no close. They now carry close 20/12 and settle 21/13, and the expected
     −3,250 is unchanged at the close.
3. **Frontend specs, 5 files:**
   - The request bodies now include `max_hold_sessions` (TC-70).
   - The F&O record fixture marks option legs at `close`.
   - The target exit reads "Target (underlying levels)".

## UI / Playwright Tests

- **Specs:** copilot-app-desk-portfolio-fno, -desk-top10, -ai-watchlist, -desk-scanner, -desk-strategy-builder, -desk,
  -desk-strategy-ideas, -desk-strategy-top. These are mocked-API runs on a production build.
  - Command: `run-fe.sh /home/deploy/nivesh-p2-exits <log> e2e/tests/<8 specs>` (tsc, vite build, vite preview,
    `npx playwright test --config pw.copilot-app.config.ts`)
  - Output:
    ```
    == tsc
    tsc: clean
    == build
      14 skipped
      262 passed (3.4m)
    exit 0
    ```
  - The 14 skipped are the pre-existing Strategy Builder screenshot tests: `test.skip(!SHOTS, "set SHOTS_DIR to write
    screenshots")`.
  - The first run had 1 failure: a 390px risk-desk body assertion that predates the time exit. It was fixed in the spec
    (TC-70), and the rerun above is clean.
  - Result: PASS on a mocked API. The mocked POSTs are backed by the backend contract test
    `test_tc70_the_screen_bodies_with_a_time_exit_are_accepted`.

## Data Correctness (staging, read-only)

**TC-80 — replay of every stored staging paper trade.**

Method:
1. Mongo `find({})` on `desk_paper_trades`, with user ids hashed.
2. The data platform's own GETs (`/prices/eod/{symbol}`, `/fno/{u}/history`), from inside `nivesh-staging-app-backend`.
3. Offline replay (`--network none`) through `simulate` / `simulate_strategy` of origin/dev (today's live rules) and of this
   branch.

Nothing was written. The desk list route was not called: it applies exits.
```
cash     NORTHARC   closed stored=('stop', 268.67, '2026-10-21') | live-rules=('stop', 268.67, '2026-10-21') | new-step=('stop', 268.67, '2026-10-21') | agree=True
cash     ICICIBANK  open   stored=None | live-rules=None | new-step=None | agree=True      (checked through 2026-10-26, stop 1363.26)
cash     HAL        closed stored=('stop', 4790.0, '2026-10-22') | live-rules=('stop', 4790.0, '2026-10-22') | new-step=('stop', 4790.0, '2026-10-22') | agree=True   flags ['gap_through_stop'] both
cash     HAL        closed (same as above, ×2; the third also 'entry_outside_day_range')                                                                                agree=True
cash     FIXA/FIXC  closed stored=('manual', 100.0, None) | live-rules=None | new-step=None | agree=True
cash     ICICIBANK  open   (second, identical levels; flag entry_outside_day_range on both)                                           agree=True
strategy NIFTY      closed stored=('manual', None, None) | live-rules=None | new-step=None | agree=True
    marks live: [[206.35, 'settle', '2026-10-26'], [77.55, 'settle', '2026-10-26']] gross 3753.75
    marks new : [[206.35, 'close',  '2026-10-26'], [77.55, 'close',  '2026-10-26']] gross 3753.75
cash     PNB        open   (pull-back entry, opened 27 Oct: no session after the open date yet)   agree=True
strategy BANKNIFTY  open   (opened 27 Oct 06:53 IST: no session yet; expires 27 Oct)             agree=True
cash     RELIANCE   open   (opened 27 Oct: no session yet)                                        agree=True
agree 12 of 12
```

Notes on the replay:
- No difference needed explaining. The only visible change is the NIFTY spread's mark label: its 26 Oct settle and close
  were equal, so the marks are the same and the basis now reads `close`.
- The BANKNIFTY spread expires today, 27 Oct, after this replay. UNVERIFIED: its expiry-day marks and settlement, which
  need the 27 Oct F&O bhavcopy (ingested around 19:30 IST).

**Settle-price trap: warehouse SELECT, NIDP staging.**
```
 expiry_date | option_rows | settle_eq_underlying | settle_eq_close | traded
 2026-10-19  |         208 |                  208 |               0 |    207
 2026-10-13  |         216 |                  216 |               0 |    206
 2026-10-06  |         232 |                  232 |               0 |    194
 as_of_date | option_rows | settle_ne_close | untraded | untraded_settle_ne_close
 2026-10-26 |       40323 |           24490 |    18697 |                    18651
```

Findings:
- On an option's expiry day, `settle_price` = `underlying_price` on 656 of 656 rows. Settle-first marking would book the
  underlying's price as a premium.
- On 26 Oct, 18,651 untraded option rows carry a settle that differs from their close.
- Result: PASS. The data confirms the trap, and the new marking avoids it.

## CI
- CI runs **no pytest** today: `.github/workflows/ci.yml` runs `py_compile` only, on PRs to `main`.
- `deploy/ci-proposals/backend-exit-tests.yml` is the smallest job that would run the four new test files. It is NOT
  enabled: it sits outside `.github/workflows/`.
- So the Phase 4.1 criterion "tests run in CI" is **not met** until the owner enables that job or a wider one.

## Inputs required from user
- None for this report.
- To finish on staging: deploy the branch (a merge to `dev`, the owner's action), then run the staging verification plan in
  the PR body.

## Verdict: NOT PASS YET — every local, contract, UI and read-only data test above passed; the staging API run of the new code awaits deployment (UNVERIFIED), and CI does not run these tests
