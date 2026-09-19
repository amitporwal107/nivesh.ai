# Roadmap v2, Phase 4 — groups A (market regime) and B (sector-relative strength): pre-registration (DRAFT)

**Status: DRAFT — awaiting owner approval. No feature in this document has been computed on real data, and no model has been fitted with it.**

| Item | Value |
|---|---|
| Owner documents | `MODEL_IMPROVEMENT_PLAN_2026-09-19.md` §4 A–B; roadmap v2 Phase 4 ("add feature groups incrementally so their contribution can be measured") |
| Baseline | The H#32 model specification, M8 (`PREREGISTRATION_P2_P3.md`, FROZEN 50fe02fd). Development result: `DEV_RESULTS.md`, where H#32 was CLOSED at development |
| Registry | #33 = group A, #34 = group B |
| Scope | **Development block only (2021–22).** The sealed Jan 2023 – Jul 2024 block is not read, and nothing here can spend it |

## 1. Question

Does either group, added **on its own** to the 44 baseline features, improve:
- (a) the **direction** of large moves; or
- (b) the **target-before-stop** ranking,

enough to be kept for a future combined model?

Why these two groups first:
- The H#32 development run found a weak directional tilt beyond volatility, but a +5% / −2% trade needs about a 32% target-first rate to break even, while the best top-5% reached 28.4%.
- Market regime and relative strength are the owner's two direction-oriented groups, and the APARINDS case named their absence as a limitation.

**What this experiment can decide:** keep or drop each group. It makes **no profitability claim**, and it cannot send anything to the sealed test (§8).

## 2. Data (development block only)

- **Rows and labels:** exactly the H#32 development dataset (`dataset_dev_20260919T212230.csv.gz`, sha256 `7bb77e5a…b327`), with the same eligibility, entries, labels and costs. The new columns are joined on (symbol, date).
- **Stock bars:** Kite adjusted daily bars, cut at 2022-12-30 (the same `dataset.load_bars` guard), for the same universe (current Nifty 500 minus ETFs; survivorship bias disclosed).
- **Index bars:** NIFTY 500, NIFTY 50 and INDIA VIX from Kite for **2019-07-01 … 2022-12-30**.
  - The 2019-07 … 2020-12 range is fetched so that 200-session index features exist from January 2021.
  - It lies before the development block and touches no sealed data.
  - It needs one Kite call per index, with a valid access token.
- **Sector:** the Nifty 500 list's `Industry` (20 industries; median members per day range from 3 in Diversified to 81 in Financial Services).

## 3. Features (cutoff: the close of D; every value uses bars dated on or before D only)

**Returns:** `ret_k` = close(D) / close(k calendar sessions before D) − 1. If the stock has no bar on either date, the value is NaN.

**Peers:** the other universe members of the stock's industry that have both bars. This is leave-one-out, so the stock itself never counts toward its own sector value. If there are fewer than 3 peers, the value is NaN.

### Group A — market regime (16 features, identical for every stock on a day)

| Feature | Definition |
|---|---|
| `mkt_ret5`, `mkt_ret20`, `mkt_ret60` | NIFTY 500 returns |
| `mkt_dist_sma50`, `mkt_dist_sma200` | NIFTY 500 close / its 50- and 200-session average − 1 |
| `mkt_adx14` | Wilder ADX(14) on NIFTY 500 high/low/close (the existing `technical_ext.wilder_adx`) |
| `mkt_vol20` | Standard deviation of NIFTY 500 daily returns over 20 sessions |
| `mkt_vol_ratio` | That 20-session standard deviation ÷ the same over 100 sessions |
| `mkt_gap1`, `mkt_range1` | NIFTY 500 open(D) / close(D−1) − 1; (high − low) / close(D−1) |
| `vix_close`, `vix_chg5` | INDIA VIX close; its 5-session change (ratio − 1) |
| `breadth_sma20`, `breadth_sma50` | Share of universe stocks with a bar on D whose close is above their own 20- or 50-session average (a stock needs that many bars to count) |
| `breadth5` | Mean of the existing one-day `breadth` over the last 5 sessions |
| `size_rot20` | NIFTY 50 `ret20` − NIFTY 500 `ret20` |

Group A cannot reorder stocks within a day by itself; it can only act through interactions with stock features. That is a known limit, stated here rather than discovered later.

### Group B — sector-relative strength and stock-relative momentum (14 features)

| Feature | Definition |
|---|---|
| `rs_mkt5`, `rs_mkt20`, `rs_mkt60` | Stock `ret_k` − NIFTY 500 `ret_k` |
| `sec_ret5`, `sec_ret20`, `sec_ret60` | Equal-weight mean `ret_k` of the stock's peers |
| `rs_sec5`, `rs_sec20`, `rs_sec60` | Stock `ret_k` − `sec_ret_k` |
| `sec_rank20` | Percentile rank of the industry's equal-weight 20-session return (all members) among the industries on D |
| `sec_breadth20` | Share of peers above their own 20-session average |
| `rel_vol_sec` | Stock volume(D) / its mean over the prior 20 sessions, minus the peers' median of the same ratio |
| `mom_rank20`, `mom_rank60` | Cross-sectional percentile of `ret20` / `ret60` across the universe on D |

