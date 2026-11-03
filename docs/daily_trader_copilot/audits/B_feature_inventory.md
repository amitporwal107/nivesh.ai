# B — Existing-feature inventory for the 15 trader questions + the phase brief (Q16+)

Ref read: `origin/dev` @ **a4294830**, read with `git show` / `git grep` only. Nothing was checked out or edited, and no database was queried.
Line numbers are origin/dev lines. A table said to "hold" data is described from code and schema only; whether it is fresh is for agent C to check.

**Path short forms**
- **R** = `backend/routes`
- **S** = `backend/services`
- **DaaS** = `backend/nidp/services/daas_api/routers` (the data-platform API; the only reader of the `nidp.*` tables)
- **FE** = `frontend-v5/src/pages/CopilotApp/screens/tradingdesk`

**How this was gathered**
- I read the route lists and the market view, smart money, top ideas, breakouts, paper trades, risk and scorecard code myself.
- Three read-only sub-agents mapped the F&O, pre-market/scanning and entry/position/EOD clusters.
- I spot-checked about 45 of their citations against origin/dev. All matched except two, corrected here:
  - `fno_roll.ROLL_WINDOW_SESSIONS` is at L37.
  - `gap_stress` is in `S/risk_gate/estimate.py`, not `strategy_plan/estimate.py`.

**Facts that apply everywhere**
1. **Most desk analytics are end-of-day.**
   - Cash rows: `nidp.prices_eod` and the app's `stock_ohlcv` / `stock_technical_features`.
   - F&O rows: `nidp.fno_bhavcopy` via DaaS `/v1/fno/*` (DaaS `fno.py` L16/L65/L134/L178).
   - Live data comes only from the platform Kite feed: `R/live_quotes.py` (`/api/live/*`) plus Mongo `kite_live_close`, `kite_live_intraday`, `kite_live_minute` (`S/kite_live_feed/feed.py` L47/L52/L58).
   - The Kite token is in Mongo `kite_platform_token` (`platform_token.py` L35). With no admin Kite login that day there is no live data.
2. **Desk paper trades are marked on end-of-day bars only.** They use DaaS `/v1/prices/eod/{symbol}` → `nidp.prices_eod` (`S/desk_trading.py` L18, L584). No desk screen marks them from Kite.
3. **`/api/paper-trades/*` (`R/paper_trades.py`) is the research model's paper portfolio** (Move-odds, Yahoo bars), not the user's trades.
4. **`CarryTag.tsx` is the AI-watchlist carry-forward tag** ("on the list N days"). It is not an overnight-carry check.
5. **SEBI wording:** the code calls them "ideas", not picks or recommendations, and serves no probability unless one has been validated.

---

## Q1 — What is the market view today? [direction, breadth, volatility, key levels]

**Existing pieces**

GET `/api/markets/home` (`R/markets.py:314`, response L465-477) returns:
- `indices`, including India VIX (yfinance plus a live overlay `nse_live.get_live_snapshot`).
- `breadth`: advances, declines, unchanged and tone (`_breadth` L416).
- `verdict`: the deploy verdict AGGRESSIVE / NORMAL / CAUTIOUS / DEFENSIVE (`market_dashboard._deploy_verdict`).
- `fii_dii`, `sectors`, movers, `global_cues`, `commodities`.
- The desk UI reads it through `useMarketOverview` (`screens/markets/hooks.ts:38`), shown in `FE/tabs/market-overview/MarketStrip.tsx:212`.

GET `/api/positional/market-dashboard` (`R/positional.py:1651`, `S/positional_engine/market_dashboard.py build` ~L94) returns:
- % of stocks above the 20 and 50 EMA, the A/D ratio, new 52-week highs and lows, VIX trend, macro risk and the deploy verdict.
- Tables: `stock_ohlcv`, `stock_master`.

GET `/api/macro/today` `.regime` and GET `/api/macro/regime-history` (`R/macro.py:48`, `:238`):
- Desk regime `classify_desk_regime` (`S/macro_engine.py:927`, rule `DESK_REGIME_RULE` L835, "desk-regime-v1").
- Classes: high_volatility / mixed / bullish / sideways / bearish, each with invalidation levels.
- Inputs: Nifty close vs its 50-session average, India VIX (high at 20) and advancing share (52/48%).
- Tables: `macro_daily`, `macro_features`, `macro_state` (`backend/migrations/016_macro_intelligence.sql`); `nidp.index_eod`; breadth from `stock_ohlcv`.
- Only the legacy `frontend/` calls `/api/macro/today`.

GET `/api/risk/freshness` (`R/risk_controls.py:218`):
- Returns `market_state` {regime, vix} exactly as the risk gate judges it (`risk_gate/inputs.market_state` → `strategy_plan/regime_fit.read_regime` L112 → `macro_engine.latest_state` L583).
- UI: `FE/tabs/market-overview/overview-data.ts:73-79` and MarketStrip.

GET `/api/markets/sector-returns` (`R/markets_desk.py:53` → DaaS `desk_market.py:141`):
- Sectoral index 1-day, 1-week and 1-month returns, plus breadth inside each index.
- Tables: `nidp.index_eod`, `nidp.index_constituents`, `nidp.prices_eod`.
- UI: `FE/overview-data.ts:87`.

Live indices:
- GET `/api/live/snapshot?universe=indices` (`R/live_quotes.py:185`): every NSE INDICES-segment instrument (`kite_live_feed/universe.py:17-20`).
- GET `/api/live/close` (L193): the saved close, from Mongo `kite_live_close`.

Key levels (NIFTY / BANKNIFTY) — option-derived only:
- GET `/api/fno/{symbol}/chain` `summary` (`R/fno.py:794`; `summarise_chain` L289) returns `put_wall`/`call_wall` (spot-side OI walls), `max_pain` (L220), `pcr` (L207), and `expected_move` / `expected_move_pct` (L528, set at L848).
- POST `/api/desk/strategy/levels` (`R/strategy_plan.py:85` → `S/strategy_levels.compute` L67) returns underlying stop, target and range levels from the walls or the expected move.
- UI: `FE/FnoIndexExpiries.tsx`, `tabs/trade-desk/analysis/ChartAnalysis.tsx` (max-pain and wall lines).

**True gaps**
- **No price pivots** (classic or Camarilla) and **no price-based support/resistance for indices**.
  - Stock S/R (`research_chart.py` L196-198; `stock_features_daily.swing_high_20`/`swing_low_20`) returns 404 for indices.
  - Searched: `pivot|camarilla|key_levels|support_resistance|swing_high`.
- **No single reconciled market view.** At least four regime definitions coexist: desk-regime-v1 on the Nifty 50 vs its 50DMA, the market_dashboard 20DMA trend on NIFTYBEES, macro BULL/BEAR (`classify_regime` L437), and research N12 on the Nifty 500 (`/api/ai-trader/evidence`, with no frontend caller).
- **The regime's VIX is end-of-day**, while the strip shows a live VIX.
- **No intraday breadth** beyond the live Nifty-50 count in `/home`.

## Q2 — Where is smart money moving? [FII/DII flows, sector rotation, buildup signals]

**Existing pieces**

GET `/api/markets/smart-money/{feeds,flows,sectors,breadth,summary,amc,scanner}` (`R/markets_smart_money.py:57-166` → DaaS `smart_money.py`):
- **flows** (L65): FII/DII cash net and cumulative over 1M/3M/6M (daily) and 1Y (monthly).
  - Rows are `nidp.fii_dii_flows` with `segment='EQUITY_CASH'` (DaaS `smart_money.py:142`).
  - Source SENSIBULL (daily, from 2026-04-01) or SENSIBULL_MONTHLY (from 2018-09) (`backend/nidp/services/sensibull_fii_dii/service.py` header).
- **sectors** (L119): disclosed MF holdings change by industry, from `nidp.mf_holdings_deltas`.
- **amc** (L153): which fund houses drive one stock's change.
- **scanner** (L166): one row per Nifty-500 stock with an `accumulation|distribution` direction filter. Carries MF delta, delivery (`deliv_10d`/`deliv_60d`/`deliv_vs_base_pp`) and `change_pct`.
- **summary** (L140): the four headline KPIs.
- Other tables: `nidp.mf_holdings_monthly`, `nidp.mf_holdings_coverage`, `nidp.shareholding_pattern`, `nidp.v_trendlyne_deals_net`, `nidp.smart_money_scores_daily`.
- It serves evidence, not a verdict: the validation study was INCONCLUSIVE (module docstring L15-18).
- UI: `FE/SmartMoneyTab.tsx` + `FE/smart-money-data.ts` (L88-843).

Other flow and positioning routes:
- GET `/api/markets/fii-dii` (`R/markets.py:546`, DaaS `/market-pulse/fii-dii` → `nidp.fii_dii_flows`).
- GET `/api/markets/institutional-positioning` (L1011): quarterly FII/DII holdings by sector, from `nidp.shareholding_pattern`.
- GET `/api/flows/ledger/{company/{sym},sector/{s},sectors}` (`R/flow_ledger.py:78-92`): FPI fortnightly flows and AUC by sector, from `nidp.fpi_sector_auc` (NSDL).

