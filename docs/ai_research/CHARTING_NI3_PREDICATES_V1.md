# NI-3 v1.0 — Frozen predicate table for the new chart-pattern families

**Status: FROZEN — 2026-09-22.**
- **Approval:** the owner answered "approved" to draft r2 (`.claude/workspace/charting-pattern-engine/ni3-new-family-predicates-r2.md`),
  including the recommended answers to its five open questions (§10). Decisions-log #110–#112; `docs/charting.md` §38.18.
- **Configuration fingerprint:** `de86626c6f15e5f2d41708e92f8b66367394eb1c8e52ed2534ecfd8e0ded44a8`. This is the SHA-256 of the canonical JSON of
  `docs/ai_research/charting_ni3_config_v1.json`, computed the same way as the v1 `config_hash`
  (`json.dumps(sort_keys=True, separators=(",", ":"))`).
- **Detector check:** the detector code must reproduce this fingerprint from its own configuration, or it is not this
  table.
- **Changes:** any change is a new version (v1.1, …) with its own date and reason, never an edit to this file.
- **Principle (owner):** freeze → detect → evaluate → report everything → interpret. No value here is tuned after
  results are seen.

## Tags

| Tag | Meaning |
|---|---|
| **OWNER** | Stated by the owner (quoted from `docs/charting.md` §37 or the #110 decisions). Approval does not reopen it. |
| **FROZEN** | Reused unchanged from the frozen v1 detector configuration (`research/charting/config.py`, config_hash `05167d3ae57f…`). |
| **APPROVED** | Proposed by the orchestrator in draft r2 (with the rationale shown) and approved by the owner on 2026-09-22. |

A row can carry two tags, e.g. "OWNER value, APPROVED application", when the owner gave the number and the application
was proposed and approved. Units: `%` = percent of price, `× ATR` = multiples of ATR(14) at the evaluation bar, bars = daily sessions.
`pct(a, b) = (a − b) / b`.

## What changed from r1

| Owner decision (#110) | Effect on this table |
|---|---|
| P-1 hybrid | r1's three triangle sections (22 numbers, 18 proposed) are replaced by one geometry engine (§2), which also adds rising/falling wedges and ascending/descending channels. The owner's percentage rules decide flatness (1.5%), breakout (0.5%) and volume (1.5×). |
| P-2 | r1's bull/bear flag sections (16 proposed numbers) are replaced by "pole + P-1 shape" (§3), which adds bull/bear pennants. |
| P-3 | New §8: a large-swing layer. |
| P-4, P-6 | New research-metadata fields (§1.6). They never gate a state. |
| Research states | `NOT_TRIGGERED` and `INCONCLUSIVE` added to the research_state mapping (§1.2). |
| Volume | New families gate on breakout-bar volume ≥ 1.5× (OWNER). Today's 3 families are unchanged: follow-through bar at 1.0–4.0×, frozen v1. |
| Candle/retest metrics | For the new families, these live only in the research record from the start (§1.6). |
| Double top/bottom 10 sessions | B1 and P1 are OWNER. |
| H&S stop | Primary is right-shoulder based; the neckline stop is kept as a secondary research variant (§6). |
| Cup up to 260 sessions | C6 is OWNER. |

**Families: 16 pattern types**, up from r1's 9. Every type adds tests to study v2, which must report all of them.

| Group | Types |
|---|---|
| P-1 shapes (§2) | ascending triangle, descending triangle, symmetrical triangle, rising wedge, falling wedge, ascending channel, descending channel |
| P-2 (§3) | bull flag, bear flag, bull pennant, bear pennant |
| Own rules (§4–§7) | double bottom, double top, head & shoulders, inverse head & shoulders (§6b, added by Q1), cup & handle |


---

## 1. Shared mechanics

### 1.1 Point-in-time base (unchanged from r1 §0.1)
- **Confirmed pivots only:** every family is built only from `swings_as_of(bars, t)`. A pivot exists at bar `t` only
  if `confirmed_index = pivot_index + swing_right_bars ≤ t`.
- **Earliest detection:** a pattern is known no earlier than the latest `confirmed_index` among its required pivots.
- **Completed bars only:** a breakout bar's volume and ATR are that bar's completed values (no intrabar confirmation,
  FROZEN).
- **Live readiness measures:** readiness and "percent complete" use the live §34.7.1 definition, never a
  retrospective fraction.
- **No repainting:** once a pattern is recorded as FORMING, later pivots may refine its fitted lines, and each
  refinement is logged as an event. If the refined geometry changes the pattern's type, the pattern ends with reason
  `SHAPE_CHANGED`, and a new pattern starts from that bar. The history is never silently redrawn. (APPROVED;
  Trendoscope's script has repainting off by default for the same reason.)
- **Research enrichment never mutates the production pattern record** (§37.6, owner rule).

### 1.2 States, and the research_state mapping
The lifecycle is unchanged from r1 §0.2: FORMING → EARLY_SIGNAL → BREAKOUT_CANDIDATE → CONFIRMED_BREAKOUT →
FAILED_BREAKOUT / COMPLETED, with INVALIDATED and EXPIRED as the pre-breakout alternatives. research_state is derived
from it:

| Lifecycle outcome | research_state |
|---|---|
| INVALIDATED or EXPIRED before any BREAKOUT_CANDIDATE | **NOT_TRIGGERED** (OWNER, #110) |
| DATA_BLOCKED or UNRESOLVED | **INCONCLUSIVE** (OWNER, #110) |
| All other states | as §37.6 / decisions-log #94 |

The mapping is additive. It applies to today's 3 families' enrichment record as well. It does not change v1's
population, which is confirmed instances only, so none of them is ever NOT_TRIGGERED.

### 1.3 Breakout, failure and volume (the new families only)
```text
Bullish BREAKOUT_CANDIDATE  iff  Close > level(t) × (1 + breakout_threshold_pct)
Bearish BREAKOUT_CANDIDATE  iff  Close < level(t) × (1 − breakout_threshold_pct)
CONFIRMED_BREAKOUT          iff  BREAKOUT_CANDIDATE and breakout-bar volume ≥ 1.5 × 20-session average
FAILED_BREAKOUT             iff  within failure_window_bars a close crosses back beyond level(t) × (1 ∓ failure_threshold_pct)
```
`level(t)` is the live value at bar `t`. For a sloped line it comes from the new helper `trendline_value_at` (r1 C6,
a code gap), fitted only to pivots confirmed by `t`.

### 1.4 Stops (§37.3, OWNER)
- **Layer 1:** the family's structural level (see each section).
- **Layer 2:** at least 0.75 × ATR(14) below entry.
- **Rule:** the stop is whichever layer is farther from entry, i.e. "widened, never tightened".
- **Gaps:** a bar that opens beyond the stop fills at the open.
- **Bearish patterns:** under §37.4 they are INFORMATIONAL / AVOID_NEW_LONG and no short is priced. Their stop is the
  invalidation level and the R for the gross price-path outcomes, not a priced trade.

### 1.5 Targets and entry
- **Targets:** +2 / +3 / +5 / +10% and 1 / 1.5 / 2 / 3 R, with a same-bar double touch labelled AMBIGUOUS (§37.2,
  OWNER).
- **Entry:** the next session's open (FROZEN, v1 pre-registration §5).

### 1.6 Research metadata: stored on every event, never gating
| Field | What it is | Source |
|---|---|---|
| `breakout_threshold_atr` | `abs(Close − level(t)) / ATR` at the breakout bar | §37.7 ("both measures stored") |
| `followthrough_rel_volume` | the follow-through bar's volume / 20-session average (today's families' volume measure, stored for comparison) | OWNER (#110: definitions kept separate, both comparable) |
| `persistence_break_3c` | the date of the first run of 3 consecutive closes beyond the level at any distance, else null | OWNER (P-6) |
| `extreme_diff_pct_of_height` | double top/bottom only: `abs(extreme1 − extreme2) / (extreme level − neckline)` | OWNER (P-4) |
| candle quality, retest quality | as §35.2, research record only | OWNER (#93 → #110) |
| `scale` | `small` (3/3) or `large` (§8) | OWNER (P-3) |
| `linked_pattern_id` | the same structure found at the other scale, or an overlapping live-family pattern (§10 C-A) | APPROVED |

### 1.7 Shared parameters
| # | Name | Value | Tag | Note |
|---|---|---:|---|---|
| S1 | `swing_left_bars` / `swing_right_bars` (small scale) | 3 / 3 | FROZEN | |
| S2 | `atr_period` | 14 | FROZEN | |
| S3 | `volume_baseline_bars` | 20 | FROZEN | |
| S4 | `min_formation_bars` / `max_formation_bars` (small scale) | 15 / 120 | FROZEN | cup & handle overrides (§7); flags use their own bounds (§3) |
| S5 | `breakout_threshold_pct` | 0.5% | OWNER value | §37.7 "× 1.005". By the P-1 hybrid decision it governs every P-1 shape; for §4–§7 it is a APPROVED extension (as in r1) |
| S6 | `failure_threshold_pct` | = S5 | APPROVED | equal to the breakout threshold so states cannot overlap (the NI-2 #5 precedent) |
| S7 | `failure_window_bars` | 5 | FROZEN | |
| S8 | `breakout_volume_ratio_min` | 1.5 × | OWNER | #110: new patterns use the breakout bar at ≥ 1.5× |
| S9 | `readiness_band_pct` | 1.0% | APPROVED | EARLY_SIGNAL when the close is within 1% of the live breakout level (2× the breakout threshold) |
| S10 | `stop_min_distance_atr` | 0.75 | OWNER | §37.3 |

---

## 2. P-1 geometry engine: triangles, wedges, channels

**Method (evaluated at every bar `t`, confirmed pivots only).**
1. Take the most recent confirmed alternating pivots (high, low, high, …). Try `k = 6`, then 5, then 4, and keep the
   largest `k` that passes every check. The longest valid structure wins.
2. Fit an upper line (least squares) through the high pivots and a lower line through the low pivots.
3. **Fit check:** every pivot lies within G3 of its own line.
4. **Containment check:** between the first and last pivot, no close lies beyond either line by more than the
   breakout threshold (S5); wicks are allowed. So the formation holds only while no breakout has happened.
5. **No crossing:** the two lines do not intersect between the first and the last pivot.
6. **Length:** it lies within S4.
7. **Classify** each line and the pair (below), then look up the shape.

**Line direction (hybrid: percentage decides flatness).** A line is **FLAT** if its fitted value changes by ≤ G4
(1.5%) of its starting value across the formation. Otherwise it is **RISING** or **FALLING** by the sign of the
change. One threshold, so there is no gap and no second number.

**Pair.** `w = width at the last pivot / width at the first pivot`, where width = upper line − lower line.

| w | Pair |
|---|---|
| ≤ 0.70 (G5) | converging |
| ≥ 1.43 (G6) | expanding |
| 0.85–1.15 (G7) | parallel |
| anything else | unclassified: rejected, `SHAPE_UNCLASSIFIED` |

**Shape table.**

| Upper | Lower | Pair | Shape | Direction | Opposite-side close before breakout |
|---|---|---|---|---|---|
| FLAT | RISING | converging | ascending triangle | bullish (§13.4) | INVALIDATED (§13.4) |
| FALLING | FLAT | converging | descending triangle | bearish (§13.5) | INVALIDATED (§13.5) |
| FALLING | RISING | converging | symmetrical triangle | set by the side broken (r1 §3) | — (either side is a breakout) |
| RISING | RISING | converging | rising wedge | bearish (§13.10 "breakdown confirms") | INVALIDATED, code `COUNTERTREND_BREAKOUT` (APPROVED) |
| FALLING | FALLING | converging | falling wedge | bullish (§13.10) | INVALIDATED, code `COUNTERTREND_BREAKOUT` (APPROVED) |
| RISING | RISING | parallel | ascending channel | set by the side broken (APPROVED; the PRD is silent) | — |
| FALLING | FALLING | parallel | descending channel | set by the side broken (APPROVED) | — |
| FLAT | FLAT | parallel | not emitted: the live RECTANGLE family covers it | — | — |
| any | any | expanding | not emitted in v2: `SHAPE_EXPANDING_OUT_OF_SCOPE` (§10 Q2) | — | — |

The §13.10 slope conditions, e.g. "support slope greater than resistance slope" for a rising wedge, are exactly what
"both rising and converging" means, so no extra test is needed.

**Expiry.**
- **Converging shapes:** EXPIRED, reason `APEX_REACHED`, if no breakout comes before G13 of the distance from the
  first pivot to the apex. The apex is re-projected at each `t` from confirmed pivots only.
- **Parallel shapes:** EXPIRED at `max_formation_bars` (S4).

**Stops.**
- **Layer 1:** the opposite line's value at the breakout bar. This is OWNER for triangles (§37.3 "triangle at the
  opposite boundary") and a APPROVED extension to wedges and channels.
- **Layer 2:** §1.4.

**Parameters.**

| # | Name | Value | Tag | Rationale |
|---|---|---:|---|---|
| G1 | `min_pivots` | 4 (2 per line) | OWNER + FROZEN | §37.7 triangle "≥ 2 resistance touches, ≥ 2 rising swing lows"; FROZEN `pattern_boundary_min_touches: 2` |
| G2 | `max_pivots_considered` | 6 | APPROVED | Trendoscope's 5–6-pivot window; the longest valid structure wins |
| G3 | `pivot_line_residual_max_atr` | 0.25 | FROZEN | `boundary_max_residual_atr` (the NI-2 boundary fit test) |
| G4 | `flat_max_drift_pct` | 1.5% | OWNER value, APPROVED application | §37.7 "resistance deviation ≤ 1.5%", applied to the fitted line's change across the formation (the hybrid decision) |
| G5 | `convergence_max_ratio` | 0.70 | FROZEN | `convergence_max_ratio` (reserved in the v1 config for triangle/wedge detectors) |
| G6 | `expanding_min_ratio` | 1.43 (= 1/0.70) | APPROVED | the mirror of G5; used only to label and exclude expanding shapes |
| G7 | `parallel_ratio_band` | 0.85–1.15 | APPROVED | a channel's width changes by at most ±15%; ratios between the bands are rejected rather than force-fitted |
| G13 | `apex_breakout_deadline_frac` | 0.75 | APPROVED | r1 Y7, extended to every converging shape |
| — | breakout, failure, volume, readiness | S5, S6/S7, S8, S9 | as §1.7 | |

**P-1 total: 5 APPROVED numbers** (G2, G4's application, G6, G7, G13), plus S6 and S9 shared. r1 needed 18 proposed
numbers for the three triangles alone.

**PIT notes.** The lines, the width ratio, the apex and `level(t)` are re-fitted at each `t` from pivots confirmed by
`t`. A pivot that confirms after the breakout bar never contributes to that bar's level (r1 §1 and §3 PIT notes,
kept).

**Reason codes.** `SHAPE_INSUFFICIENT_PIVOTS` · `SHAPE_PIVOT_OFF_LINE` · `SHAPE_LINES_CROSS` ·
`SHAPE_UNCLASSIFIED` · `SHAPE_EXPANDING_OUT_OF_SCOPE` · `SHAPE_CHANGED` · `APEX_REACHED` ·
`STRUCTURE_INVALIDATED` · `COUNTERTREND_BREAKOUT` · `WICK_ONLY_BREAKOUT` · `VOLUME_NOT_CONFIRMED` ·
`FAILED_BREAKOUT_REVERSAL` · `AMBIGUOUS_DIRECTION` (both lines crossed in one bar).

**Fixtures.**
1. Flat upper line (change 0.9%) with a rising lower line (change 4%) and w = 0.55 → ascending triangle.
2. Both lines flat and parallel → nothing emitted (the rectangle family owns it).
3. w = 1.6 → `SHAPE_EXPANDING_OUT_OF_SCOPE`.
4. w = 0.78 (between the bands) → `SHAPE_UNCLASSIFIED`, never force-fitted.
5. A close 0.6% above the upper line mid-formation → the formation ends as a breakout; the pattern is not stretched
   past it.
6. A pivot whose `confirmed_index > t` is used in the fit → the look-ahead test fails (§24.2).
7. The lines intersect between the first and last pivot → `SHAPE_LINES_CROSS`.
8. A rising wedge closes 0.6% above its upper line before any breakdown → INVALIDATED with `COUNTERTREND_BREAKOUT`.
9. A new pivot turns an ascending triangle's flat upper line into a rising one → `SHAPE_CHANGED`, and a new pattern
   starts; the old one is not redrawn.

---

## 3. P-2 flags and pennants: a pole, then a P-1 shape

**Pole.** A confirmed LOW pivot followed by a confirmed HIGH pivot for a bull pole (the reverse for a bear pole), with
a move of at least F1 within at most F2 bars.

**Body.** A P-1 shape (§2) that starts at the pole's end pivot. It is built from ≥ 4 pivots (G1), lasts F5–F4 bars,
is shorter than the pole (F3, OWNER) and retraces less than 50% of the pole (F6, OWNER). Body volume ≤ F8 is recorded
as a descriptive field (§13.8 "reduced or stable consolidation volume"), not a gate.

**Classification.**

| Pole | Body shape | Type |
|---|---|---|
| up | descending channel, falling wedge, or flat parallel (sideways) | bull flag (§13.8 "countertrend or sideways consolidation") |
| up | symmetrical triangle | bull pennant (APPROVED: symmetrical only, §10 Q3) |
| down | ascending channel, rising wedge, or flat parallel | bear flag |
| down | symmetrical triangle | bear pennant |
| either | any other shape (e.g. an ascending triangle after an up pole) | not a flag. It stays that P-1 shape, and `linked_pattern_id` points to the pole |

**Direction.** The same as the pole.
- **Breakout:** the close crosses the with-pole line by S5; volume per S8.
- **Invalidation (§13.8):** a close beyond the other line first (opposite-direction breakout), retracement ≥ 50%, or
  duration ≥ the pole's or > F4.
- **Stop:** Layer 1 is the opposite line at the breakout bar, i.e. the flag low or high (APPROVED, r1 C4; the owner
  has not addressed it). Layer 2 is §1.4.
- **Bear flags and bear pennants** are §37.4 INFORMATIONAL.

| # | Name | Value | Tag | Rationale |
|---|---|---:|---|---|
| F1 | `pole_min_move_atr` | 2.0 × ATR | APPROVED | r1 F1: a pole must be visibly steeper than an ordinary sloped line (0.75 × ATR) |
| F2 | `pole_max_bars` | 15 | APPROVED | r1 F2: a pole is a swift move |
| F3 | body duration < pole duration | strict | OWNER | §37.7 |
| F4 | `body_max_bars` | 20 | APPROVED | r1 F4 |
| F5 | `body_min_bars` | 5 | APPROVED | r1 F5 |
| F6 | body retracement < 50% of the pole | 50% | OWNER | §37.7 |
| F8 | `body_max_rel_volume` (descriptive) | 1.0 × | APPROVED | r1 F8, §13.8 |

**A limit to know about (disclosed, not tuned).** With 3-bar swings, a body needs 4 confirmed pivots, so bodies
shorter than roughly 10 bars will rarely qualify even though F5 allows 5. Study v2 reports how many flags are found at
each body length. If very short flags are wanted, the fix is a smaller body swing, which would be a new decision
before the freeze, never a change after results.

**Reason codes.** `POLE_TOO_WEAK` · `POLE_TOO_SLOW` · `BODY_INSUFFICIENT_PIVOTS` · `BODY_OVER_RETRACEMENT` ·
`BODY_DURATION_EXCEEDS_POLE` · `BODY_TOO_LONG` · `BODY_SHAPE_NOT_FLAG` · `STRUCTURE_INVALIDATED` ·
`WICK_ONLY_BREAKOUT` · `VOLUME_NOT_CONFIRMED` · `FAILED_BREAKOUT_REVERSAL`.

**Fixtures.**
1. A pole of 1.5 × ATR → `POLE_TOO_WEAK`.
2. A body retracing 60% of the pole → `BODY_OVER_RETRACEMENT`.
3. A flat parallel body after an up pole → bull flag (sideways).
4. A symmetrical-triangle body after an up pole → bull pennant.
5. An ascending-triangle body after an up pole → reported as an ascending triangle, linked, and not counted as a
   pennant.
6. A body with only 3 confirmed pivots → `BODY_INSUFFICIENT_PIVOTS`.

---

## 4. Double bottom (r1 §4, re-tagged)

**Rules.** Troughs at least B1 apart and within B2 of each other. The neckline is B3. A recovery of at least B5.
Breakout: close > neckline × (1 + S5). Invalidation: a close below the second trough. Layer-1 stop: below the second
trough (OWNER §37.3). P-4 metadata: `extreme_diff_pct_of_height` (§1.6).

| # | Name | Value | Tag |
|---|---|---:|---|
| B1 | `trough_min_separation_bars` | 10 | OWNER (§37.7, re-confirmed #110) |
| B2 | `trough_tolerance_pct` | 3% of price | OWNER (§37.7, re-confirmed #110 / P-4) |
| B3 | neckline | highest reaction high between the troughs | OWNER (§37.7) |
| B4 | breakout threshold | 0.5% (S5) | APPROVED extension |
| B5 | `recovery_min_pct` | 5% | APPROVED (r1) |

Reason codes and fixtures: as r1 §4.

## 5. Double top (r1 §5, re-tagged)

The mirror of §4, bearish, and §37.4 INFORMATIONAL.

| # | Name | Value | Tag |
|---|---|---:|---|
| P1 | `peak_min_separation_bars` | 10 | OWNER (#110 "double top/bottom separation → 10 sessions") |
| P2 | `peak_tolerance_pct` | 3% of price | OWNER (#110 "keep 3% double-top/bottom tolerance") |
| P3 | neckline | lowest reaction low between the peaks | APPROVED (mirror of B3) |
| P4 | breakdown threshold | 0.5% (S5) | APPROVED extension |
| P5 | `decline_min_pct` | 5% | APPROVED (mirror of B5) |
| P-stop | Layer 1 | above the second peak | APPROVED (r1 C4, the mirror of the owner's double-bottom rule) |

## 6. Head & shoulders (r1 §6, stop revised)

The structure, states and PIT notes are as in r1 §6. It is bearish and §37.4 INFORMATIONAL.

| # | Name | Value | Tag |
|---|---|---:|---|
| H1 | `shoulder_tolerance_pct` | 5% | APPROVED (r1) |
| H2 | `head_min_prominence_pct` | 3% | APPROVED (r1) |
| H3 | `peak_min_separation_bars` | 5 | APPROVED (r1 C7; the owner did not address it) |
| H4 | `neckline_trough_min_separation_bars` | 3 | FROZEN (`touch_min_separation_bars`) |
| H5 | breakdown threshold | 0.5% (S5) on the neckline's live value | APPROVED extension |
| H-stop-1 | **primary** Layer 1 | right-shoulder high + H-buf × ATR | OWNER rule (#110) |
| H-stop-2 | **secondary** research variant | neckline value at breakdown + H-buf × ATR | OWNER (#110: kept as a research variant) |
| H-buf | ATR buffer multiple | 0.25 | APPROVED choice to reuse FROZEN `failure_buffer_atr` (the owner said "ATR buffer" without a multiple) |

**Both stop variants are computed and reported for every H&S event.** Neither is picked for looking better (#110).

**Note:** because H&S is bearish and no short is priced (§37.4), the stop choice changes the invalidation level and
R-based gross outcomes, not net P&L. The stop decision would matter for a priced trade only in an inverse H&S (§10 Q1).

## 6b. Inverse head & shoulders (added by the approval of §10 Q1)

**Structure.** The mirror of §6:
- **Pivots:** left shoulder (confirmed LOW) → reaction high 1 (confirmed HIGH) → head (confirmed LOW, lower than both
  shoulders) → reaction high 2 (confirmed HIGH) → right shoulder (confirmed LOW).
- **Neckline:** the line through the two reaction highs. It may slope; its live value comes from `trendline_value_at`.
- **Direction:** bullish, `long_actionable` once CONFIRMED_BREAKOUT, so the stop choice affects priced trades.
- **Invalidation (pre-breakout):** a close below the right-shoulder low.

| # | Name | Value | Tag |
|---|---|---:|---|
| I1 | `shoulder_tolerance_pct` | 5% | APPROVED (mirror of H1) |
| I2 | `head_min_prominence_pct` | 3% (head below the lower shoulder) | APPROVED (mirror of H2) |
| I3 | `peak_min_separation_bars` | 5 | APPROVED (mirror of H3) |
| I4 | `neckline_peak_min_separation_bars` | 3 | FROZEN (`touch_min_separation_bars`) |
| I5 | breakout threshold | 0.5% (S5) above the neckline's live value | APPROVED extension |
| I-stop-1 | **primary** Layer 1 | right-shoulder low − 0.25 × ATR | OWNER rule (#110, mirrored by Q1) |
| I-stop-2 | **secondary** research variant | neckline value at breakout − 0.25 × ATR | OWNER (#110, mirrored by Q1) |

**Both stop variants are computed and reported for every event.** The PIT notes are the mirror of §6.

**Fixtures (mirror of §6).**
1. Head only 1% below both shoulders → reject (a triple bottom, not inverse H&S).
2. A sloped neckline: the breakout test uses the projected value at the breakout bar.
3. A head chosen using a pivot whose `confirmed_index > t` → the look-ahead test fails.

## 7. Cup & handle (r1 §9, re-tagged)

The rules are as in r1 §9, including the live-maturity treatment of the owner's "cup ≥ 80% complete".

| # | Name | Value | Tag |
|---|---|---:|---|
| C1 | cup ≥ 80% complete (early setup) | 80% | OWNER |
| C2 | `cup_resistance_proximity_pct` (the owner's "X%") | 2% | APPROVED |
| C3 / C4 | cup depth | 15%–50% | APPROVED |
| C5 | `cup_min_bars` | 25 | APPROVED |
| C6 | `cup_max_bars` | 260 | OWNER (#110) |
| C7 | `cup_rim_tolerance_pct` | 3% | APPROVED |
| C8 / C9 | cup low in the middle third of the cup's bars | 0.33–0.67 | APPROVED |
| C10 | `cup_max_single_bar_range_atr` | 3.0 | APPROVED |
| C11 / C12 | handle depth | ≤ 50% of the cup / ≤ 15% of price | APPROVED |
| C13 / C14 | handle length | 5–25 bars | APPROVED |
| C15 | handle ≤ 25% of the cup's duration | 25% | APPROVED |
| C16 | `handle_max_rel_volume` | 1.0 × | APPROVED |
| C17 | breakout threshold | 0.5% (S5) | APPROVED extension |
| — | Layer-1 stop | below the handle low | OWNER (§37.3) |

## 8. P-3 large-swing layer

**Scope.** Every family, at a second pivot scale, reported separately and never pooled. This includes today's 3
families: they stay at small scale in v1, and their large-scale versions are researched in v2 (§10 Q4).

**Chart first.** The chart shows it first, as its own toggleable layer drawn with heavier lines and an "L" label.
Research use comes only through study v2.

| # | Name | Value | Tag | Rationale |
|---|---|---:|---|---|
| L1 | `large_swing_left_bars` / `right_bars` | 8 / 8 | APPROVED | about 1.5 trading weeks each side; finds multi-month structures the 3/3 scale misses |
| L2 | large-scale `min` / `max_formation_bars` | 40 / 260 | APPROVED | scaled with the swing (4 alternating 8/8 pivots rarely fit in fewer than ~40 bars); 260 matches the owner's cup ceiling |
| L3 | `scale_link_min_overlap` | 50% | APPROVED | same type at both scales, overlapping ≥ 50% of the shorter span → `linked_pattern_id` set; both kept and counted in their own scale |

**Costs, disclosed.** Large-scale patterns become known about 5 bars later than small-scale ones (8-bar confirmation
instead of 3). The layer also doubles the number of tests in v2.

---

## 9. Drawings (plan §38.15, generated from this geometry)

Each new type is drawn from the fields the detector stores, never designed separately:
- **P-1 shapes:** the two fitted lines from the first to the last pivot, extended to the breakout, the apex (converging
  shapes) and a label.
- **P-2:** the pole line plus the body's two lines.
- **Double top/bottom:** two extreme markers and a dashed neckline.
- **H&S and inverse H&S:** three extreme markers, the neckline, and both stop variants when selected.
- **Cup & handle:** a rim line, the cup-low marker and a handle box.

The per-type drawing table goes into `docs/charting.md` §38.15 (step 6).

## 10. Questions resolved at approval (2026-09-22)

| # | Question | Resolution (owner approved the recommendation) |
|---|---|---|
| Q1 | Add inverse head & shoulders? | **Added** as §6b, the 16th type. |
| Q2 | Expanding (broadening) shapes in v2? | **Out of v2.** They are emitted as `SHAPE_EXPANDING_OUT_OF_SCOPE` and not reported as a type. |
| Q3 | Pennant bodies? | **Symmetrical triangle only.** Other shapes after a pole stay their own type, linked. |
| Q4 | Does the large-swing layer cover today's 3 families? | **Yes.** On the chart now; in research in v2 only. Their large-scale config hash is `9b81eae7…` (the v1 config with swings 8/8 and lengths 40/260). |
| C-A | Overlap with live families (e.g. ascending channel vs HH_HL)? | **Reported separately, never pooled.** `linked_pattern_id` records the overlap, and v2 reports overlap counts. |

## 11. Approval record

The owner approved every item below as listed (2026-09-22). They were the APPROVED rows as proposed in r2.

- **Shared:** S6 failure threshold = breakout threshold · S9 readiness band 1.0% · no-repainting rule (`SHAPE_CHANGED`) ·
  S5 0.5% extended to §4–§7.
- **P-1:** G2 `max_pivots_considered` = 6 · G4 application (the fitted line's change across the formation) · G6
  `expanding_min_ratio` = 1.43 · G7 `parallel_ratio_band` = 0.85–1.15 · G13 `apex_breakout_deadline_frac` = 0.75 ·
  channel direction set by the side broken · a wedge's opposite-side close = INVALIDATED (`COUNTERTREND_BREAKOUT`) ·
  wedge/channel Layer-1 stop = opposite line.
- **P-2:** F1 pole ≥ 2.0 × ATR · F2 pole ≤ 15 bars · F4 body ≤ 20 bars · F5 body ≥ 5 bars · F8 body volume ≤ 1.0×
  (descriptive) · flag stop = opposite body line.
- **Double bottom:** B5 recovery ≥ 5%.
- **Double top:** P3 neckline = lowest reaction low · P5 decline ≥ 5% · stop above the second peak.
- **H&S:** H1 5% · H2 3% · H3 5 bars · H-buf 0.25 × ATR.
- **Cup & handle:** C2 2% · C3/C4 15–50% · C5 25 bars · C7 3% · C8/C9 0.33–0.67 · C10 3.0 × ATR · C11/C12 50% / 15% ·
  C13/C14 5–25 bars · C15 25% · C16 1.0×.
- **P-3:** L1 8/8 · L2 40/260 · L3 50%.
- **§10:** Q1–Q4 and C-A, resolved as shown in §10.

**Count: 39 approved checklist items (43 values if the paired cup ranges are counted separately) and 5 resolved
questions, for 16 pattern types.**

**Implementation prerequisite (a code gap, not a parameter):** `trendline_value_at(pivots, t)` in
`research/charting/geometry.py` (r1 C6). It must exist before any P-1, P-2 or sloped-neckline detector.

**These are research parameters, not optimised ones.** They are frozen and never tuned against results (owner principle,
#110).
