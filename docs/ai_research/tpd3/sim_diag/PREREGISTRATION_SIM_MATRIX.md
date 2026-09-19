# Pre-registration — simulation comparison matrix (deliverable D5)

**Status:** FROZEN at the commit that adds this file. Nothing below may change after that commit. One run.
**Date:** 2026-09-20.
**Authority:** the owner approved `prd/Consecutive_Session_Simulation_Diagnostic_PRD_v1.0.md` as drafted on
2026-09-20 — its §19 items 1–4, which freeze the replay window, the entry models of §10, the stop and target models
of §11, the portfolio settings and matrix of §12, and keep Phase 4 C/D paused until D6.
**Precedes:** the run. If this document and the code disagree, the run is void.

---

## 1. What this run is, and what it is not

It is a **diagnostic attribution**, not a hypothesis test. H#32 lost money (−0.78% net per trade, verified in D3/D4).
This run splits that loss into selection, entry, stop/target, cost and allocation, by changing **one thing at a time**
against a baseline that has already been reconciled against an independent implementation.

- **No configuration in this matrix is a candidate strategy**, and none is being validated. Every number is
  descriptive, on development data that has already been used.
- **No rule may be adopted because it scores best here.** A configuration that looks better only says where to point
  the next hypothesis, which needs its own pre-registration and out-of-sample test (owner policy
  `TPD model success gates`, 2026-09-19).
- **The sealed 2023-01..2024-07 block is not touched.** The guarded loader asserts it.

## 2. Frozen inputs (identical to the D1–D4 run `run_20260920T003043`)

| Input | sha256 |
|---|---|
| dataset `dataset_dev_20260919T212230.csv.gz` | `7bb77e5ad50f4bf6a6db54527bc6a90437701e9d5bc5d36a87f4b187e0f9b327` |
| out-of-fold predictions `dev_oof_20260919T214001.csv.gz` | `8763f064b35b633332db6c60bfdd36dbc3b8cf65bd3c83bb7eafb0ef38650569` |
| picks `dev_picks_M8_20260919T214001.csv` | `d05cccc241be6a55217b2557dc82657befd1420894b8e5c339f387caa0d3281b` |
| isotonic calibration `iso__M8__tbs_5_2.pkl` | `1f1b22c567634f597dfaad4d006612e0af10d3637e24704fdae53f928e1c0597` |

- Predictions commit: `a499ce19b22000756da00fc813b3aa27c8e18f9a`. Model M8, label `tbs_5_2`.
- Bars: Kite daily, re-read raw and checked against the dataset before use (D1 check, must stay green).
- Cost model: `zerodha-equity-v1`, applied retroactively to 2022, as in every earlier run.
- Sectors: the Nifty 500 list's Industry column (the same map as Phase 4 group B).

## 3. Sessions and universe

- **Full year:** every 2022 decision session in the dataset's development block (242 sessions).
- **Replay window:** 2022-10-03 → 2022-11-01, 20 sessions, including the Diwali Muhurat session 2022-10-24. It is a
  strict subset of the year and is reported separately for the hand-checked audit, never as a separate result.
- **Eligible pool** on a session: the dataset rows of that session with `entry_status` computable — i.e. the same
  candidate set the H#32 picks were drawn from. The pool is used for the rank bands and for control G.
- Selection for A–F and H: the frozen M8 top-5 per session, exactly the 1,210 picks already reproduced in D1.

## 4. The matrix (single run, nothing tuned between runs)

