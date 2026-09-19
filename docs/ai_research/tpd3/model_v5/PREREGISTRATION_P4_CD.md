# Roadmap v2, Phase 4 — groups C (breakout quality) and D (tradeability): pre-registration (FROZEN)

**Status: FROZEN.** Approved by the owner on 2026-09-19 (~22:40 IST), "approve as drafted". At approval, no feature in this document had been computed on real data, and no model had been fitted with it.

| Item | Value |
|---|---|
| Owner documents | `MODEL_IMPROVEMENT_PLAN_2026-09-19.md` §4 C–D; roadmap v2 Phase 4 |
| Design | The same as `PREREGISTRATION_P4_AB.md` (FROZEN ac54c1b4), unless a change is stated here. Each group is added **on its own** to the 44 baseline features (B0) |
| Registry | #35 = group C, #36 = group D |
| Scope | **Development block only (2021–22).** The sealed Jan 2023 – Jul 2024 block is not read, and nothing here can spend it |

## 1. Question

Does breakout-quality information (C) or tradeability and execution information (D), added on its own to the 44 baseline features, improve the direction of large moves or the target-before-stop ranking, enough to be kept for a future combined model? This completes Phase 4 before any combined model is proposed. That combined model would be B0 + group B (kept) + any group kept here.

## 2. Data

These are identical to groups A and B:
- the H#32 development dataset (sha256 `7bb77e5a…b327`);
- Kite adjusted daily bars cut at 2022-12-30;
- the Nifty 500 industry list.

No index data is used.

**Conventions:**
- Windows count the stock's **own bars**, as the v4 features do.
- "Prior N" means the N bars **before** D, excluding D itself.
- ATR is the baseline's own value: `atr_pct` (v4 Wilder ATR(14) over the last 260 bars) × close / 100.
- Every value uses bars dated on or before D only.

## 3. Features

### Group C — breakout and continuation quality (11 features)

**Breakout level:** `hi55p` = the maximum high of the prior 55 bars. It is distinct from the baseline's `dist_swing20` (a 20-bar high including D) and `dist_52w_high`.

**Breakout day:** a bar t whose close is above its own `hi55p`.

| Feature | Definition |
|---|---|
| `bo_dist_atr55` | (close(D) − `hi55p`) / ATR: breakout distance in ATRs (negative = below the level) |
| `bo_dist_atr20` | The same against the prior-20-bar high |
| `bo_dist_pct55` | close(D) / `hi55p` − 1: distance from the breakout level |
| `bo_days_since` | Bars since the most recent breakout day at or before D (0 = D itself). NaN if there is none in the last 260 bars |
| `bo_vol_last` | On the most recent breakout day within the last 10 bars: volume / mean volume of its prior 20 bars (volume confirmation). NaN if there is none |
| `bo_close_pos_last` | On that same day: (close − low) / (high − low), the close location. 0.5 if high = low |
| `bo_follow_through` | close(D) / close(most recent breakout day within the last 10 bars, before D) − 1. NaN if there is none |
| `bo_failed_120` | Breakout days t in the prior 120 bars **with t ≤ D − 5 bars** whose close fell back to or below that day's `hi55p` within the next 5 bars (all ≤ D) |
| `bo_held_120` | The same window: breakout days that did not fall back |
| `bo_gap_through_freq` | Over breakout days in the prior 260 bars: the share whose **open** was already above `hi55p`. NaN if there are fewer than 3 |
| `bo_peer_share` | Sector confirmation: the share of industry peers (leave-one-out, at least 3) whose close(D) is within 3% of, or above, their own `hi55p` |

**Deliberately omitted from C:**
- "Market regime at breakout", because group A (regime) was dropped under its frozen rule, and regime information may only return through its own new pre-registration.
- Pre-breakout compression, because `range20_vs_100` is already in the baseline.

### Group D — tradeability and execution (7 features)

