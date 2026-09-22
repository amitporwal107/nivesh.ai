# Test report — charting: five defect fixes, sealed-input guard, cost/tax engine, Kite index data, snapshot re-export

Date: 2026-09-22 · Branch base: origin/dev 886020d9 · Owner decisions #68-#74 (`.claude/workspace/charting-pattern-engine/decisions-log.md`)

## Scope
- `research/charting/`: five review defects (sealed-window guard, `retest_window_bars`, HH_HL breakout buffer, CONFIG-hashed
  benchmark + swing tie rule, unused helpers) and a stricter sealed guard covering lookback and forward bars (replay, movement).
  `context.py` now reads the benchmark from the committed Kite history (`research/index_history`).
- `research/costs/` (new): date-effective transaction cost, slippage and tax engine per the owner's Transaction Cost PRD (§36).
- `research/index_history/` (new): Kite NIFTY 500 / NIFTY 50 / INDIA VIX / 14 sector and cap indices + derived breadth.
- `backend/services/research_chart_snapshot/`: data re-exported with the new engine (config_hash 05167d3ae57f). No route or
  service code changed.

## Test cases (written with the fixes; research code, not a new API/UI)
| TC | What | How | Result |
|---|---|---|---|
| TC-30 | Research runs refuse the sealed window as output, lookback or forward bars | `test_research_window.py`, `test_sealed_inputs.py` (3 leak cases fail against the window-only guard) | PASS |
| TC-31 | A retest opens only within `retest_window_bars` of confirmation | `test_patterns.py` | PASS |
| TC-32 | HH_HL confirms only past `breakout_buffer_atr` × ATR | `test_patterns.py`, `test_patterns_lookahead.py` | PASS |
| TC-33 | Benchmark and swing tie rule are in CONFIG and change `config_hash` | `test_config.py`, `test_swings.py` | PASS |
| TC-34 | Cost engine: PRD worked example exact; zerodha-equity-v1 reproduced (live old module where the branch exists, pinned golden outputs everywhere); every day 2021→today priced with no gap | `research/costs/tests` | PASS |
| TC-35 | Tax: slab surcharge capped at 15%, annual LTCG allowance, calendar-exact 12 months, same-year set-off, gain on slipped fills | `test_tax_regime_switch.py`, `test_prd_illustrative.py` | PASS |
| TC-36 | Index data: 0 sealed rows, sha256 match, Kite NIFTY 500 = legacy files row for row | `research/index_history/tests`, `test_context.py` | PASS |
| TC-37 | Breadth: poisoned sealed bars change nothing; control shows the probe sees a leak | `test_breadth_sealed_inputs.py` | PASS |
| TC-38 | Real snapshot served by the backend service for all 50 symbols, strict JSON | service script below | PASS |
| TC-39 | Staging: API 17/17 and UI 4/4 against the re-exported snapshot | `tools/verify_staging_api.py`, `staging-research-charts.spec.ts` | PASS (after #140 merge b33ceff, deploy 06:08Z) |

## Real output (this session)
```
$ pytest research/charting/tests research/costs/tests research/index_history/tests -q
771 passed in 30.83s
$ cd backend && pytest tests/test_research_chart.py tests/test_research_drawings.py tests/test_charting_feature_flag.py -q
38 passed in 1.89s
$ pytest research/charting/tests/test_sealed_inputs.py research/charting/tests/test_research_window.py research/index_history/tests/test_breadth_sealed_inputs.py -q
29 passed in 0.83s
$ (real snapshot through services.research_chart: load_manifest / load_symbol / ohlcv_view / patterns_view / indicators_view)
manifest config_hash 05167d3ae57f | fixture False | symbols 50
served through the real service: 513 patterns, 68434 bars, follow-through dict rules 110, patterns with RETEST_SUCCESSFUL 37, problems []
```

## Snapshot diff vs dev (de9cc36a → 05167d3a)
- Bars and indicators: identical for all 50 symbols. Pattern ids: identical (513). `status`: 0 changes.
- 109 patterns lose a retest (88 RETEST_SUCCESSFUL, 21 RETEST_PENDING) that opened 6–185 bars after confirmation;
  `retest_window_bars` is 5 (fix 2). 88 of them drop the RETEST_CONFIRMATION rule row. Visible effect: fewer retest markers.
- 75 follow-through volume rules now carry `{relative_volume, band}` instead of a bare number (fix 5); the UI's `txt()`
  already renders objects as labelled text.
- 4 HH_HL patterns: confirmation threshold now includes the ATR buffer (fix 3); none changed status.

## Staging verification (after #140 merged → b33ceff, backend deploy succeeded 06:08Z)
```
$ STAGING_COOKIE_HEADER=<0600 file> python -m research.charting.tools.verify_staging_api
PASS  TC-2   HTTP 200; served config_hash 05167d3ae57f vs local 05167d3ae57f; fixture=False
PASS  TC-3   HTTP 200; 50 symbols served vs 50 in the committed manifest
PASS  TC-4   RELIANCE / TCS / HDFCBANK: HTTP 200; 1417 bars, ascending+unique=True, identical to committed snapshot=True
PASS  TC-5   HTTP 404 'unknown_symbol | RES-001 | NOT_FOUND'
PASS  TC-6   lowercase → 422; 40 chars → 422
PASS  TC-8   ids filter → ['rsi_14', 'sma_20']; unknown id → HTTP 400
PASS  TC-9   sma_20 @ 2026-09-18: served 1284.705000 vs independent 1284.705000
PASS  TC-10  HTTP 200; 16 patterns served vs 16 in the committed manifest
PASS  TC-11/12/14 + cleanup: drawing created (201), listed, invalid → 422, deleted (200) then 404
PASS  TC-24  RELIANCE / TCS / HDFCBANK: 1417 raw rows vs 1417 served, mismatches 0
NOT TESTED  TC-1, TC-13 (need a non-allowlisted / second account; covered by the local TestClient suite)
17/17 checks passed

$ STAGING_SESSION_FILE=<0600 file> npx playwright test e2e/tests/staging-research-charts.spec.ts
  5 passed (16.9s)     # auth setup + TC-15/16/17/21, TC-18, TC-19, TC-23 in a real browser

$ (data check: every symbol's /patterns from the staging API)
staging API: 50 symbols, 513 patterns, follow-through rules with band 110, patterns with RETEST_SUCCESSFUL 37
expected from local snapshot: 50 symbols, 513 patterns, 110, 37
```
Also read on the VM: the staging backend container's snapshot manifest has config_hash 05167d3ae57f; prod mongo/backend were not
restarted by the deploy. Session token files deleted after the run.

## Verdict: PASS
