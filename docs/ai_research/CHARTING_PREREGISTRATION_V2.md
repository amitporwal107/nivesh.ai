# Pre-registration v2.0 — New chart-pattern families and the large-swing layer

**Status: DRAFT — awaiting owner approval.**
- **When it freezes:** once approved, exactly like v1, before any outcome statistic for these families is computed.
  Later changes are new versions (v2.1, …), never edits.
- **Relationship to v1:** v1 (`CHARTING_PREREGISTRATION_V1.md`, sha256 `fed94bca…`) is frozen and unchanged. It covers
  the three live families at the small (3/3) swing scale. v2 covers everything else. v1 and v2 results are reported
  separately and never pooled.
- **Principle (owner, #110):** freeze → detect → evaluate → report everything → interpret.

---

## 1. Question, and what counts as a pass

**Question.** The same question as v1, for the new families and the large-swing layer:
- Do these detected chart patterns carry information about the subsequent price path beyond what volatility and a
  random pick from the same universe already carry, after realistic trading costs?
- The patterns are 16 new types at two swing scales, plus the three live families at the large scale.

**A negative result is a pass.** The study passes when every cell listed in §7 is present, correctly computed and
reproducible. No type, scale, direction, horizon or segment is dropped for being unfavourable.

## 2. Frozen configuration

| Item | Frozen value | Where it lives |
|---|---|---|
| New-family detector configuration | NI-3 v1.0 fingerprint **`de86626c6f15e5f2d41708e92f8b66367394eb1c8e52ed2534ecfd8e0ded44a8`** | `docs/ai_research/charting_ni3_config_v1.json`; table `CHARTING_NI3_PREDICATES_V1.md` |
| Live families at the large scale | config_hash **`9b81eae7725188cc3652b390666ce17d7db3d7afbd2a9486754fa036e54751c4`**: the v1 config (`05167d3a…`) with swings 8/8 and lengths 40/260 | `research/charting/config.py` + the overrides in NI-3 §8 |
| Research features | as v1 (§37.1 trend classes, regime, RS, VIX, breadth); `FEATURE_CONFIG` hash recorded at run | `research/charting/regime.py` |
| Costs | as v1: `nse-equity-statutory-v1`, NSE delivery, brokerage 0%, DP charge on, ₹1,00,000 notional per event | `research/costs/` |
| Tax | as v1: Series B separate, `tax-equity-v1` | `research/costs/tax.py` |

**Run validity.** The run is invalid under this document if either detector fingerprint at run time differs from the
values above.

## 3. Data, universe and windows

Everything is as in v1 §3:
- **Bars:** Kite daily 2021-01-01 → 2026-09-18.
- **Universe:** the same 2,132-symbol universe, with the sealed-ETF-list caveat disclosed.
- **Benchmark:** NIFTY 500.
- **Demergers:** as v1 (T−5..T+5 excluded, histories never spliced).
- **Data quality:** events with a FAIL status are excluded and counted.

The same two development segments, analysed and reported separately:
- **Pre-sealed:** 2021-01-01 → 2022-12-30.
- **Post-sealed:** 2024-08-01 → 2026-09-18. No sealed bar is used as lookback, as a feature input or as a forward bar.

**The sealed window 2023-01-01 → 2024-07-31 is not touched.** Spending it needs its own later pre-registration.

**Coverage disclosure (not corrected).** Large-scale patterns and cups can need up to 260 bars of history. In each
segment, the first months can only produce short patterns, so long-pattern counts start late. This is reported as
coverage per type and scale. Nothing is back-filled across the sealed window.

## 4. Unit of observation and population

**One row per pattern instance at its price-confirmation bar `t`.** For the new types, that is the
BREAKOUT_CANDIDATE transition (close beyond the live level by 0.5%) in the point-in-time replay. This mirrors v1's
PRICE_CONFIRMED row.
- **Volume subset:** the owner's volume rule (breakout bar ≥ 1.5× the 20-session average, i.e. CONFIRMED_BREAKOUT) is
  a pre-declared subset reported alongside the full population (item V-1).
- **Other events:** failures, retests and expiries are properties of the row.

**Direction.**
- **Bullish types are long-actionable:** ascending triangle, falling wedge, double bottom, inverse H&S, cup & handle,
  bull flag, bull pennant, and bullish breaks of the symmetrical triangle and both channels.
- **Bearish types are INFORMATIONAL / AVOID_NEW_LONG (§37.4):** descending triangle, rising wedge, double top, H&S,
  bear flag, bear pennant, and bearish breaks of the symmetrical triangle and both channels. No short is priced.

**Patterns that never produce a row are still counted,** per type × scale × segment:
- NOT_TRIGGERED (invalidated or expired before any breakout) and INCONCLUSIVE (data-blocked or unresolved), by reason
  code.
- `SHAPE_UNCLASSIFIED`, `SHAPE_EXPANDING_OUT_OF_SCOPE` and `SHAPE_CHANGED`.

**Scales and overlaps.** Small-scale and large-scale rows are separate populations. Rows linked across scales, or to a
live-family pattern, are flagged and counted, and never merged or pooled.

**The live families at the small scale are not rows in v2.** They are v1's population.

## 5. Entry, stops and targets

- **Entry:** the open of bar t+1 (primary). The close of bar t is a labelled alternative, never the headline.
- **Initial stop:** the NI-3 Layer-1 structural stop for the type, then widened so that entry − stop ≥ 0.75 × ATR(14).
  R = entry − stop.
- **H&S and inverse H&S:** both stop variants are computed for every row. The primary is the right-shoulder stop; the
  secondary is the neckline stop. Both are reported in full, and the primary is never swapped for the one that looks
  better.
- **Targets:** +2 / +3 / +5 / +10% and 1 / 1.5 / 2 / 3 R.
- **Fills and ambiguity:** as v1. A gap beyond the stop or target fills at the open. If both are inside one daily bar,
  the outcome is AMBIGUOUS.
- **Controls:** the random and buy-at-next-open controls use the 0.75 × ATR stop with the same targets (as v1).

## 6. Outcomes per row

**As v1 §6:**
- **Horizons:** 1, 3, 5, 10 and 20 sessions.
- **Path measures:** forward returns, MFE and MAE, and bars to +2 / +5 / +10 / +15%.
- **Per target:** hit, stop, both, neither, first exit and holding period.
- **Returns:** gross and net under the four slippage scenarios (base 0.15% primary) and the liquidity-bucket model;
  Series B separately.
- **Context at t:** as v1.

**Added (NI-3 §1.6 research metadata):**
- `breakout_threshold_atr` and `followthrough_rel_volume`
- `persistence_break_3c`
- `extreme_diff_pct_of_height` (double top/bottom)
- candle and retest quality
- `scale` and `linked_pattern_id`

**Bearish rows (as v1 §7 item 8):** directional forward returns, MFE/MAE, and whether the invalidation level was
reached within each horizon. For H&S, both the primary and the secondary level are reported.

## 7. What the report must contain — every cell, whatever the sign

**The cells are:** type × direction × scale × segment × horizon, and × target and × stop variant where those apply.
The measures in each cell are those of v1 §7 items 1–10, including every comparison group, the segmentations and the
cost sensitivity. The `n < 30` rule is as v1: shown with its n, marked `insufficient_n`, never dropped, and never used
for a conclusion.

**Every combination tested:**

| Level | Count | How |
|---|---:|---|
| Type-direction units per scale | 19 | 7 bullish-only + 6 bearish-only + 3 either-direction types × 2 directions |
| … across both scales | 38 | × 2 |
| **Headline cells (new types)** | **380** | × 2 segments × 5 horizons |
| Target-level cells (long-actionable) | 1,600 | 10 bullish units × 2 scales × 2 segments × 5 horizons × 8 targets |
| + inverse H&S secondary stop | 160 | 1 × 2 × 2 × 5 × 8 |
| **Target-level cells (new types)** | **1,760** | |
| Live families at the large scale | per v1's direction split | listed exactly in the cell manifest |

**Cell manifest.** Before any outcome is computed, the complete cell list is generated from this document, and its
sha256 is written into the run manifest. The report must contain every listed cell.

**Chance findings.** With 380 headline cells, about 19 would clear a 5% threshold by chance alone even if no pattern
carried any information. Claims therefore follow the rule in item V-2. Every cell is still shown.

## 8. Integrity rules the run must pass before any number is reported

- **As v1 §8:** the kill switch (identical `pattern_id` sets and event sha256 across two runs), the point-in-time and
  sealed-window poison probes with their negative controls, and an independent recomputation sample with zero
  mismatches.
- **Fingerprints:** the detector reproduces `de86626c…` and `9b81eae7…` from its own configuration.
- **Sloped-line look-ahead probe:** a pivot confirmed after `t` must not move `trendline_value_at(t)` or any bar-`t`
  state.
- **No-repaint test:** a type change emits `SHAPE_CHANGED` and a new pattern. The earlier pattern's recorded geometry is
  byte-identical before and after.
- **Scale-link determinism:** the same inputs produce the same `linked_pattern_id` pairs.
- **Cell manifest:** the hash in the manifest matches the cell list regenerated from this document, and every listed
  cell appears in the report.

## 9. Capability status at drafting (2026-09-22)

| Needed for the run | State |
|---|---|
| `trendline_value_at` (sloped-line helper) | not built |
| P-1 geometry engine, P-2 flags/pennants | not built |
| Double top/bottom, H&S, inverse H&S, cup & handle detectors | not built |
| Large-swing layer (all families) and scale linking | not built |
| NOT_TRIGGERED / INCONCLUSIVE mapping; candle/retest moved to the research record | not built |
| Event extraction, controls, report generator and cell manifest generalised to the new types | not built (v1 tooling exists for the live families) |
| Costs, index data, breadth, sealed guards, demerger regimes | built and verified (v1) |

The study runs only after every row is built and verified (steps 5–6). That timing does not change this document.

## 10. Not in v2

- Early-signal scores (§34) for the new types: a later version.
- Sloping S/R (P-5, deferred).
- Expanding shapes (NI-3 Q2).
- The live families at the small scale (v1).
- The sealed window.
- Intraday timeframes.

## 11. Choices in this draft that need the owner's approval

| # | Choice | Recommendation and reason |
|---|---|---|
| V-1 | The row bar is price confirmation, with the ≥ 1.5× volume-confirmed rows as a pre-declared subset. | **As drafted.** It matches v1's row definition, so old and new types stay comparable, and the owner's volume rule is still reported in full as its own subset. |
| V-2 | Claim rule: a type × direction × scale "carries information" only if, at the same horizon, its net result is above the 95th percentile of **both** the random and ATR-decile controls in **both** development segments. Benjamini–Hochberg q-values (q = 0.10) across the headline cells are reported alongside. | **As drafted.** Replication across two independent periods is the main guard against the ~19 chance findings. The q-values show the multiple-testing picture without being the only gate. |
| V-3 | Random-control seeds: **1,000** (v1 uses 200). | **1,000.** With 200 seeds, the smallest possible empirical p is about 0.005, too coarse for 380 cells. 1,000 seeds reach about 0.001, at about 5× the random-control compute. |
| V-4 | Bearish rows: directional returns, MFE/MAE, and invalidation-reached for every stop variant, with no priced trade. | **As drafted.** This is v1's treatment, plus both H&S levels as the owner asked. |
| V-5 | Short early history in each segment is disclosed as coverage, not corrected. | **As drafted.** Correcting it would need bars from the sealed window or a changed method. |