**Rules that apply to both groups:**
- No other feature, transformation or window may be added after approval.
- A group whose definition turns out to be uncomputable is reported as such. It is not silently redefined.

## 4. Models (identical rows, folds, embargo, eligibility, costs and seed 20260919)

| Arm | Features | Model |
|---|---|---|
| **B0 baseline** | the 44 v4 features | M8 specification (HistGradientBoosting: max_iter 300, lr 0.05, max_leaf_nodes 31, l2 1.0, no early stopping); the per-fit drop of never-observed columns |
| **A** | 44 + group A (60) | same |
| **B** | 44 + group B (58) | same |
| Secondary (descriptive only) | the same three feature sets | the M7 logistic specification |

- **Reproducibility check:** the B0 out-of-fold predictions must equal the H#32 development out-of-fold file (`dev_oof_20260919T214001.csv.gz`, column `M8|tbs_5_2`) to within 1e-12. If they don't, the run stops, and nothing is reported as a result.
- No hyperparameter changes and no search.

## 5. Labels

| Role | Label |
|---|---|
| Primary: trade outcome | `tbs_5_2`, P(target first), as in H#32 |
| Primary: direction | `up_given_move`, UP vs DOWN among rows that moved ±5% within 5 sessions (`dir_5_5d` ∈ {UP, DOWN}) |
| Secondary (descriptive) | `dir_5_5d` (UP vs rest), `net_pos_5_2`, `hit_high_10_5d` |

## 6. Evaluation (development walk-forward: the four 2022 quarters, as in H#32)

**Per arm vs B0:**
- pooled PR-AUC on `tbs_5_2`;
- pooled ROC-AUC on `up_given_move`;
- both of those per fold;
- top-5-a-day trading under the `tbs_5_2` rule (mean and median net per trade, target and stop rates, profit factor) under the three cost scenarios;
- the up/down share within the top 5% by the arm's `dir_5_5d` score.

**Uncertainty:** a paired, date-clustered bootstrap of the arm − B0 difference, resampling 2022 decision days (seed 20260919):
- 2,000 resamples for the AUC metrics;
- 10,000 for the per-trade means.

## 7. Keep / drop rule (applied once per group, on development)

A group is **KEPT** only if all of K1–K3 hold. Otherwise it is **DROPPED**.

| # | Criterion |
|---|---|
| K1 | Either ranking improvement is significant: the ROC-AUC on `up_given_move` **or** the PR-AUC on `tbs_5_2` is above B0, with the bootstrap lower bound of the difference > 0 after Holm correction across the four tests (2 groups × 2 metrics, α = 0.025 one-sided) |
| K2 | Trading is not worse: top-5 mean net per trade ≥ B0's, both pooled and in at least 3 of 4 folds (base costs) |
| K3 | Stability: in no fold is the arm's `tbs_5_2` PR-AUC below B0's by more than 0.01 |

**Once a group is dropped:**
- Its definitions may not be modified and re-run on this development data.
- A new definition needs a new pre-registration and is recorded as a second look at 2021–22.

## 8. What happens after (not decided by this experiment)

A combined model (B0 plus any kept groups) may be proposed for the sealed test **only through its own pre-registration and owner approval**, and only if its development walk-forward shows all three of:
- (i) top-5 mean net per trade > 0, with a bootstrap 95% lower bound > 0 at base costs;
- (ii) > 0 at conservative costs;
- (iii) both halves of 2022 > 0.

That is the H#32 criteria 1, 3 and 4 applied to development. Given the H#32 development result (−0.68% per trade), passing is unlikely, and that is stated in advance.

## 9. Known limits

- **2022 has already been looked at once.** The development folds were used for H#32, and its baseline numbers are known. The features above were fixed from the owner's plan and standard definitions, without looking at how any of them behave in 2022.
- **Short history:** stock history starts in 2021, so 2021-trained folds see fewer 60-session and 200-session values.
- **Regime changes are rare** in one development year, so a regime effect may be real but unmeasurable here. A DROP of group A means "no measurable development benefit", not "regime doesn't matter".
- **Sector sizes:** small industries (Diversified, Media, Textiles) will often have NaN sector features.

## 10. Prohibited

- Any change to definitions, windows, peers, thresholds or model settings after the first arm result is seen.
- Adding arms after the fact.
- Reading any bar after 2022-12-30.
- Using the sealed block in any way.

## 11. Deliverables and order

1. Fetch the index history (NIFTY 500, NIFTY 50 and INDIA VIX for 2019-07-01 … 2022-12-30), with the block assert.
2. `features_p4.py`, with synthetic tests before any real run:
   - hand-computed values for every feature;
   - leave-one-out and the 3-peer minimum;
   - future-shock invariance (changing bars after D leaves D's values unchanged);
   - a guard that stops any bar after 2022-12-30 from being read;
   - deliberate code breaks, checked to be caught by the tests.
3. `phase4.py` runner (reusing `walkforward.py`), with the B0 reproducibility assert. It runs once, committed first.
4. `P4_AB_RESULTS.md`: keep/drop per group, an extreme-trade audit for any arm's top-5, and registry #33/#34.
