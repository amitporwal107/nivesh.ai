# Functionality Verification Report — W2-EXPORT: weekly/monthly bars for the Charts screen

- **Branch:** fix/charting-symbols-contract (worktree `.claude/worktrees/charting`)
- **Date:** 2026-09-22/23
- **Author:** Claude (full-stack developer, package W2-EXPORT)
- **Environment:** local (research venv + `/opt/nidp/venv`); staging PENDING (see OVERRIDE)
- **Changed areas:** backend routes/services: yes (`backend/routes/research_chart.py`,
  `backend/services/research_chart.py`) · frontend src: no

## Summary
PRD `docs/charting.md` §38.7 ("Weekly and monthly (P0, display only)"), §38.12 row W2, §38.13
acceptance criterion 7, §38.11 (`timeframe=1D|1W|1M`). Added `research/charting/resample.py`
(new module: ISO-week and calendar-month OHLCV resampling, trailing-bar `incomplete` flag),
wired it into `research/charting/export.py` so every symbol's committed payload now also carries
`timeframes.1W` / `timeframes.1M` (bars + the same 8 P0 indicators, computed by the SAME
`_INDICATOR_SPECS` / `_compute_indicator_payload` code the daily series uses — never a separate
calculation path), added `timeframe=1D|1W|1M` to `GET .../ohlcv` and `GET .../indicators` in
`backend/routes/research_chart.py` / `backend/services/research_chart.py` (default `1D`, unknown
value → 400 `unknown_timeframe: <value>`), updated `research/charting/SNAPSHOT_SCHEMA.md`, and
re-exported + installed the real 50-symbol snapshot. Pattern detection stays daily-only
(untouched — `research/charting/patterns.py` / `enrich.py` were not touched, per ownership).

