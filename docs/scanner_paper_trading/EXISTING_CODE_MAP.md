# What already exists for the Scanner-to-Paper Trading PRD (code map)

This map was read from `origin/dev` 74ec45d6 on 5 Nov 2026 between 01:45 and 02:00 IST, with paths under `backend/`. It is a read
of the code only: no database was queried, so whether a table holds rows is noted as unconfirmed where it matters.

PRD: `docs/prd/Nivesh_Scanner_Paper_Trading_Capital_Allocation_Risk_Management_PRD.md`.
Workflow: `docs/prd/Nivesh_Scanner_to_Paper_Trading_Workflow.md`.

## Scanner signals

**Scan dashboard.** `services/scan_builder/signals.py` keeps everything in Redis with `TTL_S = 3 days`.
- Keys:
  - `nivesh:sb:signals:<day>:s:<widget>:<SYM>` — a list entry
  - `…:g:<SYM>` — a strong signal, frozen when the score first reaches 70, carrying the scan-plan-v3 plan
  - `…:index`, `…:strong`, `…:scores`
- **Nothing is persisted.** A raw dump of 4 Nov (2,370 keys) is at
  `/home/deploy/nivesh-signal-archive/redis_dump_20261105.jsonl`.

**Strength score.** `services/scan_builder/signal_strength.py` (`THRESHOLD = 70`):
- The parts are quality 30, trend 25, reason 20, size 15 and participation 10, minus penalties.
- Positional plan `scan-plan-v3`:
  - stop = entry − 2 × ATR14
  - T1 = entry + 2R, T2 = entry + 4R
  - trend exit = a daily close below the 20-day average

**Lists.** 31 widgets in `services/scan_builder/market_dashboard.py`. `POSITIONAL_LISTS` is in `signal_strength.py`.
`SHORT_WIDGETS` = `{open_interest, oi_7}`.

**Positional engine.** It writes Postgres `positional_signals` / `positional_signals_history` (migrations 015/025).
`positional_outcomes` and `strategy_signals` exist but have no writer.

## Paper accounts and ledger — `services/paper_account.py` (Mongo)

**Collections.** `paper_accounts` and `paper_account_ledger`. `DEFAULT_CAPITAL = 1_000_000` (₹10 lakh);
`POLICY_VERSION = paper-account-v1`. There is one account per user, keyed by `user_id`. The P&L dashboard uses the fixed
`PAPER_ACCOUNT_ID = "paper"`.

**Account fields.**
- `cash_rs`, `blocked_rs`, `starting_capital_rs`; available = cash − blocked.
- `equity_peak_rs` (`services/risk_book.py`).

**Reservations.**
- `reserve` / `release` are atomic `$expr` updates. `release` adds net P&L to cash.
- `reserve_entry` also keeps risk counters on the same document: `open_risk_rs`, `exposure_rs`, `open_positions`,
  `sector_rs.*`, `held_symbols.*` and `reservations[]`.

**Ledger actions.** reserve / release / cancel_reservation / adjust. Reconciliation is in `services/paper_reconcile.py`.

**Not there yet:** named or multiple accounts, an account mode (auto / approval / tracking), and Mongo multi-document
transactions. Everything uses single-document conditional updates plus idempotency keys.

## Paper trades — `services/desk_trading.py` (`desk_paper_trades`, rules `desk-paper-v2`)

**One document is the order, the fill and the position.** Entry rules are at_once / break_above / pullback_to; there are
no market / limit / SL / SL-M orders. The whole quantity fills or nothing does (**no partial fills, no partial exits**).
Adding to a position is refused (409). Cash trades are long only.

**Fills:**
- End-of-day bars from `nidp.prices_eod`.
- An at_once entry must lie inside the last session's range; with `price_source kite_live` it is checked against today's
  live day range ±0.5%.
- **Bid/ask and depth are never used.**
- Costs come from `services/desk_cost_card.py` `desk-cost-v2`: ₹20 brokerage a side, 0.05% slippage a side (which also
  stands in for the spread), and statutory charges per segment. `round_trip_breakdown` is at `desk_trading.py:1066`.

