# Comparison matrix — D5 run and D6 root-cause report (2026-09-20)

**Run:** `matrix_20260920T045039` (data in `/app/research/sim_diag/`, not in git; sha256 manifest in the folder).
**Code:** `60145a53`, run from a clean detached checkout so the tree could not move under it.
**Pre-registration:** `PREREGISTRATION_SIM_MATRIX.md`, frozen at `ffa0a139` **before** the run, under the owner's
approval of the PRD as drafted (2026-09-20).
**Development data only:** 2022 decision sessions, bars ≤ 2022-12-30 through the guarded loader. The sealed
2023-01..2024-07 block was not read.

## Acceptance gate (§9)

| Check | Result |
|---|---|
| Configuration A reproduces the D3 baseline | **1,206 of 1,206 trades, max net difference 0.0**, no exit-date or exit-reason mismatch |
| Bars re-read from the raw Kite files reproduce the dataset | pass |
| The ranking reproduces the frozen picks | 1,210 of 1,210 |
| RC-1 reproduces the audited D4 cause table (replay, A) | identical |
| Extreme-trade audit | clean: **0 ETF-like trades**; the 20 extremes are 7.8% of absolute P&L |

## The matrix, full year 2022 (1,206 baseline trades)

| Run | What it changes | Trades | Gross/trade | **Net/trade** | Cost drag | Win rate | Profit factor | Net ₹ | vs A (95% CI) |
|---|---|---|---|---|---|---|---|---|---|
| **A** | baseline: next open, −2%, +5%, ₹50k | 1,206 | −0.25% | **−0.78%** | 0.52% | 27.5% | 0.60 | −4,66,282 | — |
| **B** | stop 1.5×ATR, target 2R | 1,206 | −0.16% | **−0.68%** | 0.53% | 41.5% | 0.76 | −4,09,364 | +0.09% (−0.33, +0.51) |
| **C** | entry: buy-stop at D high +0.1% | 508 | −0.88% | **−1.41%** | 0.53% | 16.7% | 0.33 | −3,57,264 | −1.92% (−2.23, −1.63) |
| **D** | risk sizing, no allocation caps | 591 | −0.35% | **−2.05%** | 1.69% | 25.0% | 0.62 | −2,97,787 | −1.44% (−1.82, −1.13) |
| **E** | **costs off** | 1,206 | −0.25% | **−0.25%** | 0.00% | 28.9% | 0.84 | −1,51,196 | +0.53% (+0.52, +0.53) |
| **F** | risk engine, all caps | 594 | −0.36% | **−1.63%** | 1.27% | 25.8% | 0.63 | −2,88,761 | −1.02% (−1.33, −0.76) |
| **G** | **random 5 a day**, 200 seeds | 240,970 | −0.10% | **−0.58%** | 0.48% | 30.6% | 0.65 | — | +0.00% |
| **H** | no stop, no target, 5-session hold | 1,206 | −0.06% | **−0.59%** | 0.53% | 43.0% | 0.79 | −3,50,866 | +0.19% (−0.28, +0.67) |

Secondary rows: S1 structure stop −0.79%, S2 volatility-adjusted stop −0.82%, S3 limit entry −0.60% (891 entries),
S4 VWAP proxy −1.51%, S5 the whole eligible pool −0.60% (84,926 trades).

**Every configuration loses money. Not one is positive, gross or net.**

## What the comparisons say (the readings were fixed in §6 before the run)

**1. Costs are half the loss, and removing them does not make the rule profitable.**
A vs E: 0.53 percentage points a trade. Turning costs off leaves **−0.25%** a trade. The edge is not hiding under
the charges.

**2. The selection is worse than random.** This is the finding that matters.
Control G drew 5 stocks a session from the same eligible pool, 200 times, and ran them through A's exact execution
rules. The seeds average **−0.58%** a trade; A is **−0.78%**, at the **0.5th percentile** of that distribution —
worse than 199 of the 200 random selections. Scorecard B: **FAIL**, as pre-registered.
The rank bands say the same thing: ranks 6–10 (−0.48%) do better than the top 5 (−0.78%), and the whole pool
(−0.60%) does better than both. **The score is ordering trades the wrong way round.**

**3. The stop and target rule is not the problem.**
B (ATR stop, 2R target) and H (no stop or target at all) are both statistically indistinguishable from A — their
intervals straddle zero. H raises the win rate from 27.5% to 43.0% and still loses 0.59% a trade. Changing where the
stop sits moves money between causes; it does not create any.

**4. The entry filter makes it worse.**
C only enters when the stock trades through the previous day's high plus 0.1%: 508 of 1,210 entries, and the ones it
takes are **worse** (−1.41%, −1.92pp vs A). Waiting for confirmation buys the continuation after the move.

**5. Allocation does not save it either.**
D and F lose **−59.6%** and **−57.8%** of a ₹5,00,000 account over the year, with maximum drawdowns of **62.2%** and
**60.3%**. Their rejections are dominated by `INSUFFICIENT_CASH` (374 / 350) and `DUPLICATE_EXPOSURE` (181) — the
same symbol is picked again while it is still held, 181 times.

