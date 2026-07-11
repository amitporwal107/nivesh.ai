# Live Retrieval Map — where every domain fact really lives

This is the expert's grounding index. **Do not answer from memory** — locate the anchor
here, Read/query it, and cite `file:line` or show the query output. Paths are under `/app`.
Verified against the codebase on 2026-07-11; if a path has moved, re-Grep and update this map.

> Ignore `/.deploy-dev/` and `/.deploy-main/` — deployment mirrors of `backend/`. Live source
> is `/app/backend/`.

---

## 0. How to pull LIVE data (sanctioned read surfaces)

- **App → NIDP market/MF/fundamental data → the DaaS API.** Runtime path:
  agent node → `backend/services/copilot_tools/*` → `backend/services/copilot_tools/daas_client.py`
  → **DaaS API** `backend/nidp/services/daas_api/` (`app.py`, `routers/`, `auth.py`,
  `dq_middleware.py`). Treat DaaS as the read surface, not direct DB.
  - Health: `curl -sf https://data.niveshcopilot.com/daas/health` and `/query/health`.
  - Read-only query API: `backend/nidp/services/query_api/`.
- **Governance / feed-status / validation → read-only `SELECT`** on the `nidp` schema.
  - Staging NIDP Postgres: `127.0.0.1:5434` db `nidp_staging` (via tunnel). App Postgres:
    `127.0.0.1:5532` db `nivesh`. Ask for the DSN/tunnel/DaaS key if you don't have it.
- **Connection helpers (which DB is which):**
  - `backend/services/pg_client.py` — app pool from `POSTGRES_URL` (db `nivesh`;
    `instrument_master`, `mutual_fund_metadata`, portfolios).
  - `backend/nidp/shared/storage/pg.py` — **separate** NIDP pool from `NIDP_POSTGRES_URL`
    (`search_path=nidp,public`).
  - `backend/nidp/shared/config.py` — NIDP env knobs, source URLs, archive paths.
  - `backend/deps.py` — FastAPI DI (`db`, `get_current_user`); `backend/helpers/secrets.py` — secrets.
- **NEVER** `INSERT/UPDATE/DELETE/DDL`; never write to prod; never fabricate output.

---

## 1. Market data feeds & sources
- **Canonical feed list (single source of truth):** `backend/nidp/shared/feed_registry.py`
  (`FEEDS`: name, cadence, monitored, `slo_hours`, severity, recoverable). Everything derives
  from this — start here to answer "what feeds do we have / what's its SLA".
- **Source URLs & fetch policy:** `backend/nidp/shared/config.py`;
  `backend/nidp/shared/sources/nse_fetcher.py`, `schema_contract.py`, `content_guard.py`.
- **Per-feed wire schema:** `backend/nidp/contracts/*.avsc` (bhavcopy, delivery,
  index_constituents, nse_financials, mf_nav_daily, corporate_actions, fii_dii, …).
- **Ingester framework:** `backend/nidp/shared/ingester_base.py` (fetch→parse→validate→write→archive).
- **Ingester services** (`service.py`+`parser.py`+`writer.py`+`validators.py`+`__main__.py`)
  under `backend/nidp/services/`: equity/market/macro — `bhavcopy/`, `fno_bhavcopy/`,
  `delivery/`, `index_constituents/`, `index_close/`, `nse_equity_master/`, `nse_financials/`,
  `nse_shareholding/`, `nse_pledge_data/`, `fii_dii/`, `bulk_deals/`, `block_deals/`,
  `corporate_actions/`, `corporate_announcements{,_nse,_bse}/`, `nse_calendar/`,
  `price_adjuster/`, `rbi_yields/`, `fred_macro/`, `intl_etf_prices/`; MF — `amfi_nav/`,
  `amfi_nav_history/`, `amfi_circulars/`, `mf_holdings/`, `mf_disclosure_snapshot/`; backfill —
  `yfinance_backfill/`, `nse_financials_backfill/`.