**Not exposed:** FII/DII index-futures and index-options net OI are stored in `nidp.fii_dii_flows` (segments `INDEX_FUTURES`/`INDEX_OPTIONS`, `sensibull_fii_dii/service.py:159,170`). DaaS serves them at `/v1/flows/fii-dii?segment=` (`flows.py:109`). But no app route or screen exposes them; only `S/nidp_context.py:180` (Copilot RAG context) and `nidp.market_daily_snapshot.fii_fno_index_net_cr` (`snapshot_builder/market_builder.py:138`) read them.

Sector rotation (backward-looking):
- `/api/markets/sector-returns` and `/api/markets/sector-heatmap` (`R/markets_desk.py:72` → DaaS `desk_market.py:450`; tables `nidp.prices_eod_adjusted`, `nidp.index_constituents`, `nidp.stock_features_daily`).
- market_dashboard per-sector `rs_5d_pp` vs Nifty, with a HOT/WARM/COOL/COLD tone.
- `/api/macro/sector` (`R/macro.py:431`, table `sector_macro_scores`): a macro-tilt outlook.
- `ai_trader/sector.py:22 sector_rotation` (RS vs NIFTY 500, from research CSVs; no UI).

Build-up signals:
- GET `/api/fno/scan/buildup` (`R/fno.py:1313` → DaaS `desk_market.py:741`, `FNO_BUILDUP_SQL` L592, `buildup_label` L649).
- Long build-up, short build-up, short covering and long unwinding, per stock future plus the NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY/NIFTYNXT50 index futures.
- Tables: `nidp.fno_bhavcopy`, `nidp.prices_eod`, `nidp.index_eod`, `nidp.stock_features_daily`, `nidp.security_reference_daily`.
- UI: `FE/FnoBuildup.tsx`, `FE/fno-buildup.ts:146`.

**True gaps**
- No RRG or relative-rotation quadrant. Searched: `rrg|relative_rotation|rs_ratio|rs_momentum`.
- No FII derivatives-positioning view in the app, although the data is stored.
- No validated smart-money score.
- No industry-wide monthly MF flows (AMFI).

## Q3 — Which are today's top 5 opportunities? [ranked stocks with evidence and risk]

**Existing pieces**

POST `/api/desk/strategy/ideas` (`R/strategy_plan.py:129` → `S/strategy_plan/ideas.py build_ideas` L241):
- Takes the scanner's merged list, ranks it by the scanner score and keeps the top N (default 8, max 15; `selection.py` L28-37, `merge_setups` L98).
- The list is `/api/positional/watchlist` buckets plus `/api/positional/picks` (`read_scanner` L150).
- It then builds a full plan per idea. Each idea carries:
  - the evidence ledger (supports / conflicts / unavailable),
  - a TradePlan (entry, stop, targets, r-multiples),
  - max loss, max profit, breakevens and capital at risk per strategy,
  - plan status plan / wait / no_trade.
- The Copilot UI uses it as `useTop10Stocks` (`FE/top10-data.ts:41`).

POST `/api/desk/strategy/top` (`R/strategy_plan.py:203` → `regime_fit.build_top` L811):
- Index options (NIFTY and BANKNIFTY, L643), stock F&O and a cash class.
- Ranked by regime fit (`WEIGHTS` L98: direction 40 / volatility 30 / breadth 15 / positioning 15), then reward:risk.
- Used as `useTop10Fno` (`FE/top10-data.ts:55`).

GET `/api/desk/ai-watchlist[?date=]` (`R/ai_watchlist.py:44`):
- The nightly stored Top 10 cash plus Top 10 F&O. It is the same answer as `/ideas` and `/top`, frozen at the 22:45 IST build (`S/ai_watchlist_build.py:223 build_day`).
- Stored in Mongo `ai_watchlist_days` (`S/ai_watchlist_store.py` COL L21).
- Each row adds `days_on_list` and `carried`.

Scanner and other lists:
- GET `/api/positional/picks` (`R/positional.py:256`): `positional_signals` (`final_score`, stage, entry/stop/target/`risk_reward`) on the latest signal date.
- GET `/api/desk/chartink/picks` (`R/desk_chartink.py:173`): the user's Chartink scans merged with scanner evidence. Mongo `desk_chartink_sources`, `desk_chartink_hits`.
- Desk UI: `FE/ScannerTop10.tsx` and `FE/tabs/market-overview/MarketOverview.tsx` (Top AI opportunities).

**True gaps**
- The rank is a rules score, not a probability or performance rank. This is stated in `ideas.py` RANKING_NOTE L36 and `regime_fit` GAPS L59-75.
- No live re-rank intraday: the lists are end-of-day.
- Asking for exactly 5 is just `limit`, so that is not a gap.

## Q4 — Which breakouts are confirmed? [entry zone, volume confirmation, invalidation]

**Existing pieces**

GET `/api/positional/watchlist` bucket `breakout_confirmed` (`R/positional.py:286`; rule `S/positional_engine/setup_rules.py:36-40`; classifier `classify_setup` L171; row build `R/positional.py:485-490`):
- Rule:
  - close 0-3% above `breakout_level`,
  - `volume_spike_3v20` ≥ 1.5 (mean volume of the last 3 sessions ÷ the prior 20),
  - stage BREAKOUT or EARLY_BREAKOUT,
  - gap-up no more than 5%.
- Each row carries `trigger_price` (the breakout level), `stop_price` = level − 1.5×ATR(14), `resistance_level`/`support_level`, a `why` text, `signals.delivery_trend_pct` and `gap_up_pct`.
- Tables: `stock_technical_features`, `stock_ohlcv`, `stock_master`.

Chart patterns:
- GET `/api/research/chart/{sym}/patterns` and `/live/{sym}/patterns` (`R/research_chart.py:127,621`).
- Pattern state: confirmed, awaiting_confirmation, or "invalidated — the breakout failed: price came back through the level" (`_prd_state` L513-529).
- Data: `nidp.prices_eod_adjusted` (live variant on Kite intraday).

The TradePlan for the setup gives `entry.order_type` stop_trigger / limit_pullback / at_close (`trade_plan.order_type_for` L90), plus `stop.invalidation`.

UI: `FE/ScannerTab.tsx`, `FE/ChartTab.tsx:904`.

**True gaps**
- **No entry zone or range.** `entry.zone` is always `None` (`candidates.py:285,457,893`), although the watchlist docstring promises a "suggested entry zone" (`R/positional.py:309`).
- **No same-day relative volume.** Confirmation volume is a 3-vs-20-session average.
- **No intraday confirmation.** It is end-of-day.
- **No false-breakout flag on watchlist or pick rows.** It exists only on chart patterns.

## Q5 — Which stocks have unusual volume? [relative volume, price change, delivery data]

**Existing pieces**

GET `/api/positional/scan-universe` (`R/positional.py:639` → DaaS `/v1/features/scan-snapshot`, `features.py:274`):
- Volume: `rvol20` = volume ÷ `avg_volume_20` (L270) and `vol_z20`.
- Category `unusual_volume` when `vol_z20` ≥ 2 (`setup_rules.py` ~L81, `_NEEDS` L105).
- Prices: open, close, prev_close, `return_5d/20d_pct`.
- Tables: `nidp.stock_features_daily`, `nidp.prices_eod`, `nidp.security_reference_daily`.
- UI: `FE/desk-data.ts:663`.

Other endpoints with volume or delivery:
- GET `/api/markets/smart-money/scanner`: `change_pct` plus delivery `deliv_10d`/`deliv_60d`/`deliv_vs_base_pp` (from `nidp.prices_eod.deliv_pct`). No RVOL.
- `/api/positional/watchlist`: `volume_spike_3v20` plus `delivery_trend_pct` (from `stock_ohlcv.delivery_pct`).
- GET `/api/market/events` (`R/market_events.py:121`): `volume_spike_ratio`, `delivery_pct`, `delivery_spike_ratio`, for event stocks only (`nidp.corporate_event_signals`).
- `/api/movers/{symbol}/analysis` (`R/movers.py:153`, allowlisted): a "delivery % > 20D avg" signal from `nidp.delivery_data`.
- DaaS `/v1/prices/delivery/{symbol}` (`prices.py:224`).

**True gaps**
- **No single universe endpoint returns relative volume, price change and delivery % together.** Delivery is missing from scan-snapshot, although `nidp.stock_features_daily.deliv_pct_avg_20`/`deliv_trend10` exist.
- **POST `/api/screeners/run` has no volume, relative-volume or delivery primitive** (`S/copilot_tools/stock_intelligence.py:251 _SCREENER_PRIMITIVES`).
- **No intraday live relative volume.** The Kite snapshot has no 20-day baseline.

## Q6 — Is this stock a buy now? [buy/wait/avoid with rationale]

**Existing pieces**

