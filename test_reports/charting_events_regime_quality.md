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
| TC-49 | Staging: API 17/17, UI 4/4, served data has the new fields | after merge | **PENDING** — needs merge + deploy and a session token |

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

## Verdict
Local and data checks pass. TC-49 needs the merge, the deploy and a session token; see
`OVERRIDE_charting_events_regime_quality.md`.