- **User-facing feed catalog (DB):** table `nidp.feeds` — migration
  `backend/nidp/migrations/032_nidp_feeds_subscriptions.sql` (+ `022`, `033`);
  human-readable: `docs/NIDP_FEEDS/`, `NIDP_Feeds_Catalogue_Staging.pdf`.
- **Feed RAG binding:** `backend/services/feed_rag/registry.py` (feed_id → retriever), plus
  `orchestrator.py`, `base.py`, `retrievers/{structured,text,vector}.py`.
- **Feed API/provenance:** `backend/routes/feeds.py`, `backend/routes/_nidp_feed_provenance.py`.

## 2. Data quality / governance
- **Feed status view:** `nidp.v_feed_status` (+ `v_feed_status_base`) —
  `backend/nidp/migrations/110_v_feed_status_dq.sql`. First stop for "is this feed fresh/OK".
- **Validation findings/runs:** `nidp.validation_findings`
  (`006_nidp_validation.sql`), `validation_runs` (`111_validation_runs_asset_and_dq_rollup.sql`);
  DQ-AI/gate schemas `040`, `043`, `077`.
- **Validation & DQ logic:** `backend/nidp/shared/validation/` (`runner.py`, `rules.py`,
  `quality_score.py`, `consistency.py`, `consistency_rules/{equity,mf}.py`);
  `backend/nidp/shared/expectations.py`; `backend/nidp/shared/dq/` (`gate.py`, `gate1_ingestion.py`,
  `gate3_snapshot.py`, `gate5_parquet.py`, `config/feeds/*.yaml`, `config/gates/*`);
  `backend/nidp/services/quality_gate/` (`dq_runner.py`, `dq_gate.py`, `dq_rules.py`,
  `great_expectations_runner.py`) — canonical DQ runner writing `validation_runs`;
  `backend/nidp/services/dq_ai/` (LLM-authored expectations); replay/failure-injection
  `backend/nidp/quality/replay/` (`engine.py`, `failure_injector.py`, `policy.py`).
- **Drift guardrail:** `backend/nidp/tests/test_feed_registry_drift.py` (registry ↔ cron ↔
  monitored ↔ backfill). **Trading calendar:** `backend/nidp/shared/trading_day.py` (last NSE
  close, reads `nidp.v_market_session`), `market_hours.py`, migrations `023`, `099`.
- **Health services:** `backend/nidp/services/feed_health_check/__main__.py` (freshness),
  `feed_reconciler/service.py` (heals missed days), `amc_urls_drift_check/service.py`;
  API `backend/routes/data_health.py`.

## 3. Fundamental analysis & financials
- **Statement parser:** `backend/nidp/services/nse_financials/parser.py` (+ `llm_extractor.py`,
  `ir_scraper.py`, `validators.py`, `writer.py`, `bank_npa_patch.py`, `backfill_screener*.py`).
- **TTM / ratio / valuation compute:** `backend/nidp/services/fundamental_engine/calculator.py`
  (+ `service.py`). **Basis is subtle — read the migrations before quoting a ratio:**
  `100_fix_fundamentals_ttm_single_basis.sql`, `101_backfill_q4_annual_contamination.sql`,
  `107_fix_screener_q4_pat_contamination.sql`, `108_fix_q4_contamination_definitive.sql`,
  `089_fix_revenue_3y_cagr_annual_source.sql`.
- **Schema/views:** `024_nidp_nse_financials.sql`, `068_nse_financials_raw_data.sql`,
  `048_nidp_fundamental_scores.sql`, `069_fix_v_stock_fundamentals_latest.sql`,
  `071_fix_view_roe_debt_equity.sql`, `090_screener_balance_cashflow.sql`,
  `091_current_ratio_cfo_pat_wiring.sql`; shareholding `025`, `109`; earnings est. `114`.
- **Models & agent tools:** `backend/models_financial.py`;
  `backend/services/copilot_tools/fundamental.py`, `company_financials.py`.
