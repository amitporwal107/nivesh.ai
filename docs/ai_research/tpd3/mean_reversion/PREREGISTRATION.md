# Short-term mean reversion E1–E5 — pre-registered 2026-09-17 12:16 IST, before any mean-reversion code, query or result

Source: the user's instruction of 2026-09-17 ("Setup E — Short-Term Mean Reversion", variants E1–E5, required comparisons,
metrics and passing criteria) and the user's answer "Hold out 2026". The user's numbers are used where given; every other
number below is Claude's choice, fixed now. Nothing is tuned on results. (Not to be confused with the "E" RS-accumulation
modifier of evidence/entry_setups, which is unrelated.)

Hypothesis (not a finding): liquid stocks in an uptrend that fall sharply over a few sessions, then stabilise with reduced
selling pressure, outperform comparable stock-days over the next 1–5 sessions.
Caveat stated before the test: the idea came from exploratory analysis of 2024-10 → 2026-09 (breakout days underperformed
over 5 sessions). The 2026 holdout therefore influenced the hypothesis and is not fully untouched.

## Data and segments
- Daily NSE EQ bars exports/panel.csv.gz (unadjusted), point-in-time top-1,000 by turnover (tpd_model.backtest.universe_by_session),
  ETFs excluded. Universe exists from 2024-10-24.
- Corporate actions (known + suspected, as before): drop T if an ex-date falls in [T-20, T+5] (wider than the breakout study
  because the 20-session average and the 3/5-session declines would read a split as a crash).
- Development: T from 2024-10-24 with T+5 <= 2025-12-31. Holdout: T >= 2026-01-01 up to the last T with five forward sessions.
- Nifty 50 from Yahoo (^NSEI). Sector = exports/sectors.csv. Market-cap bucket = staging stock_features_daily as of 2026-09-15
  (current, used only for reporting). Results filings = exports/financials.csv.gz with broadcast_at.

## Eligibility (identical for signals and every baseline)
In the universe on T; ADV20 (mean close x volume of T-20..T-1) >= Rs 5 crore; five forward sessions exist and are the next five
market sessions; not in a corporate-action window; high_T > low_T; Nifty bar present; NOT (Nifty < its EMA50 AND Nifty 5-session
return < -3%) — the same market filter as the breakout study.
Negative catalyst: a material negative results print — PAT YoY <= -25% against a positive year-ago quarter, or a positive
year-ago quarter turning to a loss (consolidated where it exists, same basis both years) — assigned to any session T-4..T
(first session whose 15:30 close is at/after broadcast_at). Such stock-days are removed from signals and baselines and the
signals among them are reported separately. Insolvency, regulatory and accounting news is not point-in-time before 2026-01-18
(announcements export starts then), so it is not applied in either segment; in the holdout, signals with such an announcement
in T-4..T (keywords: insolvency, CIRP, NCLT, resolution professional, SEBI order, show cause, forensic audit, auditor
resignation, default) are counted and reported separately, descriptively.

## Indicators at the close of T
SMA20 = mean close T-19..T. r3 = close_T/close_T-3 - 1; r5 = close_T/close_T-5 - 1. CLV = (close-low)/(high-low).
RVOL = volume_T / mean volume T-20..T-1. RSI2 = Wilder RSI, period 2 (ewm alpha 1/2 of gains and losses; 100 when no losses).
RS20_sector = ret20 - median ret20 of universe members in the same sector on T. ATR14% = mean true range of 14 sessions / close.

