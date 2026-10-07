# Test report — charting: candle/retest quality moved to the research record (CANDLE-MOVE)

Date: 2026-09-22 · Branch: fix/charting-symbols-contract (worktree `.claude/worktrees/charting`)
Owner decision: `docs/charting.md` §38.18 decisions-log #93/#110 — "Candle/retest metrics —
ACCEPT. They move from the production pattern record into the research record." (§37.6:
research enrichment never mutates the production pattern result; research fields live in a
separate enrichment record keyed by `pattern_id`, `research/charting/enrich.py`.)

## Scope
- `research/charting/patterns.py`: no longer emits `body_pct`/`close_location` (on the
  PRICE_CONFIRMED event's `observed_values`) or the pattern-level `retest_quality` block.
  `_walk_retest_and_failure` is back to deciding only `LifecycleState` (no quality
  bookkeeping); every other computation (statuses, events, rules, levels, pivots, scores,
  `config_hash`) is untouched — the 2026-09-22 performance optimizations in this file are
  preserved as-is.
- `research/charting/enrich.py`: `enrich_pattern(...)` now also returns `candle_quality`
  ({body_pct, close_location} of the confirming bar) and `retest_quality` (attempts,
  penetration_atr, penetration_pct, retest_relative_volume, bars_confirmation_to_retest,
  bars_retest_to_continuation, note) — the SAME formulas patterns.py used to compute,
  relocated (not reduced), computed point-in-time from the pattern dict's own
  `levels`/`direction`/`pattern_type`/events + `bars <= t`, never mutating the input dict.
- `research/charting/SNAPSHOT_SCHEMA.md`: pattern-object example no longer shows these
  fields; a new paragraph says where they live now.
- `backend/services/research_chart_snapshot/`: re-exported and installed (data only — no
  route/service/frontend code touched).
- Tests: `test_patterns_retest_quality.py` rewritten (same hand-computed fixtures, now
  asserting on `enrich_pattern`'s output instead of `detect_as_of`'s), `test_patterns_lookahead.py`'s
  candle/retest poisoned-future probe + negative control repointed at the enrichment layer,
  `test_patterns.py`'s documented-shape test updated (no more `retest_quality` key),
  `test_patterns_retest_quality.py` gained a dedicated non-mutation test and an explicit
  "production record no longer carries these fields" test.

## Test cases
| TC | What | How | Result |
|---|---|---|---|
| TC-90 | Production `detect_as_of` output no longer carries `retest_quality`, `body_pct`, `close_location` anywhere | `test_production_pattern_no_longer_carries_the_moved_fields`, `test_pattern_snapshot_matches_documented_shape` | PASS |
| TC-91 | `enrich_pattern`'s `candle_quality`/`retest_quality` are hand-computed-correct (RECTANGLE zero-range/doji/normal candle; no-retest/false-breakout/failed-retest/2-attempt-success retest; SUPPORT_RESISTANCE and HH_HL families) — same fixtures, same expected numbers as pre-move | `test_patterns_retest_quality.py` (20 cases) | PASS |
| TC-92 | Poisoned-future probe: `candle_quality`/`retest_quality` from `enrich_pattern` unaffected by bars dated after `t`, across 5 t-values × 2 poison shapes (mid-retest through resolution) | `test_new_descriptive_fields_unaffected_by_poisoning_the_future` | PASS |
| TC-93 | Negative control: a naive whole-frame `attempts` counter DOES see the leak (2 vs 1); the real enrichment does not | `test_negative_control_peeking_attempts_count_is_detected_by_the_same_probe` | PASS |
| TC-94 | `enrich_pattern` never mutates `pattern_dict` when computing `candle_quality`/`retest_quality`, proven on a fixture that actually exercises the retest walk (2 attempts) | `test_enrich_does_not_mutate_pattern_dict_when_computing_candle_and_retest_quality` (+ existing `test_enrich.py` non-mutation tests) | PASS |
| TC-95 | New fields are strict-JSON-safe (no NaN/Infinity) across 6 fixture shapes | `test_new_fields_are_json_safe_no_nan_or_infinity` | PASS |
| TC-96 | Full `research/charting` unit suite green after the move | `pytest research/charting/tests -q` | PASS |
| TC-97 | Backend chart-serving tests green (route/service layer never imports `enrich.py`; unaffected) | `pytest backend/tests/test_research_chart.py test_research_drawings.py test_charting_feature_flag.py -q` | PASS |
| TC-98 | Re-exported snapshot vs the pre-move (candle/retest-carrying) snapshot: ONLY the 3 removed keys differ (+ `generated_at`/`run_id`/sha256 run metadata); pattern/event/rule/level/pivot counts identical | diff script (below) over all 50 committed symbols | PASS |
| TC-99 | Re-exported snapshot's pattern content is BYTE-IDENTICAL to the PR #140 snapshot (`b33cefffef`, before candle/retest fields ever existed) | diff script (below) over all 50 symbols | PASS |
| TC-100 | New snapshot installed under `backend/services/research_chart_snapshot/`, all 50 symbol files gzip-valid, served fields confirmed absent | manual gzip + field check (below) | PASS |
| TC-101 | Staging: served snapshot/API/UI reflect the field removal | — | **PENDING** — see OVERRIDE |

## Real output (this session)

```
$ cd research/charting && PYTHONPATH=<repo root> python -m pytest research/charting/tests/test_patterns_retest_quality.py research/charting/tests/test_patterns_lookahead.py research/charting/tests/test_enrich.py research/charting/tests/test_patterns.py -q
........................................................................ [ 76%]
......................                                                   [100%]
94 passed in 6.59s

$ PYTHONPATH=. python -m pytest research/charting/tests/ -q
........................................................................ [ 84%]
........................................................................ [ 91%]
........................................................................ [ 99%]
..........                                                               [100%]
1018 passed, 2 warnings in 193.68s (0:03:13)

$ cd backend && MONGO_URL=mongodb://127.0.0.1:1 DB_NAME=test_charting python -m pytest tests/test_research_chart.py tests/test_research_drawings.py tests/test_charting_feature_flag.py -q
......................................                                  [100%]
38 passed in 3.90s
```

### TC-98 / TC-99: snapshot diff (real output, this session)

Re-exported via `python -m research.charting.export --with-patterns --out-dir <tmp>` (config_hash
`05167d3ae57f18602b8761ee21de311f5ffb96c428a16df5c119678a748514cf` — unchanged, `config.py` was
not touched), 50 symbols, 513 patterns, then diffed decompressed JSON of every symbol's `patterns`
array, field by field, against (a) the on-disk snapshot as it stood before this change (candle/retest
fields present) and (b) `git show b33cefffef:backend/services/research_chart_snapshot/...` (PR #140,
merged before candle/retest fields were ever added):

```
=== new vs worktree-committed (pre-move, candle/retest-carrying) ===
symbols compared: 50
total pattern-level field diffs: 1219
distinct differing field names: ['body_pct', 'close_location', 'retest_quality']
example diffs:
  ADANIENT.json.gz[0] pattern_id=ADANIENT:SUPPORT_RESISTANCE:2025-08-20:2283.27.events[0].observed_values.body_pct: '<MISSING_IN_A>' vs 'PRESENT_IN_B'
  ADANIENT.json.gz[0] pattern_id=ADANIENT:SUPPORT_RESISTANCE:2025-08-20:2283.27.events[0].observed_values.close_location: '<MISSING_IN_A>' vs 'PRESENT_IN_B'
  ADANIENT.json.gz[0] pattern_id=ADANIENT:SUPPORT_RESISTANCE:2025-08-20:2283.27.retest_quality: '<MISSING_IN_A>' vs 'PRESENT_IN_B'
  ... (1219 total, all body_pct / close_location / retest_quality)

=== new vs PR140 (b33cefffef) ===
symbols compared: 50
total pattern-level field diffs: 0
distinct differing field names: []

manifest top-level diffs (both comparisons): generated_at, run_id only (config_hash, n_patterns
per symbol, and every other manifest field identical)
```

### TC-100: install + integrity (real output, this session)

```
$ cp <tmp>/manifest.json backend/services/research_chart_snapshot/manifest.json
$ cp <tmp>/symbols/*.json.gz backend/services/research_chart_snapshot/symbols/
$ for f in backend/services/research_chart_snapshot/symbols/*.json.gz; do gzip -t "$f" || echo CORRUPT; done
(no output -- all 50 files gzip-valid)

$ python -c "import gzip,json; d=json.load(gzip.open('backend/services/research_chart_snapshot/symbols/RELIANCE.json.gz','rt')); \
             pats=d['patterns']; print(len(pats), 'retest_quality' in pats[0]); \
             ev=[e for p in pats for e in p['events'] if e['event_type']=='PRICE_CONFIRMED']; print(sorted(ev[0]['observed_values']))"
16 False
['breakdown_level', 'close']
```

## Data Correctness
The only data path affected is the committed snapshot under `backend/services/research_chart_snapshot/`
(offline, exported by `research/charting/export.py`; no DB/API write path exists here). Its
content is proven identical to the PR #140 baseline (TC-99) and to differ from the immediately
prior on-disk state by exactly the 3 fields this task removes (TC-98) — both real, this-session
diffs over all 50 committed symbols, not a sample.

## Inputs required from user
- A staging session token, and the owner merging + deploying this change, to run
  `research.charting.tools.verify_staging_api` and the staging Playwright spec against the
  live served snapshot (TC-101). See OVERRIDE.

## Verdict: BLOCKED
<!-- Every local/data check (TC-90..TC-100) is a real, evidenced PASS. Verdict stays BLOCKED,
     not PASS, solely because TC-101 (staging) cannot run until the owner merges and deploys
     this backend-snapshot change and provides a session token -- see
     OVERRIDE_charting_candle_retest_research_record.md. -->
