# F&O Stage B: pre-registration (written before any Stage B data was loaded or analysed)

Date: 2026-10-23 · Decision of record: the user's, 2026-10-23 ("start the Kite history experiment, narrowly scoped, on the conditions below").
This file is committed BEFORE the experiment code is run. If anything here changes after a result is seen, it is a new experiment with a new id and this file stays as it is.

## 0. Lineage and what is frozen
- Baseline: experiment `fo-bt-95f4e5df42dc`, report hash `c5b125ba612073e0ce4e2c69b18c49c483c9bc813abcd7341a48a490ed287ea1` (`test_reports/fno_ranking_backtest_fo-bt-95f4e5df42dc.json`). Its result stands: no support for the ranking or the thresholds.
- Frozen for Stage B, read from that report at run time and checked against the hash: for each category the 5 frozen settings (`threshold_study.categories[c].frozen[*].config`), plus the two baselines in it (`no_threshold` and `production_floors` 0.5% price / 3% OI). **No setting is added, removed or changed after seeing Stage B results.** The weights stay `research_setting_not_validated`.
- The new experiment gets its own id. This is not a re-run of the old one: different data (Kite near-month futures), different outcome (benchmark-relative), different OI definition.

## 1. Data
Kite historical API, daily, `continuous=True`, `oi=True`, from 2021-10-25 to 2026-10-22, for every current F&O stock underlying (about 214) plus NIFTY and BANKNIFTY. Each row: open, high, low, close, volume, open interest of the near-month contract.
- Known bias, stated now: Kite lists only active contracts, so stocks removed from F&O between 2021 and 2025 are absent (survivorship). A stock enters the sample only from its first row.
- Sector: the current sector of each stock (static, from the engineered features), so sector-relative results carry a classification-drift caveat.
- No NIFTY 500 TRI is available in this system. The broad-market benchmarks are (a) the equal-weighted average return of all F&O stock futures with a valid outcome in the same window and (b) the NIFTY near-month futures. Both are reported; (a) is primary.

## 2. Chronological windows, fixed now (signal sessions)
The thresholds were chosen using 29 Dec 2025 to 25 Jun 2026 and evaluated, not tuned, on later 2026 data. The Stage B windows are all EARLIER than that, so none was used to choose them.
- W1: 2021-11-22 to 2023-03-31 (the first 20 sessions are warm-up for the volume average).
- W2: 2023-04-03 to 2024-09-30.
- W3 (final, the most recent untouched): 2024-10-01 to 2025-12-26.
A trade is assigned to a window only if its whole forward window lies inside it. 2025-12-29 to 2026-10-22 is the baseline's own period and is used ONLY for the OI-formulation diagnostic in section 6, never for acceptance.

## 3. Roll methodology (defined before the run)
The continuous series switches contract at each monthly expiry. A signal or an outcome that crosses the switch mixes two contracts, so:
- Calendar: monthly stock-futures expiry is the last Thursday of the month through August 2025 and the last Tuesday from September 2025; if that day is not a session in the series, the previous session. The **expiry session** is that day; the **roll session** is the first session after it.
- Excluded as signal sessions: the 3 sessions before the expiry session, the expiry session, and the roll session.
- Excluded trades: any whose entry-to-exit window (session D+1 through D+h) contains a roll session.
- Diagnostic, not a filter: the share of rolls where the series' OI jumped by at least 1.8x on the roll session, to check the calendar rule against the data. The rule is not changed to fit it.
- The contract is never chosen by outcome: it is whatever the near-month continuous series holds on that day.

## 4. Signals and outcomes
- Price change = close / previous close - 1; OI change = OI / previous OI - 1 (near-month, both days in the same contract by section 3); relative volume = futures volume / mean of the previous 20 sessions' futures volume. **This relative volume is futures volume, not the cash volume used in the baseline, so settings with a volume floor are evaluated with a different (futures) definition; settings without one are unaffected.**
- Category by signs: price up and OI up long build-up; price down and OI up short build-up; price up and OI down short covering; price down and OI down long unwinding. A frozen setting fires when |price| >= p, |OI| >= o and relative volume >= r (r null: no volume requirement).
- Direction: long for long build-up and short covering, short for the other two.
- Outcome: enter at the next session's open, exit at the close of D+h, h = 1, 3, 5, 10, 20; **5 is the primary horizon** (as in the baseline). Cost: assumed 0.15% round trip (stress 0.30%, which also stands in for the hedge leg of a benchmark-neutral trade).
- **Benchmark-relative outcome** = direction x (stock return - benchmark return over the same window). Benchmarks: (a) equal-weighted universe average, primary; (b) NIFTY near-month futures; (c) same-sector equal-weighted average excluding the stock, when at least 3 peers have a valid outcome.
- NIFTY and BANKNIFTY signals are NOT evaluated in this experiment: they need their own methodology (the index futures and their weekly options cannot be neutralised against a stock universe). They are loaded only as the benchmark.

## 5. Baselines and chance
- Price-only: the same price and volume floors with no OI requirement; direction by the sign of the price change (long if up, short if down). Compared with a category's frozen settings by direction.
- Permuted: within each session, the OI changes are shuffled across stocks (breaking the OI information, keeping price and volume); 200 permutations, seed 20261023; run for the first frozen setting of each category and for `production_floors`, pooled over W1 to W3; the p-value is the share of permutations with a mean net benchmark-relative return at least as high as the observed one.
- Unconditional: `no_threshold`.

## 6. The one diagnostic: near-month versus aggregate OI
Over the baseline's own period only (2025-12-29 to 2026-10-22), where both exist: the same frozen settings, the same Kite futures price and outcomes, with the OI change taken (i) from the near-month series or (ii) from the baseline's scan, which sums OI over every expiry. Reported side by side, descriptive only. No threshold grid is run.

## 7. Verdicts, fixed now
Per frozen setting (primary horizon, primary benchmark, net of the base cost): **stable** when the mean net benchmark-relative return is positive in all three windows, each window has at least 30 signal sessions, and the Newey-West t-statistic is at least 1.645 in at least two windows.
Per category: **supported** only if at least 3 of its 5 frozen settings are stable AND the permutation p-value of its first setting is at most 0.05 AND the frozen settings beat the price-only baseline in at least 2 of 3 windows. **not_supported** if fewer than 1 of 5 is stable or at least 3 of 5 have a non-positive pooled mean. Otherwise **inconclusive** (also when most settings have fewer than 30 signal sessions in a window).
Overall: **supported** only if at least 2 categories are supported. Nothing is `validated` by this experiment; the strongest word is `supported`, which still needs live shadow validation (Stage C) before any release.
Questions answered in the report, each from the numbers above: benchmark-relative expectancy; versus price-only and random baselines; stability across the three windows; near-month versus aggregate OI; survival under the stress cost; sample size and coverage; value after controlling for market and sector.

## 8. Declared limits
About four years of daily history for the liquid names, fewer for later listings; survivorship (section 1); the cost is assumed; futures-volume relative volume differs from the baseline's; the benchmark is a market proxy, not a total-return index; one regime sequence; overlapping windows (Newey-West); no options input.
