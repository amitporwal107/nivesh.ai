# Study C: research validation and data vs the trading-decision PRD

PRD: `docs/NIVESH_AI_LAB_TRADING_DECISION_GUIDELINES.md`, sections 2, 3, 8, 9, 12 and 13.
Code basis: the clean checkout `/home/deploy/nivesh-idea-levels` at HEAD `5b6b3cfd` (origin/dev). All paths below are relative to `backend/` unless they start with `research/` or `deploy/`.
Staging reads were taken on 2026-10-27 and were read-only: app Postgres through the backend's pool, Mongo `nivesh_staging`, and the NIDP warehouse through `nidp-psql.sh`.
Tests and the worked-example harness ran in `nivesh/backend:staging` with a read-only mount and `--network none`.

**Footprint note.** To run the app-Postgres SELECTs I copied 7 small query scripts into `/tmp` inside `nivesh-staging-app-backend` with `docker cp`. All of them were SELECT-only. I deleted them afterwards and confirmed with `ls` that they are gone. No data, config, cron or repo file was changed.

Labels: **VERIFIED** means the code is cited or the output was produced in this session. **UNVERIFIED** means I could not prove it here, and the reason is given.

---

## 0. The prior claims, checked one by one

| Claim (earlier review / outside reviewer) | Verdict | Evidence |
|---|---|---|
| No ADX/+DI/−DI anywhere | **REFUTED (literally), CONFIRMED where it matters** | ADX/+DI/−DI is computed in three places: `nidp/services/daas_api/routers/movers.py:857-885` (Wilder), which feeds the Top Movers v5 10-point technical score at `:946-952` ("ADX > 20 · +DI > −DI") and a "Directional trend" family at `:1006-1007`; `research/charting/series.py:184` plus the indicator catalogue at `:449` (chart, tested in `tests/test_research_chart.py:537-559`); and the AI Trader market trend class at `services/ai_trader/context.py:57` ("OLS slope and ADX 14"). It is **absent** from the AI-scanner score (`services/positional_engine/scorer.py`), the Strategy-Builder evidence ledger (`services/strategy_plan/evidence.py`), the desk regime (`services/macro_engine.py:836-841`) and regime-fit. |
| Stock-level relative strength unclear | **CLARIFIED: two inconsistent definitions, one mislabelled** | (1) The scanner's "sector" sub-score is the stock's own 20-session return minus **NIFTYBEES**' 20-session return (`positional_engine/pipeline.py:94`, `sector_strength.py:29-38`). Despite its name it is stock-level RS, and `trade_planner.py:175` tells users "Sector outperforming Nifty". (2) The plan evidence uses `rs63`: the 63-session return vs the Nifty 50 index (`routes/research_chart.py:341-360`, consumed at `strategy_plan/evidence.py:215-221`). True sector RS exists only in the plan evidence (`evidence.py:101-145`, sector indices ranked by 1-month return). |
| Scanner score components/weights differ from the PRD's six | **CONFIRMED** | `scorer.py:19-26`: trend 25, structure 20, accumulation 20, momentum 15, sector(=stock RS) 10, risk 10. Regime is not a weighted component: it is a ×0.8/1.0/1.1 multiplier plus a ±0.10 sector tilt (`scorer.py:254-260`). The same weights are stored on every 2026-10-26 feature row (query output in §Q2). |
| Keep current weights until an out-of-sample study | **AGREE**: there is no calibration evidence | `positional_outcomes` 0 rows, `positional_backtest_labels` 0, `accumulation_calibration` 0 (staging query in §Q2). No study of `final_score` against forward returns exists in the code or the docs. |
| Worked examples A–H are not encoded as tests | **CONFIRMED** | No test uses the PRD inputs. The repo functions do reproduce every A–H figure exactly (§2). No test of the ATR trailing stop exists at all (`grep trailing_atr_mult tests/` finds nothing). |
| `fno_iv_history` has 0 docs; regime_fit GAPS still says there is no IV percentile | **CONFIRMED** | Count 0 (Mongo, this session). The recorder cron is documented but not installed (`scripts/record_iv_history.py:24-29`; `/etc/cron.d` has no iv-history file). GAPS text at `strategy_plan/regime_fit.py:56-60`. regime_fit does not read the IV store at all: the only consumer is `routes/fno.py:930-946`. |
| Backtests lack Sharpe/Sortino, exposure, turnover, capital usage, slippage sensitivity, rejected-signal coverage | **CONFIRMED for every engine on Sharpe/Sortino/exposure/turnover/capital usage/rejected-signal coverage; PARTLY REFUTED on slippage sensitivity and validation design** | The DSL engine has none of them (`strategy_engine/backtest.py:399-464`). The F&O studies have cost stress (0.15%/0.30%), Newey-West t, discovery/validation/test splits and permutation tests (`fno_backtest/outcomes.py:12-16`, `stats.py`, `expiry_study.py:15-36`). The AI Trader has walk-forward folds, a sealed holdout and a full cost card (`ai_trader/strategy.py:124-145, 330-360`; `ai_trader/validation.py:1-30`). The reversal backtest has two cost scenarios and a bootstrap CI. |
| Unknown: bid/ask/depth/spread/legging for options | **RESOLVED: partial** | See Q4. Top-of-book exists on the Kite feed but feeds no decision. Plan bid/ask comes only from the user's ICICI session. OI/volume is the liquidity proxy. No depth or legging check. |
| Unknown: staleness handling | **RESOLVED: mixed** | The plan blocks stale prices and labels stale chains. regime_fit only warns. **The scanner silently defaults missing inputs to 0.5.** The benchmark lookup carries a close forward with no limit. Event-calendar coverage is not checked. See Q4/Q7. |
| Unknown: intraday minute-bar coverage | **RESOLVED: none on staging** | `nidp.intraday_bars` does not exist on staging. Mongo `kite_live_minute`=0 and `kite_live_intraday`=0. Q6. |
| Unknown: corporate-action adjustment ("adj_close null after rebuild") | **REFUTED for the warehouse; NEW DEFECT in the scanner** | `prices_eod_adjusted`: 1,098,819 rows, `adj_close` populated on all 1,098,819. 259 symbols carry a factor ≠1 and the KOTAKBANK 5:1 split is adjusted. **But the AI scanner reads raw bhavcopy bars** (`stock_ohlcv`), and 91 symbols had a ≥20% adjustment-factor step inside its bar window. |
| Unknown: survivorship | **CONFIRMED present** | On staging the DSL backtest labels its universe `latest_snapshot` (`strategy_engine/market_data.py:180-187`). All 3 stored runs say so. `nidp.index_constituents` has only 4 snapshot dates (2026-10-12 to 2026-10-22). |
| Unknown: rule/config versioning | **RESOLVED: partial** | See Q7. |

