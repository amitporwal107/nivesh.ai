# Functionality Verification Report — study-v2 storage redesign, Steps 5–7

- **Branch:** `feat/charting-study-v2-step5-wiring` (stacked on step 4)
- **Date:** 2026-09-23
- **Author:** Claude (full-stack developer + QA engineer)
- **Changed areas:** backend routes/services: **no** · frontend src: **no** · `research/` only

## Summary

Steps 5–7: wire the accumulator into `execute_study` behind a flag, move the §8 sealed-row
assertion inside the generation loop, and **measure** the footprint instead of projecting it.

`execute_study(summarise_controls=False)` is unchanged and remains the default, so the row path
stays re-runnable for comparison exactly as the owner required.

## The step-5 gate

The same study, run twice over identical inputs, once each way, must produce the same `report.json`
**bytes** — asserted per segment, with a guard that refuses to pass if neither segment produced a
report or the report carries no comparison block.

Also asserted: the summarised run writes **no** control `events.jsonl` anywhere; `n_rows_checked` on
the §8 sealed-window gate is **identical** between the two paths; the study manifest records which
output shape was used.

## Headline finding — the first measurement contradicted the projection

**At the fixture's scale the summaries were not smaller (ratio 1.0×).** Reported because it is the
substance of these steps, and because the reason changes the design:

```
ROW PATH   : 1200 random-control rows, 126.23 MB  ->  102.7 KB/row
SUMMARY    :  800 seed summaries,      123.42 MB  ->  150.7 KB/seed  (FIXED, independent of rows)
this fixture draws 1.5 rows/seed -- which is why the ratio is 1.0x
CROSSOVER  : summaries win above 1.5 rows per seed
```

A row's cost is **O(rows per seed)**; a summary's is **fixed per seed**. The fixture happened to sit
exactly on the crossover. At real scale a random-control seed draws `len(bullish)` rows per family,
so the ratio is 95×–950×:

| rows/seed | rows | summary | ratio |
|---|---|---|---|
| 10 | 1.4 MB/seed | 0.147 MB/seed | 9.5× |
| 100 | 14.0 MB/seed | 0.147 MB/seed | 94.9× |
| 1,000 | 139.6 MB/seed | 0.147 MB/seed | 949.2× |

**But the fixed cost is itself the new problem.** At V-3 scale (1,000 seeds × ~40 reporting units ×
2 segments) the per-seed summary projects to **11.43 GB against 9.3 GB free** — the wide accumulator
S-1 asked for does not fit either.

## Where the bytes are (measured, per seed, compact JSON)

```
  hit_rates                     42.4 KB   58.1%
  ambiguity_legs                20.9 KB   28.6%
  stats                          5.7 KB    7.8%
  pooling_terms                  3.1 KB    4.3%
  holding_period_histograms      0.6 KB    0.8%
  digest / segmentation / meta   0.2 KB    0.3%
  TOTAL                         73.0 KB
```

## What was fixed without any decision — encoding only, no field dropped

`indent=2` was doubling the payload, and one file per seed would mean 80,000 files per segment at
V-3. Both are encoding choices:

```
on-disk (indent=2, file per seed) : 149.8 KB/seed
compact JSONL, one line per seed  :  73.4 KB/seed
```

Re-measured end to end after the change:

```
 seeds       mode   wall_s  controls_MB
    50       rows      6.7        31.07
    50  summaries      7.8        16.41
   200       rows     15.8       126.94
   200  summaries     21.0        61.78
```

**V-3 projection: 11.43 GB → 5.60 GB against 9.3 GB free.** It now fits, with thin headroom.

## The decision this surfaces (owner)

`hit_rates` + `ambiguity_legs` are **87%** of a seed summary, and the report reads **neither** from
the random control — it reads `n` and mean net. Dropping them **from the random control's per-seed
summaries only** (keeping them in full for the ATR-decile and buy-next-open groups, which are one
summary per family, not per seed):

| Option | V-3 footprint | Headroom vs 9.3 GB free |
|---|---|---|
| Wide, as S-1 specified (current) | **5.60 GB** | 3.7 GB |
| Narrow random control only | **0.69 GB** | 8.6 GB |

I have **not** made this change: S-1 was an explicit owner decision, and narrowing it is not mine to
do quietly. The cost of choosing "narrow" later is that per-seed hit-rate and ambiguity distributions
for the random control cannot be recovered without regenerating every seed.

## Still unsolved — the other artefact trees

The redesign fixes the random control and buy-next-open. **Pattern events remain row-level by design
(they are the dataset) and TC-113 projects them at ≈24 GB against 9.3 GB free.** Nothing in this work
addresses that, and steps 8–9 will hit it. The obvious lever is gzip on `events.jsonl` — the writer
already produces one byte stream and the manifest already records its sha256 — but that is a separate
change and has not been measured.

## Test Cases

| ID | Scenario | Type | Result |
|----|----------|------|--------|
| TC-260 | Streaming per-seed summaries == batch summaries | unit | PASS |
| TC-261 | The streaming path never assembles more than one seed (spied) | unit | PASS |
| TC-262 | The real sealed gate runs on every streamed control row; counts reconcile | unit | PASS |
| TC-263 | **Step-5 gate:** `report.json` byte-identical with and without summarised controls | e2e | PASS |
| TC-264 | §8 `n_rows_checked` identical both ways; control rows checked at generation > 0 | e2e | PASS |
| TC-265 | The study manifest records `control_output.mode` | e2e | PASS |
| TC-266 | The summarised run writes no control `events.jsonl`; the row path still does | e2e | PASS |

## Real output

```
$ PYTHONPATH=. /opt/nidp/venv/bin/python -m pytest research/charting/tests/ -q
1254 passed, 2 warnings in 102.65s (0:01:42)
```

(1247 before these steps; the 7 new are TC-260..266.)

## UNVERIFIED

- **Not run at TC-113's real universe.** Every number above is from a 6-symbol synthetic universe;
  the 143 KB/row and 24 GB pattern-event figures are TC-113's own measurements, not re-measured here.
  Step 8 needs the real universe, and the pattern-event tree is unresolved before it can run.
- **Wall-clock for a real 1,000-seed run is still unknown.** The summarised path is ~30% slower per
  run at this scale (21.0 s vs 15.8 s at 200 seeds) because it computes statistics the row path
  defers to report time; whether that holds at real scale is unmeasured.

## Verdict: PASS
