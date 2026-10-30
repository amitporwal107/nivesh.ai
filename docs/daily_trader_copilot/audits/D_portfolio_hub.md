# D — Portfolio & Broker Hub: what Nivesh already has vs the owner's spec

- **Code:** `origin/dev` at `a4294830`, read with `git show` / `git grep` only. Nothing was checked out, edited or committed.
- **Data:** staging (`nivesh-staging-app-backend`), read-only aggregate queries, run 2026-10-30. No ids, tokens, names or account numbers were printed.
- **Paths** below are relative to the repo root. `file:line` refers to `origin/dev`.

## 0. Headline findings

1. **Most of the ingestion layer exists. Little of the position layer does.**
   - These are built: broker redirect sign-in, holdings sync, live reads of holdings, positions and funds, the CSV/XLSX preview-and-commit, CAS (upload and Gmail), "broker wins" reconciliation, duplicate counters and sync snapshots.
   - These are not built:
     - orders, trades and history from any broker;
     - stored positions;
     - analytics on F&O positions (payoff, Greeks, margin, scenario);
     - stops and targets on real positions;
     - DMA technicals on holdings;
     - an equity curve against Nifty 50;
     - the data-scope and review steps of the wizard;
     - manual entry in the UI.
2. **There are two separate stores:**
   - **Holdings** are stored in Mongo `db.holdings`, one flat row per lot. Broker, CAS, broker-file and manual rows all go here.
   - **Positions are never stored.** They are read live from the broker on every call (`backend/routes/broker_connect.py:407-535`, docstrings "never stored").
   - No orders or trades model exists for broker data. The only transactions are CAS mutual-fund transactions (`backend/services/cas_transactions.py`).
3. **Brokers on staging today:**
   - Three are connectable: Zerodha, ICICI Direct and Motilal Oswal.
   - Two have been connected live:
     - ICICI Direct: 5 holdings stored.
     - Zerodha: 0 holdings.
   - Motilal's sign-in fails on Motilal's own page (MO1001, per memory).
   - Both live sessions are now `expired`. Broker sessions end daily, so the owner must sign in again each day.
4. **Defect: the daily jobs run four times.**
   - Staging runs `uvicorn --workers 4`. `mf_scheduler.start()` is called in every worker (`backend/server.py:391-393`, `backend/services/mf_scheduler.py:280-284`) and nothing elects a single leader.
   - Result: the 17:30 IST broker sync (`mf_scheduler.py:260-277`, `:376`) runs about 4 times at once.
   - Evidence: `broker_sync_snapshots` holds 4 "daily" snapshots per account on 2026-10-27 and on 2026-10-28, all stamped within about 2 seconds of each other (12:00:00.486 / .502 / .526 / .767 UTC for Zerodha on 2026-10-28).
   - Each run deletes and re-inserts that account's holdings (`hub_reads.py:310-381`), so concurrent runs can race. Today the row count is still correct (5 = snapshot count).
   - The same applies to every other APScheduler job in that file.
5. **The import paths are inconsistent:**
   - Only the trading desk's Portfolio tab uses the preview/commit import (`tradingdesk/PortfolioImport.tsx`).
   - Settings, Get started and Broker connections post straight to `POST /api/portfolio/upload` with no preview (`screens/account/queries.ts:383`).
   - On staging, `holdings_import_previews` does not exist yet, so the preview has never been used there.

## 1. Onboarding — three routes into one portfolio model

### 1A. Broker API connect

**Backend**
- **Adapter registry:** `backend/services/brokers/registry.py`.
  - Required app secrets: lines 24-41.
  - `list_supported` (`implemented` / `configured` / `connectable`): lines 71-91.
  - Imports: lines 96-107.
- **Protocol:** `backend/services/brokers/base.py`.
  - `Holding` :31, `Position` :48, `Funds` :58.
  - `HubPosition` :106. It carries product, segment, `is_intraday`, FUT/CE/PE, expiry and strike.
- **Sign-in:** `backend/routes/broker_native.py`.
  - `GET /start/{slug}` :170, `GET|POST /callback/{slug}` :268/:289, short alias `/api/b/{alias}` :342/:348.
  - State lives in `broker_oauth_states` with a 10-minute TTL.
  - The callback encrypts the token, saves it and **syncs at once**.
