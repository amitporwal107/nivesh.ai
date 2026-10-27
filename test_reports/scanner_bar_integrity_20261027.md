# Functionality Verification Report — AI scanner price history and adjusted prices (N1, N2; gates 5 and 6)

- **Branch:** fix/scanner-bar-integrity (off origin/dev 5b6b3cfd), worktree /home/deploy/nivesh-scanner-integrity
- **Date:** 2026-10-27 (first commit 1f6f7e3e; follow-up for the owner's decisions 97447f67)
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER; bug fix + data-repair tooling)
- **Environment:** unit tests in the staging image (no network); a disposable local Postgres for the write paths;
  staging READ-ONLY for the dry run (branch code loaded in memory in nivesh-staging-app-backend, database sessions
  opened read-only). Nothing was deployed, applied, scheduled or written on staging.
- **Changed areas:** backend routes/services: yes (services/positional_engine; follow-up: routes/positional.py, services/strategy_plan) · frontend src: follow-up yes (desk Scanner tab)
- **Acceptance standard:** docs/NIVESH_AI_LAB_PHASE_SUCCESS_CRITERIA.md §0.1; study items N1, N2; release gates 5, 6.

## Summary

1. **A file is never stamped with a date it does not carry.** `parse_bhavcopy_csv` reads each row's own `DATE1` and
   raises `BhavcopyDateMismatch` unless the file's trade date is the requested one; `ingest()` returns an explicit
   status and writes nothing unless `written`. Root cause confirmed upstream this session: NSE answers a holiday URL with
   the previous session's file (`sec_bhavdata_full_02102026.csv` = DATE1 01-Oct-2026 on all 3,534 rows;
   `..._20102026.csv` = 19-Oct-2026). This resolves the study's UNVERIFIED "why NSE served a file for holiday URLs".
2. **Calendar guard.** `session_calendar` uses the existing NSE CM holiday list (`nidp.nse_holidays` via DaaS
   `/holidays`, the source kite_live_feed and market_research already use). The runner (exit 3/4), `pipeline.run_for_date`
   and `ingest()` refuse a weekend, a holiday, or a date the calendar cannot vouch for (a year with no CM rows is
   "calendar unavailable", never "assume a weekday trades").
3. **Back-fill.** `--backfill-missing [--backfill-days 14]` ingests warehouse sessions (`nidp.prices_eod`) the store
   lacks, each through the DATE1-checked ingester; a rerun finds nothing missing.
4. **Adjusted prices.** Bars are put on one scale with the warehouse's `cumulative_adj_factor` (DaaS
   `/prices/adjusted/bulk`, the path copilot_tools/backtest.py uses), then any residual one-session move of 40% or more
   truncates the window (the `research_chart._adjustment_break` rule). Factors unreadable → the run refuses.
   `ENGINE_VERSION` → `positional.v1.1`; each feature row records its `price_adjustment` in `components`.
5. **Data-quality check** (`bar_quality`): missing sessions, non-session dates, copied sessions, duplicate bars, stale
   symbols, invalid OHLC, zero volume. Used by the runner (`--quality-check`, `--require-clean` → exit 5) and the repair.
6. **Repair tool** `scripts/repair_scanner_bars.py`: `--dry-run` (default, read-only enforced), `--apply --snapshot`
   (snapshot first, idempotent), `--restore`. Not run with `--apply` anywhere but a disposable local Postgres.

## Test Cases

Authored up front in `test_reports/scanner_bar_integrity_TESTCASES.md`. Tests: `backend/tests/test_scanner_bar_integrity.py`
(TC-1..TC-25 and helpers), `backend/tests/test_scanner_bar_repair_pg.py` (PgStore on real Postgres),
`backend/tests/test_positional_runner_guards.py` (fixture updated for the new `ingest()`/calendar).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | ingester (gate 5) | 1-Oct file requested as 2026-10-02 (what NSE serves) | unit | refused, nothing written | PASS |
| TC-2 | ingester | matching file | unit | written with the file's own date | PASS |
| TC-3 | ingester | mixed / missing / blank DATE1 | edge | refused, nothing written | PASS |
| TC-4 | ingester | holiday | unit | `not_a_session`, NSE never asked | PASS |
| TC-5 | ingester | calendar unavailable | failure | `calendar_unavailable`, NSE never asked | PASS |
| TC-6 | ingester | no file | failure | `not_published`; `ingest_for_date` = 0 | PASS |
| TC-7 | calendar | weekend / holiday / weekday | unit | classified | PASS |
| TC-8 | calendar | empty year / HTTP error / bad body | edge | `CalendarUnavailable`; list read once per year | PASS |
| TC-9 | runner | holiday run date | unit | exit 3, nothing fetched or scored | PASS |
| TC-10 | runner | calendar unavailable | failure | exit 4, nothing fetched or scored | PASS |
| TC-11 | pipeline | `run_for_date` on a holiday | unit | `not_a_session`, nothing scored | PASS |
| TC-12 | back-fill | two missing sessions | unit | both ingested | PASS |
| TC-13 | back-fill | second run | unit | no-op | PASS |
| TC-14 | back-fill | warehouse unreadable | failure | nothing ingested, error reported | PASS |
| TC-15 | adjusted (gate 6) | KOTAKBANK-style 5:1 split (2133.30 → 421.00) | unit | SMA/EMA/ATR/returns/swings/volume z = continuous series; raw shows the break | PASS |
| TC-16 | adjusted | no factors | edge | truncated at the break | PASS |
| TC-17 | adjusted | ex-date = run date | edge | truncated, not scored that day | PASS |
| TC-18 | adjusted | factor 1 throughout | unit | bars unchanged | PASS |
| TC-19 | pipeline | factor read fails | failure | `adjustment_factors_unavailable`, nothing scored | PASS |
| TC-20 | data quality | every check | unit | exact counts and samples | PASS |
| TC-21 | repair dry-run | fake store | unit | exact phantom/unverified/missing; zero writes | PASS |
| TC-22 | repair apply | fake store | unit | snapshot first, deletes, back-fill, recompute | PASS |
| TC-23 | repair idempotency | apply twice | unit | second run writes nothing, no snapshot | PASS |
| TC-24 | repair restore | restore, restore again | unit | exact pre-apply state both times | PASS |
| TC-25 | repair guard | no `--snapshot` / existing snapshot | edge | refused before any write | PASS |
| TC-22..24-pg | repair on real Postgres | apply → apply → restore → restore | integration | exact rows (NUMERIC, JSONB, TEXT[], timestamps) | PASS |
| TC-26 | regression | existing engine + desk suites | unit | all pass | PASS |
| TC-27 | staging data | dry-run against staging, read-only | data | real counts; zero writes | PASS |

## API / Endpoint Tests (staging)

No endpoint was added or changed (`routes/` untouched). The two admin routes that call the ingester keep
`ingest_for_date` (a row count; 0 when refused) and get the calendar refusal from `pipeline.run_for_date` as a summary
`{"ok": false, "error": "not_a_session" | "calendar_unavailable"}`. The deployed code was NOT exercised on staging (no
deploy allowed); see "Pending". The staging evidence is the read-only dry run below.