- **External fundamentals scrapers:** `backend/services/groww_fundamentals.py`,
  `groww_stock_scraper.py`, `tickertape_client.py`, `morningstar_stock_client.py`.
- **Fundamental-risk (PRA) engine:** `backend/nidp/services/pra_engine/`; `087_pra_schema.sql`,
  `092_pra_fundamental_risk.sql`.

## 4. Technical analysis & quant/stat models
- **Backtest (this branch):** `backend/services/copilot_tools/backtest.py`
  (`get_historical_backtest`: lump-sum CAGR + SIP XIRR from total-return series via DaaS);
  agent node `backend/nidp/services/copilot_agent/nodes/backtest.py`;
  `backend/services/strategy_engine/backtest.py`, `backtest_sql.py`;
  `backend/services/positional_engine/backtest.py`.
- **Strategy lab / universes:** `backend/services/strategy_engine/` (`dsl.py`,
  `compiler_stock.py`, `evaluator.py`, `market_data.py`, `templates/*.json`); routes
  `strategy_builder.py`, `screeners.py`, `benchmarks.py`; `user_universes`/strategy schema
  `020_strategy_builder_core.sql`, `105`, `115`, `117_seed_public_universes.sql`.
- **Indicators / features:** `backend/nidp/services/technical_indicator_engine/` (`calculator.py`,
  `accumulation.py`); `backend/services/copilot_tools/technical.py`;
  `backend/services/positional_engine/` (`feature_calculator.py`, `scorer.py`, `conviction.py`,
  `sector_strength.py`, `macro_overlay.py`); `feature_snapshotter/`, `stock_scorer_nidp.py`,
  `sector_scoring/`, `bank_scoring/`; migrations `021`, `029`, `053`, `054`, `055`, `026`.
- **Portfolio & goal math:** `backend/services/goal_engine.py` (GBIPE: FV/inflation, SIP sizing,
  Monte-Carlo, allocation profiles) + `goal_copilot.py`, `goal_fund_picker.py`;
  `portfolio_performance_engine.py`, `portfolio_concentration.py`, `portfolio_health.py`,
  `target_allocator.py`, `allocation_policy.py`.
- **v3 scoring stack:** `backend/services/v3_scoring.py`, `v3_weights.py`, `v3_integration.py`,
  `v3_explainer.py`, `v3_score_cache.py`; `backend/nidp/services/v3_scores_engine/service.py`;
  **`v3_scored_at`** written by `backend/services/nav_analytics_sweep.py`
  (`backend/migrations/005_v3_phase2b_sweep_log.sql`).

## 5. Mutual funds
- **Schema:** `mutual_fund_metadata` (app db `nivesh`) joined via
  `backend/services/buyable_universe.py`, `v3_integration.py`; populated by
  `backend/scripts/fetch_amfi_navs.py`. NIDP MF migrations: `034`, `049`, `050/058/083/098`
  (v3 MF primitives), `051`, `052/100/101` (category scorecard), `061_nidp_sebi_category_master.sql`,
  `073/074/078/080` (AMC source registry), `084/085` (category rank),
  `094_mf_analytics_gaps_r2_te_ir.sql`, `095_mf_rolling_returns.sql`, `096_mf_active_share.sql`,
  `097_mf_holdings_duration.sql`, `113`.
- **Scoring engines:** `backend/nidp/services/mf_analytics_engine/calculator.py`,
  `mf_category_ranking/{ranking,peer_set}.py` + `weights.yaml`, `mf_derived_refresh/`,
  `mf_disclosure_snapshot/`; app-side `backend/services/fund_performance.py`,
  `mf_category_enricher.py`, `nav_analytics.py`, `debt_scoring.py` (+
  `backend/config/debt_scoring_model.yaml`), `fund_clusterer.py`, `international_funds.py`.
- **MF agent tools/node:** `backend/services/copilot_tools/{mf,mf_cards,mf_intelligence,
  scheme_resolver,sip}.py`; `backend/nidp/services/copilot_agent/nodes/mf.py`.