Baseline conventions for every fixed-notional run: ₹50,000 per trade, at most 5 sessions, time exit at the last
available close in s1..s5, stop-first on an ambiguous bar, slippage from the **decision day's** value20 bucket
(the H#32 convention), participation not capped, costs on.

| Run | Selection | Entry | Stop | Target | Sizing | Costs | Isolates |
|---|---|---|---|---|---|---|---|
| **A** | M8 top 5 | s1 open | 2% | 5% | ₹50,000 | on | baseline (reconciled in D3) |
| **B** | M8 top 5 | s1 open | 1.5 × ATR(14) | 2R | ₹50,000 | on | stop/target |
| **C** | M8 top 5 | buy-stop at D high + 0.1%, s1 only | 2% | 5% | ₹50,000 | on | entry |
| **D** | M8 top 5 | s1 open | 2% | 5% | risk engine, **no allocation caps** | on | sizing |
| **E** | M8 top 5 | s1 open | 2% | 5% | ₹50,000 | **off** | cost drag |
| **F** | M8 top 5 | s1 open | 2% | 5% | risk engine, **all caps** | on | full realism |
| **G** | **random 5 per session**, 200 seeds | s1 open | 2% | 5% | ₹50,000 | on | selection vs execution |
| **H** | M8 top 5 | s1 open | **none** | **none** | ₹50,000, 5-session hold | on | the stop/target rule itself |

**Secondary rows** (same baseline, one change each; reported below the matrix, never used to pick a winner):

| Row | Change |
|---|---|
| S1 STRUCTURE | stop = lowest low of the 10 sessions to D, less 0.1%, bounded 1–8% below entry; target 2R |
| S2 VOL_ADJ | stop = entry × (1 − 1.5 σ20), σ20 = stdev of daily returns over the 20 sessions to D, bounded 1–8%; target 2.5R |
| S3 LIMIT | entry = limit at D close × 0.995, s1 only; fills at min(open, limit) when the s1 low reaches it |
| S4 VWAP_PROXY | entry = s1 (high + low + close) / 3. **An approximation**: true VWAP needs intraday data |
| S5 POOL | every eligible candidate of every session under A's rules (the rank-band and G reference set) |

**Entry rejections** (any run): no s1 bar; s1 open locked at the upper circuit; stop ≥ entry; target ≤ entry; and for
C, S3 the order's own no-fill reasons. **Max chase is not applied in the matrix**, because configuration A (the
reconciled baseline) does not apply it; the chased-gap cases are reported through RC-1 `ENTRY_FAILURE` instead.

### 4a. Control G — random selection

- Same sessions, same eligible pool, 5 draws per session without replacement, `numpy.random.default_rng(20260920 + k)`
  for seeds k = 0..199, drawn after sorting the pool's symbols so the draw does not depend on row order.
- Every drawn (symbol, session) is simulated under A's rules. Reported: the distribution over the 200 seeds of net per
  trade, and A's percentile in it.

### 4b. Runs D and F — the portfolio loop

- Engine: `tpd_model/risk/engine.py`, MOO orders, `max_sessions = 5`, breakeven and trailing **off**
  (`breakeven_at_r`, `trail_at_r` set above any reachable R), `cost_estimate_pct_for_sizing = 0.5`.
- Sizing uses the signal's reference price (the D close) and its 2% stop. **At the fill**, the stop and target are
  reset to the fill's raw base × 0.98 and × 1.05, so D and F carry the same levels as A.
- Risk configurations, capital ₹5,00,000, FIXED basis, no leverage, no compounding:

| Setting | F (all caps) | D (no allocation caps) |
|---|---|---|
| risk per trade | 0.5% (baseline), also 1.0% and 2.0% | same |
| max positions | 8 (baseline), also 5 | 50 (effectively unlimited) |
| stock cap | 20% | 100% |
| sector cap | 40% | 100% |
| deployed cap / cash reserve | 100% / 0% | 100% / 0% |
| portfolio risk cap | 5% | 100% |
| participation, min value20, min price | 5%, ₹5 crore, ₹50 | same |
| stop distance bounds | 1–8% | same |
| daily/weekly loss pause, drawdown reduction, kill switch | **off** (they would truncate the diagnostic) | off |
| averaging down | not allowed (a second signal in an open symbol is rejected) | not allowed |

- The 3 risk levels × 2 position limits give 6 F variants; the baseline F is 0.5% / 8. D is run at the same 3 risk
  levels with the caps removed. **The variants are reported as a sensitivity table, not as candidates.**

## 5. Metrics — defined before the run

Per run, over trades that were entered:

- `trades`, `no_entry` (with reasons), `win_rate` = net > 0.
- `gross_per_trade`, `net_per_trade`: mean of the per-trade return on the buy value. **Fixed-notional runs report per
  trade and in rupees only.** A "% of ₹5,00,000" figure is invalid for them (config A alone needs up to ₹8.98 lakh at
  once) and is not reported.
- `cost_drag` = gross_per_trade − net_per_trade, split into slippage and statutory charges.
- `profit_factor` = sum of positive net ÷ |sum of negative net|; `expectancy` = mean net in rupees per trade.
- `max_drawdown`: **portfolio runs only** (D, F), on the engine's daily equity curve, peak-to-trough, in ₹ and % of
  ₹5,00,000. For fixed-notional runs the equivalent is reported as the worst cumulative net over the trade sequence in
  rupees, labelled `worst_cumulative_net`, and **not** called a drawdown.