- **Reads:** `backend/routes/broker_connect.py`:
  - `GET /accounts` :132;
  - `POST /accounts/{id}/sync` :145;
  - live `GET /accounts/{id}/holdings` :279 and `/holdings` :304;
  - `/funds` :353;
  - `/accounts/{id}/positions` :407 and `/positions` :485;
  - `/accounts/{id}/contract-chart` :437 (ICICI only);
  - `/accounts/{id}/snapshots` :540, `/snapshots/{id}` :557;
  - `DELETE /accounts/{id}` :568.
- **Read layer:** `backend/services/brokers/hub_reads.py`.
  - Fenix first, then the adapter, with no fallback between them.
  - Daily sync: `daily_sync` :836.

**Brokers by method and data**

| Broker | Method | Staging state | Holdings | Positions | Funds | Orders / trades / MF |
|---|---|---|---|---|---|---|
| Zerodha | Kite redirect (oauth) | connectable; connected live, 0 holdings, session expired | yes (Fenix) | net **and day** (Fenix), with contract details | yes | **none** (Kite `mf/holdings` not wired) |
| ICICI Direct | Breeze redirect, form-POST return | connectable; connected live, 5 holdings stored, expired | yes (ISIN given) | net (`fetch_hub_positions` :323), FUT/CE/PE + expiry + strike; symbol is ICICI's **stock_code**, not the NSE symbol | yes | none; contract chart and quote :451/:494 |
| Motilal Oswal | portal redirect | connectable, but the broker's page refuses (MO1001) | yes | net, with contract details (:394) | yes | none |
| Angel One | SmartAPI publisher redirect | implemented, **no keys** on staging | yes | net + hub positions (:267) | yes | none |
| Upstox / Fyers / AliceBlue | redirect | implemented, **no keys** | yes (Fenix) | net (Fenix); AliceBlue also day | yes | none |
| Dhan | user pastes a token (apikey) | "configured" (needs no secret) but not `connectable` (not oauth) | yes | net (Fenix) | yes | none |
| Groww | user pastes the day's token | configured, not connectable | yes | net + hub (:210) | yes | none |
| 5paisa | form (credential form) | implemented, not connectable | yes | net only, no contract details | yes | none |
| 11 stubs: Definedge, Flattrade, IIFL, IIFL Capital, INDmoney, Kotak Neo, m.Stock, Paytm Money, Samco, Shoonya, Tradejini | — | `IMPLEMENTED=False` (`_stub.py:69-79`) | — | — | — | — |

- Fenix 2.0.2 is installed in the staging image.
- 21 brokers are registered in all.
- **No adapter has an orders, trades, tradebook or history method.** A `git grep` for orderbook/tradebook/fetch_orders/fetch_trades in `services/brokers` finds nothing.