- **pytest (all relevant suites, staging image, `--network none`):**
  - Command: `sudo docker run --rm --network none -v /home/deploy/nivesh-scanner-integrity:/work:ro -w /work/backend -e PYTHONDONTWRITEBYTECODE=1 -e MONGO_URL=mongodb://localhost:27017 -e DB_NAME=unit_test -e OPENAI_API_KEY=unit-test-placeholder nivesh/backend:staging python -m pytest tests/test_scanner_bar_integrity.py tests/test_scanner_bar_repair_pg.py tests/test_positional_engine.py tests/test_positional_runner_guards.py tests/test_positional_calibration.py tests/test_positional_scan_universe.py tests/test_positional_desk_fields.py tests/test_positional_scenario.py tests/test_ai_watchlist.py tests/test_chartink_desk.py tests/test_copilot_market_sources.py tests/test_desk_overview_backend.py tests/test_index_tape_as_of.py tests/test_reversal_backtest.py tests/test_reversal_candidates.py tests/test_reversal_rules.py tests/test_risk_gate_desk_journal.py tests/test_scan_rules_v2.py tests/test_strategy_ideas.py tests/test_symbol_lookup.py -q -p no:cacheprovider`
  - Output: `526 passed, 1 skipped, 4 warnings in 25.98s` (the skip is the opt-in Postgres test, run next)
  - Result: PASS
- **pytest, PgStore on a disposable Postgres** (`postgres:16-alpine`, `--network none`; the test container shares only its loopback; removed afterwards):
  - Output: `tests/test_scanner_bar_repair_pg.py::test_pg_apply_twice_then_restore_exactly PASSED [100%]` / `1 passed in 0.38s`; `pgtest containers left: 0`
  - Result: PASS
- No test failed on the branch, so no origin/dev baseline run was needed for blame.

## Before / after (same inputs, origin/dev engine vs the branch)

`git archive origin/dev backend` into the scratchpad vs the worktree, one script, staging image, `--network none`:

```
### origin/dev
engine positional.v1.0
holiday URL file (DATE1 01-Oct) requested as 2026-10-02 -> [('INFY', '2026-10-02', 1035.0), ('KOTAKBANK', '2026-10-02', 418.35)]
KOTAK-like features on raw (no adjustment step in this engine) {'close': 362.76, 'sma_50': 1828.27, 'sma_200': 1963.26, 'atr_14': 97.05, 'return_20d_pct': -84.62, 'high_20d': 2362.36, 'swing_low_20': 359.85}
### fix/scanner-bar-integrity
engine positional.v1.1
holiday URL file (DATE1 01-Oct) requested as 2026-10-02 -> REFUSED: BhavcopyDateMismatch file trade date 2026-10-01 != requested 2026-10-02
KOTAK-like features on adjusted (warehouse_adjusted, steps=1) {'close': 362.76, 'sma_50': 426.95, 'sma_200': 407.97, 'atr_14': 11.78, 'return_20d_pct': -23.1, 'high_20d': 472.47, 'swing_low_20': 359.85}
```

Upstream check (NSE, from the staging app VM, files held in the scratchpad only). Condensed from the real `curl -w`
lines (HTTP code, size) and `awk -F, 'NR>1{print $3}' | sort | uniq -c` over each file's DATE1 column; values unchanged:

```
26102026 http=200 size=398036   DATE1 26-Oct-2026 x3526
02102026 http=200 size=401205   DATE1 01-Oct-2026 x3534   <- Gandhi Jayanti URL serves 1 Oct
20102026 http=200 size=397312   DATE1 19-Oct-2026 x3517   <- Dussehra URL serves 19 Oct
21102026 http=200 size=400625   DATE1 21-Oct-2026 x3536
```

## Data Correctness (staging, read-only)

- Command: `python3 make_bundle.py <worktree>/backend > dryrun_bundle.py && sudo docker exec -i -w /app/backend nivesh-staging-app-backend python - < dryrun_bundle.py`
  (the bundle loads the branch's changed modules and the script in memory; `args.apply=False`, `args.restore=None`; the
  script opens every DB session with `default_transaction_read_only=on`). Exit 0. Full unedited stdout:
  `test_reports/scanner_bar_integrity_dryrun_20261027.txt`. Excerpts below are copied from it.

**Window**
```
{
 "start": "2025-10-20",
 "end": "2026-10-26",
 "store_dates": 262,
 "warehouse_sessions": 250
}
```
**Phantom dates** (not a warehouse session, every bar identical to the previous stored date) — [date, previous date, rows, identical]:
```
{"count": 14, "rows": 36361, "dates": [["2025-10-22", "2025-10-21", 2430, 2430], ["2025-11-05", "2025-11-04", 2434, 2434], ["2026-01-15", "2026-01-14", 2495, 2495], ["2026-01-26", "2026-01-23", 2501, 2501], ["2026-03-03", "2026-03-02", 2533, 2533], ["2026-03-26", "2026-03-25", 2538, 2538], ["2026-03-31", "2026-03-30", 2552, 2552], ["2026-04-03", "2026-04-02", 2550, 2550], ["2026-04-14", "2026-04-13", 2558, 2558], ["2026-05-01", "2026-04-30", 2650, 2650], ["2026-05-28", "2026-05-27", 2658, 2658], ["2026-06-26", "2026-06-25", 2669, 2669], ["2026-09-14", "2026-09-11", 2885, 2885], ["2026-10-02", "2026-10-01", 2908, 2908]]}
```
Non-session dates that are not a 100% copy (never deleted): `[]`

