# B — Engine layer audit: backtest engines, options/F&O engine, results, job management

Snapshot audited: `origin/dev @ 4855622005368e8ea0d1da4127ec4b43f7c1256e` (devsnap/DEV_SHA). All paths are relative to the snapshot root
(`devsnap/`). PRD = "Nivesh AI Strategy Copilot" v1.0 (prd/prd.md). Read-only audit: no code ran against a database, so
**data depth and live behaviour are UNVERIFIED** unless stated. The code is the evidence.

---

## 0. Central answer (read this first)

**No existing engine can backtest a 1–4-leg options / futures / mixed strategy over a historical window using real historical
contract premiums.** Today the only strategy backtester is the **equity, long-only, end-of-day DSL engine**
(`backend/services/strategy_engine/backtest.py`). Options exist only as (a) a point-in-time payoff calculator
(`backend/services/strategy_plan/`), and (b) **forward** multi-leg paper trades whose marks come from real NSE F&O bhavcopy
rows (`backend/services/desk_strategy_trades.py`).

The good news: (b) contains a **pure, deterministic multi-leg EOD replay kernel**, `simulate_strategy(trade, bars, leg_rows)`
(`backend/services/desk_strategy_trades.py:517-606`), that already marks every leg on the contract's own bhavcopy close
(options) / settle (futures), never fills a missing price, settles options at intrinsic on expiry, applies the shared exit step
(stop-first on a same-bar touch), premium stop/target as a share of the debit/credit, and a time exit. It is driven today only
for open paper trades (and for `risk_book` point-in-time marks), never over a series of historical entry signals. An options EOD
backtest is therefore a **build from existing parts** (loop + contract resolution + persistence + metrics adapter), not a
rewrite — estimated **L (≈2 weeks with tests)**.

