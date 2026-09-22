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
| TC-39 | Staging: API 17/17 and UI 4/4 against the re-exported snapshot | `tools/verify_staging_api.py`, `staging-research-charts.spec.ts` | **PENDING** — needs the owner's merge + deploy and a fresh session token |

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

## Verdict
Local and data checks pass. TC-39 (staging) cannot run until the PR is merged and deployed; see
`OVERRIDE_charting_fixes_costs_context.md`. This report is updated to PASS after staging verification.

Clean-export check: the commit's `research/` + `backend/nidp` extracted outside git ran 748 passed, 12 skipped before the golden
file was added (the 12 were the git-show reproduction tests); the pinned golden outputs now cover that case in any clone.