POST `/api/desk/strategy/plan` (`R/strategy_plan.py:97` → `S/strategy_plan/plan.py:375 build_plan`):
- `status` = plan / wait / no_trade / insufficient_data, with `status_reasons`, `would_change_if` (`WOULD_CHANGE` L218), `thesis.supports/conflicts` and `failure_conditions` (L313).
- Cash candidates can be "avoid" (`candidates.py:245`).
- The Copilot chat already uses it: `S/copilot_trade_idea.py:229 build`, called at `R/chat.py:1561-1562`.

Conviction verdict:
- `S/positional_engine/conviction.py:195 classify_verdict` returns HIGH_CONVICTION / SETUP_FORMING / AVOID_LATE (L177).
- Served only by GET `/api/positional/picks/mine?live=true` (`R/positional.py:866`, yfinance LTP via `_enrich_with_live` L798) and POST `/api/positional/basket`.
- No frontend calls `picks/mine`.

Per-stock scanner view:
- GET `/api/positional/picks/{symbol}` (L923): stage, confidence and score.
- Tables: `positional_signals`, `stock_technical_features`, `chartink_scan_hits`.

Research card:
- GET `/api/move-odds/stocks/{symbol}/card` (`R/move_odds.py:67`, allowlisted).
- Buy/Hold/Sell from `S/copilot_tools/instrument_research.py:590 _build_recommendation`.

**True gaps**
- **No single per-symbol buy-now / wait / avoid answer** that joins plan status, conviction and an intraday price.
- **The plan is end-of-day.**
- **The conviction verdict is not shown in any UI.**

## Q7 — What is the entry, target and stop-loss? [trade plan with risk-reward]

**Existing pieces**

TradePlan (`S/strategy_plan/trade_plan.py:329 linear_plan`):
- entry {price, order_type, valid_for_sessions}
- stop {price, method, atr_multiple, distance_atr, invalidation}
- `r_per_unit`
- targets conservative / base / optimistic, each with an `r_multiple`
- reward:risk gate `candidates.reward_risk` L180 (minimum 1.5)

Stored in Mongo `trade_plans` (COLLECTION L57) and `desk_strategy_plans` (`R/strategy_plan.py:45`). Read with GET `/api/desk/trade-plans/{plan_id}` (`R/desk_trading.py:539`).

Scanner levels:
- `positional_signals.entry_price/stoploss/target_price/risk_reward` (`S/positional_engine/trade_planner.py`), via `/api/positional/picks` and `/picks/{symbol}`.
- Revisions: `/signals/{symbol}/record` (L1011), from `positional_signals_history` and `positional_outcomes`.

Calculator: GET `/api/positional/scenario` (`R/positional.py:2023`) returns per-share reward:risk and sizing.

F&O: POST `/api/desk/strategy/levels`.

UI: `FE/decision/DecisionCard.tsx`, `FE/IdeaLevels.tsx`, `FE/decision/plan-view.ts:167`.

**True gap:** no entry range (see E2). Everything else in the target exists.

## Q8 — Is my existing trade still valid? [thesis status and changing signals]

**Existing pieces**
- **Lifecycle state machine** (`S/trade_lifecycle.py:6,34-58`): NO_SETUP → … → POSITION_OPEN → EXIT_PENDING → CLOSED / REJECTED. Shown by GET `/api/desk/paper-trades/{id}` (`R/desk_trading.py:920`) and `FE/tabs/trade-desk/Journal.tsx`.
- **Plan versions:** GET `/api/desk/trade-plans/{id}`. Note `trade_plan.validate` (L636) checks only internal consistency.
- **Invalidation text:** `stop.invalidation`, `plan._failure_conditions` (L313).
- **Signal revisions:** `/api/positional/signals/{symbol}/record`.
- **Desk alerts** (POST/GET `/api/desk/alerts`, `R/desk_trading.py:973/998`; `S/desk_alerts.py`; Mongo `desk_price_alerts`):
  - Conditions: price, scanner, filing, volume, ATR-risk and sector.
  - Data: DaaS `/v1/flows/*-deals` and `/v1/indices/{index}/eod`.
- **Chart-pattern state "invalidated"**, as in Q4.

**True gaps**
- **Nothing re-checks an open trade** against today's scanner bucket and stage, evidence ledger, pattern state or events. The exit job (`scripts/check_desk_alerts.py`) checks only stop, target, time and the opt-in trend exit.
- **The plan's "invalidated" state is never set:** plan `LIFECYCLE` (`plan.py:32`) lists it, but no code sets it.

## Q9 — Should I book profits or hold? [exit conditions and trailing-stop options]

**Existing pieces**

Exit engine (`S/exit_rules.py:222 step`; versions L47-48):
- Always on: stop, target, time and the gap-open fill.
- Opt-in: ATR trail `trail-atr-v1` (writes `stop_history`) and EMA trend exit `trend-ema-v1`.

Wiring:
- Desk paper trades accept an `exit_rules` field; it is off by default.
- The AI trader sets it from `exit_spec.trailing_atr_mult` (`S/ai_trader/execution.py:282-301`).
- Job status: GET `/api/desk/exit-job-status` (`R/desk_trading.py:1054`, Mongo `job_runs`).

Journal exit ladder (`R/positional_journal.py:140 _exit_ladder`):
- Steps: +5%, then book 25% at +9%, book 25% at +13.5%, trail the rest.
- Each step is marked HIT or WAITING against a yfinance LTP.
- Mongo `trade_journal`.

**True gaps**
- **TradePlan `exit_plan.trailing` is a placeholder** `{enabled: False}` (`trade_plan.py:301`).
- **No UI sends `exit_rules`.**
- **No book-now-vs-hold verdict** for an open desk trade.
- **No move-to-breakeven rule.**

## Q10 — Which F&O setups are attractive? [strategy candidates and defined risk]

**Existing pieces**

POST `/api/desk/strategy/top` (`regime_fit.build_top` L811, `ideas_for_underlying` L559):
- Seven defined-risk families (`FAMILY` L83): long call/put, bull/bear call and put spreads, iron condor.
- Each idea returns `max_profit`, `max_loss`, `loss_unbounded`, `breakevens`, `capital_at_risk`, `reward_risk` at the expected move, and `net_greeks` (L421).
- Regime from `read_regime` L112, which reads `macro_state`/`macro_features`/`macro_daily`.

POST `/api/desk/strategy/plan`:
- `candidates.options_candidates` and `combo_candidates` (covered call, protective put, collar).

Scanner and templates:
- GET `/api/fno/scan/candidates` (`R/fno.py:1340` → `S/fno_candidates/engine.py`): top names per build-up category with five confirmations. Reads DaaS `/desk/fno-buildup` + `/features/bulk` (`nidp.stock_features_daily`).
- GET `/api/desk/strategy/templates` (L74).

Defined-risk rule: `S/desk_strategy_trades.py:219 check_defined_risk`.

UI: `FE/strategy/TopByRegime.tsx`, `FE/FnoCandidates.tsx`, `FE/FnoStrategies.tsx`, `FE/tabs/trade-desk/analysis/RecoStrategies.tsx`.

**True gaps**
- **Not ranked by performance or probability.**
- **No straddle, strangle, butterfly or calendar in the engines.** They exist only as UI presets in `FnoBuilder.tsx`.
- **The `/plan` engine is equity-only**, so there is no index plan through chat.
- **`/top` ideas carry no margin** (`regime_fit.py:414,619` `"margin": None`).

## Q11 — What is the expected move in Nifty? [options-implied move and relevant levels]

**Existing pieces**
- **GET `/api/fno/NIFTY/chain`:**
  - `summary.expected_move` / `expected_move_pct` = ATM call + put close (`R/fno.py:495 straddle`, `:528 expected_move`, set L847-848).
  - Also returns `atm_iv` (L489), `days_to_expiry`, `put_wall`/`call_wall`, `max_pain` and `pcr`.
  - `?expiry=` chooses the expiry; `/chain/consolidated` (L1043) sums over all expiries.
  - Source: `nidp.fno_bhavcopy`.
- **The expected move is reused** in strike placement (`candidates.spread_strike` L629), scenario price (`regime_fit._expected_move_price` L531) and the levels fallback (`strategy_levels.compute`).
- **UI:** `FE/fno-parts.tsx` L307-310, `FE/FnoIndexExpiries.tsx`, `ChartAnalysis.tsx`.

**True gaps**
- **No IV-based 1-SD range** (ATM IV × √T). Searched `sqrt` in fno.py, strategy_plan, strategy_levels and fno_iv_history: none.
- **No live expected move.** `/api/live/option-chain` (`R/live_quotes.py:304`) caches NIFTY/BANKNIFTY at ATM±15 strikes for 2 expiries (`kite_live_feed/config.py:29-31`), but nothing computes on it.
- **No implied-vs-realised record.**
- **Chat's F&O block never gets the expected move or ATM IV:** `market_research._option_summary` (L533) uses only `summarise_chain`.

## Q12 — How much should I risk? [position sizing and capital at risk]