**Missing sessions**, with each NSE file checked against the warehouse:
```
{
 "count": 2,
 "dates": [
  {
   "date": "2026-10-21",
   "warehouse_rows": 2916
  },
  {
   "date": "2026-10-22",
   "warehouse_rows": 2915
  }
 ],
 "nse_file_check": {
  "2026-10-21": {
   "warehouse_rows": 2916,
   "nse_file": "trade date matches",
   "nse_eq_be_rows": 2916,
   "in_both": 2916,
   "close_mismatches": 0,
   "mismatch_sample": [],
   "only_in_nse_file": 0
  },
  "2026-10-22": {
   "warehouse_rows": 2915,
   "nse_file": "trade date matches",
   "nse_eq_be_rows": 2915,
   "in_both": 2915,
   "close_mismatches": 0,
   "mismatch_sample": [],
   "only_in_nse_file": 0
  }
 }
}
```
**Derived rows** (deleted on phantom dates; replaced on the recompute date; left as recorded elsewhere):
```
{
 "on_phantom_dates_deleted_by_apply": {
  "stock_technical_features": {
   "2025-10-22": 0,
   "2025-11-05": 0,
   "2026-01-15": 2116,
   "2026-01-26": 2122,
   "2026-03-03": 2153,
   "2026-03-26": 2171,
   "2026-03-31": 2164,
   "2026-04-03": 2167,
   "2026-04-14": 2170,
   "2026-05-01": 2179,
   "2026-05-28": 2187,
   "2026-06-26": 2216,
   "2026-09-14": 2213,
   "2026-10-02": 2212
  },
  "positional_signals": {
   "2025-10-22": 0,
   "2025-11-05": 0,
   "2026-01-15": 456,
   "2026-01-26": 222,
   "2026-03-03": 462,
   "2026-03-26": 358,
   "2026-03-31": 217,
   "2026-04-03": 321,
   "2026-04-14": 921,
   "2026-05-01": 1358,
   "2026-05-28": 1386,
   "2026-06-26": 1087,
   "2026-09-14": 1049,
   "2026-10-02": 909
  }
 },
 "scored_dates": 190,
 "recompute_dates": [
  "2026-10-26"
 ],
 "recompute_rows_replaced": {
  "stock_technical_features": {
   "2026-10-26": 2210
  },
  "positional_signals": {
   "2026-10-26": 666
  }
 },
 "affected_dates": 190,
 "affected_not_recomputed": {
  "count": 189,
  "first": [
   "2026-01-12"
  ],
  "last": [
   "2026-10-23"
  ]
 },
 "other_stores": {
  "positional_outcomes": {
   "rows": 0,
   "on_phantom_dates": 0
  },
  "positional_backtest_labels": {
   "rows": 0,
   "on_phantom_dates": 0
  },
  "chartink_scan_hits": {
   "rows": 0,
   "on_phantom_dates": 0
  },
  "mongo.ai_watchlist_days": {
   "docs": 1,
   "on_phantom_dates": 0,
   "note": "a stored day is never rewritten (services/ai_watchlist_store); not touched by --apply"
  }
 }
}
```
**Data quality, as stored:**
```
{
 "window": [
  "2025-10-20",
  "2026-10-26"
 ],
 "dates": 262,
 "rows": 688123,
 "symbols": 3067,
 "copied_sessions": {
  "count": 14,
  "dates": [
   [
    "2025-10-22",
    2430,
    2430,
    1.0
   ],
   [
    "2025-11-05",
    2434,
    2434,
    1.0
   ],
   [
    "2026-01-15",
    2495,
    2495,
    1.0
   ],
   [
    "2026-01-26",
    2501,
    2501,
    1.0
   ],
   [
    "2026-03-03",
    2533,
    2533,
    1.0
   ],
   [
    "2026-03-26",
    2538,
    2538,
    1.0
   ],
   [
    "2026-03-31",
    2552,
    2552,
    1.0
   ],
   [
    "2026-04-03",
    2550,
    2550,
    1.0
   ],
   [
    "2026-04-14",
    2558,
    2558,
    1.0
   ],
   [
    "2026-05-01",
    2650,
    2650,
    1.0
   ],
   [
    "2026-05-28",
    2658,
    2658,
    1.0
   ],
   [
    "2026-06-26",
    2669,
    2669,
    1.0
   ],
   [
    "2026-09-14",
    2885,
    2885,
    1.0
   ],
   [
    "2026-10-02",
    2908,
    2908,
    1.0
   ]
  ]
 },
 "missing_sessions": {
  "count": 2,
  "dates": [
   "2026-10-21",
   "2026-10-22"
  ]
 },
 "extra_dates": {
  "count": 14,
  "dates": [
   "2025-10-22",
   "2025-11-05",
   "2026-01-15",
   "2026-01-26",
   "2026-03-03",
   "2026-03-26",
   "2026-03-31",
   "2026-04-03",
   "2026-04-14",
   "2026-05-01",
   "2026-05-28",
   "2026-06-26",
   "2026-09-14",
   "2026-10-02"
  ]
 },
 "duplicate_bars": {
  "count": 36363,
  "on_copied_sessions": 36361,
  "outside_copied_sessions": 2,
  "sample": [
   "SHIVAUM 2026-03-10",
   "SONAL 2026-04-22"
  ]
 },
 "stale_symbols": {
  "count": 137,
  "sessions_behind": {
   "1": 4,
   "2-5": 11,
   ">5": 122
  },
  "sample": [
   {
    "symbol": "SONAL",
    "last_bar": "2026-10-23",
    "sessions_behind": 1
   },
   {
    "symbol": "PALASHSECU",
    "last_bar": "2026-10-23",
    "sessions_behind": 1
   },
   {
    "symbol": "LIQUIDBETA",
    "last_bar": "2026-10-23",
    "sessions_behind": 1
   },
   {
    "symbol": "DSKULKARNI",
    "last_bar": "2026-10-23",
    "sessions_behind": 1
   },
   {
    "symbol": "VIVIMEDLAB",
    "last_bar": "2026-10-19",
    "sessions_behind": 2
   },
   {
    "symbol": "VASUPRADA",
    "last_bar": "2026-10-19",
    "sessions_behind": 2
   },
   {
    "symbol": "PARSVNATH",
    "last_bar": "2026-10-19",
    "sessions_behind": 2
   },
   {
    "symbol": "ICICIPRULI",
    "last_bar": "2026-10-19",
    "sessions_behind": 2
   },
   {
    "symbol": "HAMPTON",
    "last_bar": "2026-10-19",
    "sessions_behind": 2
   },
   {
    "symbol": "GSEC10ABSL",
    "last_bar": "2026-10-19",
    "sessions_behind": 2
   }
  ]
 },
 "invalid_ohlc": {
  "count": 0,
  "by_rule": {},
  "sample": []
 },
 "zero_volume": {
  "count": 0,
  "sample": []
 }
}
```
**Data quality with the phantom dates removed** (the two missing sessions stay listed until back-filled):
```
{
 "dates": 248,
 "rows": 651762,
 "missing_sessions": {
  "count": 2,
  "dates": [
   "2026-10-21",
   "2026-10-22"
  ]
 },
 "extra_dates": {
  "count": 0,
  "dates": []
 },
 "copied_sessions": {
  "count": 0,
  "dates": []
 },
 "duplicate_bars": {
  "count": 2,
  "on_copied_sessions": 0,
  "outside_copied_sessions": 2,
  "sample": [
   "SHIVAUM 2026-03-10",
   "SONAL 2026-04-22"
  ]
 }
}
```
**Corporate actions** (factor step ≥ 20% in the window) and adjusted closes vs the warehouse's `adj_close`:
```
{
 "symbols_with_step": 91,
 "steps": 91,
 "price_ratio_histogram": {
  "0.1": 29,
  "0.5": 23,
  "0.2": 17,
  "0.3333": 4,
  "0.25": 3,
  "0.75": 3,
  "0.0667": 2,
  "0.01": 2,
  "0.6667": 2,
  "0.7143": 1,
  "0.0909": 1,
  "0.4": 1
 },
 "symbols": [
  "AASTHA",
  "AHCL",
  "AIIL",
  "AJMERA",
  "ANANDRATHI",
  "ANGELONE",
  "AQYLON",
  "AVROIND",
  "AZADIND",
  "BANKNIFTY1",
  "BANSALWIRE",
  "BECTORFOOD",
  "BEML",
  "BESTAGRO",
  "BHARATRAS",
  "BLSE",
  "BRIGADE",
  "BUILDPRO",
  "CAMS",
  "CONS",
  "CORDELIA",
  "CUB",
  "CUPID",
  "DBEIL",
  "DELPHIFX",
  "E2E",
  "ECLERX",
  "FCL",
  "GEEKAYWIRE",
  "GOLDADD",
  "GOLDIAM",
  "GOODLUCK",
  "GRMOVER",
  "GROWWGOLD",
  "GROWWSLVR",
  "HARDWYN",
  "HDFCAMC",
  "HEALTHADD",
  "HIRECT",
  "INFOBEAN",
  "IRB",
  "IVZINGOLD",
  "IVZINNIFTY",
  "JLHL",
  "JSWDULUX",
  "KAPSTON",
  "KILITCH",
  "KIRLPNU",
  "KMEW",
  "KOTAKBANK",
  "KOTYARK",
  "KRISHANA",
  "LALPATHLAB",
  "LEMERITE",
  "LICI",
  "LICMFGOLD",
  "MBAPL",
  "MCX",
  "METROPOLIS",
  "MIDCAP",
  "MIDQ50ADD",
  "MOLDTKPAC",
  "MONEYBOXX",
  "MWL",
  "NARMADA",
  "NUVAMA",
  "NV20",
  "PASHUPATI",
  "PGIL",
  "POCL",
  "PSUBANK",
  "QNIFTY",
  "RAMRAT",
  "RMDRIP",
  "RNBDENIMS",
  "SIKKO",
  "SILVER1",
  "SILVERADD",
  "SILVERTUC",
  "SKMEGGPROD",
  "SMCGLOBAL",
  "TAALTECH",
  "TCC",
  "TDPOWERSYS",
  "TEMBO",
  "THYROCARE",
  "TRENT",
  "V2RETAIL",
  "VGL",
  "WEBELSOLAR",
  "ZFCVINDIA"
 ],
 "store_symbols_with_factors": 2996,
 "store_symbols": 3067,
 "adjusted_vs_warehouse_sample": [
  {
   "symbol": "KOTAKBANK",
   "ex_date": "2026-01-14",
   "dates_compared": 248,
   "max_rel_diff": 0.0,
   "price_basis": "warehouse_adjusted",
   "break_truncated_at": null,
   "day_before_ex": {
    "date": "2026-01-13",
    "raw_close": 2132.6,
    "adjusted_close": 426.52,
    "warehouse_adj_close": 426.52
   }
  },
  {
   "symbol": "AASTHA",
   "ex_date": "2026-09-28",
   "dates_compared": 66,
   "max_rel_diff": 0.0,
   "price_basis": "warehouse_adjusted",
   "break_truncated_at": null,
   "day_before_ex": {
    "date": "2026-09-25",
    "raw_close": 72.72,
    "adjusted_close": 36.36,
    "warehouse_adj_close": 36.36
   }
  },
  {
   "symbol": "AHCL",
   "ex_date": "2026-04-24",
   "dates_compared": 201,
   "max_rel_diff": 0.0,
   "price_basis": "warehouse_adjusted",
   "break_truncated_at": null,
   "day_before_ex": {
    "date": "2026-04-23",
    "raw_close": 143.79,
    "adjusted_close": 14.379,
    "warehouse_adj_close": 14.379
   }
  },
  {
   "symbol": "AIIL",
   "ex_date": "2026-01-13",
   "dates_compared": 248,
   "max_rel_diff": 0.0,
   "price_basis": "warehouse_adjusted",
   "break_truncated_at": null,
   "day_before_ex": {
    "date": "2026-01-12",
    "raw_close": 3098.6,
    "adjusted_close": 619.72,
    "warehouse_adj_close": 619.72
   }
  },
  {
   "symbol": "AJMERA",
   "ex_date": "2026-01-14",
   "dates_compared": 248,
   "max_rel_diff": 0.0,
   "price_basis": "warehouse_adjusted",
   "break_truncated_at": null,
   "day_before_ex": {
    "date": "2026-01-13",
    "raw_close": 910.05,
    "adjusted_close": 182.01,
    "warehouse_adj_close": 182.01
   }
  },
  {
   "symbol": "ANANDRATHI",
   "ex_date": "2026-06-03",
   "dates_compared": 248,
   "max_rel_diff": 0.0,
   "price_basis": "warehouse_adjusted",
   "break_truncated_at": null,
   "day_before_ex": {
    "date": "2026-06-02",
    "raw_close": 3539.3,
    "adjusted_close": 1769.65,
    "warehouse_adj_close": 1769.65
   }
  },
  {
   "symbol": "ANGELONE",
   "ex_date": "2026-02-26",
   "dates_compared": 248,
   "max_rel_diff": 0.0,
   "price_basis": "warehouse_adjusted",
   "break_truncated_at": null,
   "day_before_ex": {
    "date": "2026-02-25",
    "raw_close": 2489.9,
    "adjusted_close": 248.99,
    "warehouse_adj_close": 248.99
   }
  },
  {
   "symbol": "AQYLON",
   "ex_date": "2026-03-05",
   "dates_compared": 163,
   "max_rel_diff": 0.0,
   "price_basis": "warehouse_adjusted",
   "break_truncated_at": null,
   "day_before_ex": {
    "date": "2026-03-04",
    "raw_close": 1084.1,
    "adjusted_close": 108.41,
    "warehouse_adj_close": 108.41
   }
  }
 ]
}
```
Reconciliation with the study's 91 (warehouse SQL over 2025-10-17..2026-10-26 vs the dry run's list):
```
warehouse: 91  dry-run(store): 91  identical: True  only_wh: []  only_store: []
in scanner equity universe: 71 excluded (ETF/non-equity): 20
excluded: AASTHA AZADIND BANKNIFTY1 CONS CORDELIA GOLDADD GROWWGOLD GROWWSLVR HEALTHADD IVZINGOLD IVZINNIFTY LICMFGOLD MIDCAP MIDQ50ADD NV20 PSUBANK QNIFTY SILVER1 SILVERADD TAALTECH
```
**Scanner rerun preview for 2026-10-26** (in memory; three runs compared with the stored rows: the old engine replayed
on the stored bars, the fixed engine on the stored bars = what a deploy alone changes, and the fixed engine on the
corrected bars = deploy + repair):
```
{
 "date": "2026-10-26",
 "corrected_run": {
  "universe": 2210,
  "scored": 2205,
  "actionable": 682,
  "price_basis": {
   "warehouse_adjusted": 2194,
   "raw_no_factors": 11,
   "unadjusted_replay": 0
  },
  "break_truncated": 17,
  "skipped_short_after_break": 5,
  "macro_multiplier": 1.0
 },
 "symbols_with_adjustment": 81,
 "replay_as_stored_vs_table": {
  "scored": {
   "before": 2210,
   "after": 2210,
   "both": 2210
  },
  "actionable": {
   "before": 666,
   "after": 666,
   "added": 0,
   "removed": 0
  },
  "top20": {
   "before": [
    "ICICIBANK",
    "CRISIL",
    "SGMART",
    "UNIONBANK",
    "ACUTAAS",
    "KOTAKBANK",
    "MPHASIS",
    "COFORGE",
    "ABMINTLLTD",
    "LAURUSLABS",
    "PANACHE",
    "FEDERALBNK",
    "MARKOLINES",
    "NAZARA",
    "INDHOTEL",
    "BAFNAPH",
    "DRREDDY",
    "INDUSTOWER",
    "PETRONET",
    "BHARTIARTL"
   ],
   "after": [
    "ICICIBANK",
    "CRISIL",
    "SGMART",
    "UNIONBANK",
    "ACUTAAS",
    "KOTAKBANK",
    "MPHASIS",
    "COFORGE",
    "ABMINTLLTD",
    "LAURUSLABS",
    "PANACHE",
    "FEDERALBNK",
    "MARKOLINES",
    "NAZARA",
    "INDHOTEL",
    "BAFNAPH",
    "DRREDDY",
    "INDUSTOWER",
    "PETRONET",
    "BHARTIARTL"
   ],
   "entered": [],
   "exited": [],
   "rank_shifts": []
  },
  "stage_changes": 0,
  "final_score_delta": {
   "identical": 2139,
   "changed_gt_0_01": 0,
   "mean_abs": 6.9e-05,
   "max_abs": 0.0082
  }
 },
 "adjusted_unrepaired_vs_table": {
  "scored": {
   "before": 2210,
   "after": 2205,
   "both": 2205
  },
  "actionable": {
   "before": 666,
   "after": 676,
   "added": 11,
   "removed": 1
  },
  "top20": {
   "before": [
    "ICICIBANK",
    "CRISIL",
    "SGMART",
    "UNIONBANK",
    "ACUTAAS",
    "KOTAKBANK",
    "MPHASIS",
    "COFORGE",
    "ABMINTLLTD",
    "LAURUSLABS",
    "PANACHE",
    "FEDERALBNK",
    "MARKOLINES",
    "NAZARA",
    "INDHOTEL",
    "BAFNAPH",
    "DRREDDY",
    "INDUSTOWER",
    "PETRONET",
    "BHARTIARTL"
   ],
   "after": [
    "ICICIBANK",
    "CRISIL",
    "SGMART",
    "UNIONBANK",
    "ACUTAAS",
    "KOTAKBANK",
    "MPHASIS",
    "ANANDRATHI",
    "COFORGE",
    "ABMINTLLTD",
    "LAURUSLABS",
    "PANACHE",
    "FEDERALBNK",
    "MARKOLINES",
    "NAZARA",
    "INDHOTEL",
    "BAFNAPH",
    "DRREDDY",
    "INDUSTOWER",
    "PETRONET"
   ],
   "entered": [
    "ANANDRATHI"
   ],
   "exited": [
    "BHARTIARTL"
   ],
   "rank_shifts": [
    {
     "symbol": "COFORGE",
     "from": 8,
     "to": 9
    },
    {
     "symbol": "ABMINTLLTD",
     "from": 9,
     "to": 10
    },
    {
     "symbol": "LAURUSLABS",
     "from": 10,
     "to": 11
    },
    {
     "symbol": "PANACHE",
     "from": 11,
     "to": 12
    },
    {
     "symbol": "FEDERALBNK",
     "from": 12,
     "to": 13
    },
    {
     "symbol": "MARKOLINES",
     "from": 13,
     "to": 14
    },
    {
     "symbol": "NAZARA",
     "from": 14,
     "to": 15
    },
    {
     "symbol": "INDHOTEL",
     "from": 15,
     "to": 16
    },
    {
     "symbol": "BAFNAPH",
     "from": 16,
     "to": 17
    },
    {
     "symbol": "DRREDDY",
     "from": 17,
     "to": 18
    },
    {
     "symbol": "INDUSTOWER",
     "from": 18,
     "to": 19
    },
    {
     "symbol": "PETRONET",
     "from": 19,
     "to": 20
    }
   ]
  },
  "stage_changes": 12,
  "final_score_delta": {
   "identical": 2094,
   "changed_gt_0_01": 34,
   "mean_abs": 0.001271,
   "max_abs": 0.2053
  }
 },
 "corrected_vs_table": {
  "scored": {
   "before": 2210,
   "after": 2205,
   "both": 2205
  },
  "actionable": {
   "before": 666,
   "after": 682,
   "added": 32,
   "removed": 16
  },
  "top20": {
   "before": [
    "ICICIBANK",
    "CRISIL",
    "SGMART",
    "UNIONBANK",
    "ACUTAAS",
    "KOTAKBANK",
    "MPHASIS",
    "COFORGE",
    "ABMINTLLTD",
    "LAURUSLABS",
    "PANACHE",
    "FEDERALBNK",
    "MARKOLINES",
    "NAZARA",
    "INDHOTEL",
    "BAFNAPH",
    "DRREDDY",
    "INDUSTOWER",
    "PETRONET",
    "BHARTIARTL"
   ],
   "after": [
    "ICICIBANK",
    "CRISIL",
    "ACUTAAS",
    "UNIONBANK",
    "COFORGE",
    "ANANDRATHI",
    "PNB",
    "ABMINTLLTD",
    "INDUSTOWER",
    "GESHIP",
    "PERSISTENT",
    "LAURUSLABS",
    "CANTABIL",
    "SGMART",
    "DRREDDY",
    "FEDERALBNK",
    "MPHASIS",
    "ZYDUSLIFE",
    "INDGN",
    "KOTAKBANK"
   ],
   "entered": [
    "ANANDRATHI",
    "PNB",
    "GESHIP",
    "PERSISTENT",
    "CANTABIL",
    "ZYDUSLIFE",
    "INDGN"
   ],
   "exited": [
    "PANACHE",
    "MARKOLINES",
    "NAZARA",
    "INDHOTEL",
    "BAFNAPH",
    "PETRONET",
    "BHARTIARTL"
   ],
   "rank_shifts": [
    {
     "symbol": "ACUTAAS",
     "from": 5,
     "to": 3
    },
    {
     "symbol": "COFORGE",
     "from": 8,
     "to": 5
    },
    {
     "symbol": "ABMINTLLTD",
     "from": 9,
     "to": 8
    },
    {
     "symbol": "INDUSTOWER",
     "from": 18,
     "to": 9
    },
    {
     "symbol": "LAURUSLABS",
     "from": 10,
     "to": 12
    },
    {
     "symbol": "SGMART",
     "from": 3,
     "to": 14
    },
    {
     "symbol": "DRREDDY",
     "from": 17,
     "to": 15
    },
    {
     "symbol": "FEDERALBNK",
     "from": 12,
     "to": 16
    },
    {
     "symbol": "MPHASIS",
     "from": 7,
     "to": 17
    },
    {
     "symbol": "KOTAKBANK",
     "from": 6,
     "to": 20
    }
   ]
  },
  "stage_changes": 55,
  "final_score_delta": {
   "identical": 76,
   "changed_gt_0_01": 1377,
   "mean_abs": 0.021766,
   "max_abs": 0.1922
  }
 }
}
```
First adjusted symbols, stored vs corrected rerun:
```
[
 {
  "symbol": "AHCL",
  "price_adjustment": {
   "price_basis": "warehouse_adjusted",
   "factor_steps": 1,
   "break_truncated_at": null,
   "bars_dropped": 0
  },
  "stored": {
   "stage": "WEAK",
   "final_score": 0.1431,
   "sma_200": 54.9703,
   "return_20d_pct": -16.78
  },
  "rerun": {
   "stage": "ACCUMULATION",
   "final_score": 0.2688,
   "sma_200": 15.846715000000003,
   "return_20d_pct": -13.787085514834207
  }
 },
 {
  "symbol": "AIIL",
  "price_adjustment": {
   "price_basis": "warehouse_adjusted",
   "factor_steps": 1,
   "break_truncated_at": null,
   "bars_dropped": 0
  },
  "stored": {
   "stage": "WEAK",
   "final_score": 0.146,
   "sma_200": 511.8813,
   "return_20d_pct": -13.3
  },
  "rerun": {
   "stage": "WEAK",
   "final_score": 0.139,
   "sma_200": 518.4410999999999,
   "return_20d_pct": -11.756707759245833
  }
 },
 {
  "symbol": "AJMERA",
  "price_adjustment": {
   "price_basis": "warehouse_adjusted",
   "factor_steps": 1,
   "break_truncated_at": null,
   "bars_dropped": 0
  },
  "stored": {
   "stage": "WEAK",
   "final_score": 0.51,
   "sma_200": 125.7265,
   "return_20d_pct": 2.68
  },
  "rerun": {
   "stage": "ACCUMULATION",
   "final_score": 0.4277,
   "sma_200": 129.00924999999995,
   "return_20d_pct": 2.779852294415397
  }
 },
 {
  "symbol": "ALLCARGO",
  "price_adjustment": {
   "price_basis": "warehouse_adjusted",
   "factor_steps": 0,
   "break_truncated_at": "2025-11-12",
   "bars_dropped": 15
  },
  "stored": {
   "stage": "ACCUMULATION",
   "final_score": 0.2952,
   "sma_200": 9.3495,
   "return_20d_pct": -16.52
  },
  "rerun": {
   "stage": "ACCUMULATION",
   "final_score": 0.314,
   "sma_200": 9.460949999999999,
   "return_20d_pct": -13.242009132420085
  }
 },
 {
  "symbol": "ANANDRATHI",
  "price_adjustment": {
   "price_basis": "warehouse_adjusted",
   "factor_steps": 1,
   "break_truncated_at": null,
   "bars_dropped": 0
  },
  "stored": {
   "stage": "EARLY_BREAKOUT",
   "final_score": 0.5711,
   "sma_200": 2661.575,
   "return_20d_pct": 2.8
  },
  "rerun": {
   "stage": "EARLY_BREAKOUT",
   "final_score": 0.7047,
   "sma_200": 1850.4035000000017,
   "return_20d_pct": 2.8882532066069944
  }
 },
 {
  "symbol": "ANGELONE",
  "price_adjustment": {
   "price_basis": "warehouse_adjusted",
   "factor_steps": 1,
   "break_truncated_at": null,
   "bars_dropped": 0
  },
  "stored": {
   "stage": "WEAK",
   "final_score": 0.187,
   "sma_200": 642.3207,
   "return_20d_pct": -5.8
  },
  "rerun": {
   "stage": "WEAK",
   "final_score": 0.28,
   "sma_200": 290.33420000000007,
   "return_20d_pct": -2.786377708978316
  }
 }
]
```
**What `--apply` would change:**
```
{
 "delete_dates": [
  "2025-10-22",
  "2025-11-05",
  "2026-01-15",
  "2026-01-26",
  "2026-03-03",
  "2026-03-26",
  "2026-03-31",
  "2026-04-03",
  "2026-04-14",
  "2026-05-01",
  "2026-05-28",
  "2026-06-26",
  "2026-09-14",
  "2026-10-02"
 ],
 "backfill_dates": [
  "2026-10-21",
  "2026-10-22"
 ],
 "recompute_dates": [
  "2026-10-26"
 ],
 "note": "snapshot first; a second --apply finds nothing to do"
}
exit=0
```
**Zero writes:** fingerprint taken while the last dry run was running and again after it; identical, and the last write
times are the 19:45 IST scheduled job of 2026-10-26 (14:15 UTC), before the first dry run started (~20:10 UTC):
```
stock_ohlcv rows 688123 dates 262 last_write 2026-10-26T14:15:05.364706+00:00
stock_technical_features rows 440693 dates 202 last_write 2026-10-26T14:15:25.554618+00:00
positional_signals rows 180841 dates 202 last_write 2026-10-26T14:15:25.529901+00:00
UNCHANGED
```

