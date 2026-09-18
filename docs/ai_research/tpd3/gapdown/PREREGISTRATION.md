# Pre-registration — Gap-down sleeve (G1) + target/stop grid

**Registered:** 2026-09-18 (before any G1 or grid result was computed)
**Registrant:** Claude Opus 5, on owner instruction
**Supersedes nothing.** Independent of the v5 net-return pre-registration.

Results computed before this file's commit timestamp DO NOT COUNT.

## 1. Motivation and the ONE prior result

Exploratory analysis on the 511-session bhavcopy panel found that stocks opening
**≤ −3% below the prior close** averaged **+1.86% intraday**, hit +5% at **18.17%**
vs a **2.24%** base rate (8× lift), and returned **+0.39%/session net of 0.25% costs
(t = +3.50, 501 sessions, 54.7% of sessions positive)**.

**This is in-sample and exploratory.** It was found after many tests on one panel.
Year splits: 2024 **−0.03% (t = −0.14)**, 2025 **+0.57% (t = +3.07)**, 2026 **+0.35% (t = +2.33)**.
Liquidity splits: ₹50L–5cr **+0.69% (t = +4.10)**, >₹5cr **+0.31% (t = +2.35)**.
The liquid-bucket survival is what distinguishes it from the rejected overnight variant
(which was t = 18.4 in illiquid and t = 0.56 in liquid names — a bid-ask artefact).

This registration exists to test it honestly, not to confirm it.

## 2. Hypothesis (H1)

A portfolio entering at the official open of stocks gapping ≤ −3%, subject to liquidity
and data-quality gates, earns a **positive mean net return per session** after 0.25% costs.

## 3. Selection rules — FIXED

**Deliberate design decision:** the EOD model ranking is **NOT** a selection input.

Rationale, stated in advance: the prior result was measured on *all* gap-down stocks with no
ranking applied. The EOD model selects for high ATR, and the ATR ≥ 5% cohort loses
**−0.56%/session (t = −9.21, n = 136,431)**. Intersecting opposing filters risks destroying
the effect while shrinking ~17 stock-days/session to a handful, removing the power to detect
anything. Whether the EOD rank adds value on top is a SEPARATE question (H2, section 8).

Gates, all evaluated at the open:
1. `gap_pct = next_open / prev_close_adj - 1 <= -3.0%`
2. `turn20 >= ₹50,00,000` (20-day average turnover)
3. Bar exists; `open > 0`; not a lower-circuit open (open == low at a band)
4. No unexplained-jump / unfactored corporate-action flag on the entry bar
5. **ATR eligibility:** reject if required stop distance > risk budget (see 4)
6. Equal rupee weight per position. Max 20 positions/session; if more qualify, take the
   **most negative gaps** (deterministic, no discretion).

## 4. ATR eligibility — the stop-loss redesign

The v1 engine computed `stop = entry − min(1.5×ATR, 8%)`, which hit the 8% cap on 9 of 10
picks, giving R:R 0.625 by construction.

**Replacement rule:** the risk budget REJECTS the candidate; it never silently caps the stop.

```
required_stop_dist = k_atr * ATR14 / entry
if required_stop_dist > risk_budget:  REJECT (reason = ATR_EXCEEDS_RISK_BUDGET)
else:                                 stop = entry * (1 - required_stop_dist)
```

## 5. Target/stop grid — FIXED, tested as a grid, no post-hoc winner

| Variant | Target | Stop | Risk budget |
|---|---|---|---|
| CONSERVATIVE | +2.0% | −1.5% | 1.5% |
| MODERATE | +3.0% | −2.0% | 2.0% |
| EXTENDED | +5.0% | −3.0% | 3.0% |
| ATR_BASED | 0.75 × ATR | 0.50 × ATR | 3.0% |

All targets/stops are relative to **entry price**, not prior close.
Exit resolution on daily OHLC: a gap through a level exits at that session's **open**;
a session touching both counts the **stop** (conservative). Horizon = intraday close of
the entry session (G1 v1 is a single-session strategy).

## 6. Primary endpoint and decision rule

**Primary:** mean per-session net return, MODERATE variant, over the walk-forward period.
**Success:** mean > 0 AND lower bound of the 95% Newey-West HAC CI > 0.
**All four variants are reported regardless of outcome.** The primary is fixed as MODERATE
in advance precisely so a winner cannot be chosen after the fact.

**Multiple-testing:** 4 variants. Any secondary variant is Bonferroni-corrected (α = 0.0125).

## 7. Abandon conditions — declared in advance

Abandon G1 if ANY holds:
- Primary endpoint CI includes 0
- 2025 and 2026 disagree in sign
- The effect exists only in the ₹50L–5cr bucket and not >₹5cr (→ liquidity artefact)
- Median qualifying stocks/session < 3 (too thin to trade)

## 8. Secondary question (H2) — NOT the primary

Does the EOD model rank add value ON TOP of the gap gate? Tested only after H1 concludes,
reported separately, never substituted for the primary if H1 fails.

## 9. Known limitations, stated up front

- G2–G5 and intraday exits are **not testable** (60-day Yahoo cap; see INTRADAY_SOURCE_EVALUATION.md)
- Daily OHLC cannot resolve intra-session path order (touched-both → stop assumed; conservative)
- Bhavcopy panel: NSE_BHAVCOPY 2025-01-01+, NSE_SEC_BHAVDATA 2024-05-31..2024-12-31
- No slippage model beyond the flat 0.25% cost; gap-down opens may fill worse than printed
