# Paper trading in NIDP — specification and gap analysis

**Owner specification, 2026-09-19.** Paper trading is a **controlled measurement and feedback layer** around NIDP,
not a simulated brokerage account and not an automatic learning loop. It must answer three questions:
1. Did the model identify a genuine market pattern?
2. Could the opportunity have been executed profitably in real market conditions?
3. How should the model improve, based on its mistakes?

**Governing principle: paper-trading results never automatically retrain the production model.** Capture them,
analyse them, and promote improvements only through controlled validation (see `SUCCESS_CRITERIA.md`).

Target structure: **pattern recognition → calibrated prediction → realistic paper execution → outcome attribution →
controlled model validation.**

---

## 1. Architecture (owner)
Market data (Kite WebSocket · 5-minute candles · daily data · events) → Feature & pattern engine (technical,
fundamental, event, regime, liquidity) → Prediction models (movement · direction · target/stop · expected return) →
**Signal ledger (immutable)** → **Paper execution (realistic fills)** → **Outcome & attribution engine** (target/stop
path, costs, slippage, model errors) → **Research & controlled retraining** (drift, pattern review, new versions,
walk-forward validation).

## 2. Requirements (owner)
**R1 Freeze every prediction.** Never overwrite a prediction when the market changes. Signal record: signal_id, symbol,
exchange, pattern_id, pattern_version, model_version, signal_timestamp_ist, feature_snapshot_id, entry_price,
entry_rule, target_price, stop_price, holding_period, movement_probability, direction_probability,
target_before_stop_probability, expected_net_return, market_regime, sector, liquidity_bucket, signal_status —
**plus the exact feature values at the signal timestamp.**

**R2 Separate pattern detection, trade decision and execution,** so a failure can be attributed to pattern
recognition, probability estimation, trade selection or execution simulation.
- Detection: does the current condition match a known pattern?
- Decision: is the risk-adjusted opportunity acceptable? (target-before-stop probability, expected net return,
  liquidity, regime, risk limits, entry/exit rules)
- Execution: had we attempted it, what would realistically have happened?

**R3 Realistic execution on 5-minute (or tick-derived) bars**, never "daily high touched the target". Record signal
time, intended entry, simulated entry, spread assumption, fill delay, MFE, MAE, exit reason and time, gross and net
P&L, gap-through-stop handling. **If the next candle opens below the stop, exit at the achievable price, not the stop.**

**R4 Outcome labels:** target_hit, stop_hit, timeout, gap_through_stop, no_fill, invalid_signal, net_return,
time_to_event, mfe, mae. Train on all of them where they reflect real operating conditions — not only wins and losses.

**R5 Error analysis after every completed trade:** correct prediction, false positive, false negative, probability
error — segmented by pattern, model version, sector, regime, time of day, liquidity, volatility, market cap and
probability bucket.

**R6 Calibration from completed outcomes:** reliability curves, Brier score, expected calibration error, drift, by
pattern and regime. Recalibrate with Platt, isotonic or beta calibration **fitted only on historical validation data —
never on the data used to declare performance.**

**R7 No retraining after every trade.** Lifecycle: immutable outcomes → monitoring → research dataset (finalised,
quality-checked labels only) → candidate model (defined window, versioned features) → validation on untouched data vs
current model and a simple baseline → promotion only after approval → paper evaluation again.

**R8 Phases** (duration set by sample size and market coverage, not the calendar; a few weeks of positive P&L is not
evidence): 1 Shadow mode (signals, no orders, 2–4 weeks) · 2 Historical replay (identical logic) · 3 Paper execution
on live data (8–12 weeks or sufficient sample) · 4 Stability analysis (rolling) · 5 Controlled production (limits,
monitoring).

**R9 Promotion gates** (gates, not a score): *Data & execution* — no look-ahead, correct timestamp alignment,
realistic entry/exit, costs and slippage, gap-through-stop, sufficient liquidity. *Model* — out-of-sample
performance, calibration, regime stability, baseline comparison, model version and feature snapshot recorded.
*Economics* — positive net expectancy in the evaluation period, drawdown within the declared limit, not dependent on a
few outliers, trade-level results retained, pattern failure conditions documented.

**R10 Tables:** pattern_definitions, pattern_signals, signal_feature_snapshots, paper_orders, paper_fills,
paper_positions, paper_trade_outcomes, model_predictions, model_evaluation_runs, pattern_performance_daily,
model_versions. Chain: definition → signal → prediction → order → fill → outcome → evaluation run. **Records are
immutable; a correction creates a new evaluation version.**

**R11 Implementation priority:** 1 immutable signal ledger · 2 live 5-minute candle aggregation · 3 deterministic
paper-execution engine · 4 target-before-stop labelling · 5 pattern-level dashboard (signal count, calibration, net
expectancy, max drawdown; by pattern, model version, regime, probability bucket, sector/liquidity, failure reason) ·
6 calibration · 7 drift monitoring · 8 controlled retraining pipeline.