## Inputs required from user

- none for the work done. Owner decisions are listed in the PR draft (apply approval, recompute window, cron flags).

## Pending at the first commit (superseded by the follow-up section below)

- UNVERIFIED on staging: the deployed scheduled job with the new guards (calendar refusal, DATE1 refusal, adjusted
  features, `--backfill-missing`, `--quality-check`/`--require-clean`). Needs merge + deploy; plan in the PR draft.
- NOT RUN: `--apply` / `--restore` on staging (needs the owner's go-ahead; verified only on a disposable Postgres).
- Not covered: the 189 scored dates before 2026-10-26 stay as recorded unless the owner picks `--recompute-from`;
  historical recomputes would use today's macro state (`macro_engine.latest_state()` is not point-in-time).
- Overall status: IN PROGRESS (code and evidence complete; staging repair and deploy await approval).

---

# Follow-up for the owner's decisions (§9.1), commit 97447f67

Status of this section: code and tests complete; staging was only read. The repair itself is for the coordinator to
run with `runbook_scanner_repair.md` (not run by me).

## What changed, by decision

| # | Decision | Implementation | Tests |
|---|---|---|---|
| 1 | One transaction; snapshot verified first; quality rerun; second apply no-op; exact restore | `bar_repair.apply_repair` fetches the missing NSE files (trade date checked) and scores 26 Oct on the corrected bars in memory, writes + reads back + verifies the snapshot, then `PgStore.apply_txn` re-checks the counts and does every write on one connection in one transaction. `--restore` verifies, then one transaction, and marks the apply's run record `rolled_back`. `--fingerprint` / `--compare-fingerprints`. Apply mode uses its own pool (300 s per statement). | TC-28..TC-32, TC-35, TC-45 |
| 2 | `--verify-snapshot` | readable, non-empty, every table and date covered, per-date counts = plan; `--expect` = the reviewed dry run's per-table counts; apply verifies its own snapshot and refuses on a problem; `--snapshot-only` preflight | TC-33, TC-34 |
| 3 | Recompute only 26 Oct | default and documented; `--recompute-from` kept, documented as not the path | dry run below |
| 4 | Calendar readiness, visible | `session_calendar.readiness` from the lead date (default 12-01, `SCANNER_CALENDAR_LEAD` / `--calendar-lead`); the runner logs `ERROR ALERT calendar not ready`, still scores, exits 6; every run writes Mongo `job_runs` (`job: positional_engine`, `calendar_ready`, `calendar_missing_year`, also in `counts`/`error`); a crash is recorded as `failed` | TC-36..TC-39 |
| 5 | Publish engine version, price basis, data quality | `scan_meta.basis_for_date` → `scan_basis` on `/api/positional/picks`, `/watchlist` and the ideas `selection`; `price_basis` per row; desk Scanner line `desk-scan-basis` and the `desk-scan-raw-prices` row marker; quality check on by default (report only) | TC-40..TC-42, SB-1..SB-4 |
| 6 | Exceptions explicit | `score_universe` summary `exceptions` (raw prices, not scored after truncation, truncated); in the dry run, the run record and `scan_basis` | TC-43 |
| 7 | Before/after record | `<snapshot>.before_after.json` with stored / code-change-only / post-repair rankings and signals and three comparisons | TC-44 |

**Disclosure (decision 3):** the 189 older scored dates (2026-01-12 .. 2026-10-23) stay as recorded. They were computed
by engine v1.0 on the previously stored price basis: raw, unadjusted prices on the unrepaired bar store (with the
phantom dates, without 21–22 Oct). They are not rescored with today's macro regime.

**Not a claim of better predictions:** the rankings change because the inputs are corrected. Whether the new ranking
predicts better needs its own out-of-sample validation.

## Test runs (real output, this session)

- Backend, staging image, `--network none`, 23 files: `626 passed, 1 skipped, 4 warnings in 29.54s`
- Throwaway Postgres (`postgres:16-alpine`, no network; container removed after, `count=0`):
  `tests/test_scanner_bar_repair_pg.py::test_pg_one_transaction_failure_rolls_back_then_apply_twice_then_restore_exactly PASSED [100%]` /
  `1 passed in 0.48s`. It injects a failure while the recompute's signals are written, after the phantom deletes and
  the back-fill insert ran in the same transaction, and asserts every table is byte-identical (to_jsonb dump and
  `--fingerprint` compare); then apply, a second apply with no change, restore to the exact prior rows, twice.
- Frontend, `run-fe.sh` (tsc, production build, Playwright with the API mocked, no network):
  - `e2e/tests/copilot-app-desk-scanner.spec.ts`: `tsc: clean` · `✓ built in 26.82s` · `85 passed (1.1m)`; new:
    `SB-1 an adjusted scan says so, counts its exceptions, names them, and marks a raw-price row`, `SB-2 a clean adjusted
    scan reads as one quiet line`, `SB-3 a scan from before v1.1 is raw prices and unchecked, said plainly`, `SB-4 the
    picks route's basis is used when the watchlist sends none; an unreadable basis or none at all is said`.
  - the 14 other specs that mock `/api/positional/watchlist|picks`: `tsc: clean` · `✓ built in 26.03s` ·
    `405 passed (6.4m)` · `2 skipped` (the lab's screenshot tests, skipped by their own condition).

## Staging, read-only (fresh dry run on 97447f67)

The branch's modules and script loaded in memory in `nivesh-staging-app-backend` from stdin; database sessions
read-only. Unedited stdout: `test_reports/scanner_bar_integrity_dryrun_20261027.txt` (replaces the first run's file;
the first run's output stays in git history at 1f6f7e3e). Excerpts:

Window: `{
 "start": "2025-10-20",
 "end": "2026-10-26",
 "store_dates": 262,
 "warehouse_sessions": 250
}`

Phantom dates: `{"count": 14, "rows": 36361}` (same 14 dates as reviewed). Missing sessions with NSE file checks:
```
{
 "count": 2,
 "dates": [
  {
   "date": "2026-10-21",
   "warehouse_rows": 2916
  },
  {
   "date": "2026-10-22",
   "warehouse_rows": 2915
  }
 ],
 "nse_file_check": {
  "2026-10-21": {
   "warehouse_rows": 2916,
   "nse_file": "trade date matches",
   "nse_eq_be_rows": 2916,
   "in_both": 2916,
   "close_mismatches": 0,
   "mismatch_sample": [],
   "only_in_nse_file": 0
  },
  "2026-10-22": {
   "warehouse_rows": 2915,
   "nse_file": "trade date matches",
   "nse_eq_be_rows": 2915,
   "in_both": 2915,
   "close_mismatches": 0,
   "mismatch_sample": [],
   "only_in_nse_file": 0
  }
 }
}
```
Recompute and what stays as recorded:
```
{
 "recompute_dates": [
  "2026-10-26"
 ],
 "recompute_rows_replaced": {
  "stock_technical_features": {
   "2026-10-26": 2210
  },
  "positional_signals": {
   "2026-10-26": 666
  }
 },
 "affected_not_recomputed": {
  "count": 189,
  "first": [
   "2026-01-12"
  ],
  "last": [
   "2026-10-23"
  ],
  "note": "left as recorded: computed by engine v1.0 on the previously stored (raw, unrepaired) price basis"
 }
}
```
Data quality, as stored (counts):
```
{
 "window": [
  "2025-10-20",
  "2026-10-26"
 ],
 "dates": 262,
 "rows": 688123,
 "symbols": 3067,
 "copied_sessions": 14,
 "missing_sessions": 2,
 "extra_dates": 14,
 "duplicate_bars": 36363,
 "stale_symbols": 137,
 "invalid_ohlc": 0,
 "zero_volume": 0
}
```
With the phantom dates removed (counts):
```
{
 "dates": 248,
 "rows": 651762,
 "missing_sessions": 2,
 "extra_dates": 0,
 "copied_sessions": 0,
 "duplicate_bars": 2
}
```
Corporate actions (91 = the study's 91) and the adjusted-close sample against the warehouse `[dates compared, max relative difference]`:
```
{
 "symbols_with_step": 91,
 "sample_max_rel_diff": {
  "KOTAKBANK": [
   248,
   0.0
  ],
  "AASTHA": [
   66,
   0.0
  ],
  "AHCL": [
   201,
   0.0
  ],
  "AIIL": [
   248,
   0.0
  ],
  "AJMERA": [
   248,
   0.0
  ],
  "ANANDRATHI": [
   248,
   0.0
  ],
  "ANGELONE": [
   248,
   0.0
  ],
  "AQYLON": [
   163,
   0.0
  ]
 }
}
```
**Exceptions for 26 Oct, code + repair (decision 6):**
```
{
 "raw_prices": {
  "count": 11,
  "symbols": [
   {
    "symbol": "RAJRILTD",
    "reason": "no split/bonus factors in the warehouse (nidp.prices_eod_adjusted) for this symbol: scored on raw NSE prices"
   },
   {
    "symbol": "HITECHGEAR",
    "reason": "no split/bonus factors in the warehouse (nidp.prices_eod_adjusted) for this symbol: scored on raw NSE prices"
   },
   {
    "symbol": "GVKPIL",
    "reason": "no split/bonus factors in the warehouse (nidp.prices_eod_adjusted) for this symbol: scored on raw NSE prices"
   },
   {
    "symbol": "RCOM",
    "reason": "no split/bonus factors in the warehouse (nidp.prices_eod_adjusted) for this symbol: scored on raw NSE prices"
   },
   {
    "symbol": "EQUIPPP",
    "reason": "no split/bonus factors in the warehouse (nidp.prices_eod_adjusted) for this symbol: scored on raw NSE prices"
   },
   {
    "symbol": "SEYAIND",
    "reason": "no split/bonus factors in the warehouse (nidp.prices_eod_adjusted) for this symbol: scored on raw NSE prices"
   },
   {
    "symbol": "EASTSILK",
    "reason": "no split/bonus factors in the warehouse (nidp.prices_eod_adjusted) for this symbol: scored on raw NSE prices"
   },
   {
    "symbol": "SWANDEF",
    "reason": "no split/bonus factors in the warehouse (nidp.prices_eod_adjusted) for this symbol: scored on raw NSE prices"
   },
   {
    "symbol": "MTEDUCARE",
    "reason": "no split/bonus factors in the warehouse (nidp.prices_eod_adjusted) for this symbol: scored on raw NSE prices"
   },
   {
    "symbol": "PREMIER",
    "reason": "no split/bonus factors in the warehouse (nidp.prices_eod_adjusted) for this symbol: scored on raw NSE prices"
   },
   {
    "symbol": "VHLTD",
    "reason": "no split/bonus factors in the warehouse (nidp.prices_eod_adjusted) for this symbol: scored on raw NSE prices"
   }
  ]
 },
 "not_scored_after_truncation": {
  "count": 5,
  "symbols": [
   {
    "symbol": "MOLDTECH",
    "break_date": "2026-10-09",
    "bars_left": 11,
    "reason": "a price break the warehouse factors do not explain on 2026-10-09; 11 bars after it, fewer than the 60 the scanner needs"
   },
   {
    "symbol": "BHAGYANGR",
    "break_date": "2026-10-08",
    "bars_left": 12,
    "reason": "a price break the warehouse factors do not explain on 2026-10-08; 12 bars after it, fewer than the 60 the scanner needs"
   },
   {
    "symbol": "VERANDA",
    "break_date": "2026-10-06",
    "bars_left": 14,
    "reason": "a price break the warehouse factors do not explain on 2026-10-06; 14 bars after it, fewer than the 60 the scanner needs"
   },
   {
    "symbol": "CCAVENUE",
    "break_date": "2026-10-19",
    "bars_left": 5,
    "reason": "a price break the warehouse factors do not explain on 2026-10-19; 5 bars after it, fewer than the 60 the scanner needs"
   },
   {
    "symbol": "INDIAGLYCO",
    "break_date": "2026-09-02",
    "bars_left": 36,
    "reason": "a price break the warehouse factors do not explain on 2026-09-02; 36 bars after it, fewer than the 60 the scanner needs"
   }
  ]
 },
 "truncated_but_scored": {
  "count": 12,
  "symbols": [
   {
    "symbol": "KAPSTON",
    "break_date": "2026-01-28",
    "bars_dropped": 67,
    "bars_left": 183
   },
   {
    "symbol": "MAHAPEXLTD",
    "break_date": "2026-03-20",
    "bars_dropped": 103,
    "bars_left": 147
   },
   {
    "symbol": "DBEIL",
    "break_date": "2026-06-19",
    "bars_dropped": 162,
    "bars_left": 88
   },
   {
    "symbol": "SIKKO",
    "break_date": "2025-12-08",
    "bars_dropped": 33,
    "bars_left": 217
   },
   {
    "symbol": "RNBDENIMS",
    "break_date": "2026-04-02",
    "bars_dropped": 110,
    "bars_left": 140
   },
   {
    "symbol": "BIOFILCHEM",
    "break_date": "2026-02-02",
    "bars_dropped": 70,
    "bars_left": 180
   },
   {
    "symbol": "VEDL",
    "break_date": "2026-04-30",
    "bars_dropped": 128,
    "bars_left": 122
   },
   {
    "symbol": "SETCO",
    "break_date": "2026-06-02",
    "bars_dropped": 149,
    "bars_left": 101
   },
   {
    "symbol": "TRIVENI",
    "break_date": "2026-07-22",
    "bars_dropped": 184,
    "bars_left": 66
   },
   {
    "symbol": "DCMSRIND",
    "break_date": "2025-12-26",
    "bars_dropped": 46,
    "bars_left": 204
   },
   {
    "symbol": "SADHNANIQ",
    "break_date": "2026-02-18",
    "bars_dropped": 82,
    "bars_left": 168
   },
   {
    "symbol": "ALLCARGO",
    "break_date": "2025-11-12",
    "bars_dropped": 15,
    "bars_left": 235
   }
  ]
 }
}
```
Code change only (counts): `{"raw_prices": 11, "not_scored_after_truncation": 5, "truncated_but_scored": 16}`

**Rerun preview for 26 Oct (decision 7's split):**
```
{
 "date": "2026-10-26",
 "corrected_run": {
  "universe": 2210,
  "scored": 2205,
  "actionable": 682,
  "price_basis": {
   "warehouse_adjusted": 2194,
   "raw_no_factors": 11,
   "unadjusted_replay": 0
  },
  "break_truncated": 17,
  "skipped_short_after_break": 5,
  "macro_multiplier": 1.0
 },
 "replay_as_stored_vs_table": {
  "scored": {
   "before": 2210,
   "after": 2210,
   "both": 2210
  },
  "actionable": {
   "before": 666,
   "after": 666,
   "added": 0,
   "removed": 0
  },
  "stage_changes": 0,
  "final_score_delta": {
   "identical": 2139,
   "changed_gt_0_01": 0,
   "mean_abs": 6.9e-05,
   "max_abs": 0.0082
  },
  "top20_entered": [],
  "top20_exited": [],
  "top20_rank_shifts": []
 },
 "adjusted_unrepaired_vs_table": {
  "scored": {
   "before": 2210,
   "after": 2205,
   "both": 2205
  },
  "actionable": {
   "before": 666,
   "after": 676,
   "added": 11,
   "removed": 1
  },
  "stage_changes": 12,
  "final_score_delta": {
   "identical": 2094,
   "changed_gt_0_01": 34,
   "mean_abs": 0.001271,
   "max_abs": 0.2053
  },
  "top20_entered": [
   "ANANDRATHI"
  ],
  "top20_exited": [
   "BHARTIARTL"
  ],
  "top20_rank_shifts": [
   [
    "COFORGE",
    8,
    9
   ],
   [
    "ABMINTLLTD",
    9,
    10
   ],
   [
    "LAURUSLABS",
    10,
    11
   ],
   [
    "PANACHE",
    11,
    12
   ],
   [
    "FEDERALBNK",
    12,
    13
   ],
   [
    "MARKOLINES",
    13,
    14
   ],
   [
    "NAZARA",
    14,
    15
   ],
   [
    "INDHOTEL",
    15,
    16
   ],
   [
    "BAFNAPH",
    16,
    17
   ],
   [
    "DRREDDY",
    17,
    18
   ],
   [
    "INDUSTOWER",
    18,
    19
   ],
   [
    "PETRONET",
    19,
    20
   ]
  ]
 },
 "corrected_vs_table": {
  "scored": {
   "before": 2210,
   "after": 2205,
   "both": 2205
  },
  "actionable": {
   "before": 666,
   "after": 682,
   "added": 32,
   "removed": 16
  },
  "stage_changes": 55,
  "final_score_delta": {
   "identical": 76,
   "changed_gt_0_01": 1377,
   "mean_abs": 0.021766,
   "max_abs": 0.1922
  },
  "top20_entered": [
   "ANANDRATHI",
   "PNB",
   "GESHIP",
   "PERSISTENT",
   "CANTABIL",
   "ZYDUSLIFE",
   "INDGN"
  ],
  "top20_exited": [
   "PANACHE",
   "MARKOLINES",
   "NAZARA",
   "INDHOTEL",
   "BAFNAPH",
   "PETRONET",
   "BHARTIARTL"
  ],
  "top20_rank_shifts": [
   [
    "ACUTAAS",
    5,
    3
   ],
   [
    "COFORGE",
    8,
    5
   ],
   [
    "ABMINTLLTD",
    9,
    8
   ],
   [
    "INDUSTOWER",
    18,
    9
   ],
   [
    "LAURUSLABS",
    10,
    12
   ],
   [
    "SGMART",
    3,
    14
   ],
   [
    "DRREDDY",
    17,
    15
   ],
   [
    "FEDERALBNK",
    12,
    16
   ],
   [
    "MPHASIS",
    7,
    17
   ],
   [
    "KOTAKBANK",
    6,
    20
   ]
  ]
 },
 "note": "Rankings change; that is not evidence the new ranking predicts better (separate validation needed)."
}
```
**What `--apply` would do, and the `--expect` value:**
```
{
 "delete_dates": [
  "2025-10-22",
  "2025-11-05",
  "2026-01-15",
  "2026-01-26",
  "2026-03-03",
  "2026-03-26",
  "2026-03-31",
  "2026-04-03",
  "2026-04-14",
  "2026-05-01",
  "2026-05-28",
  "2026-06-26",
  "2026-09-14",
  "2026-10-02"
 ],
 "backfill_dates": [
  "2026-10-21",
  "2026-10-22"
 ],
 "recompute_dates": [
  "2026-10-26"
 ],
 "snapshot_rows_by_table": {
  "stock_ohlcv": 36361,
  "stock_technical_features": 28280,
  "positional_signals": 9412
 },
 "expect_arg": "stock_ohlcv=36361,stock_technical_features=28280,positional_signals=9412",
 "note": "snapshot first and verified, then one transaction; a second --apply finds nothing to do"
}
```
**Zero writes:** read-only fingerprint before and after this dry run, identical; last writes are the 19:45 IST job of 26 Oct:
```
stock_ohlcv rows 688123 dates 262 last_write 2026-10-26T14:15:05.364706+00:00
stock_technical_features rows 440693 dates 202 last_write 2026-10-26T14:15:25.554618+00:00
positional_signals rows 180841 dates 202 last_write 2026-10-26T14:15:25.529901+00:00
UNCHANGED
```
**`scan_basis` and calendar readiness on staging today** (read-only probe with the branch's modules):
```
2026-10-26: price_basis "raw", engine_versions ["positional.v1.0"], price_basis_rows {"corp_action_adjusted": 0, "raw_no_factors": 0, "raw_before_v1_1": 2210}, data_quality "not_checked" ("no data-quality check is recorded for this date")
2026-10-23: price_basis "raw", engine_versions ["positional.v1.0"], raw_before_v1_1 2208, data_quality "not_checked"
readiness 2026-10-27: ready (checked [2026]) · 2026-11-30: ready (checked [2026]) · 2026-12-01: NOT ready, missing_year 2027 ("the NSE holiday list (segment CM) has no rows for 2027")
```
(condensed from the probe's JSON output; values unchanged.)

Snapshot size, measured read-only: `snapshot_bytes_estimate 10296811 47264246 4444930 total_MB 62.0`; `/app/data`:
`/dev/vda1 96G 91G 5.3G 95% /app/data`.

## Pending (not claimed as passed)

- NOT RUN by me: the staging repair (preflight, apply, second apply, restore, exact compare, final apply). The run-book
  is `runbook_scanner_repair.md` in the coordinator's scratchpad.
- UNVERIFIED on staging: the deployed runner (calendar alert, run record, default quality check) and the API's
  `scan_basis` and desk line: they need merge + deploy.
- The `job_runs` admin route lives on `fix/paper-exit-job-reconcile` (unmerged); until then the alert is visible in the
  cron log (ERROR, exit 6) and the Mongo record.
- The 2027 NSE CM holiday list is not loaded on staging: from 1 Dec the nightly run will alert until it is.

## Verdict: PASS
