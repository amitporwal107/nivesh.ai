# Positional study — results (the single pre-registered run)

**Verdict: all six arms CLOSED** (E1, E2, E3, C-E2, C-E3, D1). The rule in PREREGISTRATION.md §7 was applied once, and the extreme-trade audit was clean for every arm. No arm reaches validation-candidate status; the sealed period (Jan 2023 – Jul 2024) stays untouched.

## Run identity

| Item | Value |
|---|---|
| Pre-registration | `PREREGISTRATION.md`, FROZEN at fe60155f (owner-approved 2026-09-19 20:21 IST) |
| Runner code | a4f37562 (tests on synthetic data only, committed before the run) |
| Audit script | 4ccaaeae (committed 20:31, before any result) |
| Recorded commit | `code_commit` in the results file = f481368c. HEAD moved during the run because a plan document was committed; `git diff a4f37562 f481368c -- research/positional backend` shows only `audit.py` added, so the executed code is a4f37562. |
| Run time | 2026-09-19 20:30–20:39 IST (521 s) |
| Output | `/app/research/positional/results_20260919T203933.json`, sha256 `8e3871975d7550e62bd457b7c390760bae7a937a2ed2d49c2fbae10b0823f080`; audit in `results_20260919T203933_audit.json` |
| Configuration | RISK-POS-1 (hash `2289cfcf…58f0`), zerodha-equity-v1 applied **retroactively** (flagged), 200 seeds |
| Data | 255,390 daily bars, 498 symbols, 2024-08-01 → 2026-09-18 (discovery only, asserted) |

## 1. Primary results (₹5,00,000 fixed capital)

| Arm | Signals | Closed trades | Net return | Gross before charges | Charges | Max DD | Sharpe | Newey-West t | Win % | Profit factor | Mean / median net R |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 pre-breakout buy-stop | 8,259 | 393 | **−11.03%** | −5.41% | ₹28,094 | 15.3% | −1.20 | −1.61 | 42.2 | 0.75 | −0.10 / −0.17 |
| E2 pullback | 3,379 | 447 | **−13.75%** | −6.54% | ₹36,070 | 15.9% | −1.13 | −1.50 | 38.9 | 0.76 | −0.12 / −0.24 |
| E3 55-day breakout | 2,115 | 443 | **−14.40%** | −8.55% | ₹29,274 | 15.5% | −1.48 | −2.36 | 42.2 | 0.69 | −0.11 / −0.11 |
| C-E2 pullback, close entry | 3,229 | 346 | **−12.29%** | −6.77% | ₹27,616 | 15.4% | −1.19 | −1.58 | 39.9 | 0.70 | −0.12 / −0.17 |
| C-E3 breakout, close entry | 2,109 | 391 | **−14.86%** | −9.86% | ₹24,959 | 15.4% | −1.79 | −2.29 | 40.4 | 0.63 | −0.13 / −0.18 |
| D1 results reaction | 463 | 288 | **−7.98%** | −3.69% | ₹21,423 | 12.7% | −0.81 | −1.09 | 40.6 | 0.80 | −0.09 / −0.20 |

- "Gross before charges" still includes slippage in the fill prices.
- **Kill switch:** the 15% drawdown switch fired in five arms, and those arms took no new entries afterwards, as registered:
  - E1 from 2026-07-23;
  - E2 from 2025-12-04;
  - E3 from 2026-02-01;
  - C-E2 from 2025-08-08;
  - C-E3 from 2025-10-10;
  - D1 never.
  So E2, E3, C-E2 and C-E3 traded for only part of the period. Every decision criterion also fails on the trades they did take (mean R < 0, not above the random maximum).
- **Exits:** mostly the 5-session time exit (69–87%). Gap-through stops were 1.4–4.3% of exits. Breakeven or trailing stops were live on 5–14% of trades.

## 2. Decomposition (PREREGISTRATION.md §6)

| Arm | Selection: arm mean R vs 200 random-entry runs (median / p99 / max), percentile | Risk management: net without stops | Costs: 2× slippage | Market: beta; daily alpha (t) |
|---|---|---|---|---|
| E1 | −0.099 vs −0.175 / 0.017 / 0.043, **83rd** | −8.92% (stops cost 2.1 pp) | −11.21% | 0.12; −0.021% (−1.77) |
| E2 | −0.118 vs −0.187 / 0.049 / 0.134, **76th** | −13.01% (stops cost 0.7 pp) | −12.62%* | 0.16; −0.026% (−1.69) |
| E3 | −0.113 vs −0.116 / −0.049 / −0.030, **56th** | −13.32% (stops cost 1.1 pp) | −14.08%* | 0.10; −0.027% (−2.56) |
| C-E2 | −0.118 vs −0.167 / −0.035 / −0.016, **77.5th** | −11.07% (stops cost 1.2 pp) | −12.23%* | 0.13; −0.023% (−1.76) |
| C-E3 | −0.128 vs −0.077 / −0.002 / 0.019, **8th** | −15.30% (stops helped 0.4 pp) | −14.94%* | 0.08; −0.028% (−2.46) |
| D1 | −0.092 vs −0.096 / 0.014 / 0.019, **52.5th** | −2.84% (stops cost 5.1 pp) | −8.89% | 0.10; −0.015% (−1.13) |

