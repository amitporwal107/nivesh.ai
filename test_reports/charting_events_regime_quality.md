# Test report — charting: event dataset, regime/trend features, candle + retest quality

Date: 2026-09-22 · Base: origin/dev b33ceff (#140) · Decisions #81-#85 (`.claude/workspace/charting-pattern-engine/decisions-log.md`)

## Scope
- `research/charting/events/` (new): pattern event dataset tooling (§35.2, §36). Built and tested; **not run for results**
  (the study pre-registration is not frozen).
- `research/charting/regime.py` (new): relative strength, market regime, trend context, India VIX and breadth features, with
  their own `FEATURE_CONFIG` hash (the detector `config_hash` is unchanged: 05167d3ae57f).
- `research/charting/patterns.py`: breakout candle quality (`body_pct`, `close_location` on PRICE_CONFIRMED) and a
  `retest_quality` block per pattern — descriptive only.
- `backend/services/research_chart_snapshot/`: re-exported; data only, no route/service/frontend code changed.

## Test cases
| TC | What | How | Result |
|---|---|---|---|
| TC-40 | Event rows equal an independent recomputation from raw bars and the cost engine | script below (RELIANCE + TCS, post-sealed) | PASS |
| TC-41 | Event extraction refuses sealed-window frames; segments stay on one side | `test_events_sealed.py` | PASS |
| TC-42 | Event signal fields unchanged by poisoning bars after t; a horizon reads only its own window; peeking control detects a leak | `test_events_lookahead.py` | PASS |
| TC-43 | Cost blocks say they are long round trips; BEARISH short-side costs flagged NOT_MODELLED | `test_events_costs.py` | PASS |
| TC-44 | Event JSONL is strict JSON (non-finite → null) | `test_events_writer.py` | PASS |
| TC-45 | Regime/trend features point in time; sealed-gap windows UNAVAILABLE at the boundaries | `test_regime_lookahead.py`, `test_regime_sealed_boundaries.py` | PASS |
| TC-46 | Sealed or pre-gap bars never reach a post-sealed regime/trend value (recursive EMA/ATR/ADX) | `test_regime_sealed_inputs.py` (6 probes fail on the old whole-frame code; 1 control) | PASS |
| TC-47 | Candle/retest quality hand-computed; poisoned-future probe + control | `test_patterns_retest_quality.py`, `test_patterns_lookahead.py` | PASS |
| TC-48 | Snapshot re-export: only the new keys differ from dev; strict JSON; served by the backend service | diff + service script below | PASS |
| TC-49 | Staging: API 17/17, UI 4/4, served data has the new fields | after #141 merged (ff52ce9a, deploy 07:19Z) | PASS (see notes: two TC-23 timeouts caused by disk saturation, third run passed) |

## Real output (this session)
```
$ pytest research/charting/tests research/costs/tests research/index_history/tests -q
924 passed in 35.55s
$ cd backend && pytest tests/test_research_chart.py tests/test_research_drawings.py tests/test_charting_feature_flag.py -q
38 passed in 2.66s

$ (TC-40: independent recomputation — match counts only; no outcome statistics computed)
rows: 121 (RELIANCE+TCS post-sealed)
  entry=open[t+1]                  match  120  mismatch 0
  exit close h5                    match  113  mismatch 0
  close_return h5                  match  113  mismatch 0
  mfe/mae h5                       match  113  mismatch 0
  base net_before_tax h5           match  113  mismatch 0
  no sealed/future-dated signal    match  121  mismatch 0
  bearish rows flagged             match   86  mismatch 1   # TCS 2026-09-18: signal on the last bar, no entry, costs None with reason

$ (TC-46: real data after the fix)
2024-09-30 / 2024-12-31 / 2025-06-30: RELIANCE OK features moved by sealed bars: [] | NIFTY 500 regime moved by pre-gap rows: []
  (before the fix, 2024-09-30: ema_20 1488 -> 24280, atr_14 24.1 -> 6449, adx_14 13.13 -> 88.32)

$ (TC-48: re-export vs dev snapshot)
symbols compared: 50 | added keys: {'retest_quality': 513, 'body_pct': 353, 'close_location': 353}
any other difference: 0 []
strict JSON (allow_nan=False) for all 50: True
served via services.research_chart: config_hash 05167d3ae57f, 50 symbols, 513 patterns, retest_quality on 513, candle quality on 353, problems []
```

## Staging verification (after #141 merged → ff52ce9a, backend deploy succeeded, container started 07:19:43Z, 0 restarts)
```
$ (API verifier, client timeout raised from 40 s to 150 s for this run only — /ohlcv took 54 s while the disk was saturated)
PASS  TC-2   HTTP 200; served config_hash 05167d3ae57f vs local 05167d3ae57f; fixture=False
PASS  TC-3   HTTP 200; 50 symbols served vs 50 in the committed manifest
PASS  TC-4   RELIANCE / TCS / HDFCBANK: 1417 bars, identical to committed snapshot=True
PASS  TC-5, TC-6, TC-8, TC-9 (sma_20 served 1284.705000 vs independent 1284.705000), TC-10 (16 patterns)
PASS  TC-11/12/14 + cleanup (create 201, listed, invalid → 422, delete 200 then 404)
PASS  TC-24  RELIANCE / TCS / HDFCBANK: 1417 raw rows vs 1417 served, mismatches 0
17/17 checks passed

$ npx playwright test e2e/tests/staging-research-charts.spec.ts
  run 1: 4 passed, 1 failed — TC-23 timed out (120 s) waiting for the drawing POST; the page showed
         "Could not load indicators (Request timed out)" / "Could not load patterns (Request timed out)" for ADANIENT
  run 2 (TC-23 only): failed the same way
  run 3 (TC-23 only): 2 passed (10.0s)   # auth setup + TC-23; drawing created, persisted through reload, deleted
  cleanup: run 1's POST had completed server-side after the test gave up → 1 leftover drawing on ADANIENT
           (13f11dbd…, created 07:30:24Z) deleted via the API (HTTP 200); ADANIENT drawings now 0

$ (deployed data, read inside nivesh-staging-app-backend — the API pass over 50 symbols was cut by a dropped connection)
deployed: config_hash 05167d3ae57f run_id chart_20260922T070536Z | 50 symbols, 513 patterns, retest_quality on 513, candle quality on 353
expected: 05167d3ae57f chart_20260922T070536Z | 50 symbols, 513 patterns, 513, 353
```
**Environment note.** During these runs nivesh-app-vm was at ~50% I/O wait with ~60–65 MB/s of sustained writes from the
kernel NFS server (the NIDP staging Postgres on nidp-stack-vm stores its data on this VM). Disk free space stayed flat (churn,
not growth). Staging and prod on this VM were slow while it lasted; the TC-23 failures were request timeouts from that, not a
code defect (no frontend or drawings code changed in #141, and TC-23 passed once responses were fast). Session token files
deleted after the run.

## Verdict: PASS
