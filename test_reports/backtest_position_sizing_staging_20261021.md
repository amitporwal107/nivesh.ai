# Functionality Verification Report — backtest position sizing on STAGING

- **Branch / commit verified:** `origin/dev` @ `044d48dd`; re-checked against `36bb791c` (current dev) — the engine is
  byte-identical between the two, so this report holds for current dev
- **Date:** 2026-10-21
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** staging app VM 45.64.105.88 — running container `nivesh-staging-app-backend`, app Postgres
  `nivesh-staging-postgres` (`pi_staging` / `portfolio_ingestion`), Mongo `nivesh-staging-mongo` (`nivesh_staging`)
- **Changed areas:** backend services: yes (`services/strategy_engine/backtest.py`) · frontend src: no
- **Supersedes:** `test_reports/OVERRIDE_backtest_position_sizing.md`, which said the real numbers were unknown. They
  are measured here, and two of that file's predictions were wrong. See "Corrections to my own earlier claims".

## Summary

`services/strategy_engine/backtest.py` used to compute profit on ONE SHARE
(`pnl_abs = (exit - entry) - 2*brokerage`) and add that rupee figure to an equity series seeded with the full
starting capital, so `total_return_pct` and `max_drawdown_pct` were not portfolio figures. It now sizes each entry to
an equal-weight slot of `current_equity / max_positions`, tracks cash, marks to market daily, and counts the entries
it had to skip. The engine is shared by the existing DSL Strategy Builder and by the AI Trader.

This is verified on staging three independent ways: the deployed files are byte-identical to the merged code; the
engine **running inside the deployed container** reproduces the stored run exactly, figure for figure; and every
stored trade reconciles to `qty × (exit − entry) − brokerage`. All output below was obtained this turn and is unedited.

## Test cases

| ID | Scenario | Expected | Result |
|----|----------|----------|--------|
| D-1 | Deployed engine identical to merged code | md5 match, `diff` exit 0 | PASS |
| D-2 | All six touched/consuming files identical | 6 of 6 identical | PASS |
| D-3 | Engine unchanged between verified commit and current dev | empty diff | PASS |
| D-4 | `persist_run` writes `qty` | `qty` in INSERT column list | PASS |
| L-1 | Deployed process actually sizes positions (in-process run) | `sizing_basis=portfolio`, every trade qty>0 | PASS, 47 of 47 |
| L-2 | In-process run reproduces the stored run | all 11 headline metrics identical | PASS |
| R-1 | Every stored trade reconciles to `qty×(exit−entry)−brokerage` | within stored-price precision | PASS, 42/47 <1 paisa, rest explained |
| R-2 | Trade-level sum reconciles to reported `ending_capital` | exact | PASS, to the paisa |
| R-3 | No position ever exceeds its slot | max position ≤ peak slot | PASS |
| R-4 | `total_quantity` equals `sum(qty)` | equal | PASS |
| R-5 | Max drawdown follows from the stored equity curve | matches to 2 dp | PASS |
| S-1 | A no-data run cannot claim `sizing_basis` | key absent | PASS, fails closed |
| S-2 | No second, unsized engine reachable by users | none | PASS |
| S-3 | Brokerage not scaled per share | flat per side | PASS |
| N-1 | `pnl_abs` has numeric headroom | large margin | PASS, 674,435× |
| N-2 | `avg_loss_pct` hazard reachable in real data? | measure it | NOT REALISED here (0 rows), hazard remains |
| T-1 | Sizing suite passes against merged code | all pass | PASS, 12 |
| T-2 | Pre-existing engine suites still pass (regression) | all pass | PASS, 26 |
| T-3 | AI Trader suites pass (second consumer) | all pass | PASS, 454 |
| T-4 | Collateral sweep, 25 further suites | all pass | PASS, 909 + 1 skip |
| A-1 | AI Trader sized run exists and is consistent | located, metrics read | PASS, in Mongo |
| U-1 | Any UI surfaces the new metrics | — | **FAIL — nothing reads them** |
| U-2 | The incoherent percentage pair is displayed | — | **FAIL — it is, at a known line** |
| H-1 | Fresh backtest over real HTTP through the route | — | NOT RUN, no session token |
| H-2 | Concurrency / interleaved runs | — | NOT RUN |

