# Nivesh Pattern Validation & Confluence Experiment — PRD v1.0

**Status:** OWNER-AUTHORED, 2026-09-25. Supersedes `CONFLUENCE_ENGINEERING_PRD_V1` as the governing
research design. Implementation notes and measured reality are in §§A–C at the end, added by app-af;
the body above them is the owner's specification and has not been edited.

---

## 1. Objective

Determine whether Nivesh chart patterns provide **incremental predictive information** about future
stock movement after controlling for characteristics that independently explain large price moves.

> **Primary question.** After controlling for price/cheapness, liquidity, recent volatility,
> momentum/trend, market regime and sector regime, does knowing that a chart pattern exists improve
> prediction of future stock movement?

> **Secondary question.** Does combining a validated chart pattern with a material market/corporate
> event provide additional information beyond either signal independently?

**A negative result is a valid outcome.**

## 2. Research questions

- **RQ1** — does a pattern contain incremental information after controlling for obvious stock
  characteristics?
- **RQ2** — which of the 16 implemented patterns, if any, show incremental information? Assume none
  until tested.
- **RQ3** — does requiring confirmation improve it? (detected · + breakout · + volume · + trend)
- **RQ4** — does behaviour change by market trend, sector trend, volatility regime, breadth,
  risk-on/off?
- **RQ5** — does a material event add information to a pattern?
- **RQ6** — does Pattern + Event differ from pattern alone / event alone / neither, after the same
  controls?

## 3. Hypotheses

**H0 (pattern):** after controls, pattern presence does not improve prediction.
**H1 (pattern):** it provides statistically *and economically* meaningful additional information.

**H0 (confluence):** the Pattern × Event interaction adds nothing.
**H1 (confluence):** the interaction adds information beyond the individual components.

## 4. Critical design principle

Do **not** compare `Pattern vs Volatility` only. That was the weakness the review identified. Use
**nested models**.

## 5–9. The nested baseline hierarchy

| rung | adds | intent |
|---|---|---|
| **B0** | nothing | base rate: P(+5%), P(+10%), P(−5%), P(−10%) |
| **B1** | ATR%, HV10/20/60, 20D realised vol, 10D/20D range, recent absolute returns | "how jumpy has it been?" |
| **B2** | price_level, log(price), market_cap, price_bucket | price/size. **Price level is NOT economic cheapness** — keep PE/PB/EV-EBITDA separate and do not casually call price level "cheapness" |
| **B3** | 20D median/avg turnover, 20D median volume, 20D RVOL, spread if available, free-float mcap, turnover/mcap | liquidity. **Primary measure is rupee turnover**, not share volume — 1M shares at ₹10 ≠ 1M at ₹1,000 |
| **B4** | NIFTY 1D/5D/20D return, above SMA20/50, market vol, breadth; sector 1D/5D/20D return, sector RS, trend, vol | controls "the whole market was moving" |
| **B5** | RSI14, ROC5/10/20, SMA20/50/200 distance, ADX14, MACD hist, ATR%, RVOL20, 20D high/low distance, 52W high/low distance, OBV slope, CMF20, RS vs NIFTY, RS vs sector | **the hardest baseline** — what a detector may simply be repackaging |

**B5 is the crux.** If a breakout's edge vanishes once momentum, relative strength, volume and
distance-from-20D-high are controlled, the "pattern effect" was those variables wearing a different
label. This experiment exists to discover exactly that.

## 10–12. The model ladder

- **P1** = B5 + `pattern_present, pattern_family, pattern_type, pattern_age, pattern_completion,
  pattern_confirmation`. **P1 vs B5 is the primary test of incremental pattern value.**
- **P2** = B5 + `corporate_event_present, event_type, event_direction, event_materiality,
  event_timing, event_surprise, event_status` (taxonomy E01–E40 plus **E41 exchange surveillance**).
- **P3** = B5 + Pattern + Event + **Pattern × Event interaction**.

```
Outcome = baseline + pattern + event + pattern×event + error
```

The question is whether the combination behaves differently from simply adding the two effects.

## 13–15. Taxonomy, certification, and three separate statuses

Registry carries `pattern_id, pattern_name, pattern_family, detector_version,
implementation_status, certification_status, parameters`.

> **Do not use the old settings-file statement "no detector implemented" as evidence.**
> Implementation must be independently verified.

Certification requires **structural tests** (pivots, highs, lows, trendlines, neckline, breakout
level, invalidation level), **fixture tests** (expected pattern/start/end/confirmation/
invalidation), **negative fixtures** (a near-pattern yields NO_PATTERN), and **boundary tests**
(equal highs/lows, gaps, missing candles, low-volume breakout, false breakout, partial formation).