## Variants (each independent; all require eligibility and ADV20 >= Rs 5 crore)
Decline core D3: r3 <= -4% AND close_T > SMA20. Decline core D5: r5 <= -5% AND close_T > SMA20.
Stabilisation S: CLV_T >= 0.25 (close not at the day's low) AND RVOL_T <= 1.5.
- E1 three-day decline + stabilisation = D3 AND S. (the user's base rule)
- E2 five-day decline + stabilisation = D5 AND S.
- E3 decline + RSI recovery = D3 AND RSI2_T-1 <= 10 AND RSI2_T > RSI2_T-1.
- E4 decline + relative strength vs sector = D3 AND RS20_sector > 0 (stocks without a sector cannot fire).
- E5 decline + positive reversal candle = D3 AND low_T < low_T-1 AND close_T > open_T AND CLV_T >= 0.60.
Cooldown: after a signal, the same variant cannot fire again on that symbol for the next 5 sessions (no overlapping trades per
symbol). Baselines have no cooldown.

## Trade and outcomes
Entry at the T+1 open. Exits at the close of T+1, T+3 and T+5 (no stop, no target). Cost 0.25% round trip (as before).
PRIMARY horizon = 5 sessions; 1 and 3 are reported, not decisive. Per trade: net return, MFE5 = max high T+1..T+5 / entry - 1,
MAE5 = min low / entry - 1.
Reported per variant and segment: trades, mean and median net, win rate, profit factor (sum of gains / |sum of losses|),
return volatility (std of trade net), mean MFE5 and MAE5, net at 1/3/5 sessions, maximum drawdown of the cumulative sum of
per-date mean net (date order), each half of the segment, by market-cap bucket (current) and by sector.

## Baselines (same eligibility, entry, exits and cost)
B1 any eligible stock-day (this is also the buy-at-next-open baseline; under identical entry and exit rules the two coincide).
B2 same stock without the signal: for each trade, the mean 5-session net of that symbol's eligible non-signal days in the same
   segment (>= 20 days, else the trade is left out of B2). Edge_B2 = mean over trades of (trade net - that mean).
B3 matched: for each trade, the mean 5-session net of eligible non-signal stock-days on the same T, same sector, same
   turnover band (universe rank 1–200 / 201–500 / 501–1000 on T, point-in-time) and same ATR14% quintile (across eligible rows
   on T). Cells with < 3 rows fall back to date x band x ATR quintile; still < 3 → left out of B3 (count reported).
   Incremental edge = mean over trades of (trade net - matched cell mean).

## Passing criteria per variant (5-session horizon)
1. >= 200 trades.  2. Mean net > 0.  3. Bootstrap CI lower bound of mean net > 0 (resample signal dates with replacement,
2,000 draws, seed 7; statistic = total net / total trades).  4. Mean net > B1 mean AND Edge_B2 > 0.  5. Mean net > 0 in both
halves of the segment (development: T <= 2025-05-31 / >= 2025-06-01; holdout: T <= 2026-04-30 / >= 2026-05-01).
6. Incremental edge vs B3 > 0 with its bootstrap CI lower bound > 0 (same resampling of dates).  7. No dependence: no symbol
holds > 10% of trades; mean net stays > 0 after removing the sector with the largest total net; mean net stays > 0 after
removing the 5 signal dates with the largest total net.  8. Slippage: mean net > 0 with an extra 0.20% round-trip cost
(0.45% total).
Development: criteria at 95% CI. A variant that fails development is "not validated" and never goes to the holdout.
Holdout: run ONCE, only for the k variants that passed development, with CIs at the 1 - 0.05/k level (percentiles 2.5/k and
100 - 2.5/k). "Validated" only if every criterion holds on the holdout. If k = 0 the holdout is not run and stays unused.
The holdout run writes holdout_lock.json (time, script sha256, variants) and the script refuses a second run.
No display or trade-card decision is made from development results.

## Addendum 2026-09-17 12:32 IST — before any mean-reversion code or data run
- The 5-session cooldown is applied within each segment separately, after eligibility and the negative-catalyst removal
  (a stock-day that could not be traded does not block later signals).
- Turnover band uses the order returned by universe_by_session for T (rank 0 = highest median turnover).
- ATR14% quintile on T: rank of ATR14% among eligible rows on T, cut into five equal-count groups.
- Maximum drawdown starts from 0 before the first signal date.
