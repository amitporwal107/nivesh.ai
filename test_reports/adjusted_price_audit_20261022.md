# Functionality Verification Report — raw vs corporate-action-adjusted price audit

- **Branch:** feat/provider-foundations
- **Date:** 2026-10-22
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER, with DOMAIN_EXPERT_ANALYST judgement on each contract)
- **Environment:** staging (nidp_staging on 45.64.105.224; `nidp-daas-api-staging` container)
- **Changed areas:** backend routes/services: **yes** (6 files) · frontend src: no
- **Test cases:** `test_reports/adjusted_price_audit_TESTCASES.md` (authored before implementation)

## Summary

Nine flagged call sites across six files read **raw** `nidp.prices_eod` where the figure being
computed spans sessions. Seven expressions were changed to `nidp.prices_eod_adjusted` across those
six files; three legs inside the same queries were deliberately left raw, because they are the
traded quote and the delivery ratio.
The trading calendar stays on `prices_eod` throughout, per commit `000336e5`.

The decisive finding, which widened the blast radius beyond what the audit assumed:
**`nidp.prices_eod.prev_close` is itself raw on an ex-date.** It reads `2132.60` against an open of
`426.00` on KOTAKBANK's 5:1 split ex 2026-01-14. So it is not only multi-session returns that
break — a *single-session* return, gap and range off this feed are wrong too, and so is any
20-session average **volume** (a split multiplies the share count).

## Per-site verdict