## RC-1: where configuration A's money went (1,206 trades)

| Primary cause | Trades | Net |
|---|---|---|
| STOP_FAILURE (stopped with the stop inside 1 ATR) | 555 | −₹6,95,937 |
| VOLATILITY_TRAP (stopped, then reached the target anyway) | 172 | −₹2,14,926 |
| DATA_FAILURE (a flagged or failed bar in the trade's window) | 61 | −₹1,63,423 |
| ENTRY_FAILURE (chased a gap over 2%) | 36 | −₹43,947 |
| RISK_FAILURE (lost more than 1.5× the planned risk) | 10 | −₹23,626 |
| WIN | 332 | +₹6,93,588 |

The ten largest losses are all **TTML**, exiting `LIQUIDITY_EXIT` — the January 2022 run of lower circuits the D3
reconciliation already identified, where the position could not be sold for days.

## Three things the run exposed that are not results

**1. The F risk sweep measures nothing.** 0.5%, 1.0% and 2.0% risk per trade produce **byte-identical** trade files
at 8 positions, and again at 5. The 20% stock cap (₹1,00,000) binds before the risk rule does at every level — the
median position is ₹98,771. Only the position count changes anything (5 positions: −₹2,73,939; 8: −₹2,88,761). A
real risk sweep needs a stock cap wide enough for the risk rule to bite, or a tighter stop.

**2. The portfolio runs' per-trade averages are distorted by micro positions.** With no cash reserve, once the
account is deployed the engine keeps entering with whatever cash is left: 19% of D's trades (113) are under ₹5,000,
the smallest **₹54**, on which the fixed ₹15.34 DP charge is **28% of the position**. They cost only ₹1,774 in
rupees but drag the per-trade mean from −0.67% to −2.05%. **Read D and F on rupees and on the equity curve, not on
their per-trade mean.** Excluding positions under ₹5,000: D −0.67%, F −0.60%. The engine needs a minimum order
value; it has a minimum price but not a minimum notional.

**3. `cost_drag` is not on one basis across the matrix.** The trade-isolated runs measure gross before slippage, so
their drag is slippage plus charges; the engine's fills carry slippage inside the price, so D's and F's drag is
charges only. Each run now states its basis in the results file. Only the **net** figures compare across the two
families.

## Scorecard (rubric fixed in §8, before the run)

| Score | Verdict | Evidence |
|---|---|---|
| **A. Data quality** | **PASS** | 0 failing sessions, 0 cutoff violations, 0 raw duplicates (D1) |
| **B. Signal** | **FAIL** | net per trade negative and at the 0.5th percentile of the random control |
| **C. Execution** | **PASS** | 0 unexplained reconciliation differences; ambiguous bars 1.2%; every rejection carries a reason |
| **D. Risk and allocation** | **WATCH** | 10 trades lost more than 1.5× planned risk (gap-throughs and circuit locks); no cap was breached; D/F drawdowns ~60% |

The pre-registration recorded the expectation "A PASS, B FAIL, C PASS, D WATCH-or-PASS" before the run. That is what
came out, so nothing here is a surprise that needs re-auditing.

## What this means for the programme

The pre-registration fixed this reading in advance: **if every configuration is negative, the loss is in the signal,
not in execution.** That is the case, and the random control makes it sharper than "no edge" — the selection is
**actively worse than random** under these execution rules, because it picks the most volatile stocks in the pool
and a −2% stop sits inside their normal daily range (median 0.45 ATR, D4).

Consequences, none of which may be decided from this run alone:
- **Phase 4 C/D (breakout quality, tradeability) stays paused.** Both add features to the same signal whose ordering
  is inverted; a better-fitting model of the same target is not the missing piece.
- **No configuration in this matrix is a candidate.** The ones that look less bad (H, B, ranks 6–10) are ideas for a
  fresh pre-registration on unused data, not results.
- The 2023-01..2024-07 sealed block was not touched and is still available for one use.

## Governance

- One run, from committed code, clean tree, single output folder with a sha256 manifest.
- Attempts are recorded: an earlier complete run (`matrix_20260920T043631`, code `2045b7ec`) passed the same
  acceptance gate but did not record the per-trade prices or the RC-1 causes, so it was rerun after those were
  added. Two `--smoke` plumbing runs before it caught a `DataFrame.flags` name collision and NaN reaching the
  results file. One smoke attempt failed with no engine trades and was **not** reproducible on identical code and
  inputs; a mutated `matrix.py` left in the shared worktree by a parallel mutation harness is the likely cause, and
  every reporting run since has executed from its own pinned checkout.
- No permutation grid was run (§7).
- The D7 engine defects (the circuit-lock heuristic's false positives, the blocked-stop recovery) are **not** fixed
  in this run and still await the owner's decision. Their direction is known from D3: fixing them makes the loss
  larger, not smaller.