- **MFD (distributor):** `backend/routes/mfd.py`, `backend/services/mfd_workspace.py`,
  `priority_engine.py`; routes `mf_data.py`, `funds.py`; `docs/MFD_Workflow_Automation_Specifications.md`.
- **CAS parsing/onboarding:** `backend/services/{cas_parser,hybrid_cas_parser,claude_cas_parser,
  nivesh_cas_normalizer,cas_snapshot_engine,cas_reconciler}.py`; routes `client_cas_invite.py`,
  `onboarding_gmail.py`, `upload.py`; docs `docs/CAS_STATEMENTS/`, `docs/ONBOARDING_STRATEGY.md`.

## 6. Copilot / agent layer
- **Graph:** `backend/nidp/services/copilot_agent/graph.py` —
  `intent → {market, stock, mf, portfolio, risk, goal, recommendation, backtest} → compliance → END`.
- **Nodes:** `backend/nidp/services/copilot_agent/nodes/` (`intent.py`+`intent_patterns.py`,
  `market.py`, `stock.py`, `mf.py`, `portfolio.py`, `risk.py`, `goal.py`, `recommendation.py`,
  `backtest.py`, `compliance.py`); `schemas.py` (`CopilotState`, `AgentResponse`),
  `_llm.py` (anti-hallucination + model config), `persona_framing.py`, `tools/daas_bridge.py`.
- **App tools:** `backend/services/copilot_tools/` — `daas_client.py` (primary retrieval),
  plus the per-domain tools above; `widget_builders.py`.
- **Chat entry & advisor/investor routing:** `backend/routes/chat.py` (`get_graph()` +
  `load_persona_context()`); `backend/routes/copilot.py` (`_is_advisor_caller`,
  `_ADVISOR_BOOK_INTENT_RE` — advisor book-summary vs investor LangGraph engine);
  `backend/services/copilot_rag/` (`orchestrator.py`, `intent_router.py`).
- Docs: `docs/FRD_COPILOT_V2.md`, `docs/COPILOT_PROMPT_CATALOG.md`, `docs/COPILOT_QA_COVERAGE_MATRIX.md`.

## 7. Compliance / SEBI / regulatory
- **The real guard (align to it, don't reinvent):**
  `backend/nidp/services/copilot_agent/nodes/compliance.py` — final graph node: injects the
  mandatory SEBI disclaimer, a numeric-grounding hallucination guard, and a length cap.
- **Risk profiling & suitability:** `backend/services/risk_profile_chat.py` (produces the
  `risk_profile` used for suitability); `backend/nidp/services/copilot_agent/nodes/risk.py` +
  `backend/services/copilot_tools/risk.py` (suitability, VaR, stress); routes
  `portfolio_risk_analytics.py`, `advisor_v4.py`, `recommendations.py`.
- **Data protection (DPDP Act 2023):** `backend/routes/compliance.py` (consents, audit trail,
  PAN encrypt/erase, export, right-to-erasure); `backend/services/consents.py`, `audit.py`,
  `pii_security.py`, `llm_safety.py`, `malware_scanner.py`.
- **SEBI MF category master:** `nidp` — `061_nidp_sebi_category_master.sql`.
- Docs: `docs/SECURITY_PRD.md`, `docs/Nivesh_Rule_Book_Elaborated.docx`,
  `docs/Nivesh_Selection_Framework.md`, `docs/prd/`.

## 8. Canonical docs (read the owner of the fact)
`docs/DATABASE_SCHEMA.md` (schema) · `docs/TECHNICAL_ARCHITECTURE.md` (architecture) ·
`docs/API_DOCUMENTATION.md` (APIs) · `docs/DEVOPS_ENVIRONMENTS.md` (envs + connection targets) ·
`docs/SCHEMA_DIAGRAM.md` · `docs/FRD_NIDP_PROJECT.md` · `docs/NIDP_STATUS.md` ·
`HANDOFF-FEED-RELIABILITY.md`. Code + migrations beat docs when they disagree — trust the
running system and note the doc drift.