- `peak_capital_required`: the largest simultaneous buy value (fixed-notional runs).
- `exit_mix`: TARGET_HIT, STOP_HIT, GAP_THROUGH_STOP, TIME_EXIT, LIQUIDITY_EXIT, unresolved.
- `stop_distance_atr` median, `ambiguous_bars`, `gap_through` count.
- RC-1 primary cause counts and net by cause (rule set version fixed in `audit.py`).
- Paired comparison to A over the common trades: mean difference in net per trade with a date-clustered bootstrap
  (2,000 resamples, dates as clusters) and a 95% interval. **Descriptive**: no p-value, no accept/reject, because the
  baseline has already been shown to lose and nothing here is being selected.

### 5a. Tax (annex only)

Pre-tax is primary. The tax line is an **annex**, computed only where the run's net is positive, at both regimes,
because the trades are 2022 and the cost model is 2026: STCG **15% + 4% cess** (the law in 2022) and **20% + 4% cess**
(after 2024-07-23). No surcharge, no set-off, no carry-forward. Every tax figure is labelled illustrative.

## 6. Interpretation rules, fixed in advance (the owner's, from PRD §12)

| Comparison | Reads as |
|---|---|
| A vs E | the cost drag |
| A vs D, D vs F | the allocation effect: sizing first, then the caps |
| A vs B (and S1, S2) | the stop and target rule |
| A vs C (and S3, S4) | the entry rule |
| A vs H | whether the stop/target rule helps at all against a plain hold |
| A vs G | whether the selection is worth anything against random picks under the same execution |
| rank bands within S5 | whether the score orders outcomes at all |

- If **every** configuration is negative, the conclusion is that the loss is in the signal (direction), not in
  execution — and Phase 4 C/D, which adds features to the same signal, stays paused pending the owner's call.
- A configuration that is positive **is not a result**. It is a candidate hypothesis for a fresh pre-registration.

## 7. Governance

- **One run**, from committed code, with the tree clean (the runner refuses a dirty tree). Failed attempts are
  recorded in the results document, as in D1–D4.
- The run writes a results folder with a sha256 manifest, outside git.
- **No permutation grid.** The Lab design's 1,300-configuration sweep is *not* part of this study: it is a
  forking-paths hazard. If it is ever run it needs its own pre-registration, a trials ledger, a multiplicity
  adjustment, and it may only run on data that has not been used to choose anything.
- **Known engine defects are not fixed in this run** (D7 decision pending): the circuit-lock heuristic's false
  positives and the blocked-stop recovery, both recorded in the D1–D4 results. Their reach is bounded and reported per
  run as `lock_affected_trades`; the D3 finding that they make the baseline loss *larger*, not smaller, still stands.
- Nothing in this run touches production crons, the pinned forward worktrees, or any database.

## 8. Scorecard rubric (thresholds fixed here, applied unchanged)

Four separate scores, never combined. Each is PASS / WATCH / FAIL.

| Score | PASS | WATCH | FAIL |
|---|---|---|---|
| **A. Data quality** | 0 failing sessions, 0 cutoff violations, 0 raw duplicates, ≥ 99.5% valid bars | any unreviewed flag class on a traded bar | any integrity failure, any cutoff violation, any duplicate |
| **B. Signal** | top-5 net per trade > 0 **and** above the 95th percentile of the 200 random seeds | positive but inside the random distribution | not positive, or at or below the random median |
| **C. Execution** | reconciliation unexplained = 0, ambiguous bars < 5%, no unexplained no-fill | ambiguous 5–10% | any unexplained mismatch, or ambiguity > 10% |
| **D. Risk and allocation** | realised loss ≤ 1.5 × planned risk on ≥ 95% of losers, no cap breach, max drawdown < 15% | 1–5% of losers beyond 1.5 × planned | any cap breach, or > 5% beyond 1.5 × planned risk |

**Expected before the run** (stated so the run cannot be read charitably afterwards): A PASS, B FAIL, C PASS,
D WATCH-or-PASS. If B comes out anything other than FAIL, that is a surprise and must be audited before it is
reported, including the extreme-trade audit that caught the ETF artefact on 2026-09-19.

## 9. Acceptance criteria for the run itself

- Configuration A reproduces the D3 numbers exactly (same trades, same net per trade, same reconciliation summary).
- No sealed-block bar is read.
- Every trade of every run carries its `prediction_id`, entry, stop, target, exits and bars used.
- Every rejected candidate carries a reason.
- Deliberate code breaks in the new matrix code are caught by its tests.
- The extreme-trade audit (the 10 largest gains and losses of every run) is clean, or the run is not reported.