---

## 1. PRD item vs implementation

Severity: **H** = can mislead a decision or invalidate research. **M** = a real gap with a workaround or a warning. **L** = cosmetic, or a documented limitation.

| PRD item | Status | Evidence (file:line / staging data) | Sev |
|---|---|---|---|
| §2 Nifty vs EMA20/50/200 | Partial | Desk regime: Nifty vs its **50-session average** only (`macro_engine.py:826-841`, `routes/macro.py:164-168`). AI Trader: NIFTY 500 vs SMA200 (`ai_trader/context.py:38-46`). No Nifty EMA20/200. `macro_daily` holds 9 rows (2026-10-09..10-23); the regime falls back to the warehouse Nifty. | M |
| §2 ADX (market) | Partial | Only the AI Trader trend class (`ai_trader/context.py:57`). Not in the desk regime or regime-fit. | L |
| §2 India VIX | Implemented | Desk regime `vix_high` 20 (`macro_engine.py:838`); regime-fit volatility axis; macro risk z-score (`macro_engine.py:175-219`). Warehouse `index_eod` India VIX: 381 rows 2024-04-01..2026-10-26, **with gaps: Nifty 50 has 118 rows in 2024, 63 in 2025, 200 in 2026** (prices_eod has 186/248/200). | M (history gap) |
| §2 Breadth | Implemented, **with a data defect** | `macro_engine.py:851-886`: advances/declines from `stock_ohlcv` with LAG over the stored bars. 2026-10-21/22 are missing from `stock_ohlcv`, so the 10-23 breadth compares 10-23 with 10-19 (a 3-session move counted as one day). | M |
| §2 Sector RS | Partial | Plan evidence: sector indices from `index_constituents`, ranked by 1-month return (`evidence.py:101-145`, `rules.py:29-36`). Only about 282 symbols belong to a non-broad index on the 10-22 snapshot, out of a scanner universe of about 2,200. The scanner's "sector" score is not sector RS (see §0). | M |
| §2 FII/DII flows, futures OI | Partial | `nidp.fii_dii_flows`: cash 2018-09..2026-10-26; FII index futures/options 2026-04-01..10-21. Not consumed by the scanner, the plan or the regime; shown on desk screens only. Stock futures OI build-up is in plan evidence (`evidence.py:549-583`) and `fno_candidates`. | L |
| §2 EMA20/50/200 (stock) | Implemented (plan) / Partial (scanner) | Plan: `research_chart.py:351` (ema20/50/200). Scanner: SMA50/200 plus EMA20 (`feature_calculator.py:343-346`), scored on SMA (`scorer.py:43-58`). | L |
| §2 RSI | Implemented | Scanner triangular band 45–70 (`scorer.py:61-77`); plan `rsi14` stretched ≥70 (`rules.py:27`). | – |
| §2 ADX/+DI/−DI (stock) | Missing in the decision path | Only Movers v5 display/score and the chart catalogue (see §0). | M |
| §2 ATR/ATR% | Implemented | Scanner `atr_14`, `atr_pct` (`feature_calculator.py:348,385-388`); plan Wilder ATR14 (`research_chart.py:177-180`). | – |
| §2 RS vs benchmark | Implemented (two definitions) | See §0. The scanner benchmark is the ETF NIFTYBEES, not the index. | M |
| §2 RVOL | Implemented | Plan `rvol20` (`research_chart.py:187-188`), confirm at 1.5 (`rules.py:37`). Scanner uses volume z-score (`scorer.py:118-131`). | – |
| §2 Support/resistance, swing structure | Implemented | Scanner `swing_low_20`/`swing_high_20` (`feature_calculator.py:187-199`); plan `support20`/`resistance20`; pattern engine. | – |
| §2 Liquidity, spread, event calendar | Partial | Liquidity: ₹10 Cr/day gate (`rules.py:21`, `selection.py:33-37`). Spread: no bid/ask in EOD data (`fno_candidates/engine.py:250`). Events: `evidence.py:495-517`; the calendar ends 2026-11-16 and coverage is never checked against the horizon. | M |
| §3 Setup score, six components | Contradicts (weights) / Partial (mapping) | Mapping in §Q2. The regime is a multiplier, not 15 points. A "risk" component exists that the PRD does not score. | M |
| §3 Calibrate out of sample | Missing for the scanner | 0 rows in every calibration/outcome table (§Q2). | H |
| §3 Score never overrides a hard rejection | Implemented (plan) | Ideas keep the scanner rank, but the plan's gates decide the status. The stored 2026-10-26 watchlist has plan_status `no_trade` 6, `plan` 3, `wait` 1 of the 10 cash ideas. | – |
| §8 A, B, G (long cash) | Arithmetic implemented | §2 table: exact match. Sizing uses **gross** risk, so the net loss at stop exceeds the budget (A: ₹3,098.94 vs ₹3,000). | M |
| §8 C (intraday ORB) | Missing | The plan refuses an intraday horizon (`strategy_plan/plan.py:183-184`). No minute bars (Q6). | M |
| §8 D (short cash) | Missing for cash | Cash plans are long only (`candidates.py:205-207`). The desk calculator rejects a stop above the entry (output in §2). Short **futures** and bearish options do exist (`candidates.py:359-399`). | M |
| §8 E (futures per lot) | Implemented | `size_position` with lot units; `scenario_levels` 2R. | – |
| §8 F (bull call spread, reject vs budget) | Implemented | Payoff engine exact; sizing `too_small` → `no_trade` "sizing_zero" (`candidates.py:748-762`). | – |
| §8 H (ATR trailing) | Partial | Exists only in the DSL **backtest** exit (`strategy_engine/backtest.py:305-313`). ATR is frozen at entry. The stop is raised with the same bar's high before that bar's low is tested. No test. No live trailing (lane B). | M |
| §9 Payoff at expiry and pre-expiry | Implemented | `strategy_plan/engine.py:25-82` (pre-expiry Black-76 via `pre_expiry`). | – |
| §9 Max loss/profit/breakeven | Implemented | Harness output F. | – |
| §9 Margin | Partial | `MARGIN_REASON` (`engine.py:15-16`): needs the platform's daily Kite login. | M |
| §9 Greeks | Partial | EOD Black-76 `net_greeks` on regime-fit rows. Not in the gate (`risk_gate/readiness.py:90-92`). | M |
| §9 IV rank/percentile | Missing in practice | Tooling and route exist (`services/fno_iv_history.py`, `routes/fno.py:930-946`). 0 docs; cron not installed; not wired into ranking. | H |
| §9 Expected move | Implemented | Chain summary `expected_move` (`ideas.py:150-158`, `evidence.py:595`). | – |
| §9 Bid/ask, depth, legging | Partial / Missing | Bid/ask only from the user's ICICI Breeze session (`strategy_plan/quotes.py:1-10`), flagged if wider than 10% (`rules.py:57-58`). No depth gate. No legging-risk check. | H for live F&O |
| §9 Expiry and event risk | Implemented | DTE 5–60 (`rules.py:62-64`), expiry-week flag, results-in-horizon. | – |
| §9 Do not rely on a single-leg stop | Implemented | Structure-level levels from the payoff engine (`services/strategy_levels.py:1-4`). | – |
| §12 Point-in-time data and signal timestamps | Partial | F&O studies are PIT with entry at the next open (`fno_backtest/outcomes.py:32-42, 45-54`). The DSL backtest **enters at the signal bar's close** (`backtest.py:189-194`). | M |
| §12 No look-ahead or survivorship bias | Partial / Contradicts on staging | DSL universe `latest_snapshot` (survivorship), honestly labelled. 4 constituent snapshots exist. | H |
| §12 Fees, taxes, spread, slippage, impact | Partial and inconsistent | DSL: 5 bps + ₹20/side, no STT/stamp/GST (`backtest.py:76-77`). F&O: assumed 0.15%/0.30% round trip. AI Trader validation: full zerodha-equity-v1 card (`research/costs/engine.py`). Reversal: 0.35%/0.60%. No impact model anywhere. | M |
| §12 Gap-through-stop | Missing | DSL fills at the stop price even when the bar opened below it (output in §2). | H |
| §12 Partial fills | Missing | No engine models them. | M |
| §12 Corporate actions | Implemented (warehouse/DSL/F&O) / **Contradicts (scanner)** | DSL uses `prices_eod_adjusted` (`backtest.py:7-14`). The scanner reads raw `stock_ohlcv` (§Q5). | H |
| §12 Symbol changes, delistings, expiry rolls | Partial | Expiry buckets in the F&O B2 study (`expiry_study.py:24-26`). Symbol changes (LTIM→LTM) and delistings are not handled in symbol joins. UNVERIFIED in code beyond grep. | M |
| §12 Out-of-sample and walk-forward | Partial | F&O studies: pre-registered splits plus permutation. AI Trader: folds plus a sealed holdout. The sealed block 2023-01..2024-07 mostly predates staging prices (start 2024-04-01). DSL itself: none. | M |
| §12 Multiple regimes, trade count | Partial | AI Trader `by_regime`, minimum trade counts; F&O `MIN_SIGNALS=100`. | L |
| §12 Sensitivity to thresholds and costs | Partial | F&O grid plus cost stress; reversal cost scenarios; none in the DSL engine. | M |
| §12 Paper trading | Partial | `desk_paper_trades` 9 docs. The F&O forward test `fno_forward_signals` has 0 docs (cron `deploy/nivesh-staging/fno-forward.cron` not installed). | M |
| §12 Metrics | Partial | Table in Q5. | M |
| §13 Rule families 1–3 (breakout, pullback, momentum) | Implemented | Scanner stages/buckets (`scorer.py:157-200`, `selection.py:27`). | – |
| §13 Family 4 (breakdown/bearish) | Partial | Futures and options only; cash is "avoid". | M |
| §13 Structural + ATR stops | Implemented | `trade_planner.py:76-84` (max(swing_low×0.995, entry−1.5×ATR)); `ATR_2X_STOP` (`research_chart.py:372-410`). | – |
| §13 Risk-based sizing | Implemented | `candidates.py:90-121`; desk `_trade_scenario` (`routes/positional.py:1642+`). | – |
| §13 Fixed-R targets | Implemented | `candidates.py:56-87` (2R base, 3R optimistic). | – |
| §13 Tested trailing exits | Missing | Untested, backtest-only. | M |
| §13 Time exits | Partial | DSL `max_hold_days`; scanner horizon days. Live exits are lane B. | L |
| §13 Options defined-risk evaluation | Implemented | Payoff engine plus sizing `too_small`. | – |

