# Test Cases — raw vs corporate-action-adjusted price audit

- **Branch:** feat/provider-foundations
- **Authored:** 2026-10-22, BEFORE implementation
- **Scope:** the 9 flagged `nidp.prices_eod` readers in 6 files under `backend/nidp/services/`
- **Companion report:** `test_reports/adjusted_price_audit_20261022.md`

## Contract being tested

Every call site must declare one of two contracts:

- **RAW** (`nidp.prices_eod`) — what actually printed on the tape. Correct for: last traded
  price shown to a human, a single historical quote, turnover/market-cap arithmetic, and
  anything reconciled against an external raw source.
- **ADJUSTED** (`nidp.prices_eod_adjusted`) — correct for any return, ratio, range, extreme,
  correlation or volatility measured ACROSS sessions.

Two cross-cutting rules the cases below enforce:

1. **No mixed pairings.** An adjusted extreme published beside a raw current price is a new
   bug. Either both legs are adjusted, or the adjusted leg is restated onto the raw leg's
   share scale (divide by the latest session's `cumulative_adj_factor`).
2. **Calendar stays raw.** `nidp.prices_eod` defines which dates are sessions, per commit
   `000336e5`. Only prices move to the adjusted table.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | data | `nidp.prices_eod.prev_close` on a split ex-date is RAW, so even a 1-session return is broken | data | KOTAKBANK 2026-01-14 `close/prev_close-1` returns a large negative number that is not a return | PASS/FAIL |
| TC-2 | data | `prices_eod_adjusted` is unique per `(symbol, as_of_date)` so dropping the `series` filter cannot fan out | data | 0 duplicate pairs | PASS/FAIL |
| TC-3 | data | `prices_eod_adjusted` loses no symbol and no session over the trailing 52 weeks vs `prices_eod` series EQ | data | 0 EQ symbols missing, 0 sessions missing | PASS/FAIL |
| TC-4 | data | `nidp.corporate_actions` is NOT "nearly empty" — the two in-repo comments saying so are stale | data | >= 70 SPLIT and >= 60 BONUS rows, first ex-date in 2025 | PASS/FAIL |
| TC-5 | `intelligence/confirmation.py` | 20-session close high across a 5:1 split: `vs_20d_high_pct` | data | raw reports roughly -80%; adjusted reports a single-digit figure | PASS/FAIL |
| TC-6 | `intelligence/confirmation.py` | 20-session average volume across a 5:1 split: `volume_spike_ratio` | edge | raw reports a false multi-x volume spike that scores points; adjusted reports ~1.5x and scores 0 | PASS/FAIL |
| TC-7 | `intelligence/confirmation.py` | 20-session average range across a split: `range_expansion` | data | raw suppresses the ratio ~4x; adjusted restores it | PASS/FAIL |
| TC-8 | `intelligence/confirmation.py` | `gap_up_pct` on the ex-date itself | edge | raw reports roughly -80%; adjusted reports a fraction of a percent | PASS/FAIL |
| TC-9 | `intelligence/confirmation.py` | `deliv_pct` is a ratio, so it stays on the raw feed and is unchanged | unit | the fixed query still returns `deliv_pct` / `deliv_qty` from `nidp.prices_eod` | PASS/FAIL |
| TC-10 | `intelligence/confirmation.py` | the displayed `close_price` stays the raw traded close | unit | `result["close_price"]` reads a raw column, not `adj_close` | PASS/FAIL |
| TC-11 | `intelligence/service.py` → `breakout.py` | 52-week high vs current price across a split | data | raw says KOTAKBANK is ~80% below its 52w high; adjusted says ~2%, which crosses breakout.py's `near_52w_high <= 5%` bonus that raw silently never fires | PASS/FAIL |
| TC-12 | `intelligence/service.py` | the pairing rule: `current_price` published to Telegram stays raw while the extremes are restated onto the same share scale | unit | `current_price` reads `close_price`; `high_52w`/`low_52w` are `adj` / latest `cumulative_adj_factor` | PASS/FAIL |
| TC-13 | `event_analyzer/analyzer.py` | 52-week range handed to the LLM prompt across a 10:1 split | data | raw tells the model ANGELONE is ~90% below its 52w high; adjusted says ~17% | PASS/FAIL |
| TC-14 | `d1_prep/service.py` | the verbatim-copy query gets the identical fix | unit | both files' `_get_price_context` read `prices_eod_adjusted` for the extremes | PASS/FAIL |
| TC-15 | `intelligence_layer/service.py` | `graph.correlations` input series: a split injects a return that never happened | data | the raw `ret1d` series carries a ~-80% observation; the adjusted series does not | PASS/FAIL |
| TC-16 | `intelligence_layer/service.py` | the corrupted series changes the correlation, including its sign | data | at least one KOTAKBANK/peer pair flips sign between raw and adjusted over a window containing the split | PASS/FAIL |
| TC-17 | `intelligence_layer/service.py` | the raw query had no `series` filter, so it was interleaving duplicate symbol-dates into `lag()`; the adjusted table removes that | data | `prices_eod` has >0 duplicate `(symbol, as_of_date)` pairs; the adjusted table has 0 | PASS/FAIL |
| TC-18 | `intelligence_layer/service.py` | the `source = 'NSE_BHAVCOPY'` filter must not survive the switch | unit | the adjusted table's only source is `NIDP_PRICE_ADJUSTER`, so the old filter would return 0 rows | PASS/FAIL |
| TC-19 | `movers.py` `_bars_for` | `_atr_pct` (14 sessions) across a split | data | raw overstates ATR by >3x; adjusted is the true figure | PASS/FAIL |
| TC-20 | `movers.py` `_bars_for` | `_leak` fires falsely for every session in the 5 days after a split | edge | raw fires `leak` on >=2 sessions where adjusted does not | PASS/FAIL |
| TC-21 | `movers.py` `_bars_for` | the fix mirrors the file's own `_sessions` helper, including the BE/BZ-hole guard (`has_event AND prev_dt >= as_of_date - 7`) | unit | `_bars_for` carries the same guard, so INDIAGLYCO-style series holes cannot print a phantom move | PASS/FAIL |
| TC-22 | `movers.py` `_bars_for` | `volume` and `turnover` keep coming from the raw feed (the adjusted table has no `turnover`) | unit | the query joins `prices_eod` for both, pinned to `series='EQ'` | PASS/FAIL |
| TC-23 | all | no site that legitimately needs raw prices was switched | unit | `fundamental_engine` market cap, `paper_trades` pivots, `trendlyne_fundamentals` reconciliation and the DQ row counts are untouched | PASS/FAIL |
| TC-24 | regression | the `nidp/tests` suite is no worse than the deployed baseline | api | <= 51 failed, >= 1281 passed against baseline `51 failed, 1281 passed, 5 skipped` | PASS/FAIL |
| TC-25 | regression | every changed file still imports and its SQL still parses against the live staging schema | api | each rewritten statement runs on staging and returns rows | PASS/FAIL |
| TC-27 | `intelligence/confirmation.py` | ADDED DURING IMPLEMENTATION (not authored up front): the OI classifier's `price_up` test is a cross-session comparison too — reading `prices_eod.prev_close` makes every ex-date a fall | edge | a name that ROSE through its split is classified LONG_BUILDUP, not SHORT_BUILDUP | PASS/FAIL |
| TC-26 | honesty | the adjuster is NOT claimed to be clean | doc | the report states the known incompleteness (symbols falling >=35% in one session with a unit factor) and does not claim `prices_eod_adjusted` is perfect | PASS/FAIL |

## Out of scope (reported, not fixed)

Readers outside the six owned files are triaged in the report with a raw/adjusted verdict
each. They are not changed here: another session owns `smart_money_study/evaluator.py` and
`smart_money_scores/service.py`, and the rest live in files this task does not own.

## Verdict: BLOCKED
<!-- Authored before implementation. The companion report carries the evidence. -->