## 1. The deployed engine is the merged engine

```
$ diff dep_backtest.py dev_backtest.py ; echo "exit=$?"
exit=0
a202300946e08103b53b0c8a6988b0d5  dep_backtest.py     (from the running container)
a202300946e08103b53b0c8a6988b0d5  dev_backtest.py     (git show origin/dev:...)
  493 lines each
```

All six files compared — `strategy_engine/backtest.py`, `strategy_engine/backtest_sql.py`,
`routes/strategy_builder.py`, `services/ai_trader/strategy.py`, `services/ai_trader/config.py`,
`routes/ai_trader.py` — returned `diff_exit=0` with matching md5s and line counts.

```
$ sudo docker exec nivesh-staging-app-backend sh -c "grep -c quantity /app/backend/services/strategy_engine/backtest.py"
22
(same count in the origin/dev worktree; it was 0 before the change)
```

The engine is unchanged between the commit verified and current dev:

```
$ git diff --stat 044d48dd origin/dev -- backend/services/strategy_engine/ backend/services/ai_trader/ backend/routes/strategy_builder.py
(empty)
```

`persist_run` writes the quantity — `qty` is in the INSERT column list, bound as `int(t.quantity or 0)`:

```
INSERT INTO strategy_trades
    (run_id, strategy_id, symbol, entry_date, entry_price, score,
     stoploss_price, target_price, qty, exit_date, exit_price, exit_reason,
     pnl_pct, pnl_abs, holding_days, brokerage, slippage_pct)
```

## 2. The deployed process sizes positions — observed, not inferred

The stored run started **17:13:18 IST**, before the current container started (**17:24:46 IST**), so it was produced
by an earlier container instance. To close that gap I called the deployed engine **in-process inside the running
container**, on the same stored spec and window, and persisted nothing:

```
spec universe: {'ref': 'NIFTY500', 'type': 'index'} | rebalance: daily

--- LIVE RUN INSIDE THE DEPLOYED CONTAINER (nothing persisted) ---
  sizing_basis                 portfolio
  max_positions                10
  trade_count                  47
  total_quantity               18975
  skipped_entries              12
  skipped_insufficient_cash    12
  total_return_pct             -4.1
  max_drawdown_pct             -8.14
  ending_capital               958955.71
  win_rate                     27.66
  profit_factor                0.64
  trades with quantity>0      47 of 47
  quantity min/max            3 / 6597
  equity_curve points         78
```

Every figure is identical to the stored run's `metrics`, and every trade carries a quantity. The deployed code sizes
positions and does so deterministically.

## 3. The stored numbers reconcile

```
$ SELECT count(*) total_rows, count(qty) rows_with_qty FROM strategy_trades;
 total_rows | rows_with_qty
        129 |            47
```

Run `b2f50576-9562-4dd7-b24c-c7343ebd2ad3` (DSL Strategy Builder, 2026-06-01..2026-09-18):

```
 reconciled_trades | exact_under_1paisa | max_abs_diff_inr | sum_pnl_abs | implied_ending_capital
                47 |                 42 |           0.0714 |   -41044.29 |              958955.71
```

`1,000,000 + sum(pnl_abs) = 958,955.71`, which is exactly the reported `ending_capital`.

**The five that miss by more than a paisa are stored-price precision, quantified:**

```
   symbol   | qty  |  pnl_abs   |  expected  | diff_inr | diff_per_share
 MMTC       | 1543 | -5767.5331 | -5767.4617 |   0.0714 |       0.000046
 IDFCFIRSTB | 1177 |  -704.5813 |  -704.5342 |   0.0471 |       0.000040
 CASTROLIND |  486 |  -135.8100 |  -135.8392 |   0.0292 |       0.000060
 ACMESOLAR  |  220 |  -135.7550 |  -135.7440 |   0.0110 |       0.000050
 TDPOWERSYS |  137 |  8738.6209 |  8738.6312 |   0.0103 |       0.000075
```