Three statuses, never conflated:

```
implementation_status  IMPLEMENTED | PARTIAL | MISSING
certification_status   PASS | FAIL
historical_result      NOT_TESTED | NO_EVIDENCE | POSITIVE | NEGATIVE | MIXED
                            implemented ≠ useful
```

## 16–17. Targets and horizons

Targets: **A** +5% · **B** +10% · **C** −5%/−10% · **D** forward returns R1/R3/R5/R10 ·
**E** MFE, MAE, MFE/MAE.

Horizons **1, 3, 5, 10, 20 sessions — run separately, do not pool.** A pattern may have a
short-term effect and no 10-session effect.

## 18–19. Event timing and causal ordering

Timing: before open · during market · after close · weekend/holiday.
**Never allow an event to leak backward into the pattern state.**

Ordering, classified per observation:

| | |
|---|---|
| **A** | pattern → event → reaction |
| **B** | event → pattern → continuation |
| **C** | same session |
| **D** | event → price shock → pattern formation |

**A D-type observation must never be used as evidence that the pattern predicted the reaction.**

## 20–23. Surprise, confounders, leakage, corporate actions

`event_expectedness ∈ {SCHEDULED, ANTICIPATED, UNEXPECTED, UNKNOWN}` — an earnings date is
fundamentally different from an unexpected acquisition.

Confounder search per observation (earnings, other corporate event, order, block/bulk, promoter
transaction, regulatory, sector, market, index inclusion/exclusion, corporate action, rumour, news
shock) → `NONE | MINOR | MATERIAL | UNKNOWN`. Material-confounder rows are excluded from the clean
experiment or analysed separately.

Leakage, absolute: **PRE_EVENT** uses only data known before the signal timestamp — never T0 close,
high, low or final volume, never a future event or future confirmation. **EVENT** uses only what is
known by the event timestamp. **POST_EVENT** is for outcome measurement only.

Corporate actions checked before any movement is computed (split, bonus, rights, demerger, merger,
capital reduction, special dividend, face-value change), storing `raw_price, adjusted_price,
adjustment_factor, adjustment_source`. **An India-Glycols-type case must never become a false 80%
crash.**

## 24–28. Statistics

Per pattern: N, hit rate, mean, median, SD, MFE, MAE, CAR, CI.
Classification: ROC-AUC, PR-AUC, Brier, calibration.
**Incremental information: out-of-sample log loss, out-of-sample Brier, incremental R²,
likelihood-ratio comparison.** Returns: mean/median difference with bootstrap CI.

**Multiple testing is mandatory** — 16 patterns × 5 horizons × targets × confirmations × regimes is
thousands of comparisons. Record `hypothesis_id, pre_registered, test_family, number_of_tests,
raw_p_value, adjusted_p_value`; **Benjamini-Hochberg FDR** for exploratory families. Do not
cherry-pick the strongest result.

**Chronological splits, never shuffled:** 2021–2023 development · 2024 validation · 2025–2026
out-of-sample, dates fixed before final evaluation, plus walk-forward.

**Freeze the detector once certified** (parameters, thresholds, pivot/confirmation/invalidation
rules). Modifying it means `detector_version = 2.x` and restarting validation.

**Costs:** test 0.10% / 0.25% / 0.50% round-trip; report gross, cost, net. A tiny statistical effect
that dies after costs is not useful.

## 29–30. The two experiments

**Pattern-only**, for each of 16: `B5` vs `B5 + Pattern` → N, base hit rate, pattern hit rate,
increment, OOS result. **Do not rank patterns by a score** — establish evidence for or against.

**Confluence**, four groups: `G0` baseline · `G1` +pattern · `G2` +event · `G3` +both.
Evaluate G1−G0, G2−G0, G3−G0, **G3−G1, G3−G2**.

> The most interesting question: does G3 contain information not already in G1 + G2?

## 31–33. Event categories, direction, regime

Run event families **separately** (orders, acquisitions, M&A, demergers, QIPs, block/bulk, promoter,
debt, ratings, regulatory, management, capacity, customer, corporate actions, surveillance,
reversals) so a strong order effect cannot hide different regulatory behaviour.

**Do not hard-code direction.** Record the event, test the reaction, keep `MIXED` until empirically
defensible.

Regime segmentation uses **predefined rules**, not categories invented after seeing results.

## 34. Acceptance criteria