**Exits.**
- Stop, target and time are always on.
- The opt-in rules are `services/exit_rules.py`: `trail-atr-v1`, `trend-ema-v1`, `step` and `replay`.
- They are evaluated on GET and by the evening job `scripts/check_desk_alerts.py`.
- **There is no breakeven stop and no T1 partial exit.**
- "Modify risk" is `PATCH /paper-trades/{id}/levels`: changes take effect from the next session and are audited.

**Live intraday paper exits exist ONLY for Market Recovery trades.** `services/market_recovery/paper_live.py`
`run_live_exits` runs every minute from `services/mf_scheduler.py`, with exit reasons `stop_live` / `target_live`.
This is the pattern to reuse.

**Multi-leg.** `services/desk_strategy_trades.py` (`kind = "strategy"`, `desk-paper-v3`): 1–4 legs and 17 families,
with `check_defined_risk`.
- `exposure_rs` is a conservative upper bound, not a true max loss.
- There are no per-leg or net Greeks on the trade, and no margin.
- Expiry is settled; there is legging but no partial fill.

**Lifecycle.** `services/trade_lifecycle.py`: NO_SETUP → WAIT_FOR_CONFIRMATION → TRADE_ELIGIBLE → ENTRY_TRIGGERED →
POSITION_OPEN → EXIT_PENDING → CLOSED, plus REJECTED. `transitions[]` is append-only.

**Idempotency.** The `Idempotency-Key` header plus `request_fingerprint`, with unique partial indexes.

## Risk — `services/risk_gate/` (Mongo `risk_decisions`)

**Universal risk service** (`service.py`, `universal-risk-v2`). It is mandatory, with no flag.
- Checks: controls, mode, structure, levels, inputs (freshness), defined_risk, lot_size, expiry, per_trade_risk,
  reward_risk, governor, position, open_risk, exposure, sector, **correlation (always skipped)**, daily_loss, weekly_loss,
  drawdown, funding, fno_additional.
- Outcomes are allow / reduce / block. A row goes to `risk_decisions` (`source = "risk_service"`) BEFORE the write.
- On allow it reserves budget via `paper_account.reserve_entry`.
- PATHS: `desk_paper_trade`, `desk_paper_roll`, `journal_create`, `journal_fill`, `ai_trader_signal`,
  `ai_trader_confirm`.
- `inputs.py`: ADV over 20 sessions; sector from the NSE `industry` of `nidp.index_constituents`; VIX and regime.
- `estimate.py`: `GAP_STRESS_PCT = 1.0`, not calibrated.
- `plan_sizing.size_for`.
- `replay.py`: replays a decision on its stored snapshot.

**F&O gate.** `gate.py` + `policy.py` (`fno-risk-v1`): max legs 4, 10 lots/leg, 10 open structures, ₹2 lakh capital at
risk, defined risk required. The `fno_risk_gate` flag only adds these extra caps.

**Limits.** `services/risk_profile.py` (Mongo `risk_profiles` + audit). A user can tighten them; loosening needs an admin.
`OWNER_DEFAULT`:

| limit | value |
|---|---|
| per trade risk | 0.5% |
| open risk | 3% |
| position | 10% |
| sector | 25% |
| daily loss | 2% |
| weekly loss | 4% |
| drawdown | 10% |
| min R:R | 1.5 |

Percentages are of paper equity. `SIMULATION_STARTING_CAPITAL_RS = 10 lakh`.

**Risk governor.** `services/ai_trader/risk_governor.py` (`gov-v1`): approve / reduce / hedge / defer / reject / halt;
VIX and regime size factors; ADV cap. It is called from the risk service.

**Kill switch.** `services/risk_controls.py` (`risk_controls`, `risk_control_audit`) blocks new paper positions. It cannot
flatten positions.

**Risk book.** `services/risk_book.py` gives equity, peak, day and week P&L, drawdown, the open book and sector.

