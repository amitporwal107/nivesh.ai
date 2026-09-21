# Entry setups A–E — pre-registered 2026-09-17 before 12:00 IST, before any setup backtest code was run

Correction (12:25 IST): this header first said "~12:25 IST", a hand-typed estimate that was wrong. The file's own record: the
addendum below was appended at 12:00:47 IST, and the backtest's first log line is 12:04 IST (run.log).

Source: the user's specification of 2026-09-17 ("Highest-value entry signals", four classifications + supporting RS signal,
EQS, risk filters, trade card, backtest plan). Thresholds below are the user's where given; where the user gave a range or
no number, the value chosen here is stated and fixed now. Nothing is tuned on the results.

## Data
- Daily NSE EQ bars (exports/panel.csv.gz, 2024-05-31 → 2026-09-16), point-in-time top-1000 universe by turnover per session
  (tpd_model.backtest.universe_by_session), ETFs excluded.
- Corporate actions: stock-days whose 7-session window [T-1, T+5] touches a known or suspected corporate action are dropped
  (tpd_model.corporate_actions_from_archive + suspected_actions).
- Nifty 50 daily closes from Yahoo Finance (^NSEI). Sector = exports/sectors.csv (current mapping). Market-cap bucket =
  staging nidp.stock_features_daily latest bucket per symbol (current, not point-in-time; labelled as such).
- Results filings for Setup C: exports/financials.csv.gz rows with broadcast_at (exchange stamp), consolidated preferred.
- Signal day T from 2024-09-02 (60-session warm-up) to the last T with five forward sessions.

## Indicators at the close of T (only data through T)
EMA20, EMA50 of close; rising = value at T > value at T-5. ATR14 = mean true range of the 14 sessions to T; atr_pct = ATR14/close.
vol_avg20 = mean volume of T-20..T-1; RVOL = volume_T / vol_avg20. hh20 / hh50 = highest high of T-20..T-1 / T-50..T-1.
CLV = (close-low)/(high-low) (0.5 when high = low). ret20 = close_T/close_T-20 - 1. RS20_nifty = ret20 - Nifty ret20.
RS20_sector = ret20 - median ret20 of universe members in the same sector on T. ADV20 = mean(close x volume) of T-20..T-1.
Price change = close_T/prev_close_T - 1.

## Setups (long only)
A Confirmed Breakout: close > hh20 AND RVOL >= 1.5 AND CLV >= 0.70 AND RS20_nifty > 0 AND close > EMA20.
  Entry: buy-stop at high_T on T+1 only (fill = max(open, high_T) if the T+1 high reaches high_T). Structure stop: low_T.
B Pullback Continuation: EMA20 > EMA50 AND both rising AND close > EMA50 AND close >= EMA20 x 0.97 AND the lowest low of
  T-2..T <= EMA20 x 1.02 (pullback reached the zone) AND mean volume of down days (close < prev close) in T-5..T-1 < vol_avg20
  AND bullish reversal (close > open AND close > close_T-1 AND CLV >= 0.60 AND volume_T > volume_T-1).
  Entry: T+1 open. Structure stop: lowest low of T-2..T.
C Catalyst Momentum: a results filing broadcast in (T-1 15:30, T 15:30] IST AND material positive (PAT YoY >= +25% on the same
  quarter a year earlier, or loss → profit) AND price change >= 2% AND RVOL >= 2 AND CLV >= 0.70.
  Entry: T+1 open. Structure stop: low_T.
D Volatility Expansion: ATR14 at T-1 < 0.75 x ATR14 at T-21 AND (highest high - lowest low of T-10..T-1)/close_T-1 <= 10%
  AND mean volume of T-10..T-1 < 0.8 x mean volume of T-30..T-11 AND close > highest high of T-10..T-1 AND RVOL >= 1.5 AND
  CLV >= 0.70. Entry: buy-stop at high_T on T+1 only. Structure stop: lowest low of T-10..T-1.
E RS Accumulation (supporting, not an entry): RS20_nifty > 0 AND RS20_sector > 0 AND up-day volume > down-day volume over T-19..T
  AND mean delivery % of T-4..T > mean of T-19..T AND close >= 0.95 x hh20. Reported as a modifier of A–D.

## Filters applied before any entry (the user's §5, as testable history allows)
- No-chase: price change >= 9.5% with CLV >= 0.98, or high = low → watchlist, never an entry (counted separately).
- Liquidity: ADV20 >= Rs 5 crore. Extension: close <= EMA20 x 1.10. Market not strongly adverse: NOT (Nifty < its EMA50 AND
  Nifty 5-session return < -3%).
