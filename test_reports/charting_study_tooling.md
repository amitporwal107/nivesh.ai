# Test report — charting study tooling (pre-registration §4–§8)

Date: 2026-09-22 · Stacked on #142 (68c3dfac) · Decisions #99

## Scope (research code only — no backend, frontend or snapshot change; no deploy)
- `research/charting/events/controls.py`: ATR-decile-matched control and the 200-seed random control batch (§7.6).
- `research/charting/events/context_join.py`: `context` (regime.features_at) and `research` (enrich.enrich_pattern) blocks per event, at t (§6).
- `research/charting/study/report.py`: every §7 table, `insufficient_n` below 30, strict JSON + Markdown.
- `research/charting/study/run.py`: universe → demerger regimes → both segments → per-event data-quality exclusion → manifest (frozen config_hash check, prereg sha256, feature hash, versions, exclusion accounting).
- `research/charting/study/integrity.py`: kill switch, sealed-row check, independent recomputation (§8).
- Review fixes before any run: demerger regimes are split, never spliced; data quality excludes events, not symbols;
  full trading calendars passed to the demerger mask (the mask fix itself is in #143).

## Test cases
| TC | What | How | Result |
|---|---|---|---|
| TC-56 | ATR-decile and random controls point in time, seeded, same schema | `test_events_atr_decile_control.py` (poisoned-future probes + control) | PASS |
| TC-57 | Context join point in time on the stock and benchmark legs | `test_events_context_join.py` | PASS |
| TC-58 | Report arithmetic hand-checked; n<30 marked, never dropped | `test_study_report.py` | PASS |
| TC-59 | Demerger regimes: split into separate frames, edges trimmed, a mask without the split raises | `test_study_run.py` | PASS |
| TC-60 | Data quality per event: only events whose window holds a hard defect are excluded; clean events of the same symbol kept | `test_study_run.py` | PASS |
| TC-61 | Real-data smoke (SIEMENS, RELIANCE, TCS, post-sealed, demerger hooks on): regimes, kill switch, sealed rows, recomputation | script below | PASS |

## Real output (this session)
```
$ pytest research/charting/tests research/costs/tests research/index_history/tests research/corporate_actions/tests -q
1161 passed in 83.59s

$ (TC-61, counts only — no outcome statistic computed)
frames: ['RELIANCE', 'SIEMENS~r1', 'SIEMENS~r2', 'TCS']
demerger regimes: RELIANCE 1 regime / 0 excluded · SIEMENS 2 regimes / 11 excluded · TCS 1 / 0
SIEMENS~r1 ends 2025-03-27 | SIEMENS~r2 starts 2025-04-17   (ex-date 2025-04-07: T-6 and T+6)
kill switch passed: True | rows 165 (identical pattern ids and event-file sha256 across two builds)
no sealed rows: PASS
independent recomputation (30 rows, horizon 5): signal_date 30/30, bearish_flagged 20/20, entry 10/10, exit_close 10/10,
  close_return 10/10, mfe 10/10, mae 10/10, net_before_tax 10/10 — 0 mismatches
```

## Verdict: PASS
Local and data checks cover the whole change; there is no staging surface.
