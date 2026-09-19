# Roadmap v2, Phases 2–3 — development walk-forward results (owner checkpoint)

**Status: H#32 CLOSED at the development stage.** Owner decision on 2026-09-19 (~21:55 IST): option B, "close at dev". The locked test (Jan 2023 – Jul 2024) was **not run**; no 2023–24 bar has been read, and the block stays sealed.

The decision on H#32 is reserved for the locked test. Every number below comes from the development block (2021–22) and **decides nothing** on its own. It is here so the owner can decide at this checkpoint whether the one-use sealed period should be spent on H#32.

## Run identity

| Item | Value |
|---|---|
| Pre-registration | `PREREGISTRATION_P2_P3.md`, FROZEN at 50fe02fd |
| Dataset builder | 10758e8f: 28 synthetic tests; 13 of 13 deliberate code breaks caught by the tests |
| Walk-forward runner | 15e4f25c + a499ce19: 11 synthetic tests; 9 of 9 deliberate code breaks caught |
| Dataset | `dataset_dev_20260919T212230.csv.gz`, sha256 `7bb77e5a…b327`<br>198,945 rows, 426 symbols, 490 sessions (2021-01-01 → 2022-12-22)<br>Last bar read 2022-12-30; last label date 2022-12-29 |
| Walk-forward output | `dev_results_20260919T214001.json`, sha256 `9d9934f4…766b`<br>Out-of-fold predictions `dev_oof_20260919T214001.csv.gz` |
| Frozen models | 103 files in `/app/research/model_v5/models_20260919T214001/`, hashed in `MODELS_FROZEN_20260919T214001.json` (this commit) |
| Folds | 2022 Q1–Q4, expanding window, 5-session embargo; see the table below |

| Fold | Training rows | Last training date | Validation rows |
|---|---|---|---|
| 2022Q1 | 60,483 | 2021-12-24 | 20,951 |
| 2022Q2 | 81,339 | 2022-03-24 | 21,535 |
| 2022Q3 | 102,994 | 2022-06-23 | 21,935 |
| 2022Q4 | 124,746 | 2022-09-23 | 20,505 |

**First attempt stopped at its first fit.** No result was produced or seen.
- `vol_ratio_250` needs 251 bars, and the Kite data starts on 2021-01-01, so the column is entirely missing in the 2022Q1 training rows. scikit-learn's gradient boosting cannot fit an all-missing column.
- Fix (a499ce19): a gradient-boosting fit now drops any column missing in all its training rows, and logs the drop. Such a column carries no information for that fit.
- This affected 18 fold-level fits (`vol_ratio_250`, and `dist_sma200` in early inner fits). The final models dropped nothing.

## 1. The dataset (development block, rows that could be traded)

- **Rows that could be traded:** 147,068, i.e. eligible on D with an entry at the s1 open.
- **Primary label base rates:**

  | Outcome | Share |
  |---|---|
  | TARGET first | 21.2% |
  | STOP first | 62.9% |
  | Expired | 15.9% |

- **Mean net return per trade over all these rows:** −0.50%. Gross before costs: −0.03%.
- **2022 average net return by outcome:**

  | Outcome | Mean net |
  |---|---|
  | TARGET | +4.54% |
  | STOP | −2.53% (worst −20.1%, a gap-through) |
  | EXPIRED | +0.76% |

  So the +5 / −2 trade breaks even at roughly a **32% TARGET rate**.
- **Excluded as upper-circuit-locked opens:** 653 eligible rows (0.44%).
  - The frozen rule (`risk/execution.py`: open = high at a 2/5/10/20% band, ±0.25 points) also catches ordinary stocks that opened about 2% up and never traded above the open.
  - Every model loses these slots equally ("missed, no entry").
  - They are therefore likely to be slightly unfavourable rows, and the absolute net returns are slightly flattered.

## 2. Prediction quality (pooled 2022 out-of-fold, rows that could be traded)

| Label | Base rate | M1 random, PR-AUC | M3 volatility, PR-AUC | M4 movement, PR-AUC | M7 logistic, PR-AUC | **M8 gradient boosting, PR-AUC** | M8 precision at top 1% (lift) |
|---|---|---|---|---|---|---|---|
| hit_high_5_1d | 5.1% | 0.052 | 0.118 | 0.127 | 0.140 | **0.144** | 29.2% (5.7×) |
| hit_high_10_5d | 8.0% | 0.079 | 0.168 | 0.174 | 0.168 | **0.174** | 33.2% (4.2×) |
| hit_close_5_5d | 18.6% | 0.185 | 0.272 | 0.274 | 0.267 | **0.272** | 48.5% (2.6×) |
| **tbs_5_2** (TARGET) | 20.2% | 0.201 | 0.243 | 0.247 | 0.242 | **0.239** | 32.4% (1.6×) |
| tbs_10_4 (TARGET) | 7.2% | 0.071 | 0.140 | 0.145 | 0.138 | **0.140** | 24.4% (3.4×) |
| net_pos_5_2 | 30.3% | 0.303 | 0.286 | 0.294 | 0.329 | **0.296** | 25.0% (0.8×) |
| dir_5_5d (UP) | 27.8% | 0.276 | 0.375 | 0.378 | 0.373 | **0.369** | 53.9% (1.9×) |

