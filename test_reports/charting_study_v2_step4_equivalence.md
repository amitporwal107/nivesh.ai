# Functionality Verification Report — study-v2 storage redesign, Step 4 (equivalence)

- **Branch:** feat/charting-indicator-catalogue (worktree) → PR from `feat/charting-study-v2-step4-equivalence`
- **Date:** 2026-09-23
- **Author:** Claude (full-stack developer + QA engineer)
- **Environment:** local research suite. **No product code touched** — `research/` only.
- **Changed areas:** backend routes/services: **no** · frontend src: **no**

## Summary

Step 4 of `docs/ai_research/CHARTING_STUDY_V2_STORAGE_REDESIGN.md`: prove that the accumulator
reproduces the row-level calculation before anything stops being written.

The invariant the owner specified — same seeds, same input rows, same config, same outcome
calculation, down two paths:

```
rows ──> report.comparison_block(...)                                      (existing)
rows ──> accumulate.group_summary(...) ──> comparison_block_from_summaries(...)   (new)
```

The test compares the **final comparison block**, not intermediate counters, across every horizon
(1/3/5/10/20) × every cost scenario (optimistic/base/conservative/stress), and again as serialised
JSON bytes.

**Floating-point tolerance: none. The assertion is exact equality**, and that is a design property
rather than luck — a seed's summary holds `report.return_stats`' own output, computed in memory while
that seed's rows exist, not a running sum that would have to be re-averaged. `statistics.fmean` is
exactly rounded, so re-deriving a mean from stored sums would differ in the last bits; storing the
statistic avoids the question. The raw sums are kept alongside as pooling insurance, with a docstring
stating plainly that they reconstruct a pooled mean only to within float rounding and that nothing
the report prints comes from them.

Owner decisions implemented: **S-1** the wider accumulator (hit rates, segmentation and all four cost
scenarios for the comparison groups), **S-2** context segmentation reported as an explicit
`UNAVAILABLE / CONTROL_CONTEXT_NOT_GENERATED`, **S-3** the ambiguity legs preserved. The
sealed-window gate is wired as a per-row hook so it can move inside the generation loop.

## Two fixture defects found and fixed — the tests were passing vacuously

Reported because they are the substance of this step, not a footnote.

1. **The ATR-decile control was empty.** The first fixture used one symbol. The ATR-decile control
   matches *within a signal date*, so with one symbol every event's candidate pool is itself, every
   event is skipped, and the group comes back `[]` — while the equivalence assertions all passed,
   comparing nothing to nothing. Fixed by building a 12-symbol universe that shares a calendar
   (copies scaled by a constant, so ATR%(t) differs and the copies spread across deciles), and by
   adding **non-vacuity guards to the fixture itself** so it refuses to hand over an empty group.
2. **The S-3 ambiguity test asserted `0 == 0`.** The pipeline fixture produces no AMBIGUOUS outcomes,
   so "the legs are preserved" was unproven. Replaced with rows whose `pct_2` block is the **real**
   output of `stops.target_outcome_by_horizon` on the one-bar-both-touched sequence — a genuine
   AMBIGUOUS resolution with really-computed leg costs — and the zero case kept as its own separate,
   honest assertion.
3. **The holding-period median was `None == None`.** This fixture's controls do not resolve within 5
   sessions. Moved to h=10, where they do, with an explicit `sum(hist.values()) > 0` guard.

## Fixture scale (so "non-vacuous" is checkable)

