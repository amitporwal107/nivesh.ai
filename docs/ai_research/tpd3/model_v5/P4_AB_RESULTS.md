# Phase 4 groups A (market regime) and B (sector-relative strength): results of the single development run

**Verdicts under the frozen rule (§7): group A DROPPED, group B KEPT.**
- This is development data only (2021–22). The sealed Jan 2023 – Jul 2024 block was not read.
- No arm makes money after costs, so nothing qualifies for the sealed test under §8.

## Run identity

| Item | Value |
|---|---|
| Pre-registration | `PREREGISTRATION_P4_AB.md`, FROZEN at ac54c1b4 (owner-approved 2026-09-19 ~22:10 IST) |
| Code | features 0a35bd2a + b4b96445 + 0ba12ac8 (9 synthetic tests, 15 of 15 deliberate code breaks caught)<br>runner f32c8d30 (10 synthetic tests, 10 of 10 caught) |
| Run | 2026-09-19 22:15–22:23 IST, once, from f32c8d30 with a clean tree |
| Output | `p4ab_results_20260919T221514.json`, sha256 `78fc99d8…03ab3`<br>out-of-fold predictions `p4ab_oof_20260919T221514.csv.gz` |
| Inputs | H#32 development dataset (sha256 `7bb77e5a…b327`)<br>`index_p4.csv`: NIFTY 500, NIFTY 50 and INDIA VIX, 2019-07-01 … 2022-12-30; its 2021–22 rows are identical to the file H#32 used |
| Reproducibility gate | B0 reproduces the H#32 M8 out-of-fold predictions to a maximum absolute difference of **9.7e-17** (the limit was 1e-12) |
| Feature checks on real data | All 198,945 rows joined. The one-day breadth matches v4 to 1e-16. Missing values are under 1% on 2022 tradable rows (small industries under the 3-peer rule) |

## 1. Primary ranking metrics (pooled 2022 out-of-fold; M8 specification)

| Metric | B0 (44) | A (+ regime, 60) | B (+ relative strength, 58) |
|---|---|---|---|
| `tbs_5_2` PR-AUC (base rate 0.202) | 0.2386 | 0.2398 | **0.2460** |
| per fold Q1 / Q2 / Q3 / Q4 | 0.256 / 0.250 / 0.270 / 0.197 | 0.272 / **0.221** / 0.298 / 0.212 | 0.262 / 0.253 / 0.278 / 0.206 |
| `up_given_move` ROC-AUC | 0.501 | **0.549** | 0.513 |
| per fold Q1 / Q2 / Q3 / Q4 | 0.502 / 0.596 / 0.467 / 0.488 | 0.550 / 0.590 / 0.576 / 0.559 | 0.514 / 0.626 / 0.507 / 0.498 |

**Paired, date-clustered bootstrap of the arm − B0 difference** (2,000 resamples of decision days):

| Test | Difference | 95% range | One-sided p | Holm threshold | Significant? |
|---|---|---|---|---|---|
| B, `tbs_5_2` PR-AUC | +0.0075 | [+0.0015, +0.0134] | 0.0055 | 0.00625 | **yes** |
| B, `up_given_move` ROC-AUC | +0.0126 | [+0.0016, +0.0234] | 0.013 | 0.0083 | no |
| A, `up_given_move` ROC-AUC | +0.0485 | [−0.0015, +0.0955] | 0.028 | 0.0125 | no |
| A, `tbs_5_2` PR-AUC | +0.0012 | [−0.0160, +0.0188] | 0.427 | 0.025 | no |

## 2. Trading: top 5 a day on each arm's `tbs_5_2` score (2022; ₹50,000 per trade; +5% / −2% / 5 sessions)

| Arm | Trades | Net / trade: optimistic | **Net / trade: base** | Net / trade: conservative | Per fold, base: Q1 / Q2 / Q3 / Q4 | TARGET % | STOP % | Profit factor |
|---|---|---|---|---|---|---|---|---|
| B0 | 1,206 | −0.54% | **−0.68%** | −0.95% | −0.58 / −1.00 / −0.23 / −0.93 | 24.5 | 69.0 | 0.63 |
| A | 1,205 | −0.14% | **−0.28%** | −0.55% | −0.12 / −0.61 / +0.37 / −0.81 | 29.4 | 64.0 | 0.83 |
| B | 1,203 | −0.35% | **−0.49%** | −0.75% | −0.50 / −0.82 / +0.05 / −0.70 | 26.9 | 66.3 | 0.72 |

**Arm − B0, per trade** (date-clustered bootstrap, 10,000 resamples):

| Arm | Difference | 95% range | One-sided p |
|---|---|---|---|
| A | +0.40% | [+0.20%, +0.61%] | 0.000 |
| B | +0.19% | [+0.02%, +0.36%] | 0.011 |

**Extreme-trade audit** (the 10 best and 10 worst trades per arm against the raw bars): **CLEAN** for B0, A and B.

## 3. Keep / drop (§7, applied once)

| Group | K1: Holm-significant ranking gain | K2: trading not worse (pooled, and ≥ 3 of 4 folds) | K3: no fold PR-AUC loss > 0.01 | **Verdict** |
|---|---|---|---|---|
| A: market regime | ✗ (p 0.028 and 0.427) | ✓ (4 of 4) | ✗ (Q2: −0.029) | **DROPPED** |
| B: sector-relative strength | ✓ (`tbs_5_2`, p 0.0055) | ✓ (4 of 4) | ✓ | **KEPT** |

## 4. What the result says, and does not say

- **Group B carries a small, real ranking improvement** on target-before-stop. It is significant after Holm correction, consistent across all four folds, and not worse in trading. It is the first feature group in this programme to pass a pre-registered keep rule.
- **Group A is dropped, although it has the largest trading gain** (+0.40% per trade, 95% range +0.20% to +0.61%).
  - Its direction gain (ROC-AUC 0.549 vs 0.501, at least 0.55 in every fold) is large but not significant after correction. Regime values change only by day, so a year has few independent observations.
  - It also lost 0.029 PR-AUC in 2022Q2.
  - The keep rule was fixed before the run so that a result like this would **not** be acted on because it looks attractive afterwards.
  - Testing regime again needs a new pre-registration, recorded as a second look at 2021–22, or better, a period that hasn't been used.
- **No arm is profitable.** The best is A at −0.28% per trade.
  - The trade breaks even at roughly a 32% target-first rate; A reaches 29.4% and B 26.9%.
  - The only candidate under §8 is B0 + B, and its development net is −0.49% per trade. **Nothing qualifies for the sealed test.**
- **Secondary results (descriptive):**

  | Measure | B0 | A | B |
  |---|---|---|---|
  | `net_pos_5_2` PR-AUC (base 0.303) | 0.296 | 0.310 | 0.305 |
  | Up-share among movers in the top 5% by direction score | 0.563 | 0.526 | 0.570 |
  | M7 logistic: `tbs_5_2` PR-AUC | 0.242 | 0.236 | 0.240 |
  | M7 logistic: `up_given_move` ROC-AUC | 0.539 | 0.523 | 0.524 |

  The logistic model gains nothing from either group.

## 5. Limits

- 2022 is the second use of these folds; H#32 used them first.
- Survivorship: current Nifty 500 members only.
- Zerodha's 2026 cost schedule is applied retroactively.
- `vol_ratio_250` was dropped in 14 early fits because it didn't exist yet (logged).
- Development-period effects are necessary, not sufficient, evidence.

Registry: **#33 (group A) DROPPED**, **#34 (group B) KEPT** for a future combined model, 2026-09-19.