- The complete table covers all 10 labels × M0–M9, with ROC-AUC, Brier and precision at the top 1% / 5% / 10%. It is in the results JSON.
- **Movement is predictable; trade outcome much less so.**
  - Touch labels reach 3–6× lift, as before.
  - Volatility alone (M3) gets most of that lift.
  - On the primary label, M8 (0.239) is no better than volatility alone (0.243) or the movement model (0.247).
  - On `net_pos_5_2`, M8 is below the base rate. Only M7 shows a trace of skill there (PR-AUC 0.329 vs 0.303).
- **Weak directional tilt** (post-hoc, descriptive, development data: not a pre-registered test).
  - Among each model's top 5% by `dir_5_5d` score, the share of up-moves among stocks that moved ±5% is:

    | Selection | UP / (UP + DOWN) |
    |---|---|
    | All rows | 0.486 |
    | M1 random | 0.487 |
    | M3 volatility | 0.498 |
    | M4 movement | 0.543 |
    | **M8** | **0.563** |
    | M9 two-stage | 0.517 |

  - So the v4 features carry some directional information beyond volatility, about +6 to +7 points. It is not enough to overcome a 5-to-2 payoff that needs a 32% TARGET rate.
- **Calibration.**
  - Raw M8 probabilities for `tbs_5_2` are over-confident at the top in 2022:

    | Predicted | Realised | Rows |
    |---|---|---|
    | 0.30–0.40 | 25.8% | 6,797 |
    | 0.40–0.50 | 27.9% | 1,961 |
    | 0.50–0.70 | 34.2% | 500 |

    2021 had higher target rates than 2022.
  - The isotonic calibrator is fitted on these same out-of-fold rows. Its gaps on them are ~0 by construction, so the development criterion-6 check is uninformative; it can only be judged on the test.

## 3. Trading: top 5 a day on each model's `tbs_5_2` score (2022, equal weight, ₹50,000 per trade, 5-session cap)

| Model | Trades | Missed | Net / trade: optimistic | **Net / trade: base** | Net / trade: conservative | Win % | Profit factor | TARGET % | STOP % | Portfolio* | Max DD* |
|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 random | 1,205 | 5 | −0.44% | **−0.56%** | −0.78% | 30.5 | 0.67 | 20.9 | 63.7 | −23.7% | 23.9% |
| M2 momentum | 1,190 | 20 | −0.41% | **−0.50%** | −0.69% | 28.5 | 0.72 | 27.2 | 71.0 | −21.4% | 22.5% |
| M3 volatility | 1,201 | 9 | −0.74% | **−0.84%** | −1.04% | 24.0 | 0.56 | 22.1 | 75.2 | −33.3% | 33.7% |
| M4 movement-only | 1,197 | 13 | −0.40% | **−0.54%** | −0.80% | 29.2 | 0.70 | 27.7 | 69.3 | −22.8% | 22.8% |
| M5 market-only† | 1,207 | 3 | −0.37% | **−0.48%** | −0.70% | 31.2 | 0.71 | 22.8 | 62.9 | −20.9% | 21.6% |
| M6 sector-only† | 1,209 | 1 | −0.35% | **−0.44%** | −0.63% | 31.3 | 0.74 | 23.7 | 65.7 | −19.5% | 21.5% |
| M7 logistic | 1,201 | 9 | −0.70% | **−0.82%** | −1.06% | 24.8 | 0.57 | 23.1 | 74.1 | −32.9% | 32.9% |
| **M8 gradient boosting (primary)** | 1,206 | 4 | −0.54% | **−0.68%** | −0.95% | 27.4 | 0.63 | 24.5 | 69.0 | −28.1% | 28.4% |
| M9 two-stage | 1,193 | 17 | −0.30% | **−0.42%** | −0.66% | 30.3 | 0.76 | 28.8 | 68.8 | −18.3% | 18.6% |
| All tradable rows | 84,926 | – | – | **−0.60%** | – | – | – | 20.2 | – | – | – |
| Nifty 500 buy-and-hold, 2022 | – | – | – | – | – | – | – | – | – | +3.0% | – |

\* Realised basis: 25 sleeves of 4% each; P&L is booked on the exit day.