```
pattern events      : 12
random seeds        : 10 | rows/seed: [12]
atr_decile rows     : 9
buy_next_open rows  : 12
priced atr rows @h=5: 9
atr pct_2 h=10  n=9  target_first=9  median_holding_period=6.0

ROW-BASED BLOCK @h=5 (base):
  random n_seeds_with_data: 10 / 10
  mean_of_seed_means      : 1050.4535833333339
  pattern pctile in seeds : 100.0
  atr_decile n            : 9   pctile: 66.66666666666666
  buy_next_open n         : 12  mean net: 1077.7041666666667
```

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-240 | **the gate** | Comparison block from rows == from summaries, every horizon × every scenario | unit | exact equality, 20 combinations | PASS |
| TC-241 | **the gate** | The serialised block is byte-identical (dict equality treats 1 and 1.0 alike) | unit | equal JSON bytes, 5 horizons | PASS |
| TC-242 | negative control | Perturbing one seed's stored mean by 1e-12 makes the gate fail | unit | gate detects it | PASS |
| TC-243 | denominator | A seed that drew nothing is still counted in `n_seeds_total` | unit | `len(summaries) == len(random_batch)` | PASS |
| TC-244 | collapse | The random summary holds the two numbers the report reads, and no per-row vector | unit | `n` + mean net; no `net_vectors` | PASS |
| TC-245 | ATR-decile | The per-row net vector is retained and equals the row-level one | unit | element-wise equal | PASS |
| TC-246 | digest | `rows_digest` equals the sha256 `write_run` would have recorded | unit | equal hash and row count | PASS |
| TC-247 | §8 gate | Every row is offered to the per-row check — not a sample, not only priced rows | unit | check sees all rows; a raising check propagates | PASS |
| TC-248 | §8 gate | The real `assert_no_sealed_rows_in_dataset` runs clean as the hook | unit | no exception | PASS |
| TC-249 | S-1 | All four cost scenarios accumulated, not just base | unit | stats and hit rates keyed by all four | PASS |
| TC-250 | S-1 | Hit rates kept for the comparison groups, equal to the row-level cell | unit | 5 horizons | PASS |
| TC-251 | S-1 | The holding-period histogram reproduces the median **exactly** | unit | asserted at h=10 where exits resolve | PASS |
| TC-252 | S-2 | Context segmentation is an explicit UNAVAILABLE, not a NO_CONTEXT table | unit | `{status, reason}`, no `NO_CONTEXT` key | PASS |
| TC-253 | S-2 | The random control's omitted segmentation is stated, not silently absent | unit | `NOT_COMPUTED` + reason | PASS |
| TC-254 | S-3 | The ambiguity legs survive, on rows that really are AMBIGUOUS | unit | 3/3 ambiguous, target leg positive, stop leg negative | PASS |
| TC-255 | S-3 | The legs are carried through `group_summary`, not just the helper | unit | present in the summary | PASS |
| TC-256 | S-3 | A zero-ambiguity row set reports an honest zero agreeing with the row count | unit | `0 == 0`, asserted separately | PASS |
| TC-257 | artefact | The summary is JSON-serialisable — it replaces `events.jsonl` | unit | round-trips, `allow_nan=False` | PASS |

## Real output

```
$ PYTHONPATH=. /opt/nidp/venv/bin/python -m pytest research/charting/tests/test_study_accumulate.py -q
.............................................                            [100%]
45 passed in 3.29s
```

Full charting research suite — no regressions (1202 before, 1247 after; the 45 are this file):

```
$ PYTHONPATH=. /opt/nidp/venv/bin/python -m pytest research/charting/tests/ -q
1247 passed, 2 warnings in 93.61s (0:01:33)
```

## What this does NOT yet prove

- **UNVERIFIED at scale.** The equivalence holds on a 12-symbol / 10-seed fixture. Step 5 runs it at
  the TC-113 configuration and step 6 at 200 seeds; only then is the row-based path a candidate for
  being switched off, and it stays behind a flag until step 5/6 pass.
- **Nothing is wired into `execute.py` yet**, and no row persistence has been switched off. This
  commit adds a module and its proof; it changes no existing behaviour.
- **The `execute.py` sealed-gate move is designed and tested at the hook level**, not yet applied —
  `group_summary(row_check=...)` is proved to see every row, but `_run_integrity_gate` still gathers
  rows the old way. That lands with the step-5 wiring.

## Verdict: PASS
