# G1 gap-down sleeve — pre-registered result (2026-09-19 04:25 IST)

**Verdict: ABANDONED under pre-registered abandon condition 3** (effect only in the Rs 50L–5cr liquidity bucket, not
> Rs 5cr → liquidity artefact). The primary endpoint itself passed. Registered rules: `PREREGISTRATION.md` (`ea040cd6`).

## Data (all validated)
- Sleeve built on **Kite's real gaps** (adjusted prev close → next open), which implements the registered
  `next_open / prev_close_adj − 1`; the raw panel's gaps held 11.5% phantom gaps (`INTRADAY_SOURCE_EVALUATION.md`
  Addenda 5–6). 3,588 pairs; minute bars present for all.
- Two-step same-session validation: minute 09:15 open == Kite daily open for **3,558 of 3,588 (99.2%)**.
- Gate 3 (lower-circuit open: open == day low at a −5/−10/−20% band) excluded **430** pairs, as registered.
  ⚠️ That exclusion is large (12%) and may remove some of the strongest recoveries — worth its own look.
- Evaluated: 3,128 pairs, 469 sessions (ATR-based: 2,539 / 453 after the ATR budget). Cost 0.25% flat.
- Discovery period (2024-08..2026-09). **Not out-of-sample.**

## Primary resolution (as registered: daily OHLC of the trade session; both levels touched → stop)
| variant | n | sessions | target hit | stop hit | mean/session | 95% NW CI | t |
|---|---|---|---|---|---|---|---|
| CONSERVATIVE +2/−1.5 | 3,128 | 469 | 70.5% | 50.4% | −0.0429% | [−0.1409, +0.0551] | −0.86 |
| **MODERATE +3/−2 (primary)** | 3,128 | 469 | 56.9% | 42.4% | **+0.3349%** | **[+0.1945, +0.4754]** | **+4.67** |
| EXTENDED +5/−3 | 3,128 | 469 | 33.9% | 31.6% | +0.6633% | [+0.4687, +0.8579] | +6.68 |
| ATR-based 0.75/0.50×ATR | 2,539 | 453 | 55.0% | 44.3% | +0.3371% | [+0.1820, +0.4922] | +4.26 |
Target and stop percentages overlap because a session can touch both (counted as the stop).
Secondaries at Bonferroni α 0.0125: EXTENDED and ATR-based pass; CONSERVATIVE fails.

**Secondary (deviation, labelled): minute-resolved order, bar-open fills below the stop** — CONSERVATIVE +0.3467%
(t 6.82), MODERATE +0.5883% (t 8.50), EXTENDED +0.7289% (t 7.40), ATR-based +0.5027% (t 6.79). The registered
both-touched → stop rule is the conservative one.

Close-only on the same pairs: +0.7887%/session, CI [+0.4785, +1.0989], t 4.98.

## Abandon conditions (section 7), MODERATE
| # | condition | result | |
|---|---|---|---|
| 1 | primary CI includes 0 | no | pass |
| 2 | 2025 and 2026 disagree in sign | 2024 +0.4077% (t 2.51, 76 sess) · 2025 +0.4125% (t 3.99, 225) · 2026 +0.1981% (CI [−0.0359, +0.4320], t 1.66, 168) | pass |
| **3** | **effect only in Rs 50L–5cr, not > Rs 5cr** | **Rs 50L–5cr +0.8952% (t 7.38); > Rs 5cr +0.0549%, CI [−0.0942, +0.2040], t 0.72** | **ABANDON** |
| 4 | median qualifying stocks/session < 3 | median 5 (25.6% of sessions below 3) | pass |

## Risk profile (per-session equal-weight; Sharpe ×√250; max drawdown on summed session returns)
| | mean | NW CI | day-bootstrap CI | Sharpe | worst session | max DD | profit factor | median trade | sessions won |
|---|---|---|---|---|---|---|---|---|---|
| MODERATE | +0.335% | [+0.194, +0.475] | [+0.206, +0.463] | 3.81 | −2.25% | −13.3% | 1.84 | −0.22% | 59.1% |
| close-only | +0.789% | [+0.478, +1.099] | [+0.500, +1.074] | 3.94 | −9.43% | −23.1% | 2.09 | +0.58% | 60.8% |
A Sharpe near 4 in names this thin is itself a warning that fills and costs are too optimistic.

