# Test report — charting: stop/target outcomes, trend classes, research states, pre-registration v1.0

Date: 2026-09-22 · Base: origin/dev ff52ce9a (#141) · Decisions #88–#95

## Scope
Research code and documents only — no `backend/`, `frontend-v5/` or snapshot change (no staging surface; the backend deploy
workflow triggers only on `backend/**`).
- `research/charting/events/`: §37.2–§37.4 — structural + 0.75×ATR stops (with an `entry_beyond_structural_stop` flag),
  targets 2/3/5/10% and 1–3R, per-target/horizon target/stop/both/neither + first exit + AMBIGUOUS, gap fills, exit returns
  gross and net, BEARISH rows INFORMATIONAL / AVOID_NEW_LONG with no trade; old hit_high/hit_close labels removed (schema v2).
- `research/charting/regime.py`: §37.1 trend classes (20-session OLS slope + ADX) for stocks and NIFTY 500 (FEATURE_VERSION 1.1.0).
- `research/charting/states.py`, `enrich.py`: §37.6 research_state in a separate, non-mutating enrichment record.
- `docs/charting.md` §37 (owner baseline v1.1), `docs/ai_research/CHARTING_PREREGISTRATION_V1.md` (frozen, sha256 fed94bca…).

## Test cases
| TC | What | How | Result |
|---|---|---|---|
| TC-50 | Stops/targets/labels equal an independent walker on real rows | script below (RELIANCE + TCS pre-sealed) | PASS |
| TC-51 | Walk reads only its own horizon; peeking control detects a leak | `test_events_lookahead.py` | PASS |
| TC-52 | Hand-computed walks: target first, stop first, AMBIGUOUS, gaps, neither, Layer 2 widening, entry beyond structural stop | `test_events_stops.py` | PASS |
| TC-53 | Trend slope equals numpy.polyfit on real data; class boundaries; sealed-bar poison moves nothing | `test_regime_trend_classification.py` + script | PASS |
| TC-54 | research_state follows the owner's flow (close beyond level = BREAKOUT_CANDIDATE, + volume PASS = CONFIRMED_BREAKOUT; COMPLETED only from outcomes) | `test_states.py` | PASS |
| TC-55 | Enrichment never mutates the production pattern; patterns.py output unchanged on 50 symbols | `test_enrich.py` + agent diff (0 diffs, validated) | PASS |

## Real output (this session)
```
$ pytest research/charting/tests research/costs/tests research/index_history/tests -q
1033 passed in 42.71s

$ (TC-50: independent walker — counts only, no outcome statistics)
rows: 175 (RELIANCE+TCS pre-sealed)
  stop value         match  129  mismatch 0
  first_exit_event   match  516  mismatch 0
  exit session       match  331  mismatch 0
  exit price         match  331  mismatch 0
  bearish no trade   match   41  mismatch 0

$ (TC-53)
2022-06-30 slope -0.5839 = numpy -0.5839 SIDEWAYS · 2022-11-30 +0.1966 BULL · 2025-01-31 +0.0378 SIDEWAYS ·
2025-06-30 +0.2457 BULL · 2026-09-18 -0.3060 BEAR (5/5 equal); post-sealed values moved by sealed-bar poison: []

$ (TC-54: research_state on the 50 display symbols)
CONFIRMED_BREAKOUT 45, BREAKOUT_CANDIDATE 216, EARLY_SIGNAL 158, FAILED_BREAKOUT 92, unmapped 2 (INVALIDATED; owner decision #95)
```

## Verdict: PASS
Local and data checks cover the whole change; there is no staging surface to verify.
