# Phase 1 screeners — pre-registration (discovery period only)

**Status: FROZEN at the commit that adds this file, before any result is computed.** Owner's screener plan of
2026-09-19 (Phase 1 + "first three": volatility expansion, breakout, gap-down recovery). Registry families #23–#26.

## Rules that bind this study
1. **Discovery data only: 2024-08-01 → 2026-09-18.** Loaders drop every row before 2024-08-01, so indicator
   warm-up also uses discovery data only. 2021–22 is used (H-A, H-B); **2023-01 → 2024-07 stays sealed and unread**.
2. Discovery results are **research-candidate** evidence at most (owner's five gates). A screener that passes here
   becomes a validation candidate; it is not a trading signal.
3. Each screener is evaluated **separately**. No combined score until each has been validated on its own.
4. **H-B (09:45 early confirmation) is not re-tested**: it failed its sealed test. H-C and H-D below are new rules;
   H-D was suggested by the sealed H-B section 8 table, so it is registered as such.
5. Data: Kite daily bars (back-adjusted, certified) and Kite 5-minute bars (certified top 800); Nifty 500 index daily
   from Kite. Universe: **current** Nifty 500 members (survivorship-limited). Kite data: internal use only.
6. Costs: cost model v1 by 20-day traded value — > Rs 100 cr 0.20%, Rs 25–100 cr 0.30%, Rs 5–25 cr 0.40% round trip;
   every economic result also at 2× costs.

## Features (known at the close of day t; no future data)
ATR14% (Wilder ATR / close) · ATR14% expanding median (strictly before t, ≥ 60 sessions) · RVOL = volume_t / mean
volume of t-20..t-1 · VALUE20 = mean close × volume over t-19..t · RANGE10 = (max high − min low over t-10..t-1) /
close_t-1 and its expanding percentile in the stock's own history (≥ 60 sessions) · TR_t / ATR14_t-1 · HI20, HI55 =
max high over t-20..t-1 / t-55..t-1 · EMA20, EMA50 · close position in the day's range · RS20 = stock 20-session
return − Nifty 500 20-session return · regime = Nifty 500 close above its 50-session average.

## Screeners (signal at the close of day t)
| # | Screener | Rule |
|---|---|---|
| 23 | **A — Volatility expansion** | ATR14% > its own median · RVOL ≥ 1.5 · RANGE10 percentile ≤ 30% (compressed before) · TR_t ≥ 1.5 × ATR14_t-1 (range expansion today) · VALUE20 ≥ Rs 5 cr · close ≥ Rs 50 |
| 24 | **B — Breakout with confirmation** | close_t > HI20 · RVOL ≥ 1.5 · close in the top 25% of the day's range · close > EMA20 and close > EMA50 · RS20 > 0 · VALUE20 ≥ Rs 5 cr · close ≥ Rs 50. Variant **B55**: close_t > HI55 instead of HI20 |
| 25 | **H-C — Recovery after the initial low** (intraday, 5-minute) | Gap ≤ −3% at the open vs the previous close (Kite adjusted), VALUE20 ≥ Rs 5 cr. From the 09:20 bar to the 10:25 bar, the first bar whose close is ≥ 1.01 × the running session low **and** above cumulative session VWAP → buy at the next bar's open; stop at the running low at entry (touch → exit at the stop, or at the bar open if it opens through it); otherwise exit at the official close. One entry per signal |
| 26 | **H-D — Gap-down continuation** (intraday, short) | Gap ≤ −3%, VALUE20 ≥ Rs 5 cr, and at 09:45 the 09:40 bar close is < 0.995 × open **and** below VWAP (the set H-B rejected) → sell short at the 09:45 bar open; stop +2% (touch → exit at the stop, or at the bar open if it opens through it); otherwise buy back at the official close |

## Labels and outcomes (separate for 5% and 10%, never mixed)
Daily screeners (A, B, B55), entry at the next open:
- **L5_1 / L10_1**: high_t+1 ≥ close_t × 1.05 / 1.10 (the v4 model's label).
- **L5_5 / L10_5**: max high over t+1..t+5 ≥ close_t × 1.05 / 1.10.
- Tradable: MFE / MAE from the t+1 open; **net 1-day** = close_t+1 / open_t+1 − 1 − cost; **net 5-day** =
  close_t+5 / open_t+1 − 1 − cost. Downside label D5_1: low_t+1 ≤ close_t × 0.95 (movement is not direction).
Intraday (H-C, H-D): net trade return per the exits above; MFE / MAE from entry.

## Incremental value over a volatility baseline (the key question)
Baseline = logistic regression of each label on [log ATR14%, log TR_t%, log VALUE20], refit at the start of each month
on labels fully known before that month (expanding window, time-ordered). For each screener and label:
**O/E = observed hits / expected hits among its signals**, 95% CI by whole-session bootstrap (2,000 draws).
O/E > 1 with the CI above 1 = the screener adds information beyond volatility.

## Reported for every screener
Candidates and signals (per session: median, max) · P(label) and base rate · O/E vs baseline · mean net per
session (sessions with ≥ 1 signal, equal weight within a session), Newey-West t (5 lags), session bootstrap CI, 2×
costs · MFE / MAE · by liquidity bucket · by regime · by half (2024-11..2025-09 vs 2025-10..2026-09) · top-5 / top-10
session share of P&L · signals per session (capacity).

## Pass / abandon (discovery stage)
- **Movement information**: O/E(L5_1) 95% CI lower bound > 1.0.
- **Economic**: mean net 1-day (A, B, B55) or net trade (H-C, H-D) per session > 0 with NW 95% lower bound > 0, and
  still > 0 at 2× costs.
- **Abandon** if: the economic CI includes 0; the two halves disagree in sign; the effect exists only in Rs 5–25 cr;
  or the top-10 sessions supply > 50% of P&L.
A screener with movement information but no economic edge is kept only as a **monitoring / feature** screener.

Multiple testing: 26 families registered after this file; 4 new here with 5 labels and 2 cost levels each. A single
t ≈ 2 is expected by chance. Results go to `PHASE1_RESULTS.md`, run once at the commit after this one.