| Feature | Definition |
|---|---|
| `td_log_value60` | log10 of the median traded value (close × volume) over the last 60 bars. The baseline's `turn_med20` is the 20-bar version |
| `td_slippage_pct` | Expected slippage per side from the frozen cost model (`zerodha-equity-v1` bucket by 20-bar mean traded value: 0.05 / 0.10 / 0.20%) |
| `td_gap_abs60` | Mean absolute opening gap \|open / previous close − 1\| over the last 60 bars (price gap risk) |
| `td_gap_share60` | `td_gap_abs60` ÷ the mean true range / previous close over the same 60 bars: the part of daily range that arrives as a gap |
| `td_gap_down2_120` | Share of the last 120 bars that opened ≥ 2% below the previous close, the size of this experiment's stop |
| `td_hist_target` | Historical target-before-stop rate: the frozen `tbs_5_2` rule applied to the stock's own past entries t (entry at the open of t+1) with t in the prior 250 bars and **t ≤ D − 5 bars**, so every past outcome ended by D. NaN if there are fewer than 60 past outcomes |
| `td_hist_gapstop` | For those same past trades: the share that exited through a gap-through stop (open ≤ stop) |

**Deliberately omitted from D:**
- "ATR relative to price", because it is the baseline's `atr_pct`.
- "Liquidity-adjusted position size", because it is constant here. Every eligible stock trades ≥ ₹5 crore a day, so a ₹50,000 position is always filled in full at a fixed −2% stop, and the feature would carry no information.

## 4. Models, labels and evaluation

These are identical to `PREREGISTRATION_P4_AB.md` §4–§6:
- B0 / C / D on the M8 specification, with M7 logistic as a secondary, descriptive model;
- the B0 reproduction gate against the H#32 out-of-fold file (to 1e-12) before any arm result;
- primary labels `tbs_5_2` (PR-AUC) and `up_given_move` (ROC-AUC);
- the same folds, embargo, eligibility, top-5 trading, costs and bootstraps;
- an extreme-trade audit per arm.

## 5. Keep / drop rule (applied once per group)

The same rule as groups A and B. Holm runs across the **four tests of this experiment** (2 groups × 2 metrics, α = 0.025 one-sided).

| # | Criterion |
|---|---|
| K1 | A Holm-significant gain in `tbs_5_2` PR-AUC **or** `up_given_move` ROC-AUC over B0 |
| K2 | Top-5 mean net per trade ≥ B0's, both pooled and in at least 3 of 4 folds |
| K3 | In no fold does `tbs_5_2` PR-AUC drop by more than 0.01 against B0 |

A dropped group may not be redefined and re-run on this data.

## 6. After this experiment

A combined model (B0 + B + any kept group from C or D) may be proposed only through its own pre-registration and owner approval, and only with a positive development net expectancy (the §8 gate of `PREREGISTRATION_P4_AB.md`).

## 7. Known limits

- **Third use of the 2022 folds:** H#32 and groups A/B used them first. The definitions above come from the owner's list and were fixed without looking at their 2022 behaviour.
- **Short history:** stock history starts in 2021, so the 120- and 260-bar breakout counts and `td_hist_*` are sparse before late 2021. NaN is allowed.
- **`td_hist_target` resembles the label,** but uses only trades that ended by D (the future-shock tests enforce this).
- **Shared data limits:** survivorship bias and retroactive costs, as before.

## 8. Prohibited

The same as groups A and B:
- no change after the first result;
- no added arms;
- no bar after 2022-12-30;
- no use of the sealed block.

## 9. Deliverables

1. `features_p4cd.py`, with synthetic tests before any real run:
   - hand-computed values;
   - the breakout-day, failed and held logic;
   - the "t ≤ D − 5" completion rule for `bo_failed_120`, `bo_held_120` and `td_hist_*`;
   - the peer minimum;
   - future-shock invariance;
   - the block guard;
   - deliberate code breaks, checked to be caught by the tests.
2. Runner: `phase4.py`, generalised to take the group set, with its tests and B0 gate unchanged. It runs once from a committed tree.
3. `P4_CD_RESULTS.md`, and registry #35 / #36.