**Gaps in 1A**
- Orders, trades, history and MF holdings from brokers.
- Positions are not persisted, so they have no history and no as-of record.
- App keys are missing for Angel, Upstox, Fyers and AliceBlue (operations, plus the owner's keys).
- The Motilal sign-in is unresolved.
- Sessions are daily (the user signs in again each day).

### 1B. Statement upload (XLS/XLSX/CSV/CAS)

**Preview and commit:** `backend/routes/upload.py`.
- `POST /api/portfolio/upload/preview` :601 and `.../{id}/commit` :650.
- Limits and safety: 5 MB and 5,000 rows; magic bytes, malware scan, macro/ActiveX refusal and zip-bomb caps.
- Each row is flagged `ready` / `review` / `rejected`. The flag rules are in `assess_rows` :452:
  - **ISIN check digit:** `isin_check_digit_ok` :403.
  - **Symbol → ISIN:** looked up on the NSE list.
  - **Mismatches:** symbol/ISIN disagreement and unknown symbols.
  - **Duplicates and existing rows:** duplicate-in-file, held-by-connected-account (rejected), replaces-earlier-export, replaces-statement-row, already-on-file.
  - **Missing figures:** no cost, no price.
- The preview has a 30-minute TTL in `holdings_import_previews`.

**Layouts parsed:** `backend/helpers/statement_exports.py:66-101`.
- Equity: Zerodha (Console xlsx + Kite csv), Groww, Upstox, Angel, ICICI Direct, HDFC Sec, Kotak, Dhan, 5paisa.
- MF Central (mutual funds).
- A generic Name / Quantity / Buy Price sheet (`_GENERIC_COLUMNS` :109).

**F&O rows are rejected by design.** `_DERIVATIVE_RE` :365 matches them, and :496 flags them "unsupported_instrument … delivery holdings only".

**Frontend**
- The preview UI exists only in `screens/tradingdesk/PortfolioImport.tsx`, mounted in the desk's Portfolio tab.
- `screens/account/parts.tsx:280` and `queries.ts:383` (Settings, Get started, Brokers) use the direct `/api/portfolio/upload` with no preview.

**CAS**
- Direct CAS PDF upload is deprecated. The flow now is the casparser Connect SDK widget: `POST /api/casparser/access-token` :716, then `POST /api/portfolio/import-connect` :730.
- Gmail:
  - Routes: `backend/routes/gmail.py` — connect :52, status :176, history :206, scan :262, import :303, auto-import run/toggle :236/:247.
  - Monthly job: `services/gmail_auto_import.py`, on the 1st at 06:30 IST.
- Statement types: NSDL, CDSL, CAMS and KFin.
- **Snapshots:** each CAS upload writes an immutable snapshot (`services/cas_snapshot_engine.py`), and the user can switch to an older one (`routes/cas_snapshots.py:59-185`).
- **Transactions:** MF transactions and SIP detection go to `cas_transactions` (`services/cas_transactions.py`).
- **Cost basis:** an approximate cost for demat equities is rebuilt from successive snapshots (`services/cost_basis_from_snapshots.py`, `cost_basis_source` = snapshot_delta / unknown).
- On staging the CAS side looks like this:
  - 3 Gmail imports for 1 user, the latest on 2026-10-21;
  - `cas_transactions` is not present;
  - all 125 holdings have `cost_basis_source = None`.

**Gaps in 1B**
- **Templates:** there is no F&O positions template and no trade-history template. There are also no downloadable templates (no CSV/XLSX in `frontend-v5/public`; the "generic template" is column names in code only).
- **Preview coverage:** the Settings, Onboarding and Brokers uploads skip the preview.
- **Trade-history import:** there is none. CAS covers MF transactions only, and no tradebook import exists.

### 1C. Manual entry

**Backend.** These routes exist in `backend/routes/portfolio.py`:
- `POST /api/portfolio/holdings` :459. The `HoldingCreate` model (`backend/models.py:52`) takes name, ticker, asset_type, quantity, buy_price, current_price, sector, buy_date and portfolio_id.
- `PUT` :488 and `DELETE` :507.
- Instrument search: `GET /api/search/instruments` :56.

**Not built**
- No ISIN validation or master mapping on the manual path; the row is stored as typed, with `source` unset.
- **No UI to add a holding** in `/app` or in the v5 pages. A `git grep` finds no POST to `/api/portfolio/holdings`. The Ledger only *corrects* a row (PUT, in `portfolio/LedgerHoldings.tsx`).

## 2. The 4-step broker wizard

| Step | Exists | Gap |
|---|---|---|
| 1. Select broker (supported, method, scopes) | `GET /api/broker/native/supported` returns name, `auth_style`, implemented, configured, connectable. Hub UI: `screens/account/brokers.tsx` (Settings, Onboarding and Brokers all render it). Not-connectable brokers point to their file upload. | No per-broker statement of **data scopes** (which of holdings / positions / funds / orders it gives); the matrix above lives only in code. |
| 2. Authorize on the broker's page | Yes. Redirect only, never a password or OTP (`sessions.py` header; `brokers.tsx:7-10`); state TTL; read-only note shown. | none (Motilal and keys are operations work) |
| 3. Choose data to import | **No.** The callback syncs holdings at once (`broker_native.py:9-15`). Positions and funds are always read live. | Scope selection and a stored per-account consent are missing. |
| 4. Review and sync | Partly. After the commit the sync reply returns count, `duplicates` and `snapshot_id` (`broker_connect.py:224-237`). The account row carries `broker_user_masked`, `last_sync_at`, `last_sync_count` and `last_error`. | **No review before the commit.** Mapping issues (rows without ISIN, unknown symbol) and missing data (no price or cost) are not shown before writing; the CSV preview's flag logic is not reused. |

## 3. Two workspaces

**My Portfolio** exists as several screens:
- **Portfolio ledger** (`screens/Ledger.tsx`, nav `page/ledger`, `lib/views.ts:99`): health, totals, split by type, holdings, realised gains, statements, transactions and SIPs.
- **Portfolio analysis** (`screens/Analysis.tsx`, `tool/analysis`): Overview, Performance, Concentration and overlap, What to fix.
- Data: `GET /api/portfolio/holdings-enriched` (`routes/portfolio.py:73`) gives invested, value, P&L, weight, scores and action badges.
- The desk's Portfolio tab (`tradingdesk/PortfolioTab.tsx`) adds the sources line, scope, realised P&L, cash and the risk checks.

**Open Positions**
- Exists only as the broker block `screens/desk/BrokerPositions.tsx`, mounted in the Smart trading desk's Portfolio tab.
- Per account it shows live holdings, funds, and positions filtered All / F&O / Intraday. A FUT/CE/PE row names its contract and opens its chart.
- The comment in `screens/account/brokers.tsx:27` ("Not shown: open positions … no screen displays them yet") is out of date.

**Gaps**
- There is no dedicated Open Positions workspace.
- The portfolio headline has no "open positions" count tile.
- Desk paper trades and real broker positions are separate lists.

## 4. Charts for holdings

| Chart | Exists | Gap |
|---|---|---|
| Sector and instrument treemap | Only in the old v5 page `frontend-v5/src/components/charts/SectorTreemap.tsx`, used by `pages/Concentration/Concentration.tsx:54`. `/app` has a squarify treemap for the *market* (`screens/SectorHeatmap.tsx`, `heatmap/squarify.ts`), not for holdings. | Reuse the squarify code on the portfolio exposure data (S). |
| Holding weights | `weight_pct` in holdings-enriched; ShareBar (`portfolio/charts.tsx`) | — |
| Gain / loss bars | Gain/loss scatter from `/api/portfolio/analytics` (`PerformanceSection.tsx`); top gainers and losers in the Ledger | Bars specifically (S) |
| Equity curve vs Nifty | `/api/portfolio/value-history` (`routes/analytics.py:1409`) gives **CAS month-end statement values**, which include deposits and withdrawals. The `portfolio_snapshots` daily EOD series has 15 points on staging. The benchmark is the category or Nifty 500 (`PerformanceSection.tsx:19`). | No time-weighted curve and no Nifty 50 overlay (M) |
| Sector concentration | `GET /api/portfolio/exposure/concentration` (sector, company, AMC, group; look-through) in ConcentrationSection; desk risk check | — |
| Fundamental health scorecard | V3 quality/health/exit/add scores per holding in holdings-enriched (`services/portfolio_enrichment.py`). They are MF-centric; stock scores cover the scraped universe, and unscored stocks raise an alert (:425). | A per-stock fundamentals scorecard on the holding (M) |
| 20/50/200 DMA technicals | Not on holdings. Data exists: Postgres `stock_technical_features` has `sma_50`, `sma_200`, `rsi_14`, `atr_14`, breakout and support levels — **2,230 symbols, latest 2026-10-29** on staging. There is no `sma_20`. | Join holdings to it, and add the 20-DMA from OHLCV (S-M) |
| Hold / reduce / investigate evidence panel | Action badges EXIT / SWITCH / ADD / HOLD / REVIEW with a rationale (portfolio_enrichment); `holding_action_score.py` (MF HAS); Remediation section (`/api/portfolio/exposure/remediation`); Plan board | MF-centric; equity evidence (technicals, results, news) is not joined per holding (M) |
| Overlap matrix | `GET /api/portfolio/exposure/fund-overlap/matrix` (MF fund-to-fund, stock look-through) in ConcentrationSection; chat overlap widgets | No direct-stock-vs-fund overlap view (S-M) |
| Current vs target allocation | `portfolio/TargetMix.tsx`: asset class vs the risk-profile target (equity, debt, gold, cash) | No sector or stock targets; `allocation_policy.yaml` and `allocation_bands` exist but are not on this screen (S) |

## 5. Open positions analytics

**Equity positions.** BrokerPositions shows the entry price, quantity and the broker's P&L. HubPosition `pnl` is the broker's own figure and is not split into realised and unrealised.
- **Stop, target and trailing stop:** none. `BrokerPositions.tsx:25-26` and `:562-575` say no route returns them.
- **Trend and breakout-failure signals:** none on positions. `stock_technical_features` and the positional engine could feed them.

**F&O positions.** Rows carry FUT/CE/PE, expiry and strike, read live. The contract chart and quote come from ICICI only (`hub_reads.py:767-835`). These are missing:
- net position by **underlying** — `HubPosition` has no underlying field, and ICICI symbols are broker codes (SONBLW ≠ SONACOMS);
- grouping by expiry and strike;
- combined **payoff and breakeven**;
- **Greeks and IV**;
- margin per position — only the account-level `used_margin_rs` from `/api/broker/funds`;
- expiry-risk flags;
- scenario P&L;
- lot size on the position.

**Reusable building blocks:**
- `backend/services/option_pricing.py`: Black-76, `implied_vol` :198, `greeks` :229.
- `backend/services/strategy_plan/payoff.py`: payoff, breakevens, extremes, costs.
- `strategy_plan/pre_expiry.py`: position Greeks.
- `kite_live_feed/fno_quotes.py`: live quotes for named contracts through ReadOnlyKite REST.
- `nidp.fno_bhavcopy`: OI and settlement prices.

**Portfolio-wide.** The desk Portfolio tab already has, for **holdings**:
- 10 risk checks: beta, VaR, drawdown, concentration, correlation, gap risk, liquidity, volatility, missing data;
- cash via broker funds.

Missing:
- combined exposure that includes F&O (notional or delta);
- daily realised P&L (no broker day P&L route; `BrokerPositions.tsx:25`);
- risk-limit use against user limits on real positions (`services/risk_gate` covers paper trades only);
- stale-price, expiry and breach warnings on positions.

## 6. What the Copilot chat can reach

**Path.** `/api/chat/stream` (`routes/chat.py:1518`) routes to the `portfolio_analyst` node (`backend/nidp/services/copilot_agent/nodes/portfolio.py`). It calls `services/copilot_tools/portfolio.py`, which reads **stored `db.holdings` only** (`_load_holdings` :56).

**Tools available:**
- summary, XIRR, health score, top recommendations;
- rebalance plan :1637;
- concentration breakdown;
- tax harvest / full tax;
- `run_stress_test` :2064 — named scenarios, or a flat custom equity drop with debt at 10% of it; no beta and no F&O;
- FD comparison, fund comparison, overlap.

**Positions.** A question asked *from one broker position card* sends `position`. The chat then appends that contract's live facts (`_position_context` :152) and returns a contract-chart card (`_position_chart_widget` :243). It is single-position and ICICI-chart only.

**No tool reads:**
- the list of broker positions;
- funds;
- `stock_technical_features`;
- stops or targets.

| Owner's question | Today |
|---|---|
| Five holdings needing attention | Partly: recommendations, alerts and action badges (MF-centric) |
| Stocks below 50-DMA | **No** (the data exists in PG, but no tool reads it) |
| Biggest unrealised losses and why | Partly: P&L in the summary; no "why" evidence per stock |
| Sector overconcentration | **Yes** (`get_concentration_breakdown`) |
| All open F&O positions and their combined risk | **No** |
| Position closest to its stop | **No** (no stops) |
| Nifty −2% scenario | Partly: flat equity −2% on holdings; no beta, no F&O |
| Performance vs Nifty 50 | Partly: XIRR; the benchmark is category / Nifty 500 |
| Positions that hit target or broke their thesis | **No** for real holdings (desk paper trades have targets) |
| Reduce one sector | Partly: the rebalance plan is asset-class / MF-led |

## 7. Backend: ingestion → normalization → unified model → safeguards

**Ingestion.** Four routes exist:
- broker API: holdings stored, positions and funds read live;
- CSV/XLSX: preview, or direct;
- CAS: SDK widget, Gmail, monthly job;
- manual: API only.

There is also a standalone Postgres service, `backend/portfolio_ingestion/`, with a snapshot engine and `source_priority`. **It is not deployed on staging** (no such container).

**Normalization**
- **ISIN and symbol:**
  - `services/masterdata.py` is a local-CSV master (AMFI, bhav copy, NSE equity list, SGB). It does `lookup_isin` :316, fuzzy `find_isin_by_name` :359 and `enrich_broker_row` :407.
  - `helpers/holdings_reconcile.resolve_isin` and the NSE symbol index.
  - Broker sync fills name, price and sector by ISIN (`hub_reads.py:384`).
- **Quantities:** zero-quantity rows are dropped.
- **Cost basis:** the broker's average. For CAS demat it is the snapshot-delta estimate, flagged through `cost_basis_source`. `analytics.py:196-210` returns `cost_basis_estimated`.
- **Expiry and contract mapping:** **none.** Each adapter parses its own expiry and strike. There is no canonical contract key (underlying, expiry, strike, type), no lot size, and no mapping from broker codes to NSE.

**Duplicate detection** exists in three places:
- **Within a broker sync:** `repeated_in_broker_reply` and `same_instrument_lines`, keyed ISIN → exchange:symbol → ticker (`hub_reads.py:300-381`).
- **Across sources:** broker beats CAS, a new broker file replaces the old one (`_apply_broker_wins` :400; `helpers/holdings_reconcile.py`).
- **Same broker, second login:** `also_in_other_accounts` :418 (counted, not removed).

The CSV preview flags duplicates as listed in 1B. The desk shows instruments held in two sources (`/api/portfolio/composition/scope`, `routes/portfolio_composition.py:262`). The known limit is that two demat accounts at different brokers cannot be told apart (`holdings_reconcile.py` docstring).

**Unified model**
- **Holdings only:** `db.holdings`, with `source`, `broker`, `broker_account_id` and `isin` (only on broker rows; CAS keeps the ISIN in `ticker`).
- **Not modelled:** positions, orders and trades. The snapshot stores (next) record history, not a position model.

**Snapshots** are kept in three stores:
- `broker_sync_snapshots`: every sync, at most 90 per account (`sync_snapshots.py:26-27`), with masked identity and duplicate counters.
- `portfolio_snapshots`: a daily EOD summary plus the top 10, one per user per date (`services/portfolio_snapshot.py`; routes `routes/portfolio_snapshots.py`: `/snapshots`, `/trend`, `/compare`).
- CAS statement snapshots.

There is **no position snapshot**.

**Safeguards**

| Safeguard | Status |
|---|---|
| Separate entities (one row per account and lot) | yes |
| Broker's own as-of time kept | **no**. Rows carry Nivesh's `uploaded_at` / `last_sync_at`; live reads carry Nivesh's read time. |
| Average cost from transactions, estimates flagged | Partly. CAS-delta estimate only; broker rows take the broker's average. On staging all 125 rows have `cost_basis_source` unset. |
| Live / delayed / last-known prices distinguished | **Only on live reads** (`price_source` broker / masterdata, `hub_reads.py:498-570`). Stored rows have no price stamp: `price_updated_at` is set on 0 of 125 staging rows (`live_price.py:306` sets it in memory only). |
| No double counting | Broker-wins rule. The cross-broker limit is known and unsolved. |
| Secure tokens | Encrypted with `pii_security` (`sessions.py:38`, `:229-233`); `broker_user_key` is a sha256 hash; the client id is masked. |
| Per-user isolation | Every query filters on `user_id`. |
| Read-only | No order route; Fenix is used for reads only; ReadOnlyKite. |

## Staging data (aggregate only, 2026-10-30)

- **Users and holdings:**
  - 4 users in total; **1 user has holdings**.
  - 125 holdings rows: CAS 120 (60 MF, 53 equity, 6 ETF, 1 gold) and `broker_native` 5 (ICICI Direct, equity).
  - 55 rows have an `isin` field; 5 have no cost; 5 have no price; 0 have `buy_date`.
- **Broker connections:** 2, both native, both `status = expired`, both for the same user.
  - Zerodha: created 2026-10-13, last sync 2026-10-28 12:00 UTC.
  - ICICI Direct: created 2026-10-13, last sync 2026-10-28 12:00 UTC.
- **`broker_sync_snapshots`:** 32 in total.

  | Broker | Daily | Connect | Manual | First | Latest |
  |---|---|---|---|---|---|
  | ICICI Direct | 13 | 4 | 3 | 2026-10-14 | 2026-10-28 |
  | Zerodha | 8 | 3 | 1 | 2026-10-14 | 2026-10-28 |

  Daily snapshots come 3-4 per account per day because of the 4× scheduler defect in §0.
- **Positions:** **no positions collection exists.** Positions are never stored, so there is no stored timestamp. The only position-like collections are `desk_paper_trades` (3), `trade_plans` (639) and `ai_trader_strategies` (2), all paper or strategy, none from a broker.
- **Other collections:**
  - `portfolio_snapshots`: 17 (2 `cas_upload` 2026-10-13…21; 15 `eod_cron` 2026-10-14…29).
  - `holdings_import_previews`: absent (never used).
  - `cas_transactions`: absent.
  - `gmail_imports`: 3 completed.
  - `broker_oauth_states`: 32.

## Gap table

| Spec item | Exists (where) | Gap | Size |
|---|---|---|---|
| 1A Broker API connect | 10 adapters (`services/brokers/*`); redirect sign-in (`routes/broker_native.py`); holdings sync and live holdings, positions, funds (`routes/broker_connect.py:132-568`); Zerodha and ICICI live on staging | Orders, trades, history and MF holdings from brokers; Angel/Upstox/Fyers/AliceBlue keys; Motilal sign-in; daily re-login | M (orders/trades per broker) + operations |
| 1B Upload XLS/CSV/CAS | Preview + commit (`routes/upload.py:601/650`); 11 layouts (`helpers/statement_exports.py:66`); CAS via SDK + Gmail; preview UI in `tradingdesk/PortfolioImport.tsx` | F&O-positions and trade-history templates and parsers; downloadable templates; Settings/Onboarding/Brokers bypass the preview (`account/queries.ts:383`) | M |
| 1C Manual entry | `POST /api/portfolio/holdings` (`routes/portfolio.py:459`); `GET /api/search/instruments` :56 | UI form; ISIN/master validation on this path; positions entry | S |
| 2 Four-step wizard | Steps 1-2: `account/brokers.tsx`, `/native/supported`, redirect only | Step 3 data-scope selection and consent; step 4 review before commit (mapping issues, missing data); the sync currently commits on callback | M |
| 3 Two workspaces | My Portfolio = Ledger + Analysis (+ desk Portfolio tab); positions = `desk/BrokerPositions.tsx` inside the desk | A dedicated Open Positions workspace; open-position count on the portfolio headline; real and paper positions together | S-M |
| 4 Holdings charts | Weights, gain/loss scatter, sector concentration, MF overlap matrix, asset-class vs target, MF scores and badges | Portfolio treemap in /app (S); equity curve vs Nifty 50, TWR (M); DMA 20/50/200 on holdings (S-M, data in `stock_technical_features`); stock fundamental scorecard (M); equity evidence panel (M); stock-vs-fund overlap (S-M); sector/stock targets (S) | M overall |
| 5 Open-position analytics | Live position rows with FUT/CE/PE, expiry, strike; ICICI contract chart and quote; account margin used; holdings risk checks | Stop/target/trail store; trend and breakout signals; underlying mapping and net by underlying/expiry/strike; payoff and breakeven, Greeks and IV, scenario P&L (reuse `option_pricing.py`, `strategy_plan/payoff.py`, `fno_quotes.py`); per-position margin; expiry risk; combined F&O exposure; daily realised P&L; risk-limit use; stale/expiry/breach warnings | **L** |
| 6 Copilot questions | portfolio_analyst over stored holdings: concentration, stress (flat %), rebalance, XIRR, overlap, recommendations; single position card with live facts | Tools for broker positions, funds, DMA screen of holdings, stops and targets, beta-weighted Nifty scenario incl. F&O, Nifty 50 comparison, per-holding "why" evidence | M-L |
| 7a Ingestion and normalization | All four routes; ISIN master (`services/masterdata.py`), NSE symbol index, ISIN check digit; broker-wins | F&O contract normalization (canonical key, lot size, broker code→NSE); master is local CSVs | M |
| 7b Unified model and snapshots | `db.holdings`; `broker_sync_snapshots`; `portfolio_snapshots`; CAS snapshots | Positions, orders and trades entities; position snapshots; holdings `isin` on CAS rows (kept in `ticker`) | L |
| 7c Safeguards | Encrypted tokens, per-user, read-only, duplicate counters, `price_source` on live reads | Broker as-of time; price-freshness stamp on stored rows; transaction-based cost basis for broker rows; **scheduler leader lock (4× daily jobs, `server.py:391-393`)** | S (lock) + M |