| # | Site | Contract | Changed | Why |
|---|------|----------|---------|-----|
| 1 | `intelligence/confirmation.py` 20-session close high + range (now ~104-168) | **ADJUSTED** | yes | `vs_20d_high_pct` and `range_expansion` span the window |
| 1b | same query: 20-session average **volume** | **ADJUSTED** (`adj_volume`) | yes | not in the original 9. A split multiplies the share count, so the raw ratio reports a false spike that *scores points* |
| 1c | same query: `gap_up_pct` (open vs prev close) | **ADJUSTED** (`lag(adj_close)`) | yes | the feed's `prev_close` is raw on the ex-date |
| 1d | same query: `deliv_qty` / `deliv_pct` | **RAW** | **no** | delivery exists only in `prices_eod`, and `deliv_pct` is a ratio of two raw quantities — scale-invariant |
| 1e | same query: `result["close_price"]` | **RAW** | **no** | published as the traded quote; must be what printed |
| 2 | `intelligence/confirmation.py` ~247 `prev_close` for the OI direction test | **ADJUSTED** | yes | **re-judged on a second pass.** My first verdict was "raw, no change — it is only an up/down sign". That was wrong: `close > prev_close` is a cross-session comparison, so on an ex-date it is always a fall. The sign now comes off the adjusted bar already fetched in block 1, which also removes a second round trip |
| 3 | `intelligence/service.py` `_get_price_context` 52w high/low | **ADJUSTED, restated** | yes | feeds `breakout.py` ~198 `(high_52w - current_price)/high_52w` |
| 3b | same: `current_price` | **RAW** | **no** | printed to a human in the Telegram alert. The adjusted extremes are divided by the latest session's `cumulative_adj_factor` so the pair is on one share scale |
| 4 | `event_analyzer/analyzer.py` ~57 `_get_price_context` | **ADJUSTED, restated** | yes | the 52-week range goes into an LLM prompt |
| 5 | `d1_prep/service.py` ~68 (verbatim copy of #4) | **ADJUSTED, restated** | yes | identical fix |
| 6 | `intelligence_layer/service.py` ~218 correlations → `graph.correlations` | **ADJUSTED** | yes | 90-day Pearson on `ret1d`; also drops a dead `source` filter and a missing-`series` defect |
| 7 | `intelligence_layer/service.py` ~33 security master (`isin`) | **RAW** | **no** | ISIN is a feed fact, not a price |
| 8 | `intelligence_layer/service.py` ~263 DQ quality score | **RAW** | **no** | it is *measuring the raw dataset*; adjusting it would make the score describe a different table |
| 9 | `movers.py` `_bars_for` (now ~1239) | **ADJUSTED** | yes | root cause for `_atr_pct`, `_leak`, `_exec_of`, `_head_hit`, `_event_metrics` |
| 9b | same: `volume` / `turnover` | **RAW** | **no** | the adjusted table has no `turnover`; turnover is a rupee figure a split does not change. The `series='EQ'` pin also comes from this join |
| 10 | `movers.py` 1724 `max(as_of_date)`, 812 `DISTINCT symbol` | **RAW** | **no** | calendar and universe, not prices — the `000336e5` rule |
| 11 | `movers.py` 1780 candidate close/prev_close/turnover | **RAW** | **no** | one session's quote and a liquidity floor, displayed as disclosed |
| 12 | `movers.py` 284 `_sessions`, 1154 movers list | already adjusted | n/a | the pattern this fix mirrors |

Also corrected: the **two stale in-repo comments** (`movers.py` ~267 and ~438) claiming
`nidp.corporate_actions` "holds only 8 SPLIT + 9 BONUS rows" and that TAALTECH/PGIL/TCC "stay
unadjusted". Both are now false; replaced with values measured this session.

## Before/after on a real corporate action

KOTAKBANK, 5:1 split ex **2026-01-14**. All output below is unedited.

### The root fact: the feed's own `prev_close` is raw on the ex-date

```
  symbol   | as_of_date | prev_close | open_price | high_price | low_price | close_price | series
-----------+------------+------------+------------+------------+-----------+-------------+--------
 KOTAKBANK | 2026-01-13 |  2133.3000 |  2126.9000 |  2144.4000 | 2120.0000 |   2132.6000 | EQ
 KOTAKBANK | 2026-01-14 |  2132.6000 |   426.0000 |   427.6000 |  418.8000 |    421.0000 | EQ
```
```
  k  | as_of_date | prev_close | open_price | close_price | gap_pct | ret_1d_pct
-----+------------+------------+------------+-------------+---------+------------
 RAW | 2026-01-14 |  2132.6000 |   426.0000 |    421.0000 |  -80.02 |     -80.26

    k     | as_of_date |  prev_adj  |  adj_open  | adj_close  | gap_pct | ret_1d_pct
----------+------------+------------+------------+------------+---------+------------
 ADJUSTED | 2026-01-14 | 426.520000 | 426.000000 | 421.000000 |   -0.12 |      -1.29
```

### Site 1 — `confirmation.py`, the 20-session window on 2026-01-20

`confirmation.py`'s own window frame, replicated against each table:

```
 series | as_of_date |  close   | high20_close | vs_20d_high_pct | avg_vol20 | vol_spike | avg_range20 | range_exp | gap_pct
--------+------------+----------+--------------+-----------------+-----------+-----------+-------------+-----------+---------
 RAW    | 2026-01-20 | 423.8000 |      2217.80 |          -80.89 |   4406391 |      4.27 |       28.69 |      0.30 |    0.26

  series  | as_of_date |   close    | high20_close | vs_20d_high_pct | avg_vol20 | vol_spike | avg_range20 | range_exp | gap_pct
----------+------------+------------+--------------+-----------------+-----------+-----------+-------------+-----------+---------
 ADJUSTED | 2026-01-20 | 423.800000 |       443.56 |           -4.45 |  12310011 |      1.53 |        7.06 |      1.20 |    0.26
```

Three wrong numbers on one symbol-day, and the volume one is a **false positive, not just a bad
display**: 4.27x clears `_VOL_SPIKE_STRONG = 3.0`, so the raw path scores **+25** and prints
`Volume spike 4.3x 20D avg`. The true 1.53x is below `_VOL_SPIKE_MODERATE` and scores 0.

### Sites 3/4/5 — the 52-week range, as the three readers compute it (close-based)

```
   symbol   | raw_last  | raw_high52 | raw_pct_below | adj_high52 | adj_pct_below | raw_low52 | adj_low52 | factor_latest
------------+-----------+------------+---------------+------------+---------------+-----------+-----------+---------------
 ANANDRATHI | 2200.0000 |  3689.8000 |          40.4 |    2229.50 |           1.3 | 1730.7000 |   1419.75 |    1.00000000
 ANGELONE   |  293.2000 |  2847.4000 |          89.7 |     354.80 |          17.4 |  213.0700 |    213.07 |    1.00000000
 HDFCAMC    | 2311.4000 |  5646.5000 |          59.1 |    2863.60 |          19.3 | 2216.4000 |   2216.40 |    1.00000000
 KOTAKBANK  |  437.8000 |  2225.6000 |          80.3 |     447.95 |           2.3 |  353.4000 |    353.40 |    1.00000000
 MCX        | 3087.0000 | 11136.0000 |          72.3 |    3441.70 |          10.3 | 2191.0000 |   1800.70 |    1.00000000
 TRENT      | 2822.0000 |  4798.7000 |          41.2 |    3343.80 |          15.6 | 2580.0000 |   2197.20 |    1.00000000
```

`breakout.py` ~198 awards `near_52w_high` within 5%. KOTAKBANK is **2.3%** below its real
52-week high, so that bonus *should* fire; on the raw path it reads 80.3% and can never fire.
Covered by `test_near_52w_high_bonus_is_reachable_only_on_the_adjusted_extreme`.

### Site 2 — the OI direction test, on a name that ROSE through its split

AGIIL, 5:1 split ex **2025-10-10**. The raw feed calls this session a 77% crash; it was a 16% rise.

```
 symbol | as_of_date | raw_prev  | raw_close | raw_pct |  adj_prev  | adj_close  | adj_pct | action_type | ratio
--------+------------+-----------+-----------+---------+------------+------------+---------+-------------+-------
 FCL    | 2025-10-31 |  248.6000 |   29.8300 |  -88.00 |  24.860000 |  29.830000 |   19.99 | BONUS       | 4:1
 SIGMA  | 2025-10-06 |  536.0500 |   62.2000 |  -88.40 |  53.605000 |  62.200000 |   16.03 | SPLIT       | 10:1
 AGIIL  | 2025-10-10 | 1245.1000 |  287.9000 |  -76.88 | 249.020000 | 287.900000 |   15.61 | SPLIT       | 5:1
 TEMBO  | 2026-08-05 |  574.1500 |   65.9000 |  -88.52 |  57.415000 |  65.900000 |   14.78 | SPLIT       | 10:1
 CUPID  | 2026-03-09 |  402.2000 |   91.6000 |  -77.23 |  80.440000 |  91.600000 |   13.87 | BONUS       | 4:1
```

With futures OI up 10%, the raw path labels AGIIL `SHORT_BUILDUP` ("OI +10% with price down") and
the adjusted path `LONG_BUILDUP` ("OI +10% with price up") — opposite readings of the same session.
Covered by `test_oi_direction_is_decided_on_the_adjusted_bar`, which uses the real AGIIL row.

### Site 6 — `graph.correlations`

The input series, raw vs adjusted:

```
 as_of_date | raw_ret1d_pct | adj_ret1d_pct
------------+---------------+---------------
 2026-01-13 |         -0.03 |         -0.03
 2026-01-14 |        -80.26 |         -1.29
 2026-01-16 |         -0.67 |         -0.67
```

And its effect on the written rows, over the exact pair set whose value can change (a symbol
carrying a non-unit factor inside the 120-day window ending 2026-02-28, against the rest of the
`index_constituents` universe; same 60-observation floor and 0.7 cut-off as the writer):

```
 symbols_with_event | pairs_compared | raw_pairs_written | adj_pairs_written | verdict_flips | sign_flips | max_abs_delta
--------------------+----------------+-------------------+-------------------+---------------+------------+---------------
                 85 |          21163 |                 0 |                 2 |             2 |       3077 |        0.8105
Time: 17542.010 ms (00:17.542)
```

**3,077 of 21,163 pairs change the sign of their correlation**, the largest single move is 0.8105,
and the raw series writes 0 rows at the threshold where the adjusted series writes 2 — real
correlations were being lost, not just mis-valued.

### Site 9 — `movers.py` `_bars_for`: ATR, leak and the flags

Run inside the container against the real bars, through the module's own functions:

```
len 15   i=14 -> 2026-01-21   i=9 -> 2026-01-13
atr14   raw 0.07589535  adj 0.01996765  ratio 3.801
leak@14 raw True  adj False
gap@9   raw -0.80024383  adj -0.00121917
re@9    raw -0.80265317  adj -0.01326583
flip@9  raw False  adj False
flags@9  raw ['gap2', 'gap3', 'leak'] adj ['leak']
flags@14 raw ['leak'] adj []
```

ATR-14 is overstated **3.80x**, which is what pushes a name into a volatility decile it does not
belong in — and the volatility deciles are the control the flag-lift card exists to apply.
`_leak` fires on the raw bars and not the adjusted ones, and the raw bars raise two phantom gap
flags (`gap2`, `gap3`) on the session before the ex-date.

## Data correctness (staging)

Switching table must not lose coverage or fan out:

```
 pe_d0    |   pe_d1    | pe_symbols
------------+------------+------------
 2025-10-01 | 2026-10-21 |       3069

 eq_symbols_52w | adj_symbols_52w | eq_missing_from_adj
----------------+-----------------+---------------------
           2987 |            2987 |                   0

 eq_sessions | adj_sessions | sessions_missing
-------------+--------------+------------------
         245 |          245 |                0

 adj_rows | adj_symbols |     d0     |     d1
----------+-------------+------------+------------
   631900 |        2992 | 2025-10-01 | 2026-10-21

 dup_symbol_date
-----------------
               0
```
```
 source        | count
---------------------+--------
 NIDP_PRICE_ADJUSTER | 631900

 non_unit_latest | rows_latest
-----------------+-------------
               2 |        2694

 dup_symbol_date_raw
---------------------
                 887
```

- 0 EQ symbols and 0 sessions lost over the trailing 52 weeks (TC-3).
- 0 duplicate `(symbol, as_of_date)` in 631,900 adjusted rows, so dropping `series` cannot fan
  out (TC-2); the raw table has **887** such duplicates, which the correlation query — which never
  filtered `series` — was interleaving into `lag()` (TC-17).
- The adjusted table's only `source` is `NIDP_PRICE_ADJUSTER`, so the old `'NSE_BHAVCOPY'`
  predicate had to go with the table or it would match nothing (TC-18).
- 2 of 2,694 symbols carry a non-unit factor on the newest session, which is why the 52-week
  extremes are restated by that factor rather than published as-is.

`nidp.corporate_actions` is **not** "nearly empty" — the two in-repo comments were stale (TC-4):

```
   action_type    | rows | symbols |  first_ex  |  last_ex
------------------+------+---------+------------+------------
 DIVIDEND         | 1856 |    1414 | 2025-10-03 | 2026-10-23
 DISTRIBUTION     |   83 |      25 | 2025-11-04 | 2026-08-19
 SPLIT            |   71 |      71 | 2025-10-03 | 2026-10-23
 BONUS            |   62 |      62 | 2025-10-03 | 2026-10-15
 RIGHTS           |   59 |      57 | 2025-10-10 | 2026-10-15
 INTEREST_PAYMENT |   54 |      43 | 2025-10-09 | 2026-10-09
 BUYBACK          |   36 |      36 | 2025-11-14 | 2026-10-22
 DEMERGER         |   18 |      18 | 2025-10-14 | 2026-10-08
 OTHER            |    1 |       1 | 2026-04-28 | 2026-04-28
```

### The adjusted table is better, NOT clean

Measured this session (TC-26), symbols falling >=35% in one session on the **adjusted** series
while carrying `cumulative_adj_factor = 1.0`:

```
 symbols_ge35pct_unit_factor | no_ca_row | has_ca_row
-----------------------------+-----------+------------
                          38 |        25 |         13
```

My own count is **38 / 25 / 13**, not the 19 / 14 / 5 the task brief cited — the brief's figure
does not reproduce against the table as it stands today (631,900 rows vs the 537,878 it describes),
so the code comments carry my measured numbers, not the brief's. Named examples: TATAMOTORS,
POLICYBZR, SADBHAV (no corporate-action row at all) and VEDL, TRIVENI, SKFINDIA (a row the
adjuster did not apply). TAALTECH, PGIL and TCC — which the old comments said stay unadjusted —
**are now adjusted** (factors 0.20, 0.50, 0.20; worst adjusted single-session moves -7.64%,
-10.14%, -7.85%), which is why those comments were rewritten rather than merely re-dated.

## API / Endpoint tests (staging)

### Every rewritten statement runs against the live schema

The SQL was extracted programmatically from the patched source (`ast`, largest SQL literal per
function) with literal parameters substituted, so what ran **is** what ships — no retyping.

```
=== confirmation_20d  (intelligence/confirmation.py :: get_confirmation) ===
 as_of_date |  adj_open  |  adj_high  |  adj_low   | adj_close  | adj_volume |      avg_vol_20d      | close_high_20d | intraday_high_20d |   avg_range_20d    |  prev_adj  | deliv_qty | deliv_pct |   avg_del_pct_20d   | raw_close
------------+------------+------------+------------+------------+------------+-----------------------+----------------+-------------------+--------------------+------------+-----------+-----------+---------------------+-----------
 2026-01-20 | 428.000000 | 431.000000 | 422.500000 | 423.800000 |   18805991 | 12310010.571428571429 |     443.560000 |        445.600000 | 7.0600000000000000 | 426.900000 |  14016152 |   74.5300 | 69.1185714285714286 |  423.8000
(1 row)

=== intel_52w  (intelligence/service.py :: _get_price_context) ===
 close_price |  high_52w  |  low_52w   | adj_factor
-------------+------------+------------+------------
    437.8000 | 447.950000 | 353.400000 | 1.00000000
(1 row)

=== event_analyzer_52w  (event_analyzer/analyzer.py :: _get_price_context) ===
 close_price |  high_52w  |  low_52w   | sector | adj_factor
-------------+------------+------------+--------+------------
    293.2000 | 354.800000 | 213.070000 |        | 1.00000000
(1 row)

=== d1_prep_52w  (d1_prep/service.py :: _get_price_context) ===
 close_price |  high_52w  |  low_52w   | sector | adj_factor
-------------+------------+------------+--------+------------
    293.2000 | 354.800000 | 213.070000 |        | 1.00000000
(1 row)

=== bars_for  (daas_api/routers/movers.py :: _bars_for) ===
  symbol   | as_of_date |  adj_open  |  adj_high  |  adj_low   | adj_close  |  prev_adj  | cumulative_adj_factor |  volume  |     turnover
-----------+------------+------------+------------+------------+------------+------------+-----------------------+----------+------------------
 KOTAKBANK | 2026-01-13 | 425.380000 | 428.880000 | 424.000000 | 426.520000 | 426.660000 |            0.20000000 |  2543530 |  5420862060.0000
 KOTAKBANK | 2026-01-14 | 426.000000 | 427.600000 | 418.800000 | 421.000000 | 426.520000 |            1.00000000 | 10818517 |  4587503004.6000
 KOTAKBANK | 2026-01-16 | 424.000000 | 427.600000 | 417.100000 | 418.200000 | 421.000000 |            1.00000000 | 17993251 |  7581632499.6000
(18 rows, abridged here; full output in the transcript — the series is continuous across the ex-date)
```

The two prompt-context queries were run with the `nidp.symbol_master` join stubbed to a one-row
NULL-sector relation — see **Inputs / blockers** below. Everything else is verbatim.

The `graph.correlations` statement is an INSERT, so it was validated with `EXPLAIN` (plans, does
not execute):

```
=== EXPLAIN (plans, does NOT execute the INSERT) ===
                                                QUERY PLAN
----------------------------------------------------------------------------------------------------------
 Insert on correlations  (cost=3967667.52..3969261.53 rows=0 width=0)
   Conflict Resolution: UPDATE
   Conflict Arbiter Indexes: ux_graph_correlations_key
   CTE latest
     ->  Result  (cost=0.29..0.30 rows=1 width=4)
           InitPlan 1 (returns $0)
             ->  Limit  (cost=0.29..0.29 rows=1 width=4)
                   ->  Custom Scan (ChunkAppend) on prices_eod  (cost=0.29..866.58 rows=44285 width=4)
```

Column references and the conflict arbiter all resolve against the live schema. No write was made.

### pytest

**Baseline, deployed code** (`/app/backend`, unmodified):
```
51 failed, 1292 passed, 5 skipped, 23 warnings in 11.14s
```
(The brief quoted `51 failed, 1281 passed`; the deployed tree has since gained 11 passing tests.
Same 51 failures. The measured baseline is used as the comparison.)

**My 6 changed files overlaid onto a copy of that tree** (`/tmp/adjaudit`, deployed tree untouched;
md5 confirms the test tree is my code and differs from the deployed one, and matches my working
tree byte for byte):
```
38b2b39294d1371d5aebd7c228984de4  nidp/services/daas_api/routers/movers.py            (test tree)
2fa81ff1b6791c02dd2e45f7ef435493  /app/backend/nidp/services/daas_api/routers/movers.py (deployed)
38b2b39294d1371d5aebd7c228984de4  backend/nidp/services/daas_api/routers/movers.py     (my working tree)

51 failed, 1292 passed, 5 skipped, 23 warnings in 11.23s
```

**With the new test file added:**
```
16 passed in 0.34s                                         (the new file alone)
51 failed, 1308 passed, 5 skipped, 23 warnings in 11.11s   (full suite)
```

The failure **set** is byte-identical to the baseline, and none of the 51 touches my modules:
```
   51 fail_base.txt
   51 fail_mine.txt
=== diff baseline vs mine (empty = identical failure set) ===
IDENTICAL
=== do any failures touch my 6 files' modules? ===
none
```
```
87bbad72e4cae0a9e5e1c3fdc03fa9b4  -     (failure list, my tree)
=== baseline failure-list md5 ===
87bbad72e4cae0a9e5e1c3fdc03fa9b4  -     (failure list, deployed tree)
```

1292 → 1308 passed is exactly the 16 added cases. The scratch tree was removed from the container
afterwards (`cleaned`).

## Test case results

| ID | Result | Evidence |
|----|--------|----------|
| TC-1 | PASS | `prev_close` 2132.60 vs open 426.00; raw 1-day return -80.26% |
| TC-2 | PASS | `dup_symbol_date = 0` over 631,900 rows |
| TC-3 | PASS | 2987 = 2987 symbols, 245 = 245 sessions, 0 missing |
| TC-4 | PASS | 71 SPLIT / 62 BONUS / 1,856 DIVIDEND from 2025-10-03 |
| TC-5 | PASS | `vs_20d_high_pct` -80.89% raw → -4.45% adjusted |
| TC-6 | PASS | `vol_spike` 4.27x raw → 1.53x adjusted; `test_confirmation_scores_the_adjusted_window_not_the_raw_one` asserts no volume signal fires |
| TC-7 | PASS | `range_exp` 0.30x raw → 1.20x adjusted |
| TC-8 | PASS | ex-date gap -80.02% raw → -0.12% adjusted |
| TC-9 | PASS | `test_confirmation_asks_for_delivery_from_the_raw_feed`; `deliv_pct` 74.53 unchanged |
| TC-10 | PASS | `out["close_price"] == 423.80` (raw leg) |
| TC-11 | PASS | 80.3% → 2.3%; `test_near_52w_high_bonus_is_reachable_only_on_the_adjusted_extreme` |
| TC-12 | PASS | `test_52w_range_is_adjusted_and_current_price_is_raw` (3 params) |
| TC-13 | PASS | ANGELONE 89.7% → 17.4% |
| TC-14 | PASS | same parametrised test covers `d1_prep` |
| TC-15 | PASS | raw `ret1d` -80.26% vs adjusted -1.29% on 2026-01-14 |
| TC-16 | PASS | 3,077 sign flips, max delta 0.8105 |
| TC-17 | PASS | 887 duplicate raw symbol-dates vs 0 adjusted |
| TC-18 | PASS | only source is `NIDP_PRICE_ADJUSTER`; `test_correlations_read_adjusted_closes_and_drop_the_raw_source_filter` |
| TC-19 | PASS | ATR-14 7.5895% raw vs 1.9968% adjusted, ratio 3.801 |
| TC-20 | PASS | `_leak` True raw / False adjusted; `flags@14 raw ['leak'] adj []` |
| TC-21 | PASS | `test_bars_for_reads_the_adjusted_series_and_keeps_turnover_raw` |
| TC-22 | PASS | same test asserts `p.turnover` and `p.series = 'EQ'` |
| TC-23 | PASS | `git status` shows only the 6 owned files changed; triage table above |
| TC-24 | PASS | 51 failed / 1308 passed vs baseline 51 / 1292; failure-list md5 identical |
| TC-27 | PASS | AGIIL 2025-10-10: raw -76.88% vs adjusted +15.61%; `test_oi_direction_is_decided_on_the_adjusted_bar` asserts LONG_BUILDUP. **Added during implementation, not authored up front** — noted as such in the test-case file |
| TC-25 | PASS | all five SELECTs ran, the INSERT planned, every file parses |
| TC-26 | PASS | 38 / 25 / 13 under-adjusted symbols reported; no cleanliness claim made |

## Additional affected sites found (reported, NOT fixed — outside the owned files)

| Site | Verdict |
|------|---------|
| `daas_api/routers/desk_events.py` ~276 `BARS_SQL` | **AFFECTED** — `close_price` + `prev_close` over full history, used for "reaction of the stock's own price around past occurrences". Multi-session reaction windows off a raw series |
| `daas_api/routers/move_odds.py` ~230-242 | **AFFECTED** — `prev_close` plus `MAX(high)/MIN(low)` over the next 3 and 5 sessions. Its comment says it reproduces the head's own grader rule, verified on run 1, so changing it changes the published grade — needs a decision, not a patch |
| `daas_api/routers/desk_market.py` ~193 | **MARGINAL** — single-session `close_price`/`prev_close` for index breadth. Correct as a quote, but an ex-date counts as a decline |
| `daas_api/routers/flows.py` ~71/77, `desk_market.py` ~623 | **MARGINAL** — same single-session `prev_close` exposure |
| `technical_indicator_engine/service.py` ~203 | **ALREADY HANDLED** — scales bars itself via `cumulative_factors_for_dates`. Reads `corporate_actions` directly, so it inherits the same 25-symbol gap |
| `daas_api/routers/market_pulse.py` ~741 | **RAW CORRECT**, with a separate latent issue: `total_shares` from a past `period_end` multiplied by today's close mismatches across a split |
| `fundamental_engine/service.py` ~254 | **RAW CORRECT** — market cap needs the actual price and share count on the date |
| `daas_api/routers/paper_trades.py` ~99 | **RAW CORRECT** — pivots from one session's H/L/C |
| `trendlyne_fundamentals/service.py` ~414 | **RAW CORRECT** — reconciled against an external provider's figures |
| `daas_api/routers/features.py` ~316 | **NOT AFFECTED** — `close_price * volume` is scale-invariant across a split |
| `snapshot_builder/stock_builder.py` ~120, `shared/validation/*`, `quality_score.py` | **RAW CORRECT** — day snapshots and DQ measurements of the raw dataset |

## Inputs required from user / blockers

- **none** required from the user.

## UNVERIFIED

1. **`nidp.symbol_master` does not exist on staging.** `to_regclass('nidp.symbol_master')` is NULL
   (only `nidp.sector_master` and `nidp.security_reference_daily` exist). Both
   `event_analyzer/analyzer.py::_get_price_context` and `d1_prep/service.py::_get_price_context`
   join it, as does `intelligence/service.py::_get_market_cap`, so **those functions already raise
   on staging today** — pre-existing, unrelated to this change, and deliberately not fixed here
   (choosing the replacement table is a product decision, and `_get_market_cap` is a different
   defect). *UNVERIFIED: I proved the rewritten 52-week expressions correct with that one join
   stubbed to a NULL-sector relation, but could not run those two functions end-to-end on staging
   because the table they join is absent.*
2. **No end-to-end API exercise of the changed paths.** `intelligence`, `event_analyzer`, `d1_prep`
   and `intelligence_layer` are scheduled jobs, not HTTP routes, and
   `movers.py`'s `/calibration`, `/flag-lift` and the mirror list read `nidp.tpd_runs`, which my
   memory records as empty on CloudPe staging (the scanner cron was never installed).
   *UNVERIFIED: I did not call those endpoints; the fix is proven at the SQL layer against real
   staging data and at the function layer through the module's own code.*
3. **Not deployed.** Changes are in the working tree only, per instruction. The container was
   tested from an isolated copy and that copy was deleted. *UNVERIFIED: behaviour of the running
   staging process, which still has the old code.*
4. **`graph.correlations` was not rewritten.** The existing rows in that table were computed from
   the raw series and are still wrong; the fix corrects future runs only. A backfill is a separate
   decision.
5. The correlation impact (3,077 sign flips) was measured on the pair set that *can* change — the
   85 event-carrying symbols against the universe — for one target date (2026-02-28), not for
   every date the job has ever run.

## Verdict: PASS