\*With the kill switch the equity path is path-dependent: changing slippage moves the kill date and hence the set of trades, so a stress run can lose slightly less than the primary.

**What the decomposition says:**
- **Selection.**
  - No arm beats all 200 random-entry runs (criterion 2); the best, E1, sits at the 83rd percentile.
  - E1, E2 and C-E2 rank above the random median, which is weak and non-significant evidence of better-than-random entries.
  - C-E3 is worse than random; E3 and D1 are indistinguishable from it.
- **Risk management does not create an edge.** Random entries under the identical rules also lose (median mean R −0.08 to −0.19). Stops and trailing made results worse in five of six arms, most of all in D1, where stops turned −2.8% into −8.0%. On these setups, stops mostly cut trades that would have recovered by the time exit.
- **Costs are not the root cause.** Every arm is negative before charges (−3.7% to −9.9% of capital). Delivery charges add another 4.3–7.2 points (roughly doubling the loss in E1 and D1): STT is 0.1% on each side, and the DP charge is ₹15.34 per sale.
- **Market.** Low beta (0.08–0.16) and negative alpha in every arm. The losses are not the market's direction.

## 3. Decision rule (§7): criteria per arm

| Criterion | E1 | E2 | E3 | C-E2 | C-E3 | D1 |
|---|---|---|---|---|---|---|
| 1 Net > 0 with Newey-West t ≥ 2.4 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| 2 Mean R above all 200 random runs | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| 3 Alpha t ≥ 2.4 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| 4 Both halves > 0 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| 5 Net > 0 at 2× slippage | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| 6 ≥ 100 closed trades | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Verdict** | **CLOSED** | **CLOSED** | **CLOSED** | **CLOSED** | **CLOSED** | **CLOSED** |

No arm meets criterion 2, so none qualifies for "monitoring only".

## 4. Extreme-trade audit (§7, owner rule after H-A)

The 10 best and 10 worst closed trades of every arm (120 trades) were checked against the raw daily bars:
- entry and exit prices inside the session's range (plus slippage);
- volume on both sessions;
- no close-to-close move above 20% in the window;
- no ETF.

**All six arms CLEAN.** The results are not driven by data artefacts.

## 5. Implementation notes (readings of the frozen text, fixed before the run)

- **E2 "first up day":** t is up (close > previous close and close > open) and t−1 was not.
- **E2 volume:** the t−4…t−1 average is compared with the 20-session average before t.
- **C arms:**
  - relative strength uses the Nifty 500's 20-day return to t−1, because there are no intraday index bars;
  - eligibility uses value20 as of t−1;
  - E3's volume test compares volume to 15:15 with the 20-day average of volume to 15:15.
- **Random control for E1:** MOO on the arm's fill session (the arm itself enters on a buy-stop).
- **D1 mapping:** 3,841 earliest-original broadcasts; 29 excluded as AV-1 contradictions; 16 had no bar on the reaction session; 463 triggered.

## 6. Limitations

- Current Nifty 500 members only (survivorship).
- Zerodha's 2026-09-19 schedule applied to 2024–26 (retroactive, flagged).
- Discovery data only.
- The kill switch truncated four arms' samples. That was the registered policy, and the rule's criteria fail on the pre-kill trades as well.
- The owner's later additional comparisons (v4 top-ranked picks, momentum baseline, movement-only and market-only models) were not in this frozen design. They belong in the next pre-registered experiment (Model Improvement Plan, roadmap v2).

## 7. Consequence for the roadmap

This run directly tests the owner's question: "is it costs, entry or two-way movement, or are we missing risk management and allocation?"
- With early entries, positional holds, full risk management, sizing and realistic costs, every setup still loses **before costs**.
- Random entries under the same rules lose too, and stops do not help.

**The missing ingredient is a directional edge**, not risk management or allocation. That matches roadmap v2's thesis: the next work is target redesign (target-before-stop and close-based labels), directional baselines against movement-only, momentum and random controls, and point-in-time data. Adding more rules or indicators to these setups is not the next step.

Registry families #27–#31: **CLOSED 2026-09-19**.