† M5 gives every stock the same score on a day, and M6 every stock in a sector, so their top 5 is largely the seeded tie-break, i.e. random.

- **Every selection loses after costs**, under every cost scenario. None is distinguishable from random except M3 and M7, which are worse.
- **The model's top picks concentrate in high-volatility names.** Those names reach the target more often (24.5% vs 20.9% for random) but hit the stop even more (69% vs 64%), and seldom expire.
  - Break-even needs a TARGET rate of about 32%.
  - M8's top 5% pooled across the year reaches only 28.4% TARGET, with a mean net of −0.36%.
- **Extreme-trade audit** of M8's 10 best and 10 worst trades against the raw bars: **CLEAN**. Checks:
  - entry and exit inside the bar range ± 0.4%;
  - volume on both sessions;
  - no close-to-close move above 20% in the window;
  - no ETF.

**Conditional matrix** (M8 picks, mean net per trade):

| Condition | Result |
|---|---|
| Market regime | Nifty 500 above its 200-day average −0.78% (801 trades); below −0.48% (405) |
| Volatility tercile | low −0.83%, mid −0.82%, high −0.62% |
| Slippage bucket | 0.05% −0.87%, 0.10% −0.83%, 0.20% −0.49% |
| Opening gap | <−1% −0.72%, −1..0% −0.75%, 0..1% −0.70%, >1% −0.51% |

No cell is positive.

## 4. H#32 criteria computed on development out-of-fold data (descriptive only)

| # | Criterion | Development value | Would pass? |
|---|---|---|---|
| 1 | Mean net > 0 with date-clustered bootstrap 95% lower bound > 0 | −0.68% [−0.89%, −0.46%] | ✗ |
| 2 | Beats M1 / M2 / M4, Holm-corrected | Differences −0.12% / −0.18% / −0.14% per trade; one-sided p = 0.85 / 0.91 / 0.89 | ✗ |
| 3 | Mean net > 0 at conservative costs | −0.95% | ✗ |
| 4 | Both halves > 0 | H1 −0.79%, H2 −0.56% | ✗ |
| 5 | No sector > 40% of net P&L | Total net P&L negative (−8.19 trade-units; Financial Services −2.35) | ✗ (undefined for a loss) |
| 6 | Calibration gap < 5 points in buckets ≥ 100 | In-sample isotonic: trivially ~0; raw gaps up to 16 points | uninformative |

## 5. Readings of the frozen text for the owner to confirm (fixed before any fit; listed in `walkforward.py`)

1. **tbs labels:** P(TARGET) vs STOP or EXPIRED.
2. **Direction label:** `dir_5_5d` is fitted as UP vs DOWN or NONE; AMBIGUOUS rows (0.19%) are excluded.
3. **M9 stage 2:** fitted on UP vs DOWN rows only, with the stage-1 out-of-fold prediction as a 45th feature.
4. **Trading selection:** happens at D's close among all eligible rows. A pick whose s1 open turns out untradable is a missed slot, never replaced.
5. **M1:** one seeded draw.
6. **Bootstrap:** 10,000 date resamples; the lower bound is the 2.5th percentile; Holm on one-sided p at 0.025.
7. **Ranking and calibration:** ranking uses raw scores; isotonic calibration is used for probabilities and criterion 6 only.
8. **Never-observed columns:** dropped per gradient-boosting fit (see Run identity).
9. **Circuit-lock exclusions:** the frozen rule's false positives are disclosed in §1.

## 6. Checkpoint decision (owner)

The development walk-forward fails every applicable H#32 criterion by a clear margin:
- M8 is worse than random selection on 2022 out-of-fold data;
- its 95% bound is entirely below zero;
- both halves are negative.

The locked period is the last untouched block and can be used **once**.

| Option | What it means |
|---|---|
| **A. Run the locked test as pre-registered** | It gives a clean, final verdict on H#32, very likely CLOSED. It uses up the last sealed period for a hypothesis the development data already rejects. |
| **B. Close H#32 at the development stage** (recommended) | H#32 is recorded as "failed in development; locked test not spent". The Jan 2023 – Jul 2024 block stays sealed for a future hypothesis that first shows a positive development result. The frozen models and hashes stay on file. |

Either way, the next step on the roadmap is Phase 4: market regime, sector-relative strength, breakout quality and tradeability features, each with its own pre-registration. That work is informed by the weak directional tilt in §2 and by the finding that the +5 / −2 payoff needs a TARGET rate of about 32%.

**Decision (owner, 2026-09-19): B.**
- H#32 is CLOSED: it failed in development, and the locked test was not spent.
- The frozen models and hashes remain on file.
- The Jan 2023 – Jul 2024 block remains sealed and single-use.