## Test Cases
> Authored up front, after the API/schema design above and before implementation.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-120 | resample.py | Weekly bars for real ADANIENT (1,417 daily bars) match an independent pure-Python (no pandas groupby/resample) resample | unit | 0 mismatches, 299 weekly bars | PASS |
| TC-121 | resample.py | Monthly bars for real ADANIENT match the same independent resample | unit | 0 mismatches, 69 monthly bars | PASS |
| TC-122 | resample.py | Weekly + monthly independent match for RELIANCE, TCS, BEL (spans every real 2021-2026 holiday and every February in range) | unit, parametrized ×3 | 0 mismatches | PASS |
| TC-123 | resample.py | Bar counts are sane — spec's own cited figures | unit | ADANIENT: 299 weekly, 69 monthly (exact) | PASS |
| TC-124 | resample.py | Trailing bar is `incomplete=True`; every earlier bar is not | unit | last row only | PASS |
| TC-125 | resample.py | Real holiday (Republic Day, 26 Jan, confirmed absent 2022/23/24) is simply absent; weekly bar aggregates only the 4 real sessions, hand-checked against raw rows | unit, real data | open/close/high/low/volume match hand computation | PASS |
| TC-126 | resample.py | Short month (Feb 2024, leap year, 21 sessions vs Jan's 22) aggregates correctly | unit, real data | matches hand computation | PASS |
| TC-127 | resample.py | Empty input → empty correctly-shaped frame; resampling never mutates the input frame | unit, edge | no mutation, correct columns | PASS |
| TC-128 | resample.py | Hand-built fixture: OHLCV math (open=first/high=max/low=min/close=last/volume=sum), a weekly bar spanning the Jan/Feb boundary, a synthetic "holiday" (skipped weekday) with no placeholder row | unit | every field hand-checked | PASS |
| TC-129 | export.py wiring | Fixture-mode export: every symbol carries `timeframes.1W`/`1M`, 7-wide bar rows, same 8 indicator ids as daily | unit | shapes correct | PASS |
| TC-130 | export.py wiring | Exported weekly/monthly bars for a real symbol equal `resample.py` applied directly to that symbol's daily df | unit, real data | byte-for-byte equal | PASS |
| TC-131 | export.py wiring | Weekly `sma_20` values are independently recomputed from the served weekly bars via `series.sma` (proves the same series code ran on the resampled frame, not a copy of daily) | unit | matches to 1e-9; weekly bar/value set differs from daily's | PASS |
| — | export.py wiring | Determinism: two fixture exports produce byte-identical `timeframes` content | unit | identical | PASS |
| TC-132 | API | `GET .../ohlcv?timeframe=1W\|1M` returns bars equal to `resample.py` applied to the served daily bars; `findings=[]`, `data_quality_status` unchanged | api | match | PASS |
| TC-133 | API | Default (no `timeframe` param) still serves `timeframe:"1D"`, identical to `timeframe=1D` — regression guard | api | identical | PASS |
| TC-134 | API | Unknown `timeframe` → 400 `unknown_timeframe: <value>` on both `/ohlcv` and `/indicators` | api, failure | 400 reason code | PASS |
| TC-135 | API | `GET .../indicators?timeframe=1W` values independently recomputed from served weekly bars; `ids=` filter and unknown-id rejection still work per timeframe | api | match; 400 on bad id | PASS |
| TC-136 | API / snapshot integrity | Snapshot manifest hash covers the new series: a tampered weekly bar (manifest sha256 left stale) → 503 `snapshot_unavailable`, same as a tampered daily bar | api, failure | 503 | PASS |
| TC-137 | API / snapshot integrity | A symbol payload missing `timeframes.1M` fails schema validation → 503 (unit-level, mirrors existing TC-7) | unit, failure | 503 | PASS |
| TC-1..10, 24 | API | Full pre-existing chart-API regression suite | api | unchanged | PASS |
| — | Cross-stack | Mocked UI fixtures still a subset of the real API's (now larger) response shape | api | no invented keys | PASS |
| TC-1xx | Staging | Served API/UI reflect `timeframe=1D\|1W\|1M` on real staging | e2e | — | **PENDING** — see OVERRIDE |

## API / Endpoint Tests
> Staging is not reachable from this worktree (no deploy, no session token — see OVERRIDE). In
> its place: (a) the full pytest suite against a real exported fixture snapshot, and (b) a REAL
> in-process FastAPI `TestClient` call through the actual route file against the ACTUAL installed
> production snapshot on disk (`backend/services/research_chart_snapshot/`) — the same code path
> staging runs, only without a live HTTP server.

```
$ nice -n 19 ionice -c 3 /app/research/tpd3_forward/venv/bin/python -m pytest research/charting/tests -q
........................................................................ [ 83%]
........................................................................ [ 90%]
........................................................................ [ 97%]
..........................                                                [100%]
1034 passed, 2 warnings in 90.34s

$ cd backend && MONGO_URL=mongodb://127.0.0.1:1 DB_NAME=test_charting nice -n 19 ionice -c 3 /opt/nidp/venv/bin/python -m pytest tests/test_research_chart.py tests/test_research_drawings.py tests/test_charting_feature_flag.py -q
............................................                              [100%]
44 passed in 2.41s
```

### Real in-process API call against the ACTUAL installed snapshot (this session)

```python
# backend/, real feature-gate + real router + real installed backend/services/research_chart_snapshot/
r = c.get('/api/research/chart/ADANIENT/ohlcv?timeframe=1W')
# 1W ohlcv status 200
# timeframe 1W  n bars 299
# first ['2021-01-01', 462.4, 478.2, 462.4, 476.2, 5193732.0, False]
# last  ['2026-09-18', 3080.0, 3083.7, 2907.0, 3020.0, 4764125.0, True]

r2 = c.get('/api/research/chart/ADANIENT/ohlcv?timeframe=1M')
# 1M status 200  n bars 69

r3 = c.get('/api/research/chart/ADANIENT/ohlcv')
# default status 200  timeframe 1D  n bars 1417

r4 = c.get('/api/research/chart/ADANIENT/ohlcv?timeframe=5Y')
# unknown timeframe status 400 {'detail': 'unknown_timeframe: 5Y'}

r5 = c.get('/api/research/chart/ADANIENT/indicators?timeframe=1W&ids=sma_20')
# indicators 1W status 200
# [['2021-05-14', 847.555], ['2021-05-21', 887.4949999999999]]
```

## Snapshot re-export + install (real data, this session)

Re-exported via `python -m research.charting.export --with-patterns` (config_hash
`05167d3ae57f18602b8761ee21de311f5ffb96c428a16df5c119678a748514cf` — unchanged, `config.py` was
not touched) to a temp directory, diffed against the on-disk (working-tree) committed snapshot
field-by-field, then installed (host rule: export → temp dir → compare → install → delete temp):

```
same symbol set: True 50 50
total non-timeframes field diffs: 0
by key: {}
all symbols have timeframes key: True
manifest top-level check done (only generated_at/run_id excluded from comparison)
manifest symbol-entry diffs (excl sha256): 0
```

i.e. the re-export is byte-identical to the previously-committed snapshot (bars, indicators,
patterns — still 513 across 50 symbols, findings, statuses, n_bars, config_hash) in every field
except the newly-added `timeframes` key and the expected per-run metadata (`generated_at`,
`run_id`, per-file `sha256`). Patterns work from the parallel W0/CANDLE-MOVE packages is fully
preserved (`--with-patterns` used, matching the current on-disk export invocation).

```
$ for f in backend/services/research_chart_snapshot/symbols/*.json.gz; do gzip -t "$f" || echo CORRUPT; done
(no output -- all 50 files gzip-valid)
$ git status --short backend/services/research_chart_snapshot | wc -l
51   # manifest.json + 50 symbol files
```

## Data Correctness
The only data path affected is the committed snapshot under
`backend/services/research_chart_snapshot/` (offline, exported by `research/charting/export.py`;
no DB/API write path exists here). TC-120..TC-131 prove the weekly/monthly OHLCV values are
correct against code written independently of `resample.py` (pure-Python accumulation, no shared
pandas groupby/resample machinery), against real NSE data including a named real holiday
(Republic Day) and a real short month (February 2024), and that the served indicator values on
those resampled series are genuine recomputations by the same `series.py` functions, not a copy
of the daily series. TC-132/TC-135 repeat the equivalent checks through the actual API layer
against the actual installed snapshot. TC-136 proves the manifest's per-file sha256 (which hashes
the whole gzip file, not just `bars`) already covers `timeframes` — changing a weekly bar without
updating the recorded hash is detected and rejected, exactly like a tampered daily bar.

## Inputs required from user
- A staging session token, and this branch merged + deployed, to run the staging API/UI checks
  (the TC-1xx row above). See `OVERRIDE_charting_w2_weekly_monthly.md`.

## Verdict: BLOCKED
<!-- Every local/data check above (TC-120..TC-137, the full regression suite, the snapshot
     diff, and the real in-process API call against the actual installed snapshot) is a real,
     evidenced PASS. Verdict stays BLOCKED, not PASS, solely because the staging row cannot run
     from this worktree (no deploy, no session token) -- see
     OVERRIDE_charting_w2_weekly_monthly.md, the sanctioned loud skip. -->