---

## 3. Gap analysis — Paper Trade Engine v1 vs this specification
Verified against the code (`backend/nidp/services/tpd_model/paper/`) and `nidp_staging` on 2026-09-19 04:20 IST.
Current data: replay 327,002 prediction snapshots / 1,650 trades; forward 3,982 / 20; 1,655 exits per mode; one rule
set `paper-v1`.

| Req | Status | Evidence / gap |
|---|---|---|
| R1 immutable ledger | **Partial** | `tpd_paper_prediction_snapshots` is insert-only with `prediction_version` + `supersedes`, `prediction_timestamp`, `data_cutoff_timestamp`; forward snapshots are hash-verified and count only if frozen after the rules were registered; rule sets immutable by SHA-256; model pinned by `lock_sha256`. **Missing:** `pattern_id/pattern_version`; **per-signal feature snapshots** (only the model output and manifest are stored); `direction_probability` and `expected_return` columns exist but are **empty in all 330,984 rows**; no target-before-stop probability. |
| R2 separation | **Partial** | `tpd_paper_universe_outcomes` records the entry outcome for the whole ranked universe, not just the selected picks, so selection can be separated from execution. **Missing:** a pattern-detection layer — the engine ranks one movement model's output. |
| R3 realistic execution | **Partial** | Entry at the official next-session open; upper-circuit open → `ENTRY_UNAVAILABLE`; lower-circuit, large gap, corporate action and illiquidity (> 1% of turnover) flagged; **a gap through a level exits at that session's open, not the stop**; a session touching both counts the stop; cost sensitivity (`net_return_050/100`); `entry_slippage` column. **Missing:** intraday path — target/stop resolves on **daily** bars; no fill delay or spread model; no intraday signal times. |
| R4 labels | **Mostly present** | target_hit, stop_hit, `horizon close` (= timeout), `stop (gap)` (= gap_through_stop), `ENTRY_UNAVAILABLE` (= no_fill), `DATA_ERROR`/`SUSPENDED` (= invalid_signal), net_return, mfe, mae, `sessions_held`. **Gap:** time_to_event only at session resolution. |
| R5 error analysis | **Missing** | No false-positive/negative attribution or segmentation. |
| R6 calibration | **Missing** | No target/stop probabilities to calibrate yet. |
| R7 no auto-retrain | **Met** | The engine never retrains; the model is frozen by lock hash. |
| R8 phases | **Replay done; forward starts Mon 2026-09-21** | Replay found no edge. **Caution:** the forward run measures the v4 movement model, which has already failed Stage 1 (`SUCCESS_CRITERIA.md`). The leading candidate — the G1 gap-down pattern — is **not in the engine**. |
| R9 gates | **Partial** | Look-ahead controls, costs, gap-through and trade-level retention exist; calibration, regime stability and pattern failure conditions do not. |
| R10 tables | **Partial** | Existing: rule_sets, prediction_snapshots, trades, trade_daily_observations, trade_events, trade_exits, universe_outcomes, benchmark_results, index_bars, evaluations. Missing: pattern_definitions, pattern_signals, signal_feature_snapshots, paper_orders/fills (orders and fills are implicit in trades), model_versions, pattern_performance_daily. |
| R11 dashboard | **Partial** | `/v5/research/paper-trades` shows trades, lifecycle, intraday charts and the evaluation; no pattern-level breakdowns. |

## 4. Recommendations (Claude)
1. **Put the first gap-down pattern into the engine in shadow mode** (Phase 1: frozen signals, no orders), with a
   `pattern_id`, a pattern version and a per-signal feature snapshot. ⚠️ **Updated 04:25 IST:** G1 *with target/stop*
   was ABANDONED under its pre-registered condition 3 (`gapdown/G1_RESULT.md`); the shadow candidate is the gap-down
   **close-only, liquid-names (> Rs 5cr)** variant or an early-confirmation entry — each **only after its own
   pre-registration**. Paper-trading only the failed v4 model measures a model we already know fails.
2. **The signal ledger extends the existing tables rather than replacing them** — `prediction_snapshots` already has the
   immutability and supersession mechanics. Add pattern and feature-snapshot tables beside it.
3. **Intraday execution will use Kite 5-minute bars.** Two operating constraints:
   - Kite's access token expires daily (~06:00 IST) and needs the owner's interactive login, so a live session with no
     login produces no signals. Before automating the login, check Zerodha's terms.
   - Kite data may not be displayed on other platforms. An owner-only research page may or may not count — **owner
     decision.** The engine itself (internal) is unaffected.
4. **Calibration waits until there are target/stop probabilities**, and uses a validation window kept apart from any
   performance claim (R6).
5. **Error analysis (R5) should read from `tpd_paper_universe_outcomes`**, which already holds outcomes for signals that
   were not selected — the raw material for false negatives.