**Existing pieces**
- **Risk profile:** GET/PUT `/api/risk/profile` (`R/risk_controls.py:388/395`; `S/risk_profile.py` FIELDS L62, OWNER_DEFAULT L80; Mongo `risk_profiles`, `risk_profile_audit`).
  - Defaults: per trade 0.5%, open risk 3%, position 10%, sector 25%, daily loss 2%, weekly loss 4%, drawdown 10%, minimum reward:risk 1.5 of paper equity.
  - Returns `live.budgets_rs`.
- **Sizing:** `S/risk_gate/plan_sizing.py:159 size_for`. Risk = stop loss + costs + gap stress (`S/risk_gate/estimate.py:10` `GAP_STRESS_PCT`), with lot rounding.
- **Pre-trade check:** POST `/api/desk/paper-trades/check` (`R/desk_trading.py:474`) → `S/risk_gate/service.py:300 decide` returns allow / reduce / block (checks listed at L119). Mongo `risk_decisions`.
- **Calculator:** `/api/positional/scenario` (risk budget, allocation cap, lot size).
- **AI trader:** the governor's VIX and bear-market size factors (`S/ai_trader/risk_governor.py:108`).
- **UI:** `FE/risk-profile.ts:253`, `FE/tabs/risk-desk/LimitsView.tsx`, `FE/RiskDesk.tsx`.

**True gaps**
- **No Kelly or volatility-targeted sizing.** Searched `kelly`.
- **Sizing basis is paper equity only**, not the real broker capital.

## Q13 — What are my open trades doing? [live or latest available P&L and status]

**Existing pieces**
- **GET `/api/desk/paper-trades?status=open`** (`R/desk_trading.py:591`):
  - Runs pending exits, then marks each trade on the last end-of-day close.
  - Returns unrealised and net P&L, MFE/MAE, `stop_history` and lifecycle (`S/desk_trading.py:1258 public_trade`), plus a totals summary (`summarize` L1311).
  - F&O structures are marked from the F&O bhavcopy.
  - Mongo `desk_paper_trades` (L116); prices `nidp.prices_eod`.
- **Day/week P&L:** GET `/api/risk/profile` `live.day/week` (`S/risk_book.py:170 read`).
- **Account:** GET `/api/desk/paper-account` (`R/desk_trading.py:575`; Mongo `paper_accounts`, `paper_account_ledger`).
- **Journal:** GET `/api/positional/journal?live=true` (`R/positional_journal.py:242`, yfinance LTP, `_compute_pnl` L54).
- **UI:** `FE/tabs/trade-desk/BookViews.tsx`, `HeaderStrip.tsx`, `FE/PaperDesk.tsx`, `FE/tabs/market-overview/OverviewKpis.tsx` (PaperTradesPanel).

**True gaps**
- **No intraday or live mark on desk paper trades.** The Kite feed (`/api/live/quotes|stream|fno-quotes`) exists but is not used for marks.
- **Broker positions** are read-only through a separate path (`FE/desk/BrokerPositions.tsx`, `/api/broker/*`) and are not joined with paper trades.

## Q14 — What should I avoid today? [event risks, weak setups, overexposure]

**Existing pieces**

Event risk:
- **Results calendar:** GET `/api/markets/events-calendar`, `/expectations?from&to` (≤ 3 days) and `/expectation` (`R/events_calendar.py:61,97,84`).
  - Tables: `nidp.event_calendar`, `nidp.corporate_actions`, `nidp.nse_holidays`, `nidp.security_reference_daily`.
- **Macro calendar:** GET `/api/markets/macro-calendar` (`R/macro_calendar.py:52`; `nidp.macro_releases`).
- **Results week:** GET `/api/desk/results-week` (`R/results_week.py:88`; Mongo `results_week_days`, `event_ai_analysis`).
- **Event signals:** GET `/api/market/events` and `/events/tomorrow` (`R/market_events.py:121,213`; `nidp.corporate_event_signals`).
- **In-plan event checks:** the plan gate `event_in_horizon` with `avoid_events` on by default (`plan.py:206`), and scan `RISK_FLAGS.event_window_days` = 7 (`setup_rules.py:92`).
- **UI:** `FE/EventsTab.tsx`, `FE/tabs/market-overview/EventsToday.tsx`.

Weak or late setups:
- Stage WEAK or EXTENDED is excluded from the watchlist (`setup_rules.py:34`).
- Scan `risk_flags` (`setup_rules.py:326`): gap ≥ 5%, RSI > 75, thin liquidity, results due.
- Conviction AVOID_LATE (served only via `picks/mine`).
- Plan status no_trade / avoid.
- Smart-money scanner `direction=distribution`.
- Macro `strategy.avoid_sectors` (`macro_engine.py:389`).
- Results red flags (`S/results_week/signal.py:43`).

Overexposure:
- The risk gate's open-risk 3%, sector 25% and position 10% checks.
- `/api/risk/status` (`R/risk_controls.py:113`): kill switch and halt state, Mongo `risk_controls`.
- Real holdings: `/api/portfolio/exposure/concentration` (Mongo `holdings`) and `/api/portfolio/correlation` (`R/portfolio_desk.py:455`, `nidp.prices_eod_adjusted`).

**True gaps**
- **No unified "avoid today" list or endpoint.**
- **No F&O ban-period (MWPL) list.** Searched `ban_list|fno_ban|mwpl|securities_in_ban|in_ban`: not found.
- **Today's events are not cross-checked against open positions.**
- **No correlation check for paper positions** (`risk_gate/service.py:52`, explicitly skipped).

## Q15 — What did I learn from today's trades? [performance, rule adherence and mistakes]

**Existing pieces**
- **Per-trade record:** exit reason, flags, MFE/MAE, net P&L, `trade_plan_id` link and lifecycle (Journal.tsx).
- **Desk totals summary** (`summarize` L1311).
- **Journal win rate:** GET `/api/positional/journal/summary/portfolio` (`R/positional_journal.py:425`).
- **Risk decision log:** GET `/api/risk/decisions` (`R/risk_controls.py:172`; Mongo `risk_decisions`), shown in `FE/tabs/risk-desk/DecisionLog.tsx`.
- **Corrections:** GET `/api/desk/paper-account/corrections` (L583, `paper_reconcile`).
- **AI trader journal:** GET `/api/ai-trader/strategies/{id}/journal` (`R/ai_trader.py:845`) gives closed-trade calibration against the stated confidence. Mongo `ai_trader_tickets`, `desk_paper_trades`, `ai_trader_strategies`.
- **Idea scorecard:** GET `/api/desk/idea-scorecard` (`R/desk_trading.py:1063`). It is a fixed, committed study file `research/p4_adx_rs/results_20261027/result.json` (`S/idea_scorecard.py:1-8`), not live.

**True gaps**
- **No post-trade review.**
- **No rule-adherence or mistake analysis.** Searched: `adherence|rule_followed|followed_plan|plan_vs_actual|post_trade|trade_review|mistake|lesson|realised_r|r_multiple`.
- **No realised R.**
- **No statistics by exit reason.**
- **No daily "what I learned" roll-up.**

---

# Q16+ — Owner's full brief, by phase

## Pre-market

**P1 Global cues** (GIFT Nifty, US and Asian indices, crude, USD/INR, US yields)

Existing:
- `/api/markets/home` `global_cues`, `global_indices`, `commodities` (`R/markets.py:475-477` ← `S/positional_engine/nse_live.py:455 get_global_snapshot`).
  - yfinance, live, cached 60s.
  - `GLOBAL_INDEX_TICKERS` L369 (Dow, S&P, Nasdaq, Nikkei, Hang Seng, Shanghai, Kospi …).
  - `COMMODITY_TICKERS` L386.
  - `CUE_TICKERS` L399 (ES=F, INR=X, BZ=F, ^TNX).
- UI: `screens/markets/MarketTab.tsx:250`.
- `/api/macro/today` (`macro_engine.latest_state` L583):
  - values crude, usd, bond, india_vix, us_vix, dxy, sp500, nasdaq, nikkei, hang_seng;
  - features `sp500_overnight_pct`, `asia_open_pct`, `dxy_momentum_5d`;
  - a `preopen_summary` (`_build_preopen` L514).
  - Tables `macro_daily`, `macro_features`, `macro_state`, built about 18:35 IST.
- DaaS `/v1/macro/fred` (`nidp.fred_macro`) and `/v1/macro/rbi-yields` (`nidp.rbi_yields`).

Gaps:
- **GIFT Nifty is not found.** The code says so at `nse_live.py:395-398`. Searched `gift|sgx|giftnifty`.
- **India 10Y is a stub:** `_fetch_rbi_10y_yield` (`macro_ingester.py:187`) returns None, so ^TNX stands in.
- **US 2Y/10Y from FRED** are not wired into the app.

**P2 Sector outperformance outlook**

Existing (as in Q2):
- `/api/markets/sector-returns` and `/sector-heatmap`.
- `/api/macro/sector` (forward macro tilt, table `sector_macro_scores`; `S/macro_sector.py:254`).
- `/api/macro/aligned-picks` (`R/macro.py:566`).
- market_dashboard `rs_5d_pp`.
- `/api/markets/sectors` AI commentary (Mongo `market_sector_analysis`).