**Outlier dependence:** without the 5 / 10 busiest gap days +0.345% / +0.350%; without the 5 / 10 best sessions
+0.309% / +0.282% (t 4.40 / 4.07). Not outlier-driven (the top-20 cap limits any single market day).

## Timing study (descriptive, same validated pairs; 2,967 trades, 463 sessions)
- **The low comes first:** median time of the day's low = **2 minutes after 09:15**; 53.4% by 09:20, 68.3% by 10:00,
  76.5% by 11:30. Median time of the high: 18 minutes.
- MAE by 10:00 median −1.17% (day −1.64%); MFE by 10:00 median +2.71% (day +3.50%).
- **Stops from the open fire in the opening noise:** −2% stop hit 44.3%, 79.3% of hits before 10:00, median hit
  time 1 minute, 49.2% of hits inside the 09:15 bar; 24.5% of stopped trades closed above entry, 48.9% above the stop.
  −1.5%: hit 52.4%, 54.0% inside the 09:15 bar.
- Fills worse than the stop are rare: 1.1–2.4% of hits, mean extra loss 0.3–0.5%.
- **Early weakness persists:** close return by drawdown at 10:00 — < −5%: −4.95% (closed up 14.5%); −5..−3%: −1.49%;
  −3..−2%: −0.18%; −2..−1%: +0.89%; −1..−0.5%: +1.61%; > −0.5%: +3.60% (closed up 83.4%).

**Implication:** the delayed-stop hypothesis ("give it room, it recovers") is contradicted — names deep underwater by
10:00 keep falling. The evidence points instead to **early confirmation before entry** (G2–G5), measured from the later
entry price. That is a NEW hypothesis: pre-register it and test it on 2021..2024-07.

## What survives, and what is next
- **Abandoned:** G1 with target/stop (all variants), per the registered rule.
- **Exploratory, not validated:** close-only in liquid names (> Rs 5cr: +0.697%, t 3.94 on the real-gap sleeve before
  gate 3); early-confirmation entry. Both need their own pre-registration.
- **Decisive test:** the untouched 2021-01..2024-07 period (Kite daily already pulled; minute or 5-minute bars for its
  gap-down sessions need one more login).
- **Execution realism before any further claim:** a liquidity-dependent cost and slippage model (the result lives in thin
  names, where 0.25% flat is least realistic).

Trade-level files: `/app/research/kite_history/gapdown_minute_v2/g1_pairs_validated.pkl`, `timing_trades_v2.pkl`.

---

## Addendum (2026-09-19 ~05:15 IST) — gate 3 used future information; verdict unchanged
Gate 3 (lower-circuit open) was implemented as "open == the **day's** low at a band". The day's low is known only at
the close, so the 430 exclusions used future information (and removed stocks that never traded below the open —
biasing returns down). Re-run of the registered primary with look-ahead-free definitions:

| gate 3 definition | excluded | MODERATE all | > Rs 5cr | Rs 50L–5cr | abandon condition 3 |
|---|---|---|---|---|---|
| as run: day low == open (look-ahead) | 430 | +0.335% (t 4.67) | +0.055% (t 0.72) | +0.895% (t 7.38) | triggers |
| **entry-time: first-minute low == open** | 491 | +0.332% (t 4.67) | **+0.056% (t 0.75)** | +0.891% (t 7.26) | **triggers** |
| no gate 3 (not the registered rule) | 0 | +0.402% (t 5.96) | +0.167% (t 2.32) | +0.901% (t 8.15) | would not trigger |

**Verdict unchanged: ABANDONED** under the registered rule implemented without look-ahead. Dropping gate 3 is not
permitted after seeing results; a no-gate variant would be a new hypothesis. For Track 1 the exclusion is defined on
information available at 09:15 only (open at a band), see `track1/TRACK1_SCOPE_v1.md`.
