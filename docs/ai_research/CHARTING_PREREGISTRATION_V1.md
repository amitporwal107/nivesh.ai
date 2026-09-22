# Pre-registration v1.0 — Chart-pattern validation, development windows

**Status: FROZEN — 2026-09-22.** Owner approval: "3. Agree" (freeze the pre-registration with the day's definitions) and the
decision baseline v1.1 given the same day (`docs/charting.md` §37; decisions-log #88–#90). This document fixes the method
before any outcome statistic is computed. Any later change is a new version (v1.1, v1.2 …) with its own date and reason,
never an edit to this file. It supersedes `.claude/workspace/charting-pattern-engine/preregistration-draft.md` (2026-09-21),
whose eight open items are settled in §10.

---

## 1. Question, and what counts as a pass

**Question.** Do the multi-pivot chart patterns this engine detects (support/resistance breakouts, rectangles, higher-high /
higher-low continuation, with breakout/retest confirmation) carry information about the subsequent price path beyond what
volatility and a random pick from the same universe already carry, after realistic trading costs?

**A negative result is a pass** (decisions-log #4). The study passes when every number in §7 is present, correctly computed
and reproducible — never because a number is favourable. No family, horizon or segment is dropped from the report for being
unfavourable.

## 2. Frozen configuration

| Item | Frozen value | Where it lives |
|---|---|---|
| Detector configuration (swings, geometry, lifecycle, §30.1 ATR rules) | `config_hash` **05167d3ae57f18602b8761ee21de311f5ffb96c428a16df5c119678a748514cf** | `research/charting/config.py` |
| Pattern families in scope | SUPPORT_RESISTANCE, RECTANGLE, HH_HL (breakout/retest is part of each) | `research/charting/patterns.py` |
| Research features (trend class, regime, relative strength, VIX, breadth) | §37.1 thresholds: 20-session regression slope; ±0.15 / ±0.30 %/day; ADX(14) 20 / 25; SIDEWAYS = ADX < 20 OR flat slope | `research/charting/regime.py` `FEATURE_CONFIG` (hash recorded at run) |
| Costs | statutory path, `nse-equity-statutory-v1`, NSE delivery, brokerage 0% (Zerodha delivery), DP charge on, ₹1,00,000 notional per event | `research/costs/` (§36) |
| Tax | reported as a separate Series B, `tax-equity-v1`, no annual LTCG allowance, no surcharge | `research/costs/tax.py` |

The run manifest records the detector `config_hash`, the `FEATURE_CONFIG` hash, the events `dataset_version` and schema
version, the cost/tax/slippage rule versions and the sha256 of every input file. **If the detector `config_hash` at run time
differs from the value above, the run is invalid under this document.** The feature, event and cost versions must implement
the definitions in §4–§6 exactly; their hashes are recorded, not pre-stated, because the implementing code is still being
finished (§9).

## 3. Data, universe and windows

- **Bars:** Kite daily, `research/kite_history/day_2021/` (2,926 symbols with data; 2021-01-01 → 2026-09-18).
- **Universe:** symbols with ≥ 250 bars, minus the sealed ETF list `research/sealed/etf_symbols_kite_20260919.csv`
  read without a header (2,132 symbols; 291 ETFs removed). The list is known to exclude some real equities (BHARATFORG,
  BHARATGEAR-BE, BHARATRAS, BHARATWIRE, DALBHARAT; suspected FIRSTCRY, SENCO, LGHL); every report states this. A
  point-in-time ETF universe is parked on the to-do list (owner, decisions-log #89).
- **Benchmark:** NIFTY 500 (Kite, `research/index_history`).
- **Windows — two development segments, analysed and reported separately:**
  - **Pre-sealed:** 2021-01-01 → 2022-12-30.
  - **Post-sealed:** 2024-08-01 → 2026-09-18, with its own fresh history: no sealed bar is used as lookback, as input to any
    feature, or as a forward bar.
- **Sealed window 2023-01-01 → 2024-07-31 is not touched** — not read, not used as input, not used for outcomes. Enforced in
  code (`research/charting/research_window.py`; replay, movement, events and regime refuse frames that span it). Spending it
  needs a separate, later pre-registration.
- **Demergers (§37.5):** confirmed demergers are regime breaks. Sessions T−5..T+5 around each ex-date are excluded, and no
  pattern, feature window or outcome window may span one (pre- and post-demerger histories are separate). The exclusion
  list is the verified list in `research/corporate_actions/`; the number of events excluded is reported.
- **Data quality:** events whose `data_quality_status` is FAIL are excluded and counted by reason.

## 4. Unit of observation and population

- **One row per pattern instance at its confirmation bar t** (the PRICE_CONFIRMED transition in the point-in-time replay).
  Retests, failures and expiries are properties of that row, never extra rows.
- **Population:** every confirmed instance of the three families in the universe and windows above, after the demerger and
  data-quality exclusions. There is no further eligibility filter; `RESEARCH_ELIGIBLE` is not used to select rows.
- **Direction:** BULLISH rows are long-actionable. BEARISH rows are `INFORMATIONAL` with action `AVOID_NEW_LONG` (§37.4):
  no short trade is priced; they are validated on their directional forward returns only.

## 5. Entry, stops and targets

- **Entry:** the open of bar t+1 (primary). The close of bar t is reported as a labelled alternative entry; it is never the
  headline.
- **Initial stop (§37.3):** structural stop — RECTANGLE and SUPPORT_RESISTANCE: broken level − `failure_buffer_atr` × ATR(t);
  HH_HL: the invalidation swing. Then widened, never tightened, so that entry − stop ≥ 0.75 × ATR(14) at t. R = entry − stop.
- **Targets (§37.2):** +2%, +3%, +5%, +10% from entry; 1R, 1.5R, 2R, 3R.
- **Fills:** a bar that opens beyond the stop fills at its open; a bar that opens beyond the target fills at its open. If the
  target and the stop are both inside one daily bar, the outcome is **AMBIGUOUS** — never assumed either way; both bounds
  are reported.
- **Random and buy-at-next-open controls** use the ATR-minimum stop (0.75 × ATR) with the same targets.

## 6. Outcomes per row

- **Horizons:** 1, 3, 5, 10, 20 sessions from the entry bar.
- **Path measures:** forward close return, MFE, MAE, highest and lowest price, bars to +2 / +5 / +10 / +15%.
- **Per target and horizon:** `target_hit`, `stop_hit`, `both_hit`, `neither_hit`, `target_hit_session`,
  `stop_hit_session`, `first_exit_event` ∈ {TARGET, STOP, AMBIGUOUS, NONE}, exit price, holding period.
- **Returns:** gross and net (Series A), for each of the four slippage scenarios (optimistic 0.05%, **base 0.15% —
  primary**, conservative 0.30%, stress 0.50%) and the liquidity-bucket model. Series B (after tax) is separate. Position
  value / 20-day average traded value is recorded per row.
- **Context at t:** trend class of the stock and of NIFTY 500 (§37.1), NIFTY 500 vs SMA200 regime, relative strength
  5/20/50/100, India VIX, breadth; breakout distance in % and in ATR, breakout volume ratio; candle and retest quality.
  Context values that would need sealed-window data are UNAVAILABLE and counted, never filled.

## 7. What the report must contain (all of it, whatever the sign)

For each segment × family × horizon (and × target for the target/stop measures):

1. `n` (signals), and counts excluded by reason (data quality, demerger window, insufficient forward bars, AMBIGUOUS).
2. Gross hit rate and **net hit rate after costs** per target; target-first, stop-first, AMBIGUOUS and neither shares.
3. Median and mean gross return and **median and mean net return**; average transaction cost; average slippage; **net
   expectancy**; profit factor; win rate; average win; average loss; maximum drawdown of the equal-weight event sequence.
4. Median MFE and MAE; median holding period to first exit.
5. `move_auc` and `direction_auc` (movement vs direction, §S35 of the plan).
6. **Comparison groups**, same measures: (i) the pattern rows; (ii) a random selection from the same eligible universe and
   dates, 200 seeds; (iii) buy-at-next-open on the same dates; (iv) an ATR-decile-matched control; (v) NIFTY 500 over the
   same holding periods. The pattern rows' percentile within the random and ATR-matched distributions.
7. Segmentation by liquidity bucket, volatility (ATR) bucket, stock trend class, NIFTY 500 trend class and regime.
8. BEARISH rows: directional forward returns and MFE/MAE only, reported as the "avoid" signal's validation.
9. The cost-sensitivity table (four scenarios) for every headline net number.
10. The universe caveats in §3, the unverified cost rates listed by the cost engine, and the input hashes.

Sample-size rule: a cell with n < 30 is shown with its n and marked `insufficient_n`; it is never dropped and never used for a
conclusion.

## 8. Integrity rules the run must pass before any number is reported

- **Kill switch:** two runs with the same inputs produce identical `pattern_id` sets and identical event files (sha256). If
  not, stop and fix before reporting.
- **Point in time:** the poisoned-future probes and their negative controls pass (patterns, events, regime, breadth).
- **Sealed window:** the poison-only-the-sealed-bars probes pass; the run manifest shows no input or output row dated
  2023-01-01..2024-07-31.
- **Independent recomputation:** a sample of rows (entry, exits, returns, MFE/MAE, net return) is recomputed from raw bars
  and the cost engine by separate code, with zero mismatches (as in `test_reports/charting_events_regime_quality.md` TC-40).

## 9. Capability status at freeze (the method is frozen ahead of the last pieces of code)

| Needed for the run | State on 2026-09-22 |
|---|---|
| Detectors, replay, sealed guards, cost engine, index data, breadth | built and verified (PR #140, staging verified) |
| Event dataset, regime features, candle/retest quality | built, in PR #141 |
| Stop/target outcome labels (§5, §6) | in build |
| Trend classes (§37.1) and the research-state enrichment layer | in build |
| Demerger list and exclusion helper | in build |
| ATR-decile-matched control, report generator | not started |

The study runs only after every row above is built and verified. That timing does not change this document.

## 10. Items the draft left open — settled

| Draft item | Settlement |
|---|---|
| NI-4, landing `tpd_model` for outcomes and costs | Superseded: outcomes and costs come from `research/costs` + `research/charting/events` (decision #71). |
| T13, demerger discontinuities | §3: regime break, T−5..T+5 excluded, histories not spliced (§37.5). |
| Sealed ETF-list over-exclusion | Accepted for now with disclosure; point-in-time universe on the to-do list (decision #89). |
| S28, early signals for triangle / cup / flag | Out of this study: those families have no detectors yet (§37.7). A later version adds them. |
| D7 simulator defects | Not inherited: `tpd_model` is not used (decision #71). |
| G-2 eligibility, G-3 unit of observation | §4: all confirmed instances after the stated exclusions; one row per instance at its confirmation bar. |
| `test-plan.md` "290" ETF figure | The correct count is 291 (2,132 remaining); used here. |
| No `dataset_version` in the manifest | Event rows and the run manifest carry `dataset_version` and input hashes (§2). |