---

## 2. Worked examples: PRD figure vs real code output

Harness: `docs/ai_research/guidelines_gap_study_20261027/harness/worked_examples.py`. It calls only repo functions: `strategy_plan.candidates.size_position` / `scenario_levels`, `routes.positional._trade_scenario`, `strategy_plan.engine.compute_payoff`, and `strategy_engine.backtest._maybe_close_trade`. Capital is set to ₹1 crore so the 25% allocation cap never binds.

| Ex | PRD | Code output (this session) | Match | Code path / note |
|---|---|---|---|---|
| A | 85 sh, ₹2,975, 2R ₹1,075, 3R ₹1,110 | qty 85, risk_at_stop 2975.0, base 1075.0, optimistic 1110.0 | ✔ | `size_position`, `scenario_levels`. **Desk calculator: loss_at_stop_net ₹3,098.94 > ₹3,000 budget.** Costs are not in the sizing, contrary to PRD §5 and §11. |
| B | 178 sh, ₹2,492, 2R ₹910 | qty 178, 2492.0, base 910.0 | ✔ | same |
| C | 400 sh, 2R ₹532 | qty 400, 2000.0, base 532.0; ATR stop 522−2×2.5 = 517.0 | ✔ arithmetic | **No intraday path**: `plan.py:183-184` gives `intraday_not_supported`, and there are no minute bars. |
| D | 227 sh, ₹2,497, 2R ₹653 | size_position qty 227, 2497.0; scenario_levels(short) base 653.0 | ✔ arithmetic | **No short cash path**: `_trade_scenario` → `valid:false` [`stop_not_below_entry`, `target_not_above_entry`]; cash plan bearish → "avoid" (`candidates.py:205-207`). |
| E | ₹2,500/lot, 2R ₹1,300 | 1 lot (100 units), risk 2500.0, base 1300.0; desk calculator qty 100, net loss at stop ₹2,663.75 | ✔ | `linear_candidate` uses the same function (`candidates.py:293`). Net loss is again above budget. |
| F | max loss ₹4,500, max gain ₹5,500, BE 25,090, reject vs ₹2,500 | gross: max_loss −4500.0, max_profit 5500.0, BE [25090.0]; default costs: capital_at_risk 4588.75; sizing `too_small`, qty 0 | ✔ | `compute_payoff`; `candidates.py:748-762` sets `no_trade` "sizing_zero". |
| G | ₹2,485 (71 sh) | qty 71, risk_at_stop 2485.0 | ✔ | Example A's levels with a ₹2,500 budget. |
| H | trail ₹1,040 | stop_now 1040.0 after a bar with high 1080 / low 1045 | ✔ | DSL backtest only. **Same bar with low 1035: STOPLOSS at ₹1,039.48.** The trail is raised by the bar's high and then hit by the same bar's low, so intrabar order is assumed. ATR is frozen at entry. |
| (gap) | §5/§12: a stop can fill worse on a gap | Bar open 950, low 940, stop 970 → exit 969.515, pnl −₹344.85 | ✘ vs PRD | `backtest.py:317-320` fills at the stop ("could gap below; ignore for v1"). The true fill is about ₹950, so the loss is understated by about ₹195 on 10 shares. |

