# Nivesh + NIDP — Schema Diagram

Two databases underpin the system:

| Database | Engine | Purpose |
|---|---|---|
| **NIDP TimescaleDB** | PostgreSQL 16 + TimescaleDB | Market intelligence, features, portfolio sync |
| **Nivesh MongoDB** | MongoDB 7 | User state, portfolios, AI, chat, admin |

---

## 1. NIDP TimescaleDB (nidp-stack-vm :5433)

Schemas: `nidp` `public` `ref` `dq` `features` `graph` `events` `analytics` `audit` `portfolio`

```
NIDP TimescaleDB
│
├── [001] CORE INFRA (nidp schema)
│   ├── nidp.schema_migrations      Migration tracking (filename, applied_at)
│   ├── nidp.job_log                Per-run ingester logs (run_id, ingester, status, rows, duration)
│   ├── nidp.raw_archive_files      Raw downloaded bytes metadata (CSV/XLS, sha256, gcs uri)
│   ├── nidp.source_registry        Data source catalog (reliability score, schedule_cron, run counters)
│   └── nidp.daily_snapshot         Daily AS-OF coherence record (per-date ingestion gate)
│
├── [002] MARKET DATA (nidp schema — hypertables)
│   ├── nidp.prices_eod             EOD OHLCV per (symbol, date, series) — NSE bhavcopy
│   ├── nidp.delivery_data          Delivery % per (symbol, date) — T+1 lag from NSE
│   ├── nidp.index_eod              Index OHLC + PE/PB/Div Yield per (index_name, date)
│   └── nidp.index_constituents     Effective-dated index membership (symbol, index, from→to)
│
├── [003] FLOWS & CORPORATE EVENTS
│   ├── nidp.fii_dii_flows          FII/DII net buy/sell per (category, segment, date)
│   ├── nidp.corporate_actions      Splits, bonus, dividends, rights per (symbol, ex_date)
│   ├── nidp.bulk_deals             NSE bulk deals (client, broker, qty, price, date)
│   └── nidp.block_deals            NSE block deals (same schema as bulk_deals)
│
├── [004] MACRO & CALENDAR
│   ├── nidp.rbi_yields             G-Sec yields (overnight, 91D, 1Y, 5Y, 10Y) per date
│   └── nidp.nse_holidays           Trading holiday calendar (date, segment: CM/FO/CD)
│
├── [005] TIMESCALE HYPERTABLES
│   └── (ALTER existing tables → TimescaleDB hypertables, no new tables)
│
├── [006] VALIDATION & VIEWS
│   ├── nidp.validation_runs        Per-ingester validation run log
│   ├── nidp.validation_findings    Failed rules (rule_name, severity, sample rows, actual value)
│   └── VIEW nidp.v_latest_validation
│
├── [006b] WAREHOUSE VIEWS
│   └── VIEWs: v_nifty500_members, v_nifty500_prices_eod, v_nifty500_latest_close,
│             v_nifty500_delivery, v_nifty500_corporate_actions, v_warehouse_coverage
│
├── [007] DAILY SNAPSHOTS
│   ├── nidp.market_daily_snapshot  Market-level daily roll-up (Nifty, FII/DII, RBI, breadth)
│   └── nidp.stock_daily_snapshot   Per-stock daily snapshot (OHLCV, delivery, index, events)
│
├── [008] MACRO — FRED
│   └── nidp.fred_macro             Global macro (DGS10, VIX, DXY, Brent, Gold, FEDFUNDS) per date
│
├── [020] STRATEGY BUILDER (public schema)
│   ├── strategies                  User strategy definitions (DSL, backtest config)
│   ├── strategy_versions           Immutable version history
│   ├── user_universes              User-defined symbol/scheme lists
│   ├── strategy_runs               Backtest / live run records
│   ├── strategy_trades             Entry/exit trade log
│   ├── strategy_signals            ENTRY/EXIT/WATCH signals from live runs
│   ├── strategy_alerts             Notification subscriptions (email/Telegram/webhook)
│   └── strategy_audit              CREATE/UPDATE/ARCHIVE event log
│
├── [021] STOCK FEATURES (nidp schema)
│   └── nidp.stock_features_daily   Daily technical features per symbol:
│                                   SMA20/50/200, RSI, MACD, volume z-score,
│                                   accumulation score, delivery trend
│
├── [022] FEED MANAGEMENT
│   ├── nidp.parsed_archive_files   Normalized parsed-row archive (gzipped JSONL on GCS, metadata)
│   ├── nidp.feed_snapshot          Per-(ingester, snapshot_date) parsed rows as JSONB
│   └── VIEW nidp.v_feed_status     Ops dashboard — one row per feed
│
├── [023] MARKET SESSION
│   ├── nidp.market_session_state   Last closed trading day per market (NSE_EQ)
│   └── VIEW nidp.v_market_session  Stored value + 24h stale-fallback to SQL function
│
├── [024] NSE FINANCIALS
│   ├── nidp.nse_financials_quarterly  Quarterly P&L, balance sheet, per-share (revenue, EBITDA,
│   │                                  PAT, EPS, equity, debt, cash) per (symbol, period)
│   └── VIEW nidp.v_stock_fundamentals_latest  Latest quarter + TTM/YoY/ROE/debt_to_equity
│
├── [025] SHAREHOLDING PATTERN
│   ├── nidp.shareholding_pattern   Quarterly promoter/FII/DII/MF/individual/NRI %,
│   │                               pledge ratio per (symbol, period)
│   └── VIEW nidp.v_shareholding_latest  Latest quarter + QoQ deltas
│
├── [026] PRICE ADJUSTMENTS
│   └── nidp.prices_eod_adjusted    Adjusted close + total-return adjusted (splits/bonus/dividend),
│                                   cumulative adjustment factors per (symbol, date)
│
├── [027] SECTOR MASTER
│   └── nidp.sector_master          NSE equity master (symbol, ISIN, listing_date, sector, industry)
│
├── [028] F&O BHAVCOPY
│   ├── nidp.fno_bhavcopy           F&O OHLC, open interest, volume per
│   │                               (trading_day, instrument, ticker, expiry, strike, opt_type)
│   └── VIEW nidp.v_options_chain_latest
│
├── [029] STOCK FEATURES EXTENDED
│   └── EXTENDS nidp.stock_features_daily with:
│       PE_TTM, PB, ROE, debt_to_equity, revenue/PAT/EPS growth YoY,
│       promoter_pct, FII/DII/MF %, pledge %, PCR, OI
│
├── [030] CORPORATE ANNOUNCEMENTS
│   ├── nidp.corporate_announcements  Real-time NSE/BSE filings (subject, category, impact,
│   │                                 sentiment, attachment_url) per (symbol, broadcast_date)
│   └── VIEWs: v_announcements_recent, v_announcements_high_impact_today
│
├── [031] DOCUMENTS (pgvector)
│   ├── nidp.documents              Parsed PDFs (announcement attachments, annual reports,
│   │                               concall transcripts) — full text stored
│   └── nidp.document_chunks        Text chunks with 384-dim pgvector embeddings
│                                   (bge-small-en-v1.5)
│
├── [032] FEEDS & SUBSCRIPTIONS
│   ├── nidp.feeds                  Feed catalog (retrieval_kind, tier: free/pro/institutional)
│   └── nidp.user_feed_subscriptions  User subscription + filter params per feed
│
├── [033] PHASE 1B INGESTER REGISTRY
│   └── (seeds source_registry rows for NSE_FINANCIALS, NSE_SHAREHOLDING, NSE_EQUITY_MASTER,
│         NSE_FNO_BHAVCOPY, NSE_CORP_ANNOUNCEMENTS_NSE/BSE, ANNOUNCEMENT_CLASSIFIER, DOC_PARSER)
│
├── [034] MUTUAL FUNDS
│   ├── nidp.mf_amc_master          AMC master (top-N AMCs, AUM, registrar)
│   ├── nidp.mf_scheme_master       AMFI scheme code → name/category/ISIN/launch/benchmark
│   ├── nidp.mf_nav_daily           Daily NAV time series per scheme_code (hypertable)
│   ├── nidp.mf_holdings_monthly    Monthly portfolio holdings (top-10 stocks per scheme, M+10)
│   ├── nidp.mf_amfi_circulars      AMFI notices/circulars/addenda
│   ├── nidp.mf_scheme_disclosure_snapshot  Weekly TER/risk-o-meter/manager/AUM snapshot
│   ├── nidp.mf_scheme_events       Derived events (TER change, manager change, merger, rename)
│   └── nidp.mf_benchmark_master    Scheme → benchmark index mapping
│
├── [035] DaaS API
│   ├── nidp.daas_api_keys          API key registry (key_hash, plan, rate_limit_rpm, quota)
│   ├── nidp.daas_daily_usage       Per-day request counter (quota enforcement)
│   ├── nidp.daas_usage_log         Append-only request log (method, path, status, latency)
│   └── VIEW nidp.v_daas_key_status
│
├── [036] CORPORATE EVENT CALENDAR
│   ├── nidp.event_calendar         Upcoming results, board meetings, AGMs, dividends,
│   │                               bonus, buyback, rights, splits
│   ├── nidp.corporate_event_signals  AI event analysis (sentiment, confidence, estimated
│   │                                 move %, factors, risks, historical comparison)
│   └── nidp.company_ir_urls        Nifty 50+ IR page URLs
│
├── [037] FEATURE FLAGS
│   └── nidp.feature_flags          Runtime toggles (event_processing, d1_prep, etc.)
│
├── [038] INTELLIGENCE ALERTS
│   └── nidp.intelligence_alerts    Outbound notification log (Telegram, email)
│
├── [039] EVENT CALENDAR DEDUP FIX
│   └── (no new tables — fixes NULL-period UNIQUE constraint on nidp.event_calendar)
│
├── [040] CONSISTENCY & QUALITY
│   ├── nidp.consistency_runs       Cross-source consistency check runs
│   ├── nidp.consistency_findings   Per-field mismatch findings (source_a/b, deviation_pct)
│   ├── nidp.quality_scores         Quality score time-series (accuracy/consistency/completeness/
│   │                               freshness/auditability) → PLATINUM/GOLD/SILVER/REVIEW
│   ├── nidp.certified_dates        Published certified dates
│   ├── nidp.exception_queue        QualityGate outcomes requiring manual review
│   └── nidp.quarantine_log         Condemned runs audit
│
├── [041] CORE INTELLIGENCE LAYER (multi-schema)
│   ├── ref.security_master         Canonical security master (EQUITY/MF_SCHEME/INDEX/MACRO_SERIES)
│   ├── dq.validation_runs          Data quality validation runs
│   ├── dq.failed_rows              Failed DQ rows
│   ├── dq.quality_scores           Numeric quality scores per source/date
│   ├── features.stock_features_daily  Feature store (technical + fundamental daily)
│   ├── graph.correlations          Pearson correlations (STOCK_STOCK/STOCK_INDEX/STOCK_MACRO/FUND_STOCK)
│   ├── graph.entity_links          Ownership graph (FUND_HOLDS_STOCK/STOCK_IN_INDEX/SECTOR)
│   ├── events.normalized_events    Normalized events (DIVIDEND/SPLIT/EARNINGS/MGMT_CHANGE)
│   ├── analytics.market_snapshot   Daily market summary (breadth, FII/DII, VIX, Nifty, regime)
│   └── VIEW events.v_search_documents  Full-text search substrate
│
├── [042] PORTFOLIO BRIDGE (portfolio schema)
│   ├── portfolio.user_holdings_snapshot   Raw holdings per (user, date, isin/symbol)
│   ├── portfolio.holding_security_map     Holding → ref.security_master resolution
│   └── portfolio.user_intelligence_snapshot  User portfolio intelligence per date:
│                                              sector concentration, correlation pairs,
│                                              quality_tier, beta, RSI
│
├── [043] DQ AI
│   ├── dq.smell_diagnostics        AI-assisted smell analysis (root causes, suggested fixes)
│   ├── dq.expectations_active      Active validation rule registry
│   └── dq.expectation_proposals    AI-proposed rules pending human review
│
├── [044] REPLAY ENGINE (audit schema)
│   ├── audit.policy_versions       Stored scoring policy (weights, thresholds)
│   ├── audit.replay_runs           Historical replay invocations
│   ├── audit.replay_dates          Per (replay, date, domain) outcome
│   ├── audit.replay_statistics     Aggregate roll-up per replay
│   └── audit.replay_failures       Synthetic defect injection log
│
├── [045] BACKFILL
│   ├── audit.backfill_runs         Backfill orchestrator runs (date range, ingesters)
│   └── audit.backfill_jobs         Per (backfill_id, date, ingester) job records
│
├── [046] PORTFOLIO SYNC LOG ← written by portfolio_holdings_sync
│   ├── portfolio.client_master     Canonical client registry (email PK, Nivesh client_id,
│   │                               last_sync_at)
│   └── portfolio.sync_audit_log    Per-(user, snapshot_date, sync_run_id) result:
│                                   status SUCCESS/SKIPPED/ERROR, holdings_upserted,
│                                   portfolio_hash (dedup)
│
├── [047] PERFORMANCE LAYER (analytics schema)
│   ├── analytics.stock_card        Precomputed per-(symbol, date) dashboard row
│   │                               (OHLCV, technical ranks, momentum, corporate events)
│   ├── analytics.sector_snapshot   Per-(sector, date) aggregate (advances/declines, median RSI)
│   ├── analytics.fund_category_rank  Per-(scheme_code, rank_date) category leaderboard
│   │                                 (returns 1y/3y/5y, Sharpe, rank)
│   └── MATERIALIZEd VIEWs: mv_top_momentum, mv_delivery_surge,
│                            mv_sector_heatmap, mv_fund_category_top10
│
├── [048] FUNDAMENTAL SCORES
│   └── EXTENDS nidp.stock_features_daily with:
│       piotroski_score (0-9), piotroski_signals, altman_z_score,
│       valuation_signal, sector_median_pe
│
├── [049] MF ANALYTICS EXTEND
│   └── EXTENDS analytics.fund_category_rank with:
│       return_1m/3m/6m/2y, return_since_launch_cagr, sortino_1y,
│       alpha_1y, beta_1y, scheme_launch_date, nav_count, sortino_rank
│
├── [050] V3 MF PRIMITIVES VIEW
│   └── VIEW nidp.v_v3_mf_primitives   Bridge: NIDP → V3 scoring engine
│                                       (joins mf_scheme_master + fund_category_rank +
│                                        mf_scheme_disclosure_snapshot + mf_scheme_events
│                                        + mf_holdings_monthly)
│
├── [051] MF DERIVED ANALYTICS
│   ├── nidp.mf_derived_analytics   Computed per scheme: consistency_score,
│   │                               downside_capture_pct, aum_trend_score,
│   │                               portfolio_turnover_pct, credit_quality_score,
│   │                               duration_risk_score
│   └── VIEW nidp.v_v3_mf_primitives (updated to use mf_derived_analytics)
│
├── [052] MF CATEGORY SCORECARD
│   └── VIEW nidp.v_mf_category_scorecard
│
├── [053] STOCK DERIVED METRICS
│   └── EXTENDS features / analytics layer with derived stock scoring functions
│
├── [054] V3 STOCK SIGNALS
│   └── Functions/views for stock signal generation (buy/hold/sell signals)
│
└── [055] V3 STOCK PRIMITIVES VIEW
    └── VIEW nidp.v_v3_stock_primitives   Bridge: NIDP → V3 stock scoring engine
                                          (ROE, debt_to_equity, EPS growth 3Y CAGR,
                                           cap_bucket, max_drawdown, momentum_score)
```