Every `diff_per_share` lies in 0.000040..0.000075, straddling **0.00005 — exactly the half-ulp of the
`NUMERIC(14,4)` prices**. `pnl_abs` was computed from unrounded prices; reconciling from the stored, rounded prices
recovers it to within half a price-tick per share, multiplied by quantity. This is a limit of the stored precision,
not of the engine's arithmetic.

**No position ever exceeded its slot** — the check that matters, since the largest position (₹103,136) is above the
nominal ₹1,00,000 slot:

```
 points | peak_equity | trough_equity          peak_slot=104060.21
     78 |  1040602.07 |     955907.26          max_position=103136.34
```

The slot is computed on *current* equity, equity peaked at ₹10,40,602, so the ceiling at that moment was ₹1,04,060.
`103136.34 <= 104060.21`. Drawdown recomputed from the curve: `(955907.26 − 1040602.07)/1040602.07 = −8.139%`,
matching the reported `−8.14`. Position values cluster tightly on the slot: min ₹81,851, max ₹103,136, mean ₹98,149,
stddev ₹3,626 (the floor-to-whole-shares effect, largest on the dearest shares — ABBOTINDIA at ₹27,283 fits 3).

**The old engine is still visible in the same table, which is the clearest statement of what changed:**

```
         era          | trades | avg_abs_pnl_inr | max_abs_pnl_inr
 new sized engine     |     47 |         3996.77 |        14827.23
 old per-share engine |     82 |          107.73 |          479.60
```

Those 82 rows are what the Strategy Builder had been reporting to users.

## 4. Before and after on the same strategy and window

Read verbatim from Mongo (`nivesh_staging.ai_trader_strategies`, strategy
`d526fd03-af68-415b-85be-f116bdb37d04`; AI Trader runs are `$push`ed onto the strategy document, which is why they
are not in Postgres `strategy_trades`):

| | old per-share | new sized |
|---|---|---|
| `trade_count` | 30 | 27 (+18 entries skipped for cash) |
| `total_return_pct` | −0.36 | **−2.8** |
| `max_drawdown_pct` | −0.36 | **−5.6** |
| `profit_factor` | 0.08 | 0.62 |
| `win_rate` | 30.0 | 33.33 |
| `ending_capital` | 996,370.03 | 972,048.85 |
| `sizing_basis` | *absent* | `portfolio` |
| `avg_win_abs` / `avg_loss_abs` | *absent* | 5025.46 / −4065.57 |

The strategy sits at stage `backtested`; the sized run does not promote it, which is correct — it still fails
`trade_count >= 100`, `profit_factor >= 1.3`, positive return, and `universe_basis`.

## 5. Safeguards that could have been hollow, and are not

**A no-data run cannot claim `sizing_basis`.** `sizing_basis` is a hardcoded literal in `_compute_metrics`
(line 403), so it attests "this is the sized code path", not "a position was sized". But the no-data path returns at
**line 136** with `metrics={"reason": "no_data"}` and never reaches `_compute_metrics` at **line 281**, so the key is
absent and the promotion gate fails closed. A bars-but-zero-trades run would carry the key with `trade_count: 0`,
which the trade-count gate rejects independently. Adequate, but it is a label beside a counter, not a measurement.

**There is no second, unsized engine.** `backtest_sql.py` is 19 lines of SQL constants (`EXIT_BARS_SQL`), not an
engine. The only `run_backtest` callers are `routes/strategy_builder.py:628` and, via
`strategy.run_backtest_for(runner=run_backtest)`, `routes/ai_trader.py:479`. (`routes/positional.py` has its own
independent `_size_position` for the positional desk — a different feature, not this engine.)