**Intraday:** there is **no intraday-bar backtest** anywhere. `nidp.intraday_bars` exists (`backend/nidp/migrations/152_kite_intraday_bars.sql:10-27`)
but its collector fetches NSE **cash equities only** (`backend/nidp/services/kite_bars/client.py:96-100`: `segment == "NSE" and
instrument_type == "EQ"`), no option intraday premiums are ingested, the DSL reads only daily features
(`nidp.stock_features_daily`, `backend/services/strategy_engine/dsl.py:89-120`) and has **no crossover operator**
(`dsl.py:76-77`: `OPS_NUMERIC = {"<","<=",">",">=","=","!="}`). The PRD's "15-minute RSI crosses above 55" examples cannot be
run today (consistent with the owner's "positional first, intraday later").

---

## 1. Engine inventory

| # | Engine | What it simulates | Data it reads | Costs / fills / exits | Results stored | Sync/async | Tests | Callers |
|---|---|---|---|---|---|---|---|---|
| E1 | **DSL strategy backtest** `backend/services/strategy_engine/backtest.py` (887 lines) | Equities only, **long only** (`er.Rules(side="long"…)` `backtest.py:354-357`), daily bars, universe screen → top-N, equal-weight slots, one position per symbol. DSL asset classes `STOCK`/`MF` only (`dsl.py:65`); compiler is stock-only (`compiler_stock.py`). | `nidp.stock_features_daily` (signals), `nidp.prices_eod_adjusted` adj OHLC (fills/exits) via SQL or DaaS provider (`market_data.py:90-188`, `191-377`); point-in-time liquid universe `liquid_universe.py`; index universe = latest snapshot on DaaS (survivorship, labelled `market_data.py:237-250`). | Costs: `desk-cost-v2` equity-delivery card per side, or `desk-flat-v1` (`backtest.py:48-52`, `164-169`). Slippage in fill price (`375`, `426`). Entry `signal_close` (default) or `next_open` (`43-46`, `117`). Exits = shared `exit_rules.step` (gap at open, stop-before-target, time in sessions, opt-in ATR trail / EMA trend) (`29-41`, `445-464`). Force-close `BACKTEST_END` (`536-561`). | Postgres `strategy_runs` (one row, status `'OK'`) + `strategy_trades` (one row per trade, single `symbol`) (`persist_run` `833-887`). Metrics + equity curve as JSONB. | **Synchronous, inside the HTTP request** (`routes/strategy_builder.py:1003-1017`). | `tests/test_backtest_exit_rules.py` (16), `test_backtest_provenance.py` (8), `test_strategy_backtest_sizing.py` (12), `test_strategy_backtest_adjusted.py` (6), `test_liquid_universe.py`, `test_strategy_market_data.py`, `test_prd_worked_examples.py` (19). All on scripted/MOCK providers — no real-data golden run. | `POST /api/strategy-builder/strategies/{id}/backtest` (`routes/strategy_builder.py:953-1039`); AI Trader (`routes/ai_trader.py:91,477-478`). |
| E2 | **Shared exit step** `backend/services/exit_rules.py` (`exit-rules-v1`) | Pure per-bar exit evaluation for long/short: gap-through-stop at open, trend-at-open, intrabar stop then target (**both → stop**), expiry, time, then trail/trend for next session (`exit_rules.py:8-27`, `222-300`). | Bars passed in. | Fill prices before slippage (`37-38`). | n/a (pure) | n/a | `tests/test_exit_rules.py` (26; `test_tc4_a_bar_touching_both_counts_as_the_stop` `:48-51`), `test_paper_exit_rules.py` (20). | E1, E3, desk cash paper trades. |
| E3 | **Multi-leg F&O replay** `desk_strategy_trades.simulate_strategy` (`backend/services/desk_strategy_trades.py:517-606`) | 1–4 legs (`MIN_LEGS, MAX_LEGS = 1, 4` `:97`), futures/options/cash, one underlying, EOD. Marks: future = settle, option = **close only, never settle** (`:19-29`, `:575-586`); expiry: option at intrinsic vs underlying close, future at final settle (`:621-652`); missing row keeps last mark + `no_mark` flag (`:609-614`). Exits in order: underlying stop (exit_rules, stop-first, gap flagged) → premium stop → underlying target → premium target → expiry → time (`:655-699`); legs closed at session marks (`:56-57`). | Contract rows from DaaS `GET /v1/fno/{symbol}/history` (`:983-1009`; router `backend/nidp/services/daas_api/routers/fno.py:134-176`); underlying bars `GET /prices/eod/{symbol}` (`backend/services/desk_trading.py:574-597`, reads `nidp.prices_eod`). | Costs per leg per side by segment (futures / options-on-premium / equity delivery) via the cost card (`:809-836`). Entry = the leg `entry_price` given by the caller (no historical fill logic). | Mongo `desk_paper_trades` (`kind:"strategy"`); the sim itself returns a dict and never writes (`:521`). | Called by request handlers and the evening cron script. | `tests/test_desk_strategy_trades.py` (36), `test_paper_exit_rules.py`, `test_paper_fills_pnl.py` (25), `test_risk_service.py`. | `routes/desk_trading.py:531,648,765,858`; `services/risk_book.py:140` (point-in-time `through=` replay, `:128-150`); `scripts/check_desk_alerts.py`; `services/fno_roll.py:282`. **Never over historical entry signals.** |
| E4 | **Payoff engine** `backend/services/strategy_plan/engine.py` `compute_payoff` + `payoff.py`, `pre_expiry.py`, `model.py`, `templates.py` (`payoff-v2`) | Point-in-time expiry payoff for ≤ **8** legs (`model.py:15`), one underlying (`:185-187`), **one expiry** (`:188-191`), defined-risk only when any option leg (`:270-289`). Exact max profit/loss, breakevens, net premium, capital at risk (`payoff.py:174-211`); pre-expiry Black-76 repricing + Greeks (`pre_expiry.py:1-19`). | Request body; templates take a chain snapshot dict and raise `no_premium` when a close is missing (`templates.py:29-36`). | Costs = desk cost card per leg/side by segment (`payoff.py:14-25`, `40-45`). Margin **not** estimated (`engine.py:17-18`). | Not stored (plans can be saved via `/plans`). | Sync, pure | `test_strategy_payoff.py` (43), `test_payoff_cost_card.py` (10), `test_strategy_templates_first_wave.py` (20), `test_strategy_plan_templates_route.py`, `test_option_pricing.py` (30), `test_strategy_levels.py`. | `routes/strategy_plan.py:68` (`POST /payoff`), `:74` (`GET /templates`), plan/ideas builders. |
| E5 | **Option pricing** `backend/services/option_pricing.py` | Black-76 price / IV / Greeks; forward from future settle → put-call parity → carried spot (`:14-28`). Rate constant 5.75% (`:58-66`). | n/a | n/a | n/a | pure | `test_option_pricing.py` (30) | E4, `routes/fno.py` chain, `fno_iv_history.py`. |
| E6 | **IV history** `backend/services/fno_iv_history.py` | Daily ATM IV per underlying from that session's bhavcopy (`:1-20`), labelled `calc_version`, `method recorded|backfill`. | DaaS `/v1/fno/{symbol}?on=` | n/a | Mongo `fno_iv_history` | cron script (documented "not installed", `docs/DATABASE_SCHEMA.md:41-45`) | `test_fno_iv_history.py` | `GET /api/fno/{symbol}/iv-history` |
| E7 | **AI Trader strategy runs** `backend/services/ai_trader/strategy.py` | Wraps E1: full window + **4 contiguous sub-window re-runs of the same fixed spec** called "walk-forward" (`folds` `:330-353`, `run_backtest_for` `:370-432`); promotion gates (`:68-75`); sealed research block 2023-01-01..2024-07-31 readable once as holdout (`:13-15`). | via E1 | via E1 | **Mongo** strategy doc `runs[]` — metrics only, **no trades** (`:420-430`; `routes/ai_trader.py:493-495`) | Sync in request (5 E1 runs per call) | `test_ai_trader_strategy.py` | `POST /api/ai-trader/strategies/{id}/backtest` (`routes/ai_trader.py:441-496`) |
| E8 | **F&O research studies** `backend/services/fno_backtest/` (`study.py`, `expiry_study.py`, `outcomes.py`, `stats.py`) | Signal research (OI build-up ranking/thresholds). Outcome = **adjusted cash price** return as proxy for the future (`outcomes.py:31-42`), assumed cost `research-cost-v0` 0.15% round trip (`outcomes.py:9-15`). Discovery/validation/test splits with no-peek windows (`outcomes.py:57-72`), Newey-West SE (`stats.py:16-28`), permutation test (`expiry_study.py:255+`). Windows start 2025-10-01 ("the bhavcopy year", `expiry_study.py:1,28`). | Files/DaaS via scripts | assumed % | JSON report | offline scripts `scripts/run_fno_backtest.py`, `run_fno_expiry_study.py` | `test_fno_backtest.py`, `test_fno_expiry_study.py` (`test_tc9_no_lookahead_in_buckets` `:147`) | research only |
| E9 | **F&O forward test** `backend/services/fno_forward/__init__.py` | One hypothesis recorded at signal time, judged later (`:1-15`). | DaaS | 0.15% | Mongo `fno_forward_signals` | cron | — | `GET /api/fno/forward-test` (`routes/fno.py:835`) |
| E10 | Copilot "what-if" `backend/services/copilot_tools/backtest.py` + node `backend/nidp/services/copilot_agent/nodes/backtest.py` | Buy-and-hold lump-sum / SIP over 1y/3y on total-return prices / NAV (`backtest.py:1-30`). **Not a rules backtest.** | DaaS adjusted prices / NAV | none | not stored | sync in chat | — | copilot agent graph (`nodes/backtest.py:51-63`) |
| E11 | Positional research backtests `backend/services/positional_engine/backtest.py` (label/calibrate accumulation score), `reversal_backtest.py` (PIT reversal rules, research) | Equity signal studies | OHLCV store / files | % round trip (`reversal_backtest.py:19-21`) | `positional_backtest_labels` / report | scripts | `test_reversal_backtest.py`, `test_positional_calibration.py` | research routes |
| E12 | Sim Lab `backend/services/sim_lab.py` | Serves a **frozen JSON snapshot** of a pre-registered simulation; computes nothing (`:3-8`). | file | n/a | file | n/a | — | `routes/sim_lab.py` |
| — | NIDP "replay engine" (`backend/nidp/migrations/044_nidp_replay_engine.sql`, `daas_api/routers/replay.py`) | Data-quality **scoring-policy** replay, not trading. | — | — | — | — | — | — |

Supporting pieces relevant to an options backtest:
- **Point-in-time chain read exists**: DaaS `GET /v1/fno/{symbol}?on=YYYY-MM-DD[&expiry=]` returns every contract that day with
  OHLC, settle, underlying price, OI, volume and `new_board_lot_qty` (`backend/nidp/services/daas_api/routers/fno.py:16-62`).
  The `/chain` route is **latest-date only** (`fno.py:65-81`). The `/history` route returns close/settle/underlying/OI/lot but
  **not open/high/low** (`fno.py:157-161`).
- `nidp.fno_bhavcopy` schema holds OHLC, settle, underlying, OI, lot per contract per day (`backend/nidp/migrations/028_nidp_fno_bhavcopy.sql:18-55`).
  The ingester parses both pre- and post-Jul-2024 NSE formats (`backend/nidp/services/fno_bhavcopy/service.py:1-5,35-39`), so a
  multi-year backfill is technically possible. **Actual staging depth is UNVERIFIED** (not queried); the only code evidence is the
  B2 study windows starting 2025-10-01.
- Rollover: `backend/services/fno_roll.py` is a **user-initiated paper roll** to the next listed expiry at the roll session's
  close (`:1-25`), not an automatic backtest rollover.
- Strike/expiry selection: `pick_expiry` (`backend/services/strategy_plan/candidates.py:573-584`), ATM / wall / expected-move
  short-strike logic (`candidates.py:629-650, 770-805`), `structure_legs` for 5 families only (`candidates.py:683-699`). No
  generic "ATM ± N points / ± N strikes / delta" resolver.
- Premium exit levels: `strategy_levels` (`backend/services/strategy_levels.py:14-15`) and the premium plan the replay reads
  (`desk_strategy_trades.py:703-751`) = the PRD's "stop 20% / target 40% of net debit" semantics.
- Lot sizing within a risk budget, exact against the cost function: `desk_cost_card.max_lots_within` (`backend/services/desk_cost_card.py:154-173`).

---

## 2. Requirement-by-requirement reuse map

Status: **REUSE** (as-is) · **MODIFY** (exists, needs change) · **PARTIAL** (some parts exist) · **MISSING** (build).
Size: S ≤ 1 day · M 2–4 days · L ≥ 1 week.

### FR-06 Historical backtest

| PRD ref | Requirement (short) | Status | Evidence (file:line) | What to change (concrete) | Size |
|---|---|---|---|---|---|
| FR-06 | Deterministic EOD backtest of a **stock** strategy | MODIFY | `strategy_engine/backtest.py:309-617`; validates spec first `:324-330` | Wrap behind the async job (FR-10); accept a single-symbol "universe" from the Copilot config (custom universe exists, `market_data.py:253-257`); expose `cost_model` + `entry_timing` in the request (route ignores them today, `routes/strategy_builder.py:1004-1010`). | S |
| FR-06 | Stock **short** positions | MISSING | long hard-coded `backtest.py:355`; `exit_rules` already supports `side="short"` (`exit_rules.py:50,84-85`) | Add side to DSL + engine (sizing, cash, P&L sign, cost sides). Domain gate: positional cash shorts need SLB — confirm "where permitted" policy. | M |
| FR-06 | Backtest **futures / options / mixed, 1–4 legs** | MISSING (parts exist) | No engine; replay kernel `desk_strategy_trades.py:517-606`; PIT chain `daas_api/routers/fno.py:16-62` | Build `options_backtest.py` (see §4). | L |
| FR-06 / §10.1 | Point-in-time signals | PARTIAL | Features per date `market_data.py:176-182,354-366`; PIT liquid universe `market_data.py:117-141`; index universe on DaaS = latest snapshot, warned `:237-250`; **fundamental columns in `stock_features_daily` come from `*_latest` views** (`backend/nidp/migrations/146_consecutive_ttm_and_same_period_ratios.sql:432-433`), only 5 columns are as-of guarded (`162_sourced_fundamentals.sql:92-150`) | Block (or label) DSL predicates on non-PIT fundamental columns (pe_ttm, growth, shareholding) until they are as-of; make `next_open` the Copilot default. UNVERIFIED whether historical feature rows were ever rebuilt (which is when `_latest` leaks). | M |
| FR-06 / §10.2 | Explicit execution rules (signal time / order time / fill) | PARTIAL | `entry_timing` signal_close / next_open `backtest.py:43-46,483-517`; gap fill at open `exit_rules.py:249-251`; options replay closes at session marks `desk_strategy_trades.py:56-57` | Record `signal_time`, `order_time`, `fill_price_basis` per trade explicitly (today only implied by `entry_timing` + `exit_fill`). Default `next_open` for Copilot (signal_close trades at the bar that produced the signal). | S |
| FR-06 | Costs | REUSE (stock) / MODIFY (F&O) | Card by segment `desk_cost_card.py:58-87,115-135`; F&O rates "retrieved 2026-10-27", **effective date UNVERIFIED** `:14-17,72-86`; engine charges equity delivery only `backtest.py:169` | Options engine: reuse `strategy_cost_breakdown` (`desk_strategy_trades.py:812-830`). Rates are not date-effective → disclose "today's card applied to history" (research cost engine has an effective-date mechanism for equity only: `research/costs/engine.py:55-70`). | S |
| FR-06 | Slippage | REUSE | in fill prices `backtest.py:375,426`; sweep 0/5/10/20 bps `:649-675`; card slippage 0.05% = spread allowance `desk_cost_card.py:9-10` | none for stock; options: apply % slippage on premium per leg side. | S |
| FR-06 | Sizing | REUSE (stock) / MISSING (F&O) | equal-weight slots on equity `backtest.py:54-64,388-406`; lots-within-budget `desk_cost_card.py:154-173` | Options: size in lots from risk budget using `max_lots_within` against capital-at-risk from E4. | S |
| FR-06 | Exits (stop / target / time / expiry) | REUSE | `exit_rules.py:222-300`; premium stop/target `desk_strategy_trades.py:703-751`; expiry settle `:621-652` | Map PRD `profit_target_pct_of_net_debit` / `stop_loss_pct_of_net_debit` to `exit_plan.options` (entry, planned_stop, target_1, unit_shares). | S |
| FR-06 | Capital tracking | REUSE (stock) / MISSING (F&O) | cash + MTM daily `backtest.py:66-70,359-371,527-531` | Options loop: cash debit/credit of premium, per-session MTM (reuse `risk_book.structure_value(through=)` `services/risk_book.py:128-150` or return the P&L path from the sim — today only MFE/MAE `desk_strategy_trades.py:589-593`). | M |
| FR-06 | Trade-level records | REUSE (stock) / MISSING (per-leg) | `strategy_trades` single `symbol` per row (`backend/nidp/migrations/020_strategy_builder_core.sql:123-150`); metadata JSON `backtest.py:825-829` | Add a `backtest_trade_legs` table (or legs JSON) with contract id, side, lots, lot size, entry/exit price & basis, per-leg charges. | M |

### FR-07 / §11 Results & analytics

| PRD ref | Requirement | Status | Evidence | What to change | Size |
|---|---|---|---|---|---|
| FR-07 | Gross P&L | MISSING (derivable) | per-trade base prices + charges kept `backtest.py:825-829` | Add `gross_pnl_rs`, `total_costs_rs` to metrics. | S |
| FR-07 | Net P&L | PARTIAL | `pnl_abs` net per trade `backtest.py:431-435`; `ending_capital` `:744` | Add `net_pnl_rs` explicitly. | S |
| FR-07 / §11.2 | Return on capital with stated denominator | PARTIAL | `total_return_pct` vs `starting_capital` `:810,743` | Add `return_denominator: "starting_capital"` label; for options state margin is N/A (no historical margin source: `strategy_plan/margin.py:1-12`, index not attempted `:70-71`). | S |
| FR-07 | Trade count, win rate (net), avg win/loss | REUSE | `:802-807`; win = net after costs `:709-711,780-781` | Display `avg_win_abs/avg_loss_abs`, not the `%` pair (`:713-720`). | — |
| FR-07 / §11.2 | Profit factor, N/A on zero denominator | REUSE | returns `None` when no losses `:790-792` | UI renders null as "N/A". | — |
| FR-07 | Expectancy (costs stated) | REUSE | `expectancy_rs` net `:814`, `expectancy_r` `:815` | Label "net of modelled costs". | — |
| FR-07 | Max drawdown + drawdown curve | REUSE | daily MTM curve with drawdown `:630-646`, `max_drawdown_pct` `:746` | — | — |
| §11.1 | Drawdown duration, largest win/loss, periodic returns | MISSING | not computed | Add to `_compute_metrics`. | S |
| §11.1 | Exposure, capital utilisation, holding period | REUSE | `:756-772`, `:811-812` | — | — |
| FR-07 | Equity curve, ledger | REUSE (stock) | `equity_curve` JSONB, `GET /runs/{run_id}` returns all trades unpaginated `routes/strategy_builder.py:1059-1062` | Add paginated `/trades` endpoint. | S |
| §11.1 Options | Max profit/loss, breakeven, net debit/credit, payoff at expiry | REUSE (per structure at entry) | `engine.py:52-61`, `payoff.py:186-211` | Call E4 at each entry; store per trade. | S |
| §11.1 Options | Estimated margin | MISSING | margin only from live Kite calculator `margin.py:1-12` | Show N/A + reason for backtests (no historical SPAN files). | — |
| §11.1 Options | Greeks / IV labelled | REUSE (model-derived) | Black-76 `option_pricing.py:1-51`, constant rate `:58-66`; IV history labelled `fno_iv_history.py:1-20` | Label every Greek/IV "model-derived (Black-76, r=5.75%)". | S |
| §11.1 Provenance | version, dataset, date range, engine version, cost model, fill model, warnings, run ID | PARTIAL | `provenance-v1`: data watermark, git SHA + engine SHA-256, spec SHA-256, exit-rules version, strategy_version_id, cost model, universe, entry timing `backtest.py:72-81,211-295,605-615` | Add: dataset identity beyond "latest session available" (row counts / hash of inputs read), explicit `fill_model` id, `warnings[]` list, the options sources (bhavcopy dates/contracts read). | M |
| §11.3 | Ledger: per-leg, signal values & rules, exit reason, warnings for estimated fills | PARTIAL | exit reason + stop history + fill type `backtest.py:825-829`; `entry_reason` column never written (`020_strategy_builder_core.sql:131`; no writer in `persist_run` `:867-879`); replay flags (`no_mark`, `both_in_range`, `gap_through_stop`, `exit_marked_at_session_marks`) `desk_strategy_trades.py:609-699` | Persist signal inputs (the screen row's feature values) + matched predicates; persist replay flags per trade. | M |

### FR-10 Job management (and §16 NFRs)

| PRD ref | Requirement | Status | Evidence | What to change | Size |
|---|---|---|---|---|---|
| FR-10 | Async job, queued/running/completed/failed/cancelled | MISSING | Backtest runs inside the request `routes/strategy_builder.py:1003-1017`; `strategy_runs.status` CHECK is `RUNNING|OK|FAILED` (`020_strategy_builder_core.sql:90,110`) but only `'OK'` is ever written (`backtest.py:854`); no queue lib — only `APScheduler` (`backend/requirements.txt:8`, cron use `services/mf_scheduler.py:285-357`) and `BackgroundTasks` with an **in-memory** dedupe dict (`routes/admin_data_pipeline.py:100-145`) | New `backtest_runs` status machine (queued→running→completed/failed/cancelled) in Postgres + a dedicated worker process claiming rows with `SELECT … FOR UPDATE SKIP LOCKED`. In-process `BackgroundTasks` is not durable and is per-process (an older checkout's prod Dockerfile runs `--workers 4`, `deploy/nivesh-app/Dockerfile.backend.prod:49-50` — UNVERIFIED for dev/staging). | L |
| FR-10 | Unique run IDs | REUSE | `uuid4` `backtest.py:840`; AI trader `strategy.py:421` | — | — |
| FR-10 / §15 | Idempotent submission | MISSING (helper exists) | `core/idempotency.py` — Mongo, 24 h TTL, **fail-open**, key not user-scoped, stored only after the result (`:1-20,53-76,79-101`) | Use a DB unique key `(user_id, idempotency_key)` and/or a content hash (version_id + params + engine SHA) on the run row, inserted at submit time. | S |
| FR-10 / §13.4 | Progress only if measurable | PARTIAL (helper) | Redis progress tracker `services/pipeline_progress.py:1-30` (`total/processed`) | Sessions processed / total sessions is measurable in both loops (`backtest.py:466`); write via `pipeline_progress`-style record keyed by run_id. | S |
| FR-10 | Retry | MISSING | — | Retry = new attempt on same run row with attempt counter; safe because engine is pure and persistence is one transaction (`backtest.py:846-886`). | S |
| FR-10 | Cancellation | MISSING | — | Cooperative cancel flag checked once per session in the loop. | S |
| §16 | No unbounded jobs / limits | PARTIAL | 5-year window cap `routes/strategy_builder.py:961-962`; no timeout, no per-user concurrency limit, no rate limit on the route | Add worker timeout, per-user concurrent-run cap, and a lease (pattern exists: `services/job_runs.py:90-121`). | S |
| §16 | Job acknowledgement < 2 s | MISSING | sync run (E7 does 5 runs per request, `strategy.py:412-418`) | Comes with the worker. | — |
| §16 | Reproducibility | PARTIAL | provenance-v1 (above); data read live at run time, back-adjusted prices change when new corporate actions land (`backtest.py:10-15`) | Snapshot inputs or record a hash of the bars/contract rows read; define the tolerance. | M |
| Appx A | Worker failure → persisted failed status, no success metrics | MISSING | failure = HTTP 400/503, **no run row** (`routes/strategy_builder.py:1011-1012`; `routes/ai_trader.py:483-492`); a no-data run is stored as `'OK'` (§6) | Write `failed` + `error_message` (column exists, `020_…sql:103`). | S |

### FR-11 Explainability

| PRD ref | Requirement | Status | Evidence | What to change | Size |
|---|---|---|---|---|---|
| FR-11 | Timestamp, quantity, costs, exit reason, P&L | REUSE | `strategy_trades` columns + metadata `backtest.py:825-829,865-886` | — | — |
| FR-11 | Signal inputs, matched rules | MISSING | screen rows carry the features (`market_data.py:354-366`) but nothing persists them; `strategy_signals.reasons` exists only for LIVE runs (`020_…sql:165-181`) | Persist the entry row's referenced feature values + the predicates that were true. | S |
| FR-11 | Fill assumptions | PARTIAL | `exit_fill` gap_open/level/close/open, base vs slipped prices `backtest.py:150,825-829`; replay flags | Add entry fill basis (signal_close vs next_open) per trade; for options the per-leg mark basis (`MARK_BASIS_TEXT` `desk_strategy_trades.py:109-117`). | S |

### FR-14 Robustness

| PRD ref | Requirement | Status | Evidence | What to change | Size |
|---|---|---|---|---|---|
| FR-14 | Parameter sensitivity | PARTIAL | cost sensitivity only: slippage sweep re-prices the same trades `backtest.py:649-675` | Parameter grid = N child runs of the job (stop %, target, RSI threshold) with an overfitting warning. | M |
| FR-14 / §10.4 | Out-of-sample | PARTIAL | split helpers with no-peek windows `fno_backtest/outcomes.py:57-72`; AI Trader sealed holdout `ai_trader/strategy.py:13-15`, `routes/ai_trader.py:455-475` | Reuse `split_bounds`/`split_of` to tag in-sample vs OOS segments of one run. | S |
| FR-14 | Walk-forward | PARTIAL / misnamed | AI Trader "walk-forward" = 4 contiguous re-runs of a **fixed** spec, no re-fit (`strategy.py:330-353,415-418`) | Present as "fold stability"; true walk-forward needs a tuning step per fold (only meaningful with a parameter grid). | M |
| §10.4 | Sample size shown; small-sample warning | PARTIAL | `trade_count` everywhere; AI Trader gate `MIN_BACKTEST_TRADES = 100` (`strategy.py:72`); forward test hides stats < 30 sessions (`fno_forward/__init__.py:15`) | Add `warnings[]` with a small-sample rule to the engine output. | S |
| §10.4 | Warn on repeated tuning | MISSING | — | Count runs per strategy version family; warn above a threshold. | S |

### §10.1–10.3 Integrity details

| PRD ref | Requirement | Status | Evidence | What to change | Size |
|---|---|---|---|---|---|
| §10.1 | Corporate actions | REUSE (stock) | adjusted OHLC, ATR rescaled `backtest.py:7-15,376-384` | Options: contract strikes/lots are not adjusted for corporate actions — the replay uses each contract's own rows (correct), but a strike-rule resolver must read the PIT chain, not adjust. | — |
| §10.1 | Holidays / missing bars | REUSE | engine calendar from data `market_data.py:161-168,342-346`; missing bar = no step, stale-mark counter `backtest.py:470-474,536-552`; replay `no_mark` flag `desk_strategy_trades.py:609-614` | — | — |
| §10.1 | Symbol changes | PARTIAL / UNVERIFIED | no explicit handling found in E1 (memory notes an LTIM→LTM ISIN issue on staging) | Map by ISIN in the provider. | M |
| §10.1 | Contract expiry | REUSE (replay) | settle at expiry `desk_strategy_trades.py:621-652` | — | — |
| §10.2 | Same-candle stop+target | REUSE — matches owner decision (stop first) | `exit_rules.py:12-15,260-268`; replay order `desk_strategy_trades.py:657-699`; tests `test_exit_rules.py:48-51`, `test_desk_strategy_trades.py:333` | Disclose in provenance. Note: premium levels are judged on closes only (no intrabar option prices used), so a same-bar premium conflict is not detectable — say so. | S |
| §10.2 | Bid/ask, partial fills, multi-leg execution | MISSING (data) | EOD has no bid/ask; card says slippage doubles as spread allowance `desk_cost_card.py:9-10` | Label "all legs filled at the session close ± slippage; no partial fills". | — |
| §10.2 | Overnight / expiry / settlement | PARTIAL | intrinsic settlement vs underlying close `desk_strategy_trades.py:24-28`; exercise STT convention `desk_cost_card.py:21-23` | Domain caveat to confirm: NSE **stock** options/futures are physically settled; cash-intrinsic + 0.15% exercise STT may understate delivery costs. | S |
| §10.2 | Futures rollover | MISSING (backtest) | `fno_roll.py` is a manual paper roll `:1-25` | Optional auto-roll rule for futures legs (reuse `plan_roll` pricing at roll-session close). | M |
| §10.3 | Never substitute underlying for premium; block when absent | REUSE (components) | templates raise `no_premium` `templates.py:29-36`; replay never fills `desk_strategy_trades.py:30-31,575-586` | Engine must turn a missing entry premium into "trade skipped (counted)" and missing marks into a blocking preflight when coverage < threshold. | S |
| §10.3 | Strike/expiry/lot valid on each historical date | MISSING (data available) | `check_exchange_lots` validates against **today's** reference (`desk_strategy_trades.py:276-308`; `risk_gate/reference.py:4-12`); per-date lot available as `new_board_lot_qty` (`028_…sql:46`, DaaS `fno.py:46`) | Resolve contracts and lot size from `/fno/{U}?on=D`. | S |
| §10.3 | Multi-leg payoff with actual quantities/expiry/settlement | REUSE | `payoff.py:1-12`, `engine.py:28-85` | — | — |

---

## 3. §6.2 Template catalogue (51 named templates)

Columns: **Builder** = canonical leg builder in `backend/services/strategy_plan/templates.py`; **Payoff** = does `compute_payoff`
accept it (generic engine; guard `model.py:270-289`, one expiry `:188-191`, one underlying `:185-187`); **Tests**; **Paper** =
desk paper-trade family (`desk_strategy_trades.py:87-96`) / policy. **Historical backtest: none for any template except long
stock (E1).** Status is about the leg/payoff layer; every options row additionally needs the §4 engine.

| Family | Template | Builder | Payoff | Tests | Paper | Status |
|---|---|---|---|---|---|---|
| Single-leg | Long stock | `cash_long` `:167-170` | yes | `test_strategy_payoff.py:59,497` | cash share trade (strategy path refuses cash-only `:240-241`) | **REUSE** — only template with a real backtester (E1) |
| Single-leg | Permitted short stock | none | yes (`test_strategy_payoff.py:66-71`) | payoff only | refused `short_cash_not_supported` `:191-192` | MISSING (engine long-only `backtest.py:355`; SLB policy) |
| Single-leg | Long futures | `long_future` `:159-160` | yes | `test_strategy_payoff.py:89` | `long_future` | REUSE (needs §4 engine) |
| Single-leg | Short futures | `short_future` `:163-164` | yes, loss unbounded (`:117`) | yes | refused futures-only short `:242-246` (owner D2) | REUSE layer; **policy-blocked** in paper |
| Single-leg | Long call | `long_call` `:81-83` | yes | `test_strategy_payoff.py:128,484` | `long_call` | REUSE |
| Single-leg | Long put | `long_put` `:86-88` | yes | `:143` | `long_put` | REUSE |
| Single-leg | Short call | none | **rejected** `undefined_risk_not_supported` `model.py:284-286` | `test_strategy_payoff.py:254-262` | refused `unbounded_loss` `:255-256` | BLOCKED (defined-risk policy) |
| Single-leg | Short put | none | **rejected** `model.py:287-289` | same | refused `naked_short_put` `:259-260` | BLOCKED |
| Vertical | Bull call | `bull_call_spread` `:91-95` | yes | `:152,476` | yes; auto-selection `candidates.py:689-690` | REUSE |
| Vertical | Bear put | `bear_put_spread` `:98-102` | yes | `:174` | yes | REUSE |
| Vertical | Bull put (credit) | `bull_put_spread` `:114-119` | yes | `test_strategy_templates_first_wave.py:81-93` | yes | REUSE |
| Vertical | Bear call (credit) | `bear_call_spread` `:122-127` | yes | first_wave `:94-106` | yes | REUSE |
| Volatility | Long straddle | none | yes (all long) | none | `long_straddle` family | MODIFY — add builder + tests (S) |
| Volatility | Short straddle | none | rejected (net short call) | — | refused | BLOCKED |
| Volatility | Long strangle | none | yes | none | `long_strangle` family | MODIFY (S) |
| Volatility | Short strangle | none | rejected | — | refused | BLOCKED |
| Time/diagonal | Call calendar | none | **rejected** `mixed_expiries_not_supported` `model.py:188-191` (test `:295`) | — | refused `mixed_option_expiries` `:248-249` | MISSING (needs two-expiry valuation) |
| Time/diagonal | Put calendar | none | rejected | — | refused | MISSING |
| Time/diagonal | Call diagonal | none | rejected | — | refused | MISSING |
| Time/diagonal | Put diagonal | none | rejected | — | refused | MISSING |
| Synthetic/basis | Synthetic long stock (long C + short P) | none | rejected (short put uncovered) | — | refused | BLOCKED |
| Synthetic/basis | Synthetic short stock | none | rejected (net short call) | — | refused | BLOCKED |
| Synthetic/basis | Cash-and-carry (long stock + short fut) | none | yes (no option leg → guard skipped `model.py:281-282`) | none | refused (futures-only short `:242-246`) | MODIFY builder; policy-blocked in paper |
| Synthetic/basis | Reverse cash-and-carry | none | needs short stock | — | refused | MISSING |
| Synthetic/basis | Futures calendar | none | rejected (two expiries) | — | refused | MISSING |
| Relative value | Stock pair | none | rejected (two underlyings `model.py:185-187`) | — | single underlying | MISSING (L) |
| Relative value | Futures hedge (stock + short fut) | none | yes | none | refused (as cash-and-carry) | MODIFY; policy-blocked in paper |
| Relative value | Delta hedge | none | n/a (dynamic) | — | — | MISSING (L) |
| Butterflies/ratios | Call butterfly | none | yes (upside slope 0) | none (`test_strategy_levels.py:135` says levels are not solved for it) | `custom` | MODIFY (S) |
| Butterflies/ratios | Put butterfly | none | yes | none | `custom` | MODIFY (S) |
| Butterflies/ratios | Call ratio spread | none | rejected (`test_strategy_payoff.py:256`) | yes (rejection) | refused | BLOCKED |
| Butterflies/ratios | Put ratio spread | none | rejected (net short puts) | — | refused | BLOCKED |
| Butterflies/ratios | Call ladder | none | rejected (net short call) | — | refused | BLOCKED |
| Butterflies/ratios | Put ladder | none | rejected | — | refused | BLOCKED |
| Butterflies/ratios | Strap | none | yes | none | `custom` | MODIFY (S) |
| Butterflies/ratios | Strip | none | yes | none | `custom` | MODIFY (S) |
| Equity overlays | Covered call | `covered_call` `:130-134` | yes | first_wave `:55-80` | yes | REUSE |
| Equity overlays | Protective put | `protective_put` `:137-140` | yes | first_wave `:107` | yes | REUSE |
| Equity overlays | Collar | `collar` `:143-150` | yes | first_wave `:115-141` | yes | REUSE |
| Equity overlays | Stock repair (stock + 1 long C + 2 short C) | none | yes (slope 0) | none | `custom` | MODIFY (S) |
| Condors/iron | Iron condor | `iron_condor` `:105-111` | yes | `test_strategy_payoff.py:186,484` | yes; auto-selection `candidates.py:694-698` | REUSE |
| Condors/iron | Iron butterfly | none | yes | levels only `test_strategy_levels.py:64` | `iron_butterfly` family | MODIFY (S) |
| Condors/iron | Call condor | none | yes | none | `custom` | MODIFY (S) |
| Condors/iron | Put condor | none | yes | none | `custom` | MODIFY (S) |
| Condors/iron | Box spread | none | yes (flat payoff) | none | `custom` | MODIFY (S, low value) |
| Calendars | Double calendar | none | rejected | — | refused | MISSING |
| Calendars | Double diagonal | none | rejected | — | refused | MISSING |
| Mixed | Stock + futures hedge + protective option | none | yes | none | `custom` (slope ≥ 0 passes `:250-256`) | MODIFY (S) |
| Mixed | Stock + option overlay | = covered call / protective put / collar | yes | yes | yes | REUSE |
| Mixed | Futures + protective option | none | yes | `hedged_future` used in `test_desk_strategy_trades.py`, `test_risk_gate.py` | `hedged_future` | MODIFY (S) |
| Mixed | User-defined mixed | generic legs | yes, but **≤ 8 legs** `model.py:15,178-179` | `test_strategy_payoff.py:300` asserts 9 rejected | `custom`, ≤ 4 legs `:97,391` | MODIFY — cap at 4 server-side |

Tally: **14 REUSE** at the leg/payoff layer · **16 MODIFY** (payoff accepts, builder + tests missing; ≈S each, ≈M all) ·
**10 BLOCKED** by the defined-risk guard (owner policy) · **11 MISSING** (mixed expiries, two underlyings, short stock, dynamic hedge).
§6.2 also requires "margin treatment" per template: **no template has historical margin** (only the live Kite calculator, stock
underlyings only, `margin.py:61-94`).

---

## 4. Options-backtest verdict and the smallest credible design

**Verdict.** Not possible today. Every piece except the outer loop and per-leg persistence exists and is tested; the missing
glue is (1) historical entry generation, (2) point-in-time contract resolution, (3) a capital/equity loop for structures,
(4) storage of legs, (5) the job wrapper.

**Smallest credible design (EOD, defined-risk templates first, one underlying, ≤ 4 legs, no rollover):**

1. **Signals per session D** — for a stock underlying, reuse the DSL screen on a one-symbol custom universe
   (`market_data.py:253-257`, `:354-366`). For index underlyings (NIFTY/BANKNIFTY), there are **no `stock_features_daily`
   rows** → either (a) calendar entries (e.g. "first session after expiry", "every N sessions") in v1, or (b) add index features
   (gap). Daily only.
2. **Contract resolution at D (point in time)** — read `GET /v1/fno/{U}?on=D` (`daas_api/routers/fno.py:16-62`): every
   expiry, strike, OHLC, `new_board_lot_qty`. Implement `expiry_rule` (reuse `pick_expiry` `candidates.py:573-584`, made PIT)
   and `strike_rule` (ATM from bhavcopy `underlying_price` or parity forward `option_pricing.py:14-28`; offset points; ± N
   listed strikes). **New code, S–M.** Build the chain dict in the shape `templates.py:4-6` expects (the latest-only `/chain`
   route cannot be reused as-is).
3. **Legs + structure checks** — reuse the template builders (`templates.py:81-170`); they refuse a missing premium
   (`no_premium`) → count the entry as "skipped: no premium" (never substituted). Reuse `compute_payoff` for max profit/loss,
   breakevens, net debit/credit, capital at risk at entry (§11 options group).
4. **Entry fill** — D close (`signal_close`) or D+1 `open_price` from bhavcopy (the `/history` route must add open/high/low,
   `fno.py:157-161`; S). Slippage % on premium per leg side.
5. **Replay** — call `simulate_strategy(trade, bars, leg_rows)` (`desk_strategy_trades.py:517-606`) with `opened_at = D`,
   `leg_rows` from `/fno/{U}/history` (`:983-1009`), `exit_plan.options` built from the PRD's % of net debit/credit
   (`:703-751`), optional underlying stop/target and `max_hold_sessions`. Needed tweaks: return the per-session P&L path (today
   only MFE/MAE, `:589-593`), and feed **index EOD bars** for index underlyings (today bars come from `/prices/eod` →
   `nidp.prices_eod`, `desk_trading.py:584`; an index route exists, `daas_api/routers/indices.py:70`; UNVERIFIED that
   `prices_eod` lacks index rows, but without bars the sim flags `underlying_bars_missing` and skips underlying stop/target,
   `:544-548`).
6. **Costs** — `strategy_cost_breakdown` (`:812-830`) per leg per side by segment; disclose that F&O rates are today's card.
7. **Portfolio loop + metrics** — one structure per underlying at a time (or `max_positions`), cash debited/credited with
   premium and charges, daily MTM from the sim path; reuse `_compute_metrics` / `_build_equity_curve` (`backtest.py:630-822`)
   through an adapter that fills `pnl_abs`, `pnl_pct` (on net debit / capital at risk), `holding_*`, `r_multiple`
   (risk = capital at risk).
8. **Persistence** — a run row (new `backtest_runs`, or `strategy_runs` with widened status CHECK and a strategy whose
   `asset_class` can be `FNO`/`MIXED` — today CHECK is `STOCK|MF`, `020_…sql:26,31`) + `backtest_trades` + `backtest_trade_legs`.
9. **Preflight** — before queueing: earliest/latest bhavcopy date for U, % of sessions with a resolvable contract, lot sizes
   per date; block below a coverage threshold (PRD §10.3, Appendix A).

**Stated gaps of this design:** EOD only (no 15-minute signals); no bid/ask (close ± slippage); premium stop/target judged on
closes only; no historical margin (ROC on starting capital, margin N/A); defined-risk templates only unless the owner changes
policy; no calendars/diagonals (single-expiry payoff model); no auto-rollover; stock options settled at intrinsic in cash
(physical delivery not modelled — domain caveat); constant 5.75% rate for any Greek/IV; **history depth UNVERIFIED** (must be
queried: `SELECT MIN(as_of_date), MAX(as_of_date), COUNT(DISTINCT as_of_date) FROM nidp.fno_bhavcopy`).

**Size:** contract resolver + PIT chain adapter M · loop/capital/metrics adapter M · persistence + ledger M · tests (golden
replay on a fixed bhavcopy extract, missing-premium, expiry settlement, lot change mid-window, same-bar stop) M → **L overall
(≈ 2 weeks)**, excluding the job infrastructure (FR-10, separate L).

---

## 5. Metrics / provenance gaps vs §11

Present today (E1): trade count, win rate (net), avg win/loss (₹ and %), profit factor (null on zero losses), expectancy (₹, R,
per session), payoff ratio, total return % on starting capital, max drawdown % (daily MTM), Sharpe/Sortino (daily, rf 0),
exposure, capital deployed, turnover, holding days/sessions, exit-reason counts, signal coverage counters, slippage sweep
(`backtest.py:698-822`); provenance-v1 (`:72-81,605-615`).

Missing or to add:
- **Performance:** explicit `gross_pnl_rs`, `net_pnl_rs`, `total_costs_rs` (+ by component); `return_denominator` label.
- **Risk:** drawdown duration, largest win / largest loss, periodic (monthly) returns.
- **Options group:** per-trade theoretical max profit/loss, breakevens, net debit/credit, payoff at expiry (all available from
  E4 — not wired); estimated margin → N/A with reason; Greeks/IV → "model-derived" label.
- **Provenance:** explicit `fill_model` id/version (today implied by `entry_timing` + `gap_fill` + `exit_rules_version`);
  dataset identity (row counts / hash of inputs; watermark is only "latest session available"); options data sources (contracts
  + dates read); `warnings[]` (today only `universe_warning`); engine version for the options engine; cost-rate effective dates
  (F&O UNVERIFIED in the card itself, `desk_cost_card.py:14-17`).
- **Ledger:** signal inputs + matched predicates (missing), per-leg rows (missing), entry fill basis per trade, replay flags
  (`both_in_range`, `gap_through_stop`, `no_mark`, `exit_marked_at_session_marks`) persisted per trade.
- **Statistical:** small-sample warning, in-sample/OOS tags, run-count-per-strategy tuning warning.

---

## 6. Conflicts / risks vs the PRD and §19.2 release blockers

Release blockers that **would fire today** if the Copilot were wired to the existing engines as they stand:

1. **"Failed runs can appear successful"** — FIRES. An empty window returns `metrics={"reason": "no_data"}` (`backtest.py:342-345`)
   and the route persists it with status `'OK'` (`routes/strategy_builder.py:1014-1017`, `backtest.py:854`). Real failures
   leave **no run row** at all (`routes/strategy_builder.py:1011-1012`). (The AI Trader gate guards against `no_data`
   separately, `ai_trader/strategy.py:26-28,71`.)
2. **"A strategy exceeding four configured legs can bypass validation"** — FIRES if the payoff engine is the validator:
   `MAX_LEGS = 8` (`strategy_plan/model.py:15`), and a test pins 9 as the first rejected count (`test_strategy_payoff.py:300`).
   Paper trades cap at 4 (`desk_strategy_trades.py:97`).
3. **"Critical look-ahead bias"** — AT RISK. (a) Default `entry_timing="signal_close"` fills at the close of the bar that
   produced the signal (`backtest.py:43-46,320`) — documented, but a same-bar fill; `next_open` exists. (b) Non-PIT fundamental
   columns usable as DSL predicates (`dsl.py:100-119`) are populated from `*_latest` views
   (`146_consecutive_ttm_and_same_period_ratios.sql:432-433`); a rebuilt historical row would carry later filings
   (UNVERIFIED whether that happened). No release-suite look-ahead test covers the DSL engine end-to-end on real data.
4. **"Results cannot be traced to configuration, data and assumptions"** — PARTIAL. E1 has provenance-v1, but AI Trader runs
   keep metrics only, no trades (`ai_trader/strategy.py:420-430`), and the dataset is identified only by a watermark.
5. **"Costs are omitted without explicit disclosure"** — does not fire for E1 (card recorded in provenance), but F&O rates are
   today's Zerodha page with effective date UNVERIFIED (`desk_cost_card.py:14-17`), applied to any historical date → needs a
   disclosure line on every options run.
6. **"Missing historical option prices are silently substituted"** — does not fire in components (templates refuse,
   `templates.py:29-36`; replay never fills, `desk_strategy_trades.py:30-31`); the new loop must keep that property.
7. **"Unvalidated rules can reach the engine"** — E1 re-validates the DSL (`backtest.py:324-326`); the PRD's leg/rule schema has
   no validator yet (other slice).
8. **"Cross-user access"** — `GET /runs/{run_id}` checks owner or public template (`routes/strategy_builder.py:1057-1058`);
   public-template runs are readable by all by design.

Other conflicts / risks:
- **Defined-risk policy vs §6.2**: 10 catalogue templates (short call/put, short straddle/strangle, synthetics, ratios, ladders)
  are refused by both the payoff guard and paper policy; 5 more (short future, cash-and-carry, futures hedge, reverse C&C,
  futures calendar) are refused in paper by owner decision D2 (`desk_strategy_trades.py:227-230`).
- **Single-expiry payoff model** blocks all calendar/diagonal families (6 templates) — a model limitation, not a flag.
- **Sealed research block** 2023-01-01..2024-07-31 is enforced only on the AI Trader path; the strategy-builder path reads it
  freely. Copilot must pick one rule.
- **History depth** of `nidp.fno_bhavcopy` on staging is unknown to this audit; "backtest 12 months" options prompts may fail
  preflight.
- **Index underlyings**: no daily feature rows for NIFTY/BANKNIFTY in the DSL path and probably no bars on `/prices/eod` for the
  replay — the PRD's flagship example (Bank Nifty bull call) needs index bars + index signals wired.
- **"Walk-forward" naming**: AI Trader folds are fixed-spec sub-windows, not walk-forward; do not surface them under the PRD's
  term without that caveat.
- **Stock options physical settlement** (domain caveat, confirm): replay settles in cash at intrinsic; delivery STT and
  obligations are not modelled.

---

## 7. Questions only the owner can answer (recommended default in **bold**)

1. **Options MVP = EOD only?** The PRD's 15-minute examples cannot run (no intraday premiums or features). **Yes: daily bars only;
   15-minute prompts get a clear "not supported yet" and a daily alternative.**
2. **Risk policy for backtests** — keep the paper desk's defined-risk rule (no naked short options, no short-vol, no ratios, no
   futures-only shorts) for backtests too? **Yes for MVP, so backtest and paper agree; revisit with the shared risk service.**
3. **Calendars / diagonals / futures calendar (mixed expiries)** in MVP? **No — out of MVP; enable only after a two-expiry
   valuation model is built and tested.**
4. **Return-on-capital denominator for options** (no historical margin exists). **Starting capital, with margin shown as "not
   available for historical runs".**
5. **Historical cost rates** — apply today's desk cost card to all history with a disclosure, or fund date-effective F&O rate
   tables first? **Today's card + a visible disclosure in MVP; date-effective tables later.**
6. **Sealed research block (2023-01-01..2024-07-31)** — does it bind Copilot user backtests? **No: the seal stays an AI Trader
   research rule; Copilot runs may read it, and provenance records the window.**

Engineering defaults (not owner questions): Postgres-backed run table + one dedicated worker process (`SKIP LOCKED`), Redis
progress, idempotency key unique per user, cooperative cancel per session, per-user concurrency cap, `next_open` default fill.