**Missing for trading:** correlation / covariance, a portfolio-wide stress test, VaR/CVaR and portfolio-level Greeks.
`nidp/services/pra_engine/` has covariance, VaR, stress and beta for MF/investor portfolios, but it is not wired to trading.

## Market regime and sector strength

- `services/macro_engine.classify_desk_regime` (`desk-regime-v1`): Nifty vs its 50-day average, VIX 20, and 52/48 breadth.
  Read through `strategy_plan/regime_fit.read_regime`.
- Sector strength: `ai_trader/sector.sector_rotation`, `strategy_plan/evidence.sector_strength` and
  `positional_engine/sector_strength.py`.

## Sizing and strategy

- `GET /api/positional/scenario` (`routes/positional.py` `_trade_scenario`) and `desk_trading.max_units_within_budget`.
- `services/strategy_plan` ranks cash / futures / options / combinations by net R:R and computes max loss at the stop or
  at expiry.
- Margin: `strategy_plan/margin.read_margin_estimate` and `services/fno_margin`, through the Kite basket margin calculator
  (needs the daily Kite login).

## Real-time P&L and alerts

- `routes/desk_pnl.py`: `GET /pnl`, SSE `/pnl/stream`, `/pnl/timeseries`, `/pnl/journal/{id}`, `/pnl/exits`.
- `services/paper_pnl/*`: equity, exposure, open risk against its limit, daily loss used, win rate, profit factor, and a
  realised-curve drawdown.
- Alerts:
  - In-app only: `desk_alerts`, `exit_watch`, and the P&L risk alerts.
  - `nidp/shared/notify.py` (email / Telegram) is for operator jobs only.

## Analytics

- Backtest statistics: `strategy_engine/backtest.py` has expectancy, Sharpe, Sortino and max drawdown.
- AI trader: `ai_trader/validation`, `ai_trader/calibration`.
- MAE/MFE per paper trade in `desk_trading`.
- **No per-scanner or per-strategy report:** paper trades carry no signal id.

## Data

- **`stock_features_daily`** has key (symbol, as_of_date, source). Re-running a date rewrites it.
  `stock_fundamental_values` keeps only the latest value, so it is **not point-in-time for history**.
- **`nidp.intraday_bars`** (migration 152) exists, but its collector `nidp/services/kite_bars/collect.py` is manual and
  **not scheduled**. Intraday candles come on demand from Kite `historical_data`, at about 3 calls/s and ≤1.5/s for the
  scan feature.
- **Options.** Only end-of-day `nidp.fno_bhavcopy`; IV and Greeks are computed on the fly in `services/option_pricing.py`
  (Black-76). Daily ATM IV is in Mongo `fno_iv_history`.
- **`nidp.prices_eod_adjusted`.** The adjuster `nidp/services/price_adjuster` runs at 22:30 IST in prod. On staging:
  unconfirmed. On 4 Nov `/prices/eod/adjusted/{sym}` returned 0 rows for 7 symbols, and `fetch_bars` is not adjusted
  (HDFCAMC 1:1 bonus).
- Delivery (T+1), shareholding, classified announcements, `index_eod` (sectoral included) and `index_constituents`
  (industry).

## Libraries

- In `requirements.txt`: numpy 2.4.4, pandas 3.0.2, polars, pyarrow.
- **Absent:** scipy, cvxpy, riskfolio-lib, PyPortfolioOpt, quantstats, vectorbt, TA-Lib, QuantLib, statsmodels.

## Earlier PRDs this one overlaps

- `docs/prd/nivesh_paper_trading_prd.md` (22 Sep, Proposed): accounts with modes, orders, partial exits, slippage
  models — the same ground.
- `docs/prd/live_trading_alerts_signals_prd.md`: the signal lifecycle; only its Phase 1 contract was built.
- `docs/prd/AI_TRADER_PHASES_2_5.prd.md` (BUILDING): shares only. It is not scheduled and runs only when POSTed.