**Brokerage is not scaled per share**, so the `NUMERIC(10,4)` overflow I worried about cannot occur:

```
 min_brok | max_brok | distinct_vals
  40.0000 |  40.0000 |             1
```

**`pnl_abs` headroom** against the `NUMERIC(14,4)` ceiling: max observed |pnl_abs| ₹14,827 → factor **674,435**.

## 6. Tests against the merged code

Run in throwaway `nivesh/backend:staging` containers, `--network none`, with the `origin/dev` worktree mounted
read-only. Verbatim final lines:

```
tests/test_strategy_backtest_sizing.py                        ->  12 passed in 0.17s
tests/test_strategy_engine.py + test_strategy_backtest_adjusted.py ->  26 passed in 0.14s
4 AI Trader suites (needs MONGO_URL set)                      -> 454 passed, 1 warning in 49.55s
25 further strategy/desk/screen/chartink suites               -> 909 passed, 1 skipped in 33.74s
```

1,401 tests pass. The 26 in group two are the suites that covered the old per-share engine, so they are the direct
regression signal. The single skip is a deliberate live-endpoint gate
(`test_screener_contract.py:321`, "endpoint does not exist yet — plan step 13"), unrelated to sizing.

The 12 sizing tests cover the substantive branches by name: equal-weight slot per entry; `total_return_pct` as the
real account move; an entry cash cannot afford skipped and counted; a candidate too dear for one share skipped and
counted; mark-to-market drawdown seeing a dip a closed-trade series cannot; a day with no bar carrying the last mark;
a gross gain swallowed by costs counting as a loss for both metrics; the rupee averages agreeing with win rate and
profit factor; brokerage flat per side not per share; the slot compounding off current equity not starting capital;
slippage not applied twice; a no-data window still reporting its reason.

## 7. Findings that need a decision

**U-1 — nothing in any UI reads the new metrics.** Zero files in `frontend-v5/src` or `frontend/src` reference
`sizing_basis`, `total_quantity`, `skipped_entries`, `skipped_insufficient_cash`, `skipped_min_quantity`,
`stale_mark_closes`, `avg_win_abs` or `avg_loss_abs`. So a run that skipped **12 of 59 attempted entries for want of
cash** shows a user 47 trades with no explanation of the missing 12. `BacktestMetrics` in
`frontend-v5/src/services/strategyBuilder.ts:53` has an index signature `[k: string]: unknown`, so the keys pass
through untyped rather than failing typecheck — nothing breaks, nothing surfaces.

**U-2 — the one pair the engine says not to headline is the pair being displayed.**
`frontend/src/components/strategyBuilder/StepBacktest.jsx:156-157`:

```jsx
<MetricCard label="Avg win"  value={fmtPct(metrics.avg_win_pct)}  tone="text-emerald-600" />
<MetricCard label="Avg loss" value={fmtPct(metrics.avg_loss_pct)} tone="text-rose-600" />
```

The engine's own docstring says of that pair: *"Do not headline that pair"* — they are a gross per-share percentage
averaged over buckets defined by net rupees, so `avg_loss_pct` can come back positive. The coherent pair
`avg_win_abs` / `avg_loss_abs` now exists and is not rendered anywhere.

**N-2 — but that hazard did not fire in this data.** Measured, rather than assumed:

```
$ SELECT count(*) FROM strategy_trades WHERE run_id='b2f5...' AND sign(pnl_pct) <> sign(pnl_abs);
 0
```

`avg_loss_pct` reads −3.36, correctly negative. The hazard needs a positive gross below the ₹40 flat brokerage; the
closest rows are already losses (brokerage/|gross| up to 0.49 on negative gross). So it is latent, not active — a
reason to fix the display deliberately rather than urgently.

