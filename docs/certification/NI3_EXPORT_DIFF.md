# NI-3 export diff — baseline vs `--include-ni3`

Generated 2026-09-23 from the frozen Kite daily dataset (`research/kite_history/day_2021`).
Both snapshots built from **identical bars, identical configuration, identical detector versions**;
the only difference is which detectors the exporter invoked.

```
baseline : python3 -m research.charting.export --top-n 50 --with-patterns
ni3      : python3 -m research.charting.export --top-n 50 --include-ni3
```

## Result

```
NI-3 EXPORT DIFF
----------------------------------------------------------
symbols:              50
baseline patterns:    513
ni3 patterns:         679
NI-3 additions:       166

by family:
  DOUBLE_BOTTOM                59      BULL_PENNANT                 15
  DOUBLE_TOP                   58      HEAD_AND_SHOULDERS            8
  INVERSE_HEAD_AND_SHOULDERS    7      BULL_FLAG                     5
  FALLING_WEDGE                 5      DESCENDING_CHANNEL            3
  SYMMETRICAL_TRIANGLE          3      ASCENDING_TRIANGLE            1
  DESCENDING_TRIANGLE           1      RISING_WEDGE                  1

existing records modified:   0     <- required 0
existing records removed:    0     <- required 0
P0 records among additions:  0     <- required 0

same bars, same config, export switch only — all required 0:
  bars differ:                 0
  indicators differ:           0
  timeframes differ:           0
  data-quality / PIT differ:   0
  validation findings differ:  0
```

**The strong test passes.** The delta is *only* NI-3 family records plus their explicitly required
provenance. No existing pattern changed, none was deleted, and no indicator, level, bar, timeframe
or data-quality value moved because the new detectors were invoked.

## Provenance

| Field | baseline | `--include-ni3` |
|---|---|---|
| `export_mode` | `p0_certified` | `ni3_experimental` |
| `include_ni3` | `false` | `true` |
| `ni3_version` | `null` | `1.0` |
| `ni3_fingerprint` | `null` | `de86626c…` (verified on load) |
| `detector_families` | 3 | 19 |
| `config_hash` | `05167d3a…` | **same** |
| `indicator_catalogue_hash` | `6c263d64…` | **same** |
| **`pattern_registry_hash`** | `46222052…` | **same** |
| `data cutoff` | 2026-09-18 | **same** |

`pattern_registry_hash` being identical is the point: **the registry was not changed to produce this
snapshot.** `--include-ni3` is an export-selection switch, not enablement. The registry remains
3 enabled / 16 disabled in both runs.

## Four families produced nothing — **at the last bar** (corrected 2026-09-23)

`ASCENDING_CHANNEL`, `BEAR_FLAG`, `BEAR_PENNANT`, `CUP_AND_HANDLE` had no record at any symbol's
last bar. **This is a snapshot observation, not a coverage claim.** The earlier wording of this
section read it as "the detector never emits them", which was wrong: a last-bar export measures
*pattern state at one point in time*, while replay measures *detector occurrence over time*.

Replay certification over the same 12 symbols (post-sealed bars, 80-bar windows) shows three of the
four do occur:

| Family | Last-bar snapshot | Replay (12 × 80 bars) |
|---|---|---|
| ASCENDING_CHANNEL | 0 | **5** |
| BEAR_FLAG | 0 | **1** |
| CUP_AND_HANDLE | 0 | **5** |
| BEAR_PENNANT | 0 | 0 |

The defensible statement is: **14 of 16 NI-3 families were observed during replay; `BEAR_PENNANT`
was not observed in this sample.** Even that is scoped to 12 symbols × 80-bar windows — it is not a
statement about universal detector coverage, and a family can pass its frozen fixtures and still
not occur in a given window.

The bear-side and cup & handle zeroes remain study-v2 observations, unchanged.

## Data limitation, stated not worked around

The dataset's last bar is **2026-09-18**, five sessions stale. That is deliberate: this comparison
establishes *integration correctness on a frozen, reproducible dataset*. Operational behaviour on
current bars is a separate exercise, and mixing the two would make it impossible to tell whether a
difference came from the code or from five more sessions.

## What this does and does not establish

**Does:** invoking the sixteen NI-3 detectors inside the exporter changes nothing except adding
their own records, with traceable provenance.

**Does not:** that any family may be enabled. Still outstanding — replay validation, study plan v2
(DRAFT, never run), no-look-ahead verification at export scale, and certification sign-off.