Gaps:
- **No validated forward outperformance model.** Only the macro tilt hypothesis and backward-looking RS exist.
- **No RRG.**

**P3 MF deployment** (AMC holdings, monthly flows)

Existing:
- `/api/markets/smart-money/{sectors,amc,scanner,summary}`, reading `nidp.mf_holdings_monthly`, `mf_holdings_deltas` and `mf_holdings_coverage`.
- Covers 11 disclosing AMCs only.
- `nidp.scanx_mf_holdings` (migration 179) is stored, but no app route reads it.

Gaps:
- **No industry-wide monthly MF net flows** (AMFI).
- **No SEBI daily MF equity buying.**
- **No MF cash levels.**

**P4 Economic calendar** (RBI, CPI, Fed) **and today's results**

Existing:
- `/api/markets/macro-calendar` and `/history` (`R/macro_calendar.py:52,63` → DaaS `desk_macro.py`; `nidp.macro_releases`, `nidp.nse_holidays`, `nidp.index_eod`).
  - Catalog (`backend/nidp/services/macro_calendar/catalog.py:41-57`): US CPI, PCE, NFP, FOMC …; India RBI MPC, CPI, IIP, GDP.
- Results: `/api/markets/events-calendar/expectations` and `/api/desk/results-week` (as in Q14).
- UI: `FE/EventsTab.tsx`, `FE/events-data.ts:134-568`.

Gaps:
- **Consensus estimate is always null.**
- **India CPI/IIP actual values are not read.**
- **No WPI or PMI.**

**P5 Session-type classifier** (trend / range / volatile)

Existing, end-of-day only:
- desk-regime-v1 (`macro_engine.py:927`), including high_volatility / sideways.
- The deploy verdict.
- Research `trend_classification` (`research/charting/regime.py:562`; no UI).
- Per stock: NR7 (DaaS `movers.py:962`) and the opening-range check (`S/move_odds_live.py:110`).

Gap: **no intraday or opening day-type classifier for the index.** Searched `session_type|day_type|trend_day|range_day|choppy|inside_day|opening_range|vol_regime`.

**P6 S/R, pivots, key levels for NIFTY/BANKNIFTY**

Existing: OI walls, max pain and expected-move edges (`/api/fno/{sym}/chain`), and `/api/desk/strategy/levels`.

Gaps:
- **No pivots or price S/R for indices.**
- `nidp.index_eod` has `high_price`/`low_price` columns; whether they are populated is unverified.

## Scanning

**S1 Breakout probability**

Existing:
- GET `/api/positional/backtest/calibration?metric=broke_high|moved_5pct&horizon_days=5|10|20` (`R/positional.py:1522`).
  - Hit rate by accumulation-score bucket with a Wilson CI; in-sample.
  - Tables `accumulation_calibration`, `positional_backtest_labels`.
  - UI: `FE/chart-data.ts:457`.
- Move-odds `model_rank_pct` on scan-universe (`R/positional.py:651,694`).
- Rule scores: `nidp.corporate_event_signals.breakout_score`, conviction.

Gap: **no calibrated per-stock P(breakout).**

**S2 Up on volume but below resistance**

Existing: watchlist `pre_breakout` (`setup_rules.py:41-42`):
- `dist_breakout_pct` in [−2%, 0),
- `volume_spike_3v20` ≥ 1.2,
- `volume_slope` > −3.

Gaps:
- **No "up today" requirement.**
- **Volume is a 3-vs-20-session average, not the day's relative volume.**
- **The pool is only the top 80 by score.**

**S3 Fundamentally strong near 52-week lows — covered.**

Existing: GET `/api/positional/reversal-candidates?near_pct=` (`R/positional.py:738`; `S/positional_engine/reversal_rules.py:399 fundamental_component`).
- Pledge and distress gates.
- DaaS `/v1/features/reversal-snapshot` (`features.py:442`) reads `nidp.stock_features_daily`, `nidp.prices_eod_adjusted`, `nidp.prices_eod`, `nidp.index_eod`, `nidp.index_constituents`, `nidp.nse_financials_quarterly`, `nidp.nse_financials_cashflow`, `nidp.corporate_announcements`, `nidp.event_calendar`, `nidp.security_reference_daily`.
- UI: `FE/ReversalPanel.tsx`.

Gaps:
- **The weights are untuned.**
- **Piotroski and Altman** (`stock_features_daily.piotroski_score`, `altman_z_score`) are unused.

**S4 Long build-up and short covering — covered.**

`/api/fno/scan/buildup` (as in Q2), `/api/fno/{sym}/futures/oi-buildup` (`R/fno.py:885`, Kite OI candles via `S/fno_oi_windows.py`, falling back to bhavcopy), and `/positioning-history` (L1255).

Gaps:
- **`setup_quality` is null.**
- **No intraday OI scan** across the universe.

**S5 Relative strength vs Nifty**

Existing, per stock or per sector only:
- `sector_strength.compute_rs_pct` (20-day vs NIFTYBEES) inside `sector_score`.
- research_chart RS63 vs Nifty 50 (`R/research_chart.py:163,584`).
- `strategy_plan/evidence.py:221`.
- Reversal `rs_vs_index`.

Gap: **no universe-wide RS rating, rank or line, and no screener field for it.** `nidp.stock_features_daily` has no RS column.

**S6 Expected 2%/5% move over N sessions (Move-odds)**

Existing:
- `/api/move-odds/{latest,stocks/{sym},card,history,profile,diagnostics,live}` (`R/move_odds.py:57-127`, allowlist `move_odds`) and `/api/movers/*` (`R/movers.py:54-153`).
- Heads `p_up5_1d`, `p_down5_1d`, `p_up10_1d`, `p_down10_1d`: one day ahead, ±5% and ±10%.
- Tables `nidp.tpd_runs`, `tpd_run_estimates`, `tpd_run_stocks`, `tpd_run_events`, `tpd_run_grades`, `tpd_run_refusals`, `tpd_model_record`, `tpd_band_record`, `tpd_preview_runs`.
- The model code is not in this repo; it runs on the research host.

Gaps:
- **No 2% threshold.**
- **No N-session horizon.** The closest is `accumulation_calibration` (≥ 5% within 5/10/20 sessions, by bucket).

**S7 Stocks to avoid** (weak fundamentals, distribution)

Existing, in pieces:
- Smart-money scanner `direction=distribution` (DaaS `smart_money.py:533`).
- `stock_features_daily.earnings_decline_flag` / `debt_spike_flag` via DaaS `/v1/stocks/screener` (not in the app screener primitives).
- Reversal hard gates, `research_lenses` red flags (`S/copilot_tools/research_lenses.py:65`), AVOID_LATE, macro `avoid_sectors`, stage WEAK.

Gap: **no unified list.**

## Entry

**E1 False-breakout detection**

Existing:
- Pattern state "invalidated" (`R/research_chart.py:513-529`), shown in plan evidence `chart_patterns` (`strategy_plan/evidence.py:237`).
- Breakout gate: at most 3% above the level and a gap of at most 5%.

Gap: **no false-breakout flag on picks, plans or open trades.**

**E2 Entry range**

Gap: `entry.zone` is always None (`candidates.py:285,457,893`), and `TradePlan.entry` is a single price. The nearest existing piece is the `_readiness` bands (`R/positional.py:764`).

**E3 Pullback vs enter now — exists.**
- `trade_plan.order_type_for` L90: stop_trigger / limit_pullback / at_close, shown as break_above / pullback_to / at_once (FE twin `FE/desk-trading.ts:256 entryRuleFor`).
- `_readiness`: LATE > 8% / TRIGGERED / NEAR / WAIT / FAR / STOPPED.
- Conviction `_readiness_cap`.

**E4 Missing confirmations — exists.**
- Plan "wait" reasons (`setup_not_triggered`, `cash_not_confirming`, `no_fresh_buildup`) plus `would_change_if`.
- Evidence ledger supports / conflicts / unavailable.
- Candidate `missing[]`.
- UI: `FE/decision/ways-forward.tsx`.

Gap: **no "x of y confirmations" checklist view.**

**E5 Overextension**

Existing:
- Stage EXTENDED (`scorer.classify_stage` L169: RSI > 72 or > 5% above the 20-day high).
- Conviction penalties.
- `RISK_FLAGS.extended_rsi14_above` 75.
- Watchlist `dist_ema20_pct` and `atr_pct`.

Gap: **no ATR-normalised distance from the EMA.** Searched `overextend|extension_atr|dist_ema|stretch`.

## Open position

**O1 Partial booking**

Existing: only the journal's exit ladder and partial EXIT fills (`R/positional_journal.py:140`, POST `/{id}/fill` L312).

Gap for the desk: "partial exits are NOT modelled" (`S/desk_trading.py:85`), and F&O `target_2` is not acted on.

**O2 Trailing stop and move to breakeven**