**`max_positions` has no home.** Slot size decides position size, and position size is what makes the return and
drawdown gates bind, yet `max_positions` is not a `NiveshConfig` field and the Bot details design has no control for
it. `routes/strategy_builder.py:74` exposes it per request (default 10) and `frontend-v5/.../strategyBuilder.ts:211`
sends it; `routes/ai_trader.py:479` never passes it, so **every AI Trader backtest silently uses 10**. Recorded as
section 8b.7 and open question 6 of `docs/STRATEGY_BUILDER_CONFIG_SPEC.md`. Not decided.

**Skipped entries are a systematic bias, not noise.** The slot is sized on total equity but paid from cash, so a
nearly fully invested book cannot fund a slot that exists on paper: 12 of 59 here, 18 of 45 on the AI Trader run.
Correct for a cash account and visible in `metrics`, but it means a strategy under-deploys as marks rise. The
alternative, scaling the entry down to affordable size, is the `size_down_to_cash` option I declined to invent.

**Pre-existing documentation gap (not a regression).** `docs/API_DOCUMENTATION.md` and `docs/DATABASE_SCHEMA.md`
contain no mention of `strategy_trades`, of the backtest endpoint, or of any metrics key — old or new. There was no
stale text to correct because the subsystem was never documented. Flagged, deliberately not fixed here to avoid
unrequested scope.

**Operational, unrelated to this change.** The container started 17:24:46 IST; the deploy checkout
`/opt/nivesh-staging/repo` (a bind mount) advanced to `36bb791c` at 17:42:20. Python imported at startup, so the
running process still serves the pre-`36bb791c` versions of `backend/routes/events_calendar.py` and
`backend/nidp/services/daas_api/routers/desk_expectation.py`. **PR #270's changes are not live until a restart.**
This engine is unaffected — `backtest.py` is identical across both commits.

## Corrections to my own earlier claims

Stated plainly, because three of them were wrong:

1. **My "~70×" rescale estimate was wrong. The real factor is about 7.8×** (−0.36% → −2.80% on the same strategy and
   window). I had reasoned from slot value over share price without accounting for compounding, the cash skips, or
   the fact that most trades were in cheaper shares. Direction right, magnitude wrong — which is why I measured it
   instead of filing the estimate.
2. **The `NUMERIC(10,4)` brokerage overflow risk I raised does not exist.** Brokerage is flat ₹40 per side, never
   multiplied by quantity.
3. **`avg_loss_pct` reading positive is latent, not observed.** My override file implied it was already happening;
   there are zero sign disagreements in the stored data.
4. Separately, in conversation I said `docs/STRATEGY_BUILDER_CONFIG_SPEC.md` was uncommitted and at risk. It is
   committed on `dev`, byte-identical; my local checkout was simply on an older branch.

## Not verified, and why

- **No fresh backtest over real HTTP through the Strategy Builder route.** That needs a staging session token, which I
  do not have. Mitigated, not replaced, by the in-process run inside the deployed container (section 2), which
  exercises the same engine the route calls but not the route's auth, validation or persistence path.
- **`persist_run`'s INSERT was never executed under observation.** The `qty` column is read back from 47 rows an
  earlier run wrote, and the merged INSERT is quoted, but I did not watch a write happen; the in-process run
  deliberately persisted nothing.
- **No concurrency test.** Interleaved runs against the same strategy were not exercised.
- **No large-capital, short-side, or corporate-action-spanning run**, and no multi-symbol same-day slot contention
  test beyond what the unit suite covers.
- **I did not read the bodies of the 12 sizing tests**, only their names, so I cannot say which of the new metric
  keys are asserted versus merely emitted. The staging evidence covers the values themselves.
- **No frontend or Playwright run.** No frontend file changed in this work; the UI findings above are static reads.
- **8 of 10 planned verification agents died on the session usage limit** (resets 18:40 IST), including the
  completeness critic. I ran their checks myself by hand instead; the probes that completed were deploy-integrity and
  the test re-run. No check was dropped, but this report had no independent adversarial reviewer — the refutation
  attempts in section 5 are my own, which is weaker.

## Verdict: PASS