---

## 2. Nivesh MongoDB (nivesh-app-vm)

```
Nivesh MongoDB (nivesh_prod)
│
├── AUTH & IDENTITY
│   ├── users                   User record (user_id, email, name, is_admin, onboarding_completed)
│   ├── whitelisted_users       Email whitelist with admin flags
│   ├── user_profiles           Extended profile (risk_profile, goals, journey_type,
│   │                           selected_sources, playbook)
│   └── user_sessions           Active session tokens (session_token, user_id, expires_at)
│
├── PORTFOLIO & CAS
│   ├── holdings                Individual holdings (user_id, name, ticker, asset_type,
│   │                           quantity, buy_price, current_price, isin, nse_symbol)
│   │                           ← SOURCE OF TRUTH for GCS export → NIDP
│   ├── portfolio_snapshots     Portfolio snapshot summary (total_value, total_invested,
│   │                           allocation, health_score, return_pct, top_holdings)
│   ├── cas_parsed_responses    Raw parsed CAS API responses (per upload)
│   ├── cas_transactions        CAS transaction records (per fund, per date)
│   └── upload_tasks            CAS file upload task tracking
│
├── MUTUAL FUND METADATA (Nivesh side)
│   ├── fund_performance_cache  MF performance metrics (returns, ratios) — short TTL cache
│   ├── international_funds_cache  International MF data cache
│   └── detected_sips           Detected SIP patterns per (user, scheme)
│
├── ANALYTICS & AI
│   ├── portfolio_analysis      Portfolio analysis results (per user, per snapshot)
│   ├── ai_insights             AI-generated insights (per user, per topic)
│   ├── allocation_analysis_cache  Asset allocation analysis results
│   └── stock_fundamentals_cache   Stock fundamental metrics — short TTL cache
│
├── CHAT & COPILOT
│   ├── chat_sessions           Chat session metadata (session_id, user_id, created_at)
│   ├── chat_messages           Chat message history (role, content, session_id, timestamp)
│   └── copilot_cache           Copilot response cache (keyed by prompt hash)
│
├── GOALS & ACTION PLANS
│   ├── action_plans            Action plan records (rebalance/buy/sell recommendations)
│   ├── target_allocations      User target allocation (equity/debt/gold splits)
│   ├── saved_scenarios         User-saved scenario analyses (what-if)
│   └── scenario_simulations    Scenario simulation results
│
├── CAPITAL GAINS
│   └── capital_gains_summary   Tax-lot capital gains summary (per user, per FY)
│
├── BROKER INTEGRATION
│   ├── broker_accounts         Connected broker accounts (OpenAlgo, Zerodha, etc.)
│   ├── broker_oauth_states     OAuth state tokens for broker flows
│   └── openalgo_instances      OpenAlgo instance registry (user_id, host, api_key)
│
├── GMAIL INTEGRATION
│   ├── gmail_imports           Gmail transaction import history (per user)
│   ├── gmail_tokens            Gmail OAuth tokens (access_token, refresh_token)
│   └── gmail_oauth_states      Gmail OAuth state records (per flow)
│
├── MFD (Multi-Family Dashboard)
│   ├── workspaces              Workspace/team records
│   └── mfd_client_notes        Notes per MFD client
│
└── ADMIN & SYSTEM
    ├── system_config           System configuration (feature_flags, secrets, CAS keys)
    ├── audit_log               System audit log (admin actions)
    └── consent_records         User consent records (T&C versions)
```