- Stops: 5% trade stop = max(structure stop, entry - 1.5 x ATR14); 10% trade stop = max(structure stop, entry - 2.5 x ATR14);
  must be below entry. Stop compatible with ATR: stop distance >= 0.5 x ATR14. Risk/reward >= 2: 5% / stop distance >= 2 for
  the 5% trade; 10% / stop distance >= 2 for the 10% trade.
- Governance flags and unexplained regulatory events are not point-in-time before September 2026: applied live only.

## Outcomes from the entry price, five sessions T+1..T+5
P(+5%) and P(+10%) within 1 session (T+1 high) and within 5 sessions; MFE5 = max high / entry - 1; MAE5 = min low / entry - 1;
gap = open T+1 / close T - 1; slippage = entry / close T - 1.
Bracket trades: target +5% (or +10%), the stop above, exit at the T+5 close otherwise; if a day's range contains both stop and
target the stop is assumed first; a gap below the stop exits at that open. Net = exit/entry - 1 - 0.25% (delivery round trip).
Baseline: every eligible universe stock-day passing the same filters, entry T+1 open, same bracket with ATR stops.

## Decision rule, per setup A–D and per trade (5%, 10%)
"Validated entry signal" only if ALL: >= 200 trades; mean net > 0 with the 95% bootstrap CI lower bound > 0 (2,000 resamples over
signal dates, seed 7); mean net > the baseline's mean net; mean net > 0 in both halves (T <= 2025-08-31 and T >= 2025-09-01).
Otherwise "not validated". Results are also reported by market-cap bucket and by sector (reported, not decisive).

## Entry Quality Score (0–100, the user's weights) and Trade Opportunity Score
Components on 0–1: price action 20 = 0.5·CLV + 0.5·min(1, max(0, (close/hh20-1)/atr_pct)); volume 20 = 0.7·min(1, RVOL/3) +
0.3·[up-day vol > down-day vol]; trend/RS 15 = 0.5·[EMA20 > EMA50] + 0.5·[RS20_nifty > 0]; volatility 15 = 0.5·[ATR14 T-1 <
0.75·ATR14 T-21] + 0.5·[range10 <= 10%]; catalyst 15 = 1 if Setup C's event is on T, 0.5 if a positive print in T-4..T-1, else 0;
regime 10 = 0.5·[Nifty > EMA50] + 0.5·[Nifty ret5 >= 0]; liquidity 5 = min(1, ADV20 / Rs 50 crore).
Tested: net result by EQS quintile across all A–D trades (does quality rank outcomes?). TOS = normalised model probability ×
EQS/100 × min(1, R/R/3) × data confidence (1 if delivery present else 0.8) × risk adjustment (1 - min(0.5, atr_pct·5)),
tested only where model probabilities exist (Jan–Aug 2025 walk-forward, and forward from 2026-09-17).

## Addendum 2026-09-17 12:00 IST — implementation details fixed before the backtest ran (no setup result seen)
- Module: backend/nidp/services/tpd_model/entry_setups.py (tests test_entry_setups.py, 9 passed). The backtest imports it.
- Inputs pulled: nifty50_yahoo_daily.csv (Yahoo ^NSEI, 670 sessions to 2026-09-17), cap_bucket_latest.csv (staging
  stock_features_daily as of 2026-09-15: 195 large, 358 mid, 604 small, 54 micro).
- Buy-stop fills (A, D): if the T+1 high >= high_T, fill = max(open T+1, high_T); otherwise no trade (fill rate reported). On the
  fill day a low at or below the stop counts as stopped even though the low may have come before the fill (conservative).
- Price history is unadjusted: a split/bonus older than T-1 inside the 60-session look-back distorts the indicators (it suppresses
  breakouts rather than creating them). Only the [T-1, T+5] window is dropped, as registered; the count of affected rows is reported.
- Results mapping (C): consolidated row where one exists for that symbol and quarter, else standalone. YoY compares the quarter
  ending one year earlier on the same basis; no prior-year row → not material. A filing is assigned to the first session whose
  15:30 close is at or after broadcast_at. "Positive print in T-4..T-1" (EQS catalyst 0.5) = a material positive filing assigned
  to any of those four sessions.
- Baseline: no structure stop; stop = entry - 1.5 ATR (5%) / 2.5 ATR (10%), and the same R/R >= 2 and stop >= 0.5 ATR checks.
- TOS "normalised model probability" = percentile rank (0–1) of the v4 walk-forward p_tpd3 within that session's universe rows,
  head p_up5_1d for the 5% trade and p_up10_1d for the 10% trade; joined on symbol and signal day T. Data confidence 1 when
  deliverable_pct is present on T, else 0.8. TOS is tested by quintile only on A–D trades with a prediction (Jan–Aug 2025).
- Bootstrap: resample signal dates with replacement; each resample's statistic = total net / total trades over the drawn dates.