A pattern passes only if: detector certified · no material look-ahead · adequate sample ·
predefined target · out-of-sample evaluation · incremental vs B5 · multiple testing handled ·
stable across periods · survives realistic costs · no obvious confounder explanation.

Even then it is a **"historically supported incremental signal"**, never a "proven predictor".

---
---

# §A. Measured reality as of 2026-09-25 (app-af)

Added below the specification, not woven into it. Every figure first-hand.

## A1. The baseline rungs are not equally available

| rung | status |
|---|---|
| B0 | trivial |
| B1 | ATR% available per row. HV10/20/60 and range features **not** currently computed |
| B2 | `entry.primary.price` available. **market_cap not on the row** |
| B3 | `liquidity.adv_inr_at_t` available (rupee turnover, as §7 requires). Spread and free-float **absent** |
| B4 | NIFTY trend ✅ · breadth ✅ · market regime ⚠️ 68.8% coverage · **sector trend MISSING from the model path** · risk-on/off **absent** |
| B5 | RSI/MACD/ADX/ROC exist in `series.py`; **the committed export is catalogue 1.0.0 with 7 indicators and no ADX** — a re-export is required. OBV slope and CMF20 **not implemented** |

## A2. Why B2 and B3 are not optional

Measured on this study's own rows, predicting `up_5 @ H=20`:

```
atr_pct  (B1)                    0.6345
-entry price  (B2)               0.7059    <- beats B1 by 7 points
-log(ADV)     (B3)               0.6881    <- beats B1 by 5 points
calendar-month base rate         0.7151    <- no stock information at all
```

The owner's instinct to put price and liquidity in the ladder is correct, and stronger than it
looks: **both beat the volatility rung, and a pure calendar lookup beats all three.** B4 must
therefore include time effects, or a model will absorb them and report them as chart skill.

## A3. Effective sample size

Rows are not independent: overlapping 20-session windows on one symbol, and many symbols moving
together on one day. A symbol-clustered CI on the ATR AUC above is **[0.515, 0.708]** — it barely
excludes a coin flip. **Every interval in §24 must be symbol-clustered**, or n is overstated by
roughly the rows-per-symbol factor.

## A4. What the label choice does

```
up_5  @H20   base rate 72.0%
down_5 @H20  base rate 61.6%
```

Most rows hit **both**. At H=20 the ±5% label is close to "did the stock move at all". §17's
instruction to run horizons separately is what protects against this; the ±10% **race**
(`first_exit_event` TARGET vs STOP, AMBIGUOUS excluded) is the better-balanced primary.

Measured on 15,089 decided cases: **49.2% — a coin flip. The chart carries no direction.**
Asymmetric targets mislead (pct_2 shows 77.2%) because a small target against a wider stop is easy,
not directional.

## A5. §13's warning was justified

The registry disables all 16 NI-3 families with reason *"no detector implemented; specification
only"*. That reason is **stale** — the detectors landed in commits after the registry on the same
day and 86 fixture tests pass. **Not yet independently verified**; §13 says to verify, and that is
tracked, not assumed.

## A6. Data windows that bound the design

- Corporate events start **2024-06**; `pre_sealed` ends 2022-12 → **zero overlap** today. NSE serves
  history to 2019-06 and a backfill is proposed, which would remove this.
- Event labels currently span ~9 months; NSE's `subject` field (162 structured values) could extend
  that across the full history without the throttled classifier.
- Sealed block 2023-01-01..2024-07-31 has **zero rows in all 18 index CSVs**, and `market_regime()`
  is blind for the **first 219 post-sealed sessions** because its lookbacks span the hole. §26's
  chronological split must exclude that warm-up rather than read it as SIDEWAYS.

# §B. Open questions this PRD does not yet settle

1. §25 specifies BH-FDR for exploratory families; a separate ledger is running Bonferroni over ~42
   families for discovery claims. **Which governs a confluence cell?**
2. §26's split (2021–23 dev) overlaps the sealed block 2023-01..2024-07. Needs reconciling.
3. §16 lists five target families × 5 horizons × 16 patterns — the multiple-testing count explodes
   before confirmations and regimes. A pre-declared primary is needed.

# §C. Governing documents

- Multiple-testing ledger: `docs/ai_research/tpd3/pattern_engine/REGISTRY_SEED.md` (app-af owns)
- Event-side interface: `nidp.v_event_asof` (app-28, in progress)
- Frozen study v1: `docs/ai_research/CHARTING_PREREGISTRATION_V1.md`
