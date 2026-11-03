# Pre-registration: ADX and relative-strength variants of the AI scanner score (Phase 4.3)

**Registered:** 2026-10-27, before any variant was scored or any outcome was computed. The git commit of this file is the
registration timestamp. Nothing in it may change after results are seen; any later change is a new, separately labelled
analysis.
**Owner criteria:** `docs/NIVESH_AI_LAB_PHASE_SUCCESS_CRITERIA.md` §4.3. Current weights stay the baseline. Variants are
controlled research arms; the design and primary metric are fixed before results; every arm uses the same universe, period,
cost model and protocol. A change is accepted only if it is robust out of sample, meaningful after costs, and not explained
by leakage or a few trades. Negative and inconclusive results are kept.

## 1. Question
Does adding an ADX/+DI/−DI trend-strength term, or replacing the scanner's "sector" term (stock 20-session return minus
NIFTYBEES) with 63-session relative strength against the Nifty 50 index, improve how well the scanner's score ranks stocks
by their next 10-session excess return, out of sample and after costs?

## 2. Data (staging warehouse, read-only)
- Prices: `nidp.prices_eod_adjusted` (split/bonus-adjusted OHLCV), 2024-04-01 .. 2026-10-26, 634 sessions.
- Delivery: `deliv_qty` and `deliv_pct` from `nidp.prices_eod`, joined on symbol and date.
- Benchmark for the scanner's own term: NIFTYBEES **raw** close from `nidp.prices_eod` (series EQ), complete for all 634
  sessions. Its largest one-day move in the window is 3.9%, so there is no split and raw equals adjusted. The adjusted table
  holds NIFTYBEES only from 2025-10-01.
- Nifty 50 index: `nidp.index_eod`. 253 missing sessions (2024-09-23 .. 2025-09-29) were backfilled on 2026-10-27 from NSE's
  official daily index-close files, on the owner's approval. The analysis checks Nifty 50 coverage and refuses to run with a
  gap.
- Survivorship: each date's universe comes from the symbols priced on that date, so names that later disappeared are
  included while they traded. Index membership is not used.

## 3. Universe (per signal date d)
Series EQ symbols on d with:
- at least 220 prior adjusted sessions;
- a 20-session median traded value (close × volume) of at least ₹10 crore;
- a close of at least ₹20.

ETFs are excluded: NIFTYBEES and symbols the warehouse marks as ETFs or whose name ends in BEES/ETF.

## 4. Scores (computed point-in-time from data up to and including d)
- Features: `services.positional_engine.feature_calculator.compute_features` on the adjusted bars, with delivery as above.
- Sub-scores: the scanner's own functions (`scorer.score_trend`, `score_momentum`, `score_structure`, `score_accumulation`,
  `score_risk`).
- **B0 (baseline):** the scanner's base score with `DEFAULT_WEIGHTS` (trend .25, structure .20, accumulation .20,
  momentum .15, sector .10, risk .10). The sector term is `score_sector(stock 20-session return − NIFTYBEES 20-session
  return, in %)`. The macro multiplier is the same for every stock on a date, so it cannot change a ranking and is
  omitted. The per-sector macro tilt has no point-in-time history and is omitted for every arm.
- **A1:** `0.9 × B0 + 0.1 × ADX_term`, with `ADX_term = ramp(ADX14, 15, 25) × [+DI14 > −DI14]`, using Wilder's ADX on the
  adjusted high, low and close.
- **A2:** B0 with the sector sub-score replaced by `ramp(RS63, −10, +10)`, where `RS63 = stock 63-session return − Nifty 50
  63-session return` (%).
- **A3:** A2 combined with the ADX term as in A1.
- `ramp(v, lo, hi)` is the scanner's own `_ramp`: clamped linear, with a missing input scored 0.5.

## 5. Outcome
`R(s, d) = adj_close(s, d+10) / adj_open(s, d+1) − 1`: entry at the next session's open, 10 sessions held. The excess
return is `R` minus the equal-weight mean of `R` over the same day's universe.

## 6. Splits
Signal dates run from the first date with complete features to the last date with a complete forward window. They are split
chronologically 60/20/20 into discovery, validation and test (`services.fno_backtest.outcomes.split_bounds`). An outcome
whose window crosses a split boundary is excluded (`split_of`). Nothing is tuned on validation or test, and nothing is
tuned at all: the arms are fixed above.

## 7. Metrics
- **Primary:** the daily Spearman rank correlation (IC) between the arm's score and the excess return, over the day's
  universe. Each arm is compared with B0 through the paired daily difference `IC(arm) − IC(B0)`.
- **Secondary:**
  - the top-decile mean excess return net of 0.35% round-trip costs, and the top-decile minus median spread;
  - the hit rate of the top decile;
  - each arm's IC per regime (Nifty 50 above or below its 200-session SMA on d);
  - coverage: the share of each day's top-decile forward movers that were outside the universe or unscorable.

## 8. Inference and decision rule
- **Inference:**
  - the mean daily IC difference, with a Newey-West t-statistic at lag 9 (the overlap of 10-session windows);
  - a block sign-flip permutation (10-session blocks, 1,000 draws, seed 20261027) for a p-value.
- **An arm is adopted only if all of the following hold:**
  - (a) validation: IC difference > 0, NW t ≥ 2.0 and permutation p < 0.05;
  - (b) test: the same thresholds;
  - (c) test: the top-decile net spread is not below B0's;
  - (d) test: the IC difference has the same sign in both regime halves.
- Otherwise **B0 stays** and the scanner weights are not changed. If more than one arm qualifies, the simplest qualifying
  arm is preferred, in the order A1, A2, A3.
- **Power, stated in advance:** about 400 signal dates give roughly 240 / 80 / 80 per split. With 10-session overlap, that
  is only about 8 independent periods in validation and in test. A null result is reported as **inconclusive**, not as
  "no effect".

## 9. Reproducibility
The report records:
- the code SHA;
- the data watermark: per-table `max(ingested_at)`, row counts, and the canonical hash of the input arrays
  (`services.fno_backtest.stats.canonical_hash`);
- this file's commit;
- the permutation seed.

The analysis script and its output are committed together, and nothing is written to the warehouse or the app database.