Raw output, unedited:
```
A size_position {"status": "complete", "quantity": 85, "units": 85, "risk_at_stop_inr": 2975.0, "binding": "risk_budget", "reason": null} levels {"conservative": 1075.0, "base": 1075.0, "optimistic": 1110.0}
A trade_scenario {"valid": true, "problems": [], "qty": 85, "binding": "risk_budget", "loss_at_stop": 2975, "loss_at_stop_net": 3098.94, "profit_at_target": 5950, "warnings": []}
B size_position {"status": "complete", "quantity": 178, "units": 178, "risk_at_stop_inr": 2492.0, "binding": "risk_budget", "reason": null} levels {"conservative": 910.0, "base": 910.0, "optimistic": 924.0}
C size_position {"status": "complete", "quantity": 400, "units": 400, "risk_at_stop_inr": 2000.0, "binding": "risk_budget", "reason": null} levels {"conservative": 532.0, "base": 532.0, "optimistic": 537.0} ATR stop 522-2x2.5 = 517.0
D size_position {"status": "complete", "quantity": 227, "units": 227, "risk_at_stop_inr": 2497.0, "binding": "risk_budget", "reason": null} levels(short) {"conservative": 653.0, "base": 653.0, "optimistic": 642.0}
D trade_scenario {"valid": false, "problems": ["stop_not_below_entry", "target_not_above_entry"], ...}
E size_position(lot 100) {"status": "complete", "quantity": 1, "units": 100, "risk_at_stop_inr": 2500.0, "binding": "risk_budget", "reason": null} levels {"conservative": 1300.0, "base": 1300.0, "optimistic": 1325.0}
E trade_scenario(lot 100) {"valid": true, "problems": [], "qty": 100, "binding": "risk_budget", "loss_at_stop": 2500, "loss_at_stop_net": 2663.75, "profit_at_target": 5000, "warnings": []}
G size_position(budget 2500 on A's levels) {"status": "complete", "quantity": 71, "units": 71, "risk_at_stop_inr": 2485.0, "binding": "risk_budget", "reason": null}
F payoff gross {"valid": true, "problems": [], "max_loss": -4500.0, "max_profit": 5500.0, "breakevens": [25090.0], "net_premium": -4500.0, "capital_at_risk": 4500.0}
F sizing vs Rs2500 budget gross {"status": "too_small", "quantity": 0, "reason": "The risk budget or the allocation cap buys less than one share/lot."}
F payoff default costs {"valid": true, "problems": [], "max_loss": -4500.0, "max_profit": 5500.0, "breakevens": [25090.0], "net_premium": -4500.0, "capital_at_risk": 4588.75}
F sizing vs Rs2500 budget default costs {"status": "too_small", "quantity": 0, "reason": "The risk budget or the allocation cap buys less than one share/lot."}
H trail after bar(high 1080, low 1045) {"stop_now": 1040.0, "closed": false}
H same bar sets high 1080 AND low 1035 {"stop_now": 1040.0, "exit_reason": "STOPLOSS", "exit_price": 1039.48}
gap-through-stop (open 950 < stop 970) {"exit_reason": "STOPLOSS", "exit_price": 969.515, "pnl_abs": -344.85}
```

Existing tests with similar arithmetic: `tests/test_positional_scenario.py` (long worked example ₹5,000 budget / 200 sh, lot rounding, budget smaller than one share), `tests/test_strategy_payoff.py:140-155` (bull call spread 1300/1350), `tests/test_strategy_plan.py:547+` (bull-call sizing and alternatives), `tests/test_strategy_backtest_sizing.py`. **No test covers the trailing stop or gap fills.**

---

## 3. Per-question detail

### Q1. Indicator inventory, and whether it is populated on staging

The decision path has three layers, each with its own indicator set:

1. **AI scanner** (`services/positional_engine`; its `final_score` ranks the desk's cash ideas: `strategy_plan/selection.py:1-9`, `ideas.py:30-33`). Features come from `feature_calculator.compute_features` (`:328-390`): SMA20/50/200, EMA20, RSI14, MACD, ATR14/ATR%, Bollinger width, 5d/20d returns, 20/52-week highs, swing high/low 20, volume z20, delivery trend. Breadth, VIX, FII/DII and ADX are not used. Its bar store is `stock_ohlcv` (app Postgres), filled by its own bhavcopy fetch.
2. **Plan evidence ledger** (`strategy_plan/evidence.py`). Market context: desk regime, breadth, Nifty vs 50-session average, India VIX, sector strength. Technical: EMA20/50/200, MACD hist, ROC20, RSI14, rs63, ATR14/ATR%, RVOL20, traded value, support/resistance 20, chart patterns, scanner bucket and gates. Derivatives: OI build-up, cash confirmation, nearest future, chain freshness, PCR/max pain/walls, ATM IV/expected move, OI/volume liquidity proxy, broker bid/ask. Indicators are computed on demand from `nidp.prices_eod_adjusted` (`routes/research_chart.py:323-360`).
3. **Regime-fit (F&O ranking)**: direction 40 / volatility 30 / breadth 15 / positioning 15 (`regime_fit.py:89`), with VIX standing in for IV.

Data test on staging, 2026-10-26 (VERIFIED):
```
stock_technical_features 2026-10-26: n=2210, sector_score 2210, rsi_14 2210, sma_200 2155 (55 null), atr_14 2210
components.raw nulls: delivery_trend_pct 12, sma_200 55, breakout_proximity 0, bb_width 0, dist_to_support 0, macd 0
stored weights: {"risk":0.1,"trend":0.25,"sector":0.1,"momentum":0.15,"structure":0.2,"accumulation":0.2} on all 2210 rows
stock_ohlcv 2026-10-26: 2930 bars, delivery_pct on 2709
warehouse prices_eod 2024-04-01..2026-10-26 (1,973,800 rows, 6,262 symbols); prices_eod_adjusted 1,098,819 rows, adj_close 1,098,819
index_eod Nifty 50 / India VIX / Nifty Bank: 381 rows each 2024-04-01..2026-10-26; Nifty 50 by year 2024:118, 2025:63, 2026:200
index_eod 2026-10-26: 151 indices (114 'Nifty …')
fii_dii_flows FII/DII EQUITY_CASH 247 rows 2018-09-01..2026-10-26 (monthly + daily); FII FUT_NIFTY etc. 138 rows 2026-04-01..2026-10-21
macro_daily (desk regime source): 9 rows 2026-10-09..2026-10-23, india_vix 9/9, source ^NSEI / ^INDIAVIX
index_constituents: 4 snapshot dates 2026-10-12..2026-10-22; ~282 symbols in a non-broad index on 10-22
sector_master with a sector: 550
event_calendar: 27,619 rows, 815 events in the next 30 days, max event_date 2026-11-16
v_feed_status: NSE_BHAVCOPY / NSE_FNO_BHAVCOPY / NSE_INDEX_CLOSE OK (2026-10-26); NSE_DELIVERY 2026-10-23; sensibull_fii_dii STALE (10-22); every last_dq_status = NONE
```

**New defect: the scanner's bar store is corrupt (VERIFIED, H).** `stock_ohlcv` holds 262 dates. Diffed against the warehouse trading calendar, it holds **14 dates that are NSE holidays**: 2025-10-22, 2025-11-05, 2026-01-15, 2026-01-26, 2026-03-03, 2026-03-26, 2026-03-31, 2026-04-03, 2026-04-14, 2026-05-01, 2026-05-28, 2026-06-26, 2026-09-14, 2026-10-02. On every one, **100% of rows exactly duplicate the previous session** (open, close and volume identical; for example 2026-10-02: 2908/2908). It also **lacks real sessions 2026-10-21 and 2026-10-22**, which are present in `prices_eod`.

Root cause in code: `bhavcopy_ingester.parse_bhavcopy_csv` stamps the **requested** date (`bhavcopy_ingester.py:69`, `"bar_date": on_date`) and never reads the file's own trade date. It only fetches the run date (`scripts/run_positional_engine.py:91-98`), so a missed day is never back-filled.

Effects: about 5% of bars are phantom zero-change bars. They inflate volume baselines, add zero returns to RSI, and distort 20/50/200-bar windows. The 10-23 features and breadth span 4 real sessions as if they were 2. Why NSE served a file for holiday URLs is UNVERIFIED (no network access from the sandbox, and I did not fetch from staging).

**Raw prices in the scanner (VERIFIED, H).** `stock_ohlcv` is unadjusted bhavcopy: KOTAKBANK closes 2133.30 (01-13) and then 421.00 (01-14). 111 symbols show a one-day move of ≥40% in `stock_ohlcv`, and 91 symbols had a ≥20% adjustment-factor step in `prices_eod_adjusted` inside the scanner's window (2025-10-17..2026-10-26). For those symbols, SMA/ATR/returns/swing levels straddle a price break until it leaves the window. The research chart detects such breaks (`research_chart.py:309-320`); the scanner does not.

### Q2. Setup score: actual components and calibration

| PRD component (weight) | AI scanner component (weight) | Notes |
|---|---|---|
| Market regime (15) | — | Multiplier ×0.8/1.0/1.1 from `macro_state.risk`, plus a sector tilt of ±10 points /100, plus macro-blocked sectors as a hard filter (`scorer.py:228-260`, `pipeline.py:282-318`). |
| Trend quality (20) | trend (25) | Close>SMA50, close>SMA200, SMA50>SMA200, SMA20 slope ramp (`scorer.py:43-58`). No ADX. |
| Relative strength (15) | "sector" (10) | Stock 20d return − NIFTYBEES 20d return, ramp −5%..+5% (`scorer.py:138-141`). |
| Momentum (15) | momentum (15) | RSI band, MACD>signal, 5d return (`scorer.py:61-84`). |
| Volume confirmation (15) | accumulation (20) | Delivery trend and volume z-score (`scorer.py:118-135`). |
| Price setup quality (20) | structure (20) | ATR% tightness, BB width, breakout proximity (`scorer.py:87-115`). |
| — | risk (10) | Distance to support and ATR% (`scorer.py:144-165`). The PRD treats risk as a gate, not a score. |

Missing inputs collapse to **0.5 neutral** (`scorer.py:30-36` `_ramp`; `score_sector(None)` → 0.5; `classify_stage` RSI `or 50.0` at `:173`; `trade_planner.py:106` `atr_pct or 2.0`). A failed macro lookup silently becomes multiplier 1.0 at DEBUG level (`pipeline.py:305-306`).

Other scores in play:
- Chartink picks evidence score (`rules.py:121-158`): 25/12/10/8/8/10/10/8/5/4. A missing figure earns 0 there, the opposite convention to the scanner.
- Regime-fit 40/30/15/15.

Calibration / OOS evidence (staging, VERIFIED): `positional_outcomes 0, positional_backtest_labels 0, accumulation_calibration 0, strategy_signals 0, strategy_runs 3, strategy_versions 5`. The accumulation calibration pipeline exists (`positional_engine/backtest.py:1-21`) but has never filled the table on staging. regime_fit says the same thing in its own docstring (`regime_fit.py:8-12`).

Rejected-signal / never-scored-mover coverage: **not measured anywhere**. Grep finds no recall or missed-mover logic. Ideas list exclusions only above the last selected row (`ideas.py:226-227`). The DSL backtest silently drops candidates beyond free slots (`backtest.py:185`, `rows[:slots]`). The data to measure it exists: `stock_technical_features` stores all of the about 2,210 scored names per day.

### Q3. Worked examples

See §2. Summary:
- A, B, E, F and G are fully computed by production code.
- C and D are arithmetic only, with no instrument workflow (intraday is refused; cash is long-only).
- H is backtest-only, with an intrabar-order assumption and no tests.
- **Arithmetic the code gets wrong vs the PRD:** sizing ignores costs (PRD §5 "Include fees, taxes, spread and realistic slippage in the risk estimate"; §11 reject if `estimated_risk > max_trade_risk`). The desk calculator reports `loss_at_stop_net` 3,098.94 for a ₹3,000 budget and does not reject. Gap fills are also wrong.
- Cross-area fact for agent A: `routes/positional.py:1578-1606` `_size_position` forces `qty = max(1, …)` and only applies the 2% risk cap when `max_qty_by_risk > 0`. When one share's risk exceeds 2% of capital, it returns qty ≥1 above the cap instead of 0.

### Q4. Options data quality

**IV history tooling** (`services/fno_iv_history.py`):
- Schema: `_id` `"<UNDERLYING>:<date>"`, `buckets.near_month/next_month{expiry, atm_strike, spot, forward, call_iv, put_iv, atm_iv, reason}`, `calc_version` `fno-atm-iv-v1`, `method` recorded/backfill.
- Writer: idempotent upsert (`:73-86`).
- IV rank and percentile: need 252 sessions (`:54`, `:150-189`).
- Recorder and backfill: `scripts/record_iv_history.py` (`--backfill-days`, `--symbols`, `--dry-run`, `--recompute`), reading through DaaS `/v1/fno/{symbol}?on=` → `routes/fno.py` `session_iv`.
- Schedule: documented, not installed (`record_iv_history.py:24-29`; `/etc/cron.d` lists only ai-watchlist, cache-clear, db-snapshot, positional-engine, research-watchlist, sysstat).

Staging (VERIFIED): `fno_iv_history 0`. Source coverage is sufficient:
```
fno_bhavcopy 2025-10-01..2026-10-26, 262 sessions, 238 symbols, 10,339,788 rows; 2026-10-26: IDO 6, STO 213 underlyings
NIFTY/BANKNIFTY/RELIANCE: 262 sessions each; underlyings with >=252 sessions: 196; underlying-sessions with options: 56,181
```

**Where IV rank/percentile would be used:** today only `GET /api/fno/{symbol}/iv-history`. regime-fit uses India VIX vs 20 as its "rich/cheap" proxy (`regime_fit.py:122-134, 176-186`). Candidate selection uses **cross-sectional** IV Tukey fences across the chain's own strikes (`candidates.py:422-429`), not history.

**Bid/ask/depth:**
- Kite live feed: futures/options in `full` mode keep top of book (`kite_live_feed/feed.py:11-12, 96-111`). Minute replay docs carry b/a/bq/aq (`quote_cache.py:80-83`, TTL 90 days).
- Staging: `kite_live_minute 0`, `kite_live_intraday 0`, `kite_live_close` 2 docs (2026-10-23, 2026-10-26, both REST after close). The live feed is not consumed by `strategy_plan`, `fno_candidates` or `risk_gate` (grep, no hits).
- The plan's bid/ask evidence comes only from the user's ICICI Breeze session (`strategy_plan/quotes.py:1-10, 98-112`). Zerodha has no quote reader there. A spread wider than 10% of mid is flagged, not blocked (`rules.py:57-58`).
- Liquidity proxy: a leg with zero OI or zero volume blocks; OI/volume below 25% of the window median flags (`rules.py:61-69`; `candidates.py:735-739`). `fno_candidates` reports spread/depth as explicitly unknown (`fno_candidates/engine.py:250`).
- No depth threshold and no legging-risk logic anywhere (grep).

**Missing or stale data, branch by branch:**

| Input | Behaviour | Cite |
|---|---|---|
| Price history stale >4 calendar days | **blocks**: `insufficient_data` "stale_data" | `plan.py:189-193`, `rules.py:23` |
| Price source down / unknown symbol | blocks | `plan.py:185-188` |
| Chain older than the last session | evidence item `conflicts` plus a "Delayed/historical" label; candidate still built | `evidence.py:589-592`, `candidates.py:726-729` |
| Chain or build-up unavailable | explicit `unavailable` items; futures/options candidate `insufficient_data` | `evidence.py:554,567,585`; `candidates.py:373-380` |
| Leg with no premium / zero OI / no trades | blocker → `no_trade`; never a guessed premium | `candidates.py:730-739` |
| Broker quotes missing | `bid_ask` unavailable (informational) | `quotes.py:1-10` |
| Desk regime VIX/breadth missing | that check skipped with a reason; no trend → no regime | `macro_engine.py:946-958` |
| Regime older than the chain (regime-fit) | **warning only** (`staleness_note`); fit scored on the old regime. Real on staging: the stored 10-26 watchlist says "chain 2026-10-26, regime 2026-10-23" | `regime_fit.py:785-797` |
| IV history missing | route returns null rank with a reason; nothing downstream uses it | `fno_iv_history.py:160-174` |
| **Scanner inputs missing** | **silent 0.5 neutral / defaults** | `scorer.py:30-36,173`; `trade_planner.py:106` |
| **Scanner macro state missing** | **silent multiplier 1.0 (DEBUG log)** | `pipeline.py:305-306` |
| **Benchmark close for rs63** | `_close_on_or_before` carries any earlier close with **no age limit** | `research_chart.py:290-292` |
| **Scanner benchmark NIFTYBEES** | last 25 bars up to the scan date; no freshness check | `sector_strength.py:41-46` |
| **Event calendar shorter than the horizon** | "No results date inside the horizon" stated as fact; calendar ends 2026-11-16, so 60-day horizons are blind past it | `evidence.py:495-517` |
| Pre-decision freshness for live F&O | absent, and the readiness gate says so: "no freshness check runs before a decision" | `risk_gate/readiness.py:87-89` |

### Q5. Backtest engines

| Metric (PRD §12) | DSL `strategy_engine/backtest.py` | F&O Stage A/B2 `fno_backtest` | AI Trader (`ai_trader/validation.py`, `strategy.py`) | Reversal `positional_engine/reversal_backtest.py` |
|---|---|---|---|---|
| Expectancy per trade | no (derivable) | mean net return per signal | `expectancy_net_pct` | mean net |
| Expectancy per session | no | session is the unit (NW SE) | no | no |
| Win rate, avg win/loss | yes (`:443-456`) | n/a | hit rate (shrunk) | touch rates |
| Payoff ratio | no (derivable) | no | no | no |
| Profit factor, max DD | yes; DD from a daily MTM curve | no | through the DSL run | MAE |
| Sharpe / Sortino | **no** | no | no | no |
| Exposure, turnover, capital usage | **no** (only skipped counts) | no | no | no |
| Slippage/cost sensitivity | no (fixed 5 bps + ₹20) | yes, 0.15% vs 0.30% | no (one card) | yes, 0.35% vs 0.60% |
| Rejected-signal coverage | **no**; `rows[:slots]` drops silently (`:185`); `skipped_entries` counts only cash/min-qty skips | discovery-winners vs chance | `skipped{short_not_supported, sealed_window, ...}` | no |
| Costs | slippage 5 bps/side + ₹20/side; no STT/stamp/GST/exchange (`:76-77`) | assumed % of notional (`outcomes.py:12-16`) | full zerodha-equity-v1 card, retroactive | assumed % |
| Gap-through-stop | **fills at the stop** (`:317-320`; demo in §2) | n/a (close-to-close) | n/a | n/a |
| Partial fills | no | no | no | no |
| Entry timing | **same-bar close + slippage** (`:189-194`) | next open | next open | next open (UNVERIFIED detail) |
| Walk-forward / holdout | none in the engine | pre-registered splits + permutation | N folds + one sealed holdout run | split blocks + bootstrap |
| Survivorship | `latest_snapshot` on staging (DaaS provider, `market_data.py:180-187`) | F&O universe from bhavcopy per day (PIT) | through the DSL run | per-day universe |
| Corporate actions | adjusted warehouse prices | adjusted | adjusted bars (UNVERIFIED for its source) | own `adjust_actions` |

Stored staging runs (VERIFIED, metrics only; equity curves omitted):
```
run 2026-04-20..10-20: trade_count 82, win_rate 41.46, profit_factor 0.53, max_dd -0.27, total_return -0.25, universe_basis latest_snapshot, price_basis corp_action_adjusted (no sizing_basis: an older engine)
run 2026-06-01..09-18: trade_count 47, win_rate 27.66, profit_factor 0.64, max_dd -8.14, total_return -4.10, skipped_insufficient_cash 12, universe_basis latest_snapshot
run 2026-04-21..10-21: trade_count 22, win_rate 22.73, profit_factor 0.22, max_dd -5.15, total_return -3.96, universe_basis latest_snapshot
strategy_runs.snapshot_as_of = NULL on all three (no code writes it: grep finds no writer)
```
Research verdicts already on file: `docs/FO_RANKING_BACKTEST_FINDINGS_20261023.md` ("Not validated") and `docs/FO_STAGE_B2_FINDINGS_20261023.md` (short build-up near-month inconclusive, p 0.060).

Tests run this session (VERIFIED, real output):
```
pytest test_positional_scenario test_strategy_payoff test_strategy_plan test_strategy_backtest_sizing test_strategy_backtest_adjusted test_strategy_engine test_fno_backtest test_fno_iv_history test_reversal_backtest test_movers_v4 test_research_chart
361 passed, 2 warnings in 36.22s
pytest test_positional_engine test_positional_calibration test_positional_runner_guards test_ai_trader test_ai_trader_strategy test_fno_candidates test_fno_forward test_kite_live_feed test_regime_fit test_regime_fit_distinct test_strategy_ideas test_strategy_levels test_macro_regime_history
449 passed, 3 warnings in 42.31s
```
Both suites passing says the code does what its own tests encode. It does not cover the gaps above, because no test asserts gap fills, trailing behaviour, cost-inclusive sizing, or bar-store integrity.

### Q6. Intraday readiness (PRD Example C)

VERIFIED on staging:
```
warehouse: to_regclass('nidp.intraday_bars') = NULL, to_regclass('nidp.intraday_ingest_log') = NULL  (migration 152 exists in the repo, not applied)
warehouse: no table matching intraday|minute|tick; nidp.tpd_paper_index_bars 0 rows (daily open/close only)
Mongo: kite_live_minute 0, kite_live_intraday 0, kite_live_close 2 (2026-10-23, 2026-10-26)
```
Code paths:
- On-demand Kite candles at 5m/15m/30m/60m, raw, at most 30 sessions, needing the daily platform token (`kite_live_feed/intraday.py:1-40`). No 1-minute interval and no storage.
- The `kite_bars` collector (`nidp/services/kite_bars`) writes minute bars to `nidp.intraday_bars` with an ingest log, but needs a manual daily Kite login (README) and is not scheduled.
- The plan refuses an intraday horizon (`plan.py:183-184`).

Timestamp alignment cannot be tested because there are no rows. In code, `intraday.py` stamps the candle open time in IST and `bar_ts` is the candle open (`migration 152`). Days × symbols = 0. **Verdict: NO-GO for an opening-range breakout.**

### Q7. Reproducibility and versioning

| Artifact | Stored | Missing |
|---|---|---|
| `positional_signals` / `stock_technical_features` | `engine_version` (`positional.v1.0`, `positional_engine/__init__.py:11`), `computed_at`; weights plus raw features in `components` JSONB | **Upsert overwrites** (`pipeline.py:246`), so there is no history of reruns. The version string is a constant that does not change with scorer edits. No bar-set fingerprint, universe source (Chartink vs OHLCV) or macro inputs on the signal. |
| Strategy plan / ideas | `rules_version` `strategy-rules.v1.5`, `calculation_version` `payoff-v1`, per-source `data_as_of`, deterministic `plan_id`, `plan_inputs` (`ideas.py:209-220`) | Not persisted except via the watchlist. |
| `ai_watchlist_days` (insert-once) | `list_date`, `built_at`, `notes.cash_rules_version`, `fno_rules_version` `regime-fit-v1`, `cash_data_as_of` {scanner, picks, eligibility, price, fno}, regime snapshot, `fno_staleness` (VERIFIED on the 2026-10-26 doc) | Scanner `engine_version`, scorer weights, calculation_version, code SHA. |
| `strategy_runs` (DSL backtests) | `strategy_id`, `version_id` (spec in `strategy_versions`), metrics with price/universe basis, cost params per trade | `snapshot_as_of` always NULL; no code SHA; no data watermark. |
| F&O studies | `STUDY_VERSION`, canonical config hash, `FROZEN_BASELINE_HASH`, pre-registration docs, JSON reports in `test_reports/` | Fine for research. |
| `fno_forward_signals` | `version` `fno-forward-v1`, first write wins | 0 docs: cron not installed. |
| `fno_iv_history` | `calc_version`, `method`, `recorded_at` | 0 docs. |
| `risk_decisions` | `policy_version`, `limits_version`, `inputs_hash` | – |
| `desk_paper_trades` | `rules_version`, `strategy_version`, `signal_at`, `cost_model` | – |
| `ai_trader_strategies` | `version` hash, `provenance.as_of`, `stage_history`, `holdout_used` | – |

---

## 4. Recommendation: research-hardening plan (Q8)

Effort: S ≤ 1 day, M 2–5 days, L > 1 week. Any item that writes staging data needs the user's approval first.

**(f, done first) Data integrity and freshness contract. Fix first: everything below is measured on these inputs.**
1. **Fix the scanner bar store.** (S code + a separately approved data repair.) Make the bhavcopy parser read the file's own trade-date column and refuse a file whose date ≠ the requested date. Add a calendar check against `nidp.prices_eod` sessions to `--require-bars`. Back-fill missed sessions (10-21, 10-22). Delete the 14 phantom holiday bars, then recompute features for the affected dates. Validation query: `SELECT bar_date FROM stock_ohlcv EXCEPT SELECT as_of_date FROM nidp.prices_eod` must return 0 rows, and the reverse direction must return 0 since 2025-10-20.
2. **Move the scanner onto adjusted prices.** (M.) Read `prices_eod_adjusted`, or apply its factors, so the 91 symbols with splits or bonuses in the window stop producing broken SMA/ATR values. The alternative is to truncate history at an adjustment break, as `research_chart._adjustment_break` already does.
3. **Freshness contract.** (M.) One helper returns `{source, as_of, age_sessions, budget, ok}` for each input: bars, benchmark, regime/VIX/breadth, chain, IV, quotes, and event-calendar coverage end. Scanner, ideas, regime-fit and the risk gate all consume it. Rules:
   - A required input that is stale **blocks**.
   - An optional input becomes explicit `unavailable`.
   - The scanner records which sub-scores were defaulted to 0.5 instead of hiding it.
   - Cap `_close_on_or_before` at about 3 sessions.
   - Warn when `event_calendar.max(event_date)` is earlier than the horizon end.
   - Back-fill the 2024–2025 holes in `index_eod` (Nifty 50 has 63 of about 248 sessions in 2025).

**(a) Worked-example test suite.** (S.) Put `tests/test_prd_worked_examples.py` beside `test_positional_scenario.py`, parametrised over A–H with the PRD inputs.
- Functions: `size_position` (A, B, C, D, E with lot 100, G), `scenario_levels` (2R/3R, short for D), `compute_payoff` (F gross plus the default-cost `capital_at_risk` 4588.75), the `size_position(..., car)` "too_small" result, and `_maybe_close_trade` (H plus the same-bar case).
- Add explicit **divergence tests**, each pinned to a PRD clause so a later fix flips it intentionally:
  - A's net loss at stop 3,098.94 > 3,000 (cost-exclusive sizing);
  - a gap fill at the stop instead of the open;
  - intraday → `intraday_not_supported`;
  - short cash → `long_only`.
- Add the first unit tests for the trailing stop: it moves only up, uses frozen vs per-bar ATR, and has a defined intrabar order.
- Product decisions to raise, not fix silently: cost-inclusive sizing (S), gap fill at `min(open, stop)` (S, needs `open` added to `EXIT_BARS_SQL`), and trailing-stop update at bar close vs intrabar (S).

**(b) IV-history backfill, then the F&O risk gate.** (M.) Needs approval because it writes staging Mongo.
1. Source: `nidp.fno_bhavcopy` via DaaS, range 2025-10-01..2026-10-26 (262 sessions).
2. Order: `--symbols NIFTY,BANKNIFTY --backfill-days 262 --dry-run`, then the real run (expect ≤524 docs). Then the stock underlyings in groups of about 20. The script's own estimate is about 6 reads per underlying-session, so about 340k DaaS reads in total.
3. Expected total: ≤56,181 docs (the underlying-sessions with options). Underlyings that should get a defined IV rank/percentile: 196 (those with ≥252 sessions).
4. Idempotency: the upsert by `_id` is safe to rerun; leave `--recompute` off.
5. Validation queries:
   - doc counts per underlying = `fno_bhavcopy` session count;
   - `atm_iv` null rate < 2%, with the reasons listed;
   - every doc has `calc_version` `fno-atm-iv-v1` and `method=backfill`;
   - NIFTY near-month ATM IV vs India VIX: level within a few points and correlation > 0.8 (sanity, not truth);
   - one session spot-checked against `/api/fno/NIFTY/chain?on=`'s `atm_iv`;
   - `/api/fno/NIFTY/iv-history` returns non-null `iv_rank`.
6. Then install the 23:00 IST cron and the `fno-forward` cron.
7. Wire IV percentile into regime-fit's volatility axis as an A/B against the VIX proxy, and rewrite GAPS.
8. **Before the F&O risk gate is turned on in staging:**
   - the IV backfill is validated;
   - the freshness contract runs before every decision (readiness P0.1);
   - a stale chain blocks instead of warning;
   - margin is checked or the gate refuses without it;
   - the 14 phantom and 2 missing bar sessions are fixed;
   - the A–H suite is green.

**(c) ADX and RS as controlled experiments.** (M; depends on (f) 1–2.)
- Baseline: the current scorer exactly (`positional.v1.0` weights), recomputed point-in-time on adjusted prices.
- Arms: (1) add an ADX(14)>20 & +DI>−DI trend term; (2) replace the "sector" term (stock vs NIFTYBEES, 20d) with rs63 vs the Nifty 50 index; (3) both. Everything else is held fixed.
- Protocol: pre-register; reuse `fno_backtest.outcomes.split_bounds` 60/20/20 and `stats.summarize`. Outcome = next-open entry, 10-session excess return over the universe, net of 0.35%, Newey-West SE. Measure top-decile minus median spread and rank IC.
- Decision rule: adopt only if validation **and** test both improve beyond the permutation null.
- Power: the warehouse has prices from 2024-04-01 (about 2.5 years). Use it, not the scanner's 262 bars.
- Keep the current weights until this passes.

**(d) Missing backtest diagnostics.** (M.) Extend `_compute_metrics`:
- expectancy (₹ and R) per trade and per session, and the payoff ratio;
- Sharpe and Sortino from the daily mark-to-market curve;
- exposure (share of days invested, average gross exposure / equity), turnover, and average and maximum capital deployed;
- `signals_seen` vs `signals_taken` (count `rows[slots:]`);
- a slippage sweep at 0/5/10/20 bps;
- the `research/costs` card in place of the flat ₹20;
- next-open entry as an option;
- `snapshot_as_of` plus the code SHA in `strategy_runs`.

Point-in-time constituents need snapshot history. Install the monthly job (already in the repo) and import NSE's historical index files for 2024–2026. That part is M–L.

**(e) Intraday go/no-go: NO-GO.** Preconditions, L in total:
1. Apply migration 152 on the staging NIDP.
2. A daily Kite login runbook, then the scheduled `kite_bars` collector for a pilot universe.
3. ≥60 sessions of minute bars, at 375 bars per full session, with gaps audited through `intraday_ingest_log`.
4. A first-candle-at-09:15-IST timestamp test.
5. The live feed writing `kite_live_minute` during the session (for spread).
6. Only then lift `intraday_not_supported`.

**Order:** f1 → a → f2/f3 → b → d → c → e.

---

## 5. UNVERIFIED

- Why NSE returned data for holiday URLs. The code-level cause (the requested date is stamped) is verified; the upstream behaviour is not, because I had no network access from the sandbox and did not fetch from staging.
- The AI Trader's bar source and its corporate-action handling. I did not trace `research/charting` data files on staging.
- Whether `routes/research_chart` indicators are correct beyond their tests. The memory note says technicals matched stored values on 2026-10-12; I did not re-check that.
- Symbol-change and delisting handling in joins. Grep only; not exercised.
- Movers v5 ADX served on staging. The code and its tests pass; I did not call the live endpoint.
