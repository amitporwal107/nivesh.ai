# Roadmap v2, Phases 2–3 — trade-outcome labels and baseline models: pre-registration (FROZEN)

**Status: FROZEN.** Approved by the owner on 2026-09-19 (~21:05 IST), "approve as drafted".
- At approval, no dataset had been built and no model fitted.
- Index history: the owner said "the kite secret key is still valid". Only the **development range (2021–22)** is fetched now; test-period index bars are fetched at test time (§9).

| Item | Value |
|---|---|
| Owner documents | `MODEL_IMPROVEMENT_PLAN_2026-09-19.md`, `MODEL_IMPROVEMENT_ROADMAP_v2_2026-09-19.md` |
| Owner decisions (2026-09-19 20:55 IST) | chronological periods; fundamentals excluded; primary label +5% / −2% / 5 sessions |
| Success policy | `pattern_engine/SUCCESS_CRITERIA.md` and roadmap v2 §17 gates |
| Registry | primary hypothesis #32; all other comparisons are secondary and descriptive (counted, not decision-bearing) |

## 1. Question

Do the existing v4 price/volume features contain **directional / trade-outcome** information that the current touch
model does not use? The test: does a model trained on the new labels select trades with **positive net
expectancy** that beat random selection, a movement-only ranking and a momentum rule on a locked, untouched test
period?

## 2. Periods (locked before any fitting; strictly chronological)

| Block | Feature dates (decision day D) | Use |
|---|---|---|
| Development | 2021-01-01 … 2022-12-22 | Fitting and walk-forward validation. Labels must complete by 2022-12-30 (5 sessions after D). No bar from 2023 is read. |
| **Locked test** | 2023-01-02 … 2024-07-24 | **One use**, after the models are frozen. Labels complete by 2024-07-31. Never used for any choice. |
| Confirmation | 2024-08-01 … 2026-09-11 | After the test only. Earlier exploratory studies saw this block, but no model here has been fitted on it. |
| Forward | after owner sign-off | Pinned forward worktree. |

**Development walk-forward:**
- Expanding window.
- Four validation folds = the calendar quarters of 2022.
- Each fold trains on every development row with D before the fold starts, minus a 5-session **embargo**, so no training label overlaps the fold.
- Rows need at least 60 bars of history. Features needing up to 252 bars stay missing (NaN) until they exist, which in practice is until ~2022-01 because the Kite data starts in 2021.

## 3. Universe, entry and costs

- **Universe:** current Nifty 500 members (`ind_nifty500list.csv`).
  - **Survivorship bias is larger in 2021–22 and is disclosed.**
  - ETFs excluded (name contains "ETF", or an ETF-type symbol).
- **Eligible on D:** at least 60 sessions of history; 20-day average traded value ≥ ₹5 crore; close ≥ ₹50. The same eligibility as the positional study.
- **Data:** Kite daily bars, split/bonus/dividend-adjusted (`/app/research/kite_history/day_2021/`).
- **Entry:** the official open of D+1 (s1). No entry, and the row is excluded and counted, if:
  - there is no bar on D+1;
  - the open is locked at the upper circuit (as in `risk/execution.py`).
- **Costs:** the Zerodha delivery schedule `zerodha-equity-v1` (applied retroactively, flagged) for a ₹50,000 position. Slippage is 0.05% / 0.10% / 0.20% per side by `value20` bucket.
- **Cost scenarios:**
  - optimistic: 0.5× slippage;
  - base;
  - conservative: 2× slippage.

## 4. Labels (sessions s1 = D+1 … s5)

| Label | Definition |
|---|---|
| `hit_high_5_1d` | high(s1) ≥ entry × 1.05 |
| `hit_high_5_3d` / `hit_high_5_5d` | max high(s1…s3 / s1…s5) ≥ entry × 1.05 |
| `hit_high_10_5d` | max high(s1…s5) ≥ entry × 1.10 |
| `hit_close_5_5d` / `hit_close_10_5d` | max close(s1…s5) ≥ entry × 1.05 / 1.10 |
| **`tbs_5_2`** (primary) | Scan s1…s5. Stop = entry × 0.98: an open ≤ stop exits at the open (gap-through), otherwise a low ≤ stop exits at the stop. Target = entry × 1.05: an open ≥ target exits at the open, otherwise a high ≥ target exits at the target. **A bar touching both counts as STOP.** Otherwise expire at the s5 close. Outcome ∈ {TARGET, STOP, EXPIRED}. |
| `tbs_10_4` (secondary) | The same with +10% / −4% |
| `net_ret_5_2` | The `tbs_5_2` trade's return after slippage and costs |
| `net_pos_5_2` | 1 if `net_ret_5_2` > 0 |
| `dir_5_5d` (direction, model B) | UP if +5% (high) is touched before −5% (low) within s1…s5; DOWN if −5% first; NONE if neither. A bar touching both is AMBIGUOUS and excluded from direction fitting and scoring. |

Labels are built only from bars ≤ s5. The builder asserts that no development label reads a 2023 bar, and that no test label reads a bar after 2024-07-31.

## 5. Features (cutoff: the close of D)