---

## 3. Data Flow Summary

```
                    ┌─────────────────────────────┐
                    │      User (Browser)          │
                    └───────────┬─────────────────┘
                                │
                    ┌───────────▼─────────────────┐
                    │   Nivesh Backend (FastAPI)   │
                    │   nivesh-app-vm :8001         │
                    └──┬──────────────┬────────────┘
                       │              │
           ┌───────────▼──┐    ┌──────▼──────────────┐
           │   MongoDB    │    │  Nivesh PostgreSQL   │
           │  (user state,│    │  (portfolio_snapshot │
           │  chat, AI,   │    │   master, holdings,  │
           │  holdings ←  │    │   instrument_master) │
           │  SOURCE)     │    └──────────────────────┘
           └───────┬──────┘
                   │
           ┌───────▼────────────────┐
           │  portfolio_gcs_export  │ (triggered after CAS import)
           │  MongoDB → JSONL       │
           └───────┬────────────────┘
                   │
           ┌───────▼────────────────────────────────────┐
           │  GCS: gs://nidp-raw-niveshdataintelligence  │
           │  portfolio/holdings/{date}/holdings.jsonl    │
           │  portfolio/holdings/latest.json              │
           └───────┬────────────────────────────────────┘
                   │
           ┌───────▼────────────────────────────────────┐
           │   NIDP portfolio_holdings_sync              │
           │   (runs on nidp-stack-vm)                   │
           └───────┬────────────────────────────────────┘
                   │
           ┌───────▼────────────────────────────────────┐
           │   NIDP TimescaleDB (nidp-stack-vm :5433)    │
           │   portfolio.client_master                    │
           │   portfolio.user_holdings_snapshot           │
           │   portfolio.sync_audit_log                   │
           │           ↓                                  │
           │   portfolio_intelligence_sync                │
           │           ↓                                  │
           │   portfolio.user_intelligence_snapshot       │
           └────────────────────────────────────────────┘
```

---

## 4. Migration Consistency Status (as of 2026-05-16)

| Migration | Applied on VM | Notes |
|---|---|---|
| 001–021 | ✅ | Fully applied |
| 022 | ✅ | Feed management — applied 2026-05-16 |
| 023 | ✅ | Market session state — applied 2026-05-16 |
| 024–038 | ✅ | Fully applied |
| 039 | ✅ | Event calendar dedup fix — applied 2026-05-16 |
| 040–055 | ✅ | Fully applied |

All 42 migrations on disk are applied. Zero gaps, zero orphans (verified 2026-05-16).

### Note on 050/051 views
Migrations 050/051 create **views** that join `instrument_master` and `mutual_fund_metadata`. These tables are populated by the NSE equity master ingester and MF analytics engine at runtime — they are empty on a fresh VM before those ingesters have run. `CREATE OR REPLACE VIEW` succeeds at migration time; queries on the view work once ingesters populate the underlying tables.