Existing: the opt-in ATR trail (`exit_rules.py`).

Gaps:
- **TradePlan `exit_plan.trailing` is disabled** (`trade_plan.py:301`).
- **No UI toggle.**
- **No breakeven rule.**

**O3 Momentum-loss signal**

Existing:
- Opt-in `trend-ema-v1` exit.
- Chartink seed `btst.exit_warning_distribution` (`R/positional.py:1738`, `chartink_scan_hits`).
- Evidence `momentum` item (`evidence.py:213`).

Gap: **not applied to open trades.**

**O4 Add / averaging rule**

Existing:
- The desk refuses adds with 409 `duplicate_open_trade` (`R/desk_trading.py:204-213`).
- Journal staged entries PILOT / CONFIRM / SUSTAIN / MOMENTUM (`R/positional_journal.py:101-137`), with `add_exceeds_original_budget`.
- Governor ALREADY_HELD.

Gap: **no averaging-down or pyramiding rule** on the desk.

**O5 Realized and unrealized P&L — exists** (as in Q13). End-of-day mark only.

**O6 Overnight gap-risk estimate**

Existing:
- `risk_gate/estimate.py` gap_stress (a fixed % through the stop).
- `trade_plan.gap_risk_text` L272.
- The `event_in_horizon` gate.
- `/api/portfolio/holding-risk` (`R/portfolio_desk.py:540`; real holdings' overnight gaps).

Gap: **no gap estimate for open paper positions.**

## F&O

**F1 PCR, max pain, ATM IV, IV percentile, expected move**

Existing:
- `/api/fno/{sym}/chain` `summary` returns `pcr`, `max_pain`, `atm_iv` and `expected_move`.
- `/options/intraday` (`R/fno.py:1108` → `S/fno_options_intraday.py`) gives an intraday PCR from Kite candles over ATM±8 strikes.
- GET `/api/fno/{sym}/iv-history` (`R/fno.py:1289` → `S/fno_iv_history.py`; Mongo `fno_iv_history` L48).
  - `iv_rank` L116 and `iv_percentile` L127 are null until 252 sessions are recorded (L54).
  - Written by `backend/scripts/record_iv_history.py`.
- UI: ChartAnalysis "IV PCTILE" tile.
- Stocks: `nidp.stock_features_daily.options_pcr`.

Gaps:
- **No stored index PCR or max-pain history.**
- **No live PCR or max pain from Kite.**
- **`regime_fit` and `strategy_levels` still do not read IV history** (`strategy_levels.py:189` hard-codes None).
- **Weekly-expiry IV is not recorded.**

**F2 Strike and expiry selection**

Existing:
- `candidates.pick_expiry` L573 (by horizon, 5-60 days).
- `spread_strike` L629 (the wall if inside the expected move, else the expected-move edge).
- `condor_ok` L651.
- `regime_fit.strike_plans` L234 and `_chain_for` L491 (nearest expiry at least 1 session out).
- `fno_roll.plan_roll` L169.

Gaps:
- **No delta-target strike selection.** `target_delta` is only validated, in `S/strategy_store.py:66,356`.
- **No weekly-vs-monthly choice by IV or theta.**

**F3 Margin** (Zerodha calculator via Kite) **— exists.**
- POST `/api/fno/margin` (`R/fno.py:1176`) → `S/fno_margin.py:132 run`.
  - Kite `basket_order_margins(consider_positions=False, mode="compact")` (L35).
  - `hedge_benefit` L95.
  - Platform token from Mongo `kite_platform_token`; NFO instruments are cached daily.
- `S/strategy_plan/margin.py` (inside `/plan`) uses the user's own Zerodha session and skips indices.
- UI: `FE/FnoBuilder.tsx:121`, `FE/FnoCompare.tsx:68`, `basket-routes.ts:96`.

Gaps:
- **`/top` ideas carry no margin.**
- **Margin needs that day's admin Kite login.**

**F4 Greeks and scenarios — exists.**
- Per-contract Greeks on `/chain` (`option_pricing.greeks` L229, Black-76).
- POST `/api/desk/strategy/payoff` (`R/strategy_plan.py:68` → `strategy_plan/engine.compute_payoff` L28): `payoff.py` breakevens L174, extremes L186, capital at risk L201, and `pre_expiry.py` T+0 value, position Greeks, IV shift and named scenarios.
- `/levels` four-scenario matrix (`strategy_levels.py` SCENARIOS L17).
- UI: `FE/strategy/StrategyGraphs*`, `ScenarioControls.tsx`, `analysis/StrategyPanel.tsx`.

Gaps:
- **No probability of profit.**
- **No VIX-to-scenario link.**
- **No skew.**

**F5 Roll and hedge suggestions**

Existing:
- Roll: GET/POST `/api/desk/paper-trades/{id}/roll` (`R/desk_trading.py:763/812` → `S/fno_roll.py`, `ROLL_WINDOW_SESSIONS` 3 at L37; DaaS `/fno/{sym}` → `nidp.fno_bhavcopy`). UI `FE/RollAction.tsx`.
- Hedge pieces:
  - `candidates.hedge_reason` L965 (protective put or collar).
  - `positional_engine/hedge_planner.py:45 get_atm_put_cost` (used only by POST `/api/positional/basket`).
  - The build-up `rollover` flag.

Gaps:
- **No automatic roll suggestion.** Roll is user-started and paper-only.
- **No hedge suggestion for an open F&O position.**
- **No index rollover % metric.**

## Risk

**R1 Daily loss limit used — exists.**
- `risk_book.read` (`S/risk_book.py:170`) gives day P&L.
- `/api/risk/profile` `live.day` vs `daily_loss_pct`.
- Gate check `daily_loss` (`risk_gate/service.py:724`).
- UI `LimitsView.tsx`.
- Paper only.

**R2 Sector and correlation exposure**

Existing:
- The sector check (25%) in the gate.
- Real holdings: `/api/portfolio/correlation` (`nidp.prices_eod_adjusted`), `/api/portfolio/exposure/concentration`, and `positional_engine/portfolio_filter.py`.

Gap: **correlation for paper positions is SKIPPED** (`risk_gate/service.py:52,121`).

**R3 Trade count today**

Not found. Searched `trades_today|max_trades|trades_per_day|max_daily_trades|entries_today|trade_count|max_entries`.

Only open-position caps exist: governor `max_open_positions` 10 and desk `MAX_OPEN_TRADES` 100 (`S/desk_trading.py:119`).

**R4 Overlap with existing positions — exists.**
- 409 `duplicate_open_trade` / `duplicate_open_structure`.
- `/paper-trades/check` reports `duplicate`.
- Governor ALREADY_HELD.
- `portfolio_filter` against real holdings.

**R5 Stop after the loss limit — exists.**
- The daily, weekly and drawdown checks block new entries.
- PUT `/api/risk/kill-switch` and `/halt` (`R/risk_controls.py:150,157`; Mongo `risk_controls`, `risk_control_audit`).
- Open positions are untouched.

Gap: **no consecutive-loss cooldown.** Searched `consecutive_loss|loss_streak|cooldown`.

## EOD review

**D1 Trade outcome vs plan**

Raw pieces exist: exit reason, `trade_plan_id`, MFE/MAE, `stop_history`, `positional_outcomes`.

Gap: **no computed plan-vs-actual comparison.**

**D2 Rule adherence**

Not found (searches as in Q15). Only the decision log and the corrections exist.

**D3 Signal hit-rate**

Existing:
- `/api/desk/idea-scorecard` (fixed study).
- `/api/positional/backtest/calibration` (in-sample).
- The Move-odds out-of-sample record (`FE/desk-data.ts:738`).
- AI-trader journal calibration.

Gap: **no live hit-rate for desk TradePlans or AI-watchlist ideas.** The data to compute one exists in `ai_watchlist_days` + `positional_outcomes` + `trade_plans`.

**D4 Drivers of the biggest gainers and losers**

Existing:
- `/api/movers/{symbol}/analysis` (`R/movers.py:153` → DaaS `movers.py`, allowlisted) splits a move into market, sector and stock-specific parts.
  - Tables: `nidp.prices_eod`, `nidp.index_eod`, `nidp.sector_master`, `nidp.corporate_announcements`, `nidp.bulk_deals`, `nidp.block_deals`, `nidp.insider_sast`, `nidp.tpd_runs`.
- `/api/markets/movers` (`R/markets.py:529` → DaaS `market_pulse.py:400`; `analytics.stock_card`, `nidp.stock_features_daily`).

Gap: **nothing explains the user's own winners and losers.**

**D5 Overnight carry check**

Gap: **nothing checks open positions before carrying overnight.** The pieces are gap_stress, gap_risk_text, holding-risk (real holdings only) and desk alerts.

**D6 Tomorrow's setups and events**

Existing:
- `/api/desk/ai-watchlist` (built 22:45 IST).
- `/api/positional/watchlist` (preparation mode).
- `/api/markets/events-calendar/expectations?from&to`, shown as "Results today & tomorrow" in `FE/EventsTab.tsx:483-561`.
- `/api/market/events/tomorrow` (`R/market_events.py:213`).
- `/api/markets/macro-calendar`.

Gap: **tomorrow's events are not cross-checked against open positions.**

---

# Summary table (for agent C's freshness check)

| # | Best existing source(s) | True gaps | Tables / collections read |
|---|---|---|---|
| Q1 market view | `/api/markets/home`; `/api/positional/market-dashboard`; `/api/risk/freshness`; `/api/macro/today`.regime; `/api/markets/sector-returns`; `/api/fno/NIFTY/chain` summary; `/api/live/snapshot?universe=indices` | pivots and price S/R for indices; four unreconciled regimes; no intraday breadth | stock_ohlcv, stock_master, macro_daily, macro_features, macro_state, nidp.index_eod, nidp.index_constituents, nidp.prices_eod, nidp.fii_dii_flows, nidp.fno_bhavcopy, Mongo kite_live_close / kite_live_intraday, Redis live cache |
| Q2 smart money | `/api/markets/smart-money/*`; `/api/markets/fii-dii`; `/api/fno/scan/buildup`; `/api/flows/ledger/*`; `/api/markets/sector-heatmap` | FII F&O index OI stored but not exposed; no RRG; no validated score; no AMFI flows | nidp.fii_dii_flows (EQUITY_CASH; INDEX_FUTURES / INDEX_OPTIONS unused), nidp.mf_holdings_monthly, nidp.mf_holdings_deltas, nidp.mf_holdings_coverage, nidp.shareholding_pattern, nidp.v_trendlyne_deals_net (nidp.trendlyne_deals), nidp.smart_money_scores_daily, nidp.fpi_sector_auc, nidp.fno_bhavcopy, nidp.prices_eod, nidp.stock_features_daily, nidp.security_reference_daily, nidp.prices_eod_adjusted |
| Q3 top 5 | POST `/api/desk/strategy/ideas` {limit:5}; POST `/api/desk/strategy/top`; GET `/api/desk/ai-watchlist` | rank is a rules score, not a probability; end-of-day only | positional_signals, stock_technical_features, stock_ohlcv, stock_master, Mongo ai_watchlist_days, trade_plans, desk_strategy_plans, desk_chartink_hits, desk_chartink_sources; nidp.stock_features_daily, nidp.fno_bhavcopy, nidp.event_calendar, macro_state |
| Q4 confirmed breakouts | `/api/positional/watchlist` breakout_confirmed; `/api/research/chart/{s}/patterns`; TradePlan | entry zone (always None); same-day relative volume; intraday confirmation; false-breakout flag on rows | stock_technical_features, stock_ohlcv, stock_master, nidp.prices_eod_adjusted, Mongo trade_plans |
| Q5 unusual volume | `/api/positional/scan-universe` (rvol20, vol_z20); `/api/markets/smart-money/scanner` (delivery); `/api/market/events` | no single relative-volume + change + delivery list; screener has no volume or delivery primitive; no live relative volume | nidp.stock_features_daily, nidp.prices_eod (deliv_pct), nidp.delivery_data, nidp.corporate_event_signals, stock_ohlcv.delivery_pct |
| Q6 buy now? | POST `/api/desk/strategy/plan` status (chat uses it via copilot_trade_idea); conviction (`picks/mine`); `/api/positional/picks/{s}`; move-odds card | no unified buy / wait / avoid with an intraday price; conviction not in the UI | positional_signals, stock_technical_features, chartink_scan_hits, nidp.stock_features_daily, nidp.fno_bhavcopy, nidp.event_calendar, macro_state, Mongo trade_plans |
| Q7 entry / target / stop | TradePlan via `/plan`, `/ideas`, `/api/desk/trade-plans/{id}`; `positional_signals` levels; `/api/positional/scenario` | entry range | Mongo trade_plans, desk_strategy_plans; positional_signals, positional_signals_history, positional_outcomes |
| Q8 trade still valid? | `/api/desk/paper-trades/{id}` lifecycle; `/api/desk/trade-plans/{id}`; desk alerts; `/signals/{s}/record`; pattern state | no re-validation of open trades vs today's signals; "invalidated" never set | Mongo desk_paper_trades, trade_plans, desk_price_alerts, job_runs; positional_signals_history; nidp.prices_eod, nidp.bulk_deals, nidp.block_deals, nidp.index_eod |
| Q9 book or hold | `S/exit_rules.py` (ATR trail, EMA exit, opt-in); journal `_exit_ladder`; `/api/desk/exit-job-status` | TradePlan trailing disabled; no UI toggle; no breakeven; no hold/book verdict | Mongo desk_paper_trades, trade_journal, job_runs; nidp.prices_eod |
| Q10 F&O setups | POST `/api/desk/strategy/top`; `/plan` options and combos; `/api/fno/scan/candidates`; templates | no performance or probability rank; no straddle / strangle / calendar in engines; no index `/plan`; no margin on `/top` | nidp.fno_bhavcopy, nidp.stock_features_daily, nidp.prices_eod, nidp.index_eod, nidp.security_reference_daily, macro_state, macro_features, macro_daily |
| Q11 Nifty expected move | `/api/fno/NIFTY/chain` summary.expected_move(_pct), atm_iv, walls; `/api/desk/strategy/levels` | IV-based 1-SD; live expected move from the Kite option window; implied-vs-realised; chat lacks it | nidp.fno_bhavcopy; Mongo fno_iv_history; Redis/Kite option-chain cache |
| Q12 how much to risk | `/api/risk/profile`; `risk_gate/plan_sizing.size_for`; POST `/api/desk/paper-trades/check`; `/api/positional/scenario` | Kelly or volatility sizing; real-capital basis | Mongo risk_profiles, risk_profile_audit, paper_accounts, paper_account_ledger, desk_paper_trades, risk_decisions |
| Q13 open trades | GET `/api/desk/paper-trades`; `/api/desk/paper-account`; `/api/risk/profile` live.day/week; journal `?live=true` | no live or intraday mark (end-of-day only); broker positions not joined | Mongo desk_paper_trades, paper_accounts, paper_account_ledger, trade_journal; nidp.prices_eod, nidp.fno_bhavcopy |
| Q14 avoid today | events-calendar/expectations; macro-calendar; results-week; risk gate status/limits; scan risk_flags; smart-money distribution | unified avoid list; F&O ban (MWPL) list; events vs open positions; correlation for paper positions | nidp.event_calendar, nidp.corporate_actions, nidp.nse_holidays, nidp.security_reference_daily, nidp.macro_releases, nidp.corporate_event_signals, nidp.mf_holdings_deltas, Mongo results_week_days, event_ai_analysis, risk_controls, risk_profiles |
| Q15 learn from trades | paper-trades closed summary; journal summary; `/api/risk/decisions`; ai-trader journal; idea-scorecard (fixed) | post-trade review; rule adherence; mistakes; realised R; live hit-rate | Mongo desk_paper_trades, trade_journal, risk_decisions, ai_trader_tickets, ai_trader_strategies, trade_plans; file research/p4_adx_rs/results_20261027/result.json |
| P1 global cues | `/api/markets/home` global_cues (yfinance live); `/api/macro/today` | GIFT Nifty; India 10Y (stub); FRED US yields not in app | yfinance (live); macro_daily, macro_features, macro_state; nidp.fred_macro, nidp.rbi_yields, nidp.market_daily_snapshot |
| P2 sector outlook | `/api/macro/sector`; sector-returns / heatmap; market_dashboard rs_5d_pp | validated forward model; RRG | sector_macro_scores, nidp.index_eod, nidp.index_constituents, nidp.prices_eod(_adjusted), stock_ohlcv, Mongo market_sector_analysis |
| P3 MF deployment | `/api/markets/smart-money/{sectors,amc,scanner,summary}` | AMFI monthly flows; SEBI daily MF; MF cash | nidp.mf_holdings_monthly, nidp.mf_holdings_deltas, nidp.mf_holdings_coverage, nidp.scanx_mf_holdings (unread) |
| P4 econ + results calendar | `/api/markets/macro-calendar`; events-calendar/expectations; `/api/desk/results-week` | consensus; India actual values; WPI / PMI | nidp.macro_releases, nidp.nse_holidays, nidp.index_eod, nidp.event_calendar, nidp.corporate_actions, Mongo results_week_days, event_ai_analysis |
| P5 session type | desk-regime-v1 (`/api/macro/today`, regime-history); deploy verdict | intraday or opening day-type classifier | macro_daily, macro_state, stock_ohlcv, nidp.index_eod |
| P6 index levels | `/api/fno/{NIFTY,BANKNIFTY}/chain` walls, max pain, expected move; `/api/desk/strategy/levels` | pivots; price S/R | nidp.fno_bhavcopy, nidp.index_eod (high/low unverified) |
| S1 breakout probability | `/api/positional/backtest/calibration`; scan-universe model_rank_pct | calibrated per-stock P(breakout) | accumulation_calibration, positional_backtest_labels, nidp.tpd_run_estimates |
| S2 up on volume below resistance | watchlist pre_breakout | "up today" check; day relative volume; top-80 pool | stock_technical_features, stock_ohlcv |
| S3 quality near 52-week low | `/api/positional/reversal-candidates` | tuned weights; Piotroski / Altman unused | nidp.stock_features_daily, nidp.prices_eod(_adjusted), nidp.index_eod, nidp.index_constituents, nidp.nse_financials_quarterly, nidp.nse_financials_cashflow, nidp.corporate_announcements, nidp.event_calendar, nidp.security_reference_daily |
| S4 long build-up / short covering | `/api/fno/scan/buildup`; `/{s}/futures/oi-buildup`; positioning-history | setup_quality; intraday universe OI | nidp.fno_bhavcopy, nidp.prices_eod, nidp.index_eod, nidp.stock_features_daily, nidp.security_reference_daily; Kite historical OI |
| S5 RS vs Nifty | research_chart RS63; sector_score; reversal rs_vs_index | universe RS rank or screener field | stock_technical_features, nidp.prices_eod_adjusted, nidp.index_eod, nidp.stock_features_daily |
| S6 2% / 5% in N sessions | `/api/move-odds/*`, `/api/movers/*` (±5 / ±10%, 1 day) | 2% threshold; N-day horizon | nidp.tpd_runs, nidp.tpd_run_estimates, nidp.tpd_run_stocks, nidp.tpd_run_events, nidp.tpd_run_grades, nidp.tpd_run_refusals, nidp.tpd_model_record, nidp.tpd_band_record, nidp.tpd_preview_runs |
| S7 avoid list | smart-money distribution; DaaS screener flags; reversal gates; red-flag lens | unified list | nidp.mf_holdings_deltas, nidp.stock_features_daily, stock_technical_features |
| E1 false breakout | pattern state invalidated | flag on picks / plans / open trades | nidp.prices_eod_adjusted |
| E2 entry range | `_readiness` bands only | entry.zone always None | positional_signals |
| E3 pullback vs now | order_type_for / desk_entry_rule; `_readiness`; conviction cap | — | stock_technical_features, positional_signals |
| E4 missing confirmations | plan wait reasons / would_change_if; evidence ledger | x-of-y checklist | (as Q6) |
| E5 overextension | stage EXTENDED; RSI flags; dist_ema20_pct | ATR-normalised EMA distance | stock_technical_features, stock_ohlcv |
| O1 partial booking | journal exit ladder and fills | desk partial exits | Mongo trade_journal |
| O2 trailing / breakeven | exit_rules trail-atr-v1 (opt-in) | TradePlan trailing off; no UI; no breakeven | Mongo desk_paper_trades |
| O3 momentum loss | trend-ema-v1; Chartink exit-warning scan; evidence momentum | not applied to open trades | chartink_scan_hits, nidp.prices_eod |
| O4 add / average | journal staged entries; desk 409 duplicate | desk pyramiding / averaging | Mongo trade_journal, desk_paper_trades |
| O5 realised / unrealised P&L | `/api/desk/paper-trades`, `/api/risk/profile` live | live mark | Mongo desk_paper_trades, paper_account_ledger; nidp.prices_eod |
| O6 overnight gap risk | gap_stress; gap_risk_text; `/api/portfolio/holding-risk` | per-position gap estimate | nidp.prices_eod_adjusted, Mongo holdings |
| F1 PCR / max pain / IV / IVP / expected move | `/api/fno/{s}/chain`; `/options/intraday`; `/iv-history` | index PCR history; live PCR; IVP not used by engines; weekly IV | nidp.fno_bhavcopy, Mongo fno_iv_history, nidp.stock_features_daily.options_pcr, Kite candles |
| F2 strike / expiry | candidates.pick_expiry / spread_strike; regime_fit.strike_plans | delta-target strikes; weekly-vs-monthly logic | nidp.fno_bhavcopy |
| F3 margin | POST `/api/fno/margin` (Kite basket_order_margins) | margin on `/top`; needs daily Kite login | Mongo kite_platform_token; Kite NFO instruments |
| F4 Greeks / scenarios | `/chain` Greeks; POST `/api/desk/strategy/payoff` (pre_expiry); `/levels` | probability of profit; VIX link; skew | nidp.fno_bhavcopy |
| F5 roll / hedge | `/api/desk/paper-trades/{id}/roll`; hedge_reason; hedge_planner | automatic roll or hedge suggestions; rollover % | nidp.fno_bhavcopy, Mongo desk_paper_trades |
| R1 daily loss used | `/api/risk/profile` live.day; gate daily_loss | — (paper only) | Mongo desk_paper_trades, paper_accounts, risk_profiles |
| R2 sector / correlation | gate sector 25%; `/api/portfolio/correlation` (holdings) | paper-position correlation | Mongo desk_paper_trades, holdings; nidp.prices_eod_adjusted |
| R3 trade count today | not found | all of it | — |
| R4 overlap | 409 duplicate; `/paper-trades/check`; ALREADY_HELD | — | Mongo desk_paper_trades |
| R5 stop after loss limit | gate daily / weekly / drawdown blocks; kill-switch / halt | loss-streak cooldown | Mongo risk_controls, risk_control_audit, risk_decisions |
| D1 outcome vs plan | raw fields only | plan-vs-actual computation | Mongo desk_paper_trades, trade_plans; positional_outcomes |
| D2 rule adherence | not found | all of it | — |
| D3 hit-rate | idea-scorecard (fixed); calibration; ai-trader journal | live hit-rate of desk ideas | file result.json; accumulation_calibration; Mongo ai_watchlist_days, ai_trader_tickets; positional_outcomes |
| D4 gainer / loser drivers | `/api/movers/{s}/analysis`; `/api/markets/movers` | user's own trades | nidp.prices_eod, nidp.index_eod, nidp.sector_master, nidp.corporate_announcements, nidp.bulk_deals, nidp.block_deals, nidp.insider_sast, nidp.tpd_runs, analytics.stock_card, nidp.stock_features_daily |
| D5 overnight carry | pieces only | carry check on open positions | — |
| D6 tomorrow | `/api/desk/ai-watchlist`; events-calendar/expectations; `/api/market/events/tomorrow`; macro-calendar | events vs open positions | Mongo ai_watchlist_days; nidp.event_calendar, nidp.corporate_event_signals, nidp.macro_releases |

**Distinct stores to freshness-check**
- **App Postgres:** stock_ohlcv, stock_master, stock_technical_features, positional_signals, positional_signals_history, positional_outcomes, positional_backtest_labels, accumulation_calibration, chartink_scan_hits, macro_daily, macro_features, macro_state, sector_macro_scores.
- **NIDP:**
  - Prices and reference: nidp.prices_eod, nidp.prices_eod_adjusted, nidp.index_eod, nidp.index_constituents, nidp.sector_master, nidp.security_reference_daily, nidp.stock_features_daily, nidp.delivery_data, nidp.fno_bhavcopy.
  - Flows and holdings: nidp.fii_dii_flows, nidp.mf_holdings_monthly, nidp.mf_holdings_deltas, nidp.mf_holdings_coverage, nidp.scanx_mf_holdings, nidp.shareholding_pattern, nidp.trendlyne_deals, nidp.smart_money_scores_daily, nidp.fpi_sector_auc.
  - Events and filings: nidp.event_calendar, nidp.corporate_actions, nidp.corporate_announcements, nidp.corporate_event_signals, nidp.macro_releases, nidp.nse_holidays, nidp.bulk_deals, nidp.block_deals, nidp.insider_sast.
  - Fundamentals and macro: nidp.nse_financials_quarterly, nidp.nse_financials_cashflow, nidp.fred_macro, nidp.rbi_yields, nidp.market_daily_snapshot.
  - Move-odds model: nidp.tpd_runs, nidp.tpd_run_estimates, nidp.tpd_run_stocks, nidp.tpd_run_events, nidp.tpd_run_grades, nidp.tpd_run_refusals, nidp.tpd_model_record, nidp.tpd_band_record, nidp.tpd_preview_runs.
  - analytics.stock_card.
- **Mongo:**
  - Ideas and plans: ai_watchlist_days, trade_plans, desk_strategy_plans, desk_chartink_sources, desk_chartink_hits.
  - Trades and accounts: desk_paper_trades, desk_price_alerts, trade_journal, paper_accounts, paper_account_ledger.
  - Risk: risk_profiles, risk_profile_audit, risk_controls, risk_control_audit, risk_decisions.
  - Jobs and research: job_runs, results_week_days, event_ai_analysis, fno_iv_history, fno_forward_signals, market_sector_analysis.
  - AI trader: ai_trader_tickets, ai_trader_strategies.
  - Kite: kite_live_close, kite_live_intraday, kite_live_minute, kite_platform_token.
  - holdings.
- **Live external sources:** yfinance (global cues, VIX overlay, journal and picks/mine LTP), the Kite platform feed (Redis per-symbol cache), and Sensibull (feeds nidp.fii_dii_flows).