- **Included:** the existing v4 groups, computed by the v4 code itself (`tpd_model.features`, `technical_ext`) on the Kite panel:
  - PRICE (25);
  - TECHNICAL_EXT (17);
  - MARKET (2).

  That is **44 features**. Missing values are allowed. Logistic regression uses a median impute (fitted on training rows only) plus missing indicators; gradient boosting uses native NaN handling.
- **Excluded, with reasons:**
  - FUNDAMENTAL (16), OWNERSHIP (11), RESULTS_PRINT (8): the owner decision, until DEF-6/8/9 are fixed and every field is PIT-validated;
  - EVENT (2): no results dates before Oct 2024;
  - DELIVERY (4): not in the Kite data.
- **Not in this experiment:** roadmap Phase 4 groups (market regime, sector-relative strength, breakout quality, tradeability). They get separate pre-registrations, one group at a time.

## 6. Models (identical rows, periods, costs, seed 20260919)

| # | Model | Role |
|---|---|---|
| M0 | Base rate (per fold) | control |
| M1 | Random selection | control |
| M2 | Momentum rule: rank by `ret20` | control (roadmap "momentum-only") |
| M3 | Volatility rule: rank by `atr_pct` | control (movement proxy) |
| M4 | Movement-only model: gradient boosting trained on `hit_high_10_5d`, used to rank trades | control (the "current approach") |
| M5 | Market-only logistic (`mkt_ret1`, `breadth`) | control |
| M6 | Sector-only logistic (industry dummies from the Nifty 500 list) | control |
| M7 | Logistic regression, all 44 features, per label (L2, C = 1.0, standardised) | baseline |
| **M8** | **HistGradientBoosting**, all 44 features, per label (max_iter 300, learning_rate 0.05, max_leaf_nodes 31, l2 1.0, no early stopping) | **primary model for `tbs_5_2`** |
| M9 | Two-stage: P(large move) × P(UP \| large move). Stage 1 = M8 on (`hit_high_10_5d` or its downside mirror); stage 2 = M8 on `dir_5_5d` with **out-of-fold** stage-1 predictions | comparison with a direct `hit_high_10_5d` classifier |

- **No hyperparameter search.** The settings above are fixed now.
- **Calibration:** isotonic, fitted on the development out-of-fold predictions and applied unchanged on the test.
- **Not in this experiment:** LightGBM / XGBoost (not installed; the scikit-learn HistGradientBoosting is used instead).

## 7. Evaluation

**Prediction quality, per label and model:**
- PR-AUC (primary for rare labels), ROC-AUC, Brier;
- reliability by probability bucket;
- precision at the top 1% / 5% / 10%;
- lift over the base rate.

**Trading quality:**
- Each session, the top 5 eligible names by a model's score enter at the next open under the `tbs_5_2` rule, equal weight, with costs.
- Report the average and median net return per trade, profit factor, maximum drawdown of the daily portfolio, expected value per trade, turnover and exposure.
- All under the three cost scenarios.

**Conditional matrix (descriptive):** market regime (Nifty 500 above/below its 200-session average), sector, volatility tercile, liquidity bucket and opening gap bucket.

**Benchmark:** Nifty 500 buy-and-hold over the same period.

**Data dependency:** Nifty 500 and Nifty 50 index history for 2021–26 must come from Kite. That is one API call per index, but it needs a fresh owner login. If it is unavailable, the NIFTYBEES ETF is the market proxy, disclosed.

## 8. Primary hypothesis #32 and decision rule (locked test only, applied once)

**H#32:** M8's top-5 daily selection on `tbs_5_2`, over the locked test, meets **all** of:

| # | Criterion |
|---|---|
| 1 | Mean net return per trade > 0, with a date-clustered bootstrap 95% lower bound > 0 (base costs) |
| 2 | It beats M1 random, M2 momentum and M4 movement-only on mean net return per trade. Each difference has a date-clustered bootstrap lower bound > 0, Holm-corrected across the three. |
| 3 | Mean net return > 0 under conservative costs |
| 4 | Both halves of the test > 0 |
| 5 | No single sector contributes more than 40% of the net P&L |
| 6 | Calibration: the absolute gap between predicted and realised TARGET rate is below 5 points in every bucket with at least 100 rows |

- **Pass:** a *validation candidate*. The confirmation block (Aug-2024 onward) and the forward test must both agree before any promotion.
- **Fail:** H#32 CLOSED. Secondary results are reported but decide nothing.

## 9. Prohibited

- Any choice (features, labels, parameters, thresholds, the top-k) after the locked test has been scored.
- Re-scoring the test with changed code.
- Reading 2023–24 bars before the models are frozen.
- Adding models to the decision set after the fact.

## 10. Deliverables and order

1. **Label and dataset builder** (`research/model_v5/`) with tests on synthetic data: label edge cases, same-bar stop-first, gap-through, the period guards that stop any sealed-bar read, and the v4 feature parity check. It builds the **development** dataset only.
2. **Walk-forward development run** (M0–M9 on the 2022 folds) and the calibration fit. The models are frozen by a commit.
3. **Owner checkpoint**, then the **one locked-test run**.
4. `RESULTS.md`, the extreme-trade audit, the registry update, then the confirmation block.
