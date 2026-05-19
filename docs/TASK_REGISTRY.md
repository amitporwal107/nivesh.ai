# TASK_REGISTRY.md
## Nivesh AI Copilot — Full Task Registry

> **STATUS KEY**: ✅ DONE | ⏭ SKIP | 🔨 BUILD | 🔄 MODIFY

---

## EPIC 1: Foundation & Infrastructure

### TASK-001 — Repo & monorepo scaffold ✅ DONE
Existing `/app/backend/` structure, routes, services, NIDP pipeline all in place.

### TASK-002 — CI/CD pipeline ⏭ SKIP
GCP Cloud Build configs exist (`cloudbuild-daas.yaml`, `cloudbuild-service.yaml`). Disabled intentionally. Re-enable later.

### TASK-003 — FastAPI app setup ✅ DONE
`backend/` FastAPI app with middleware, CORS, auth, error handlers fully operational.

### TASK-004 — PostgreSQL async setup ✅ DONE
Two live PostgreSQL instances on `nidp-stack-vm`:
- App DB (port 5432): `nivesh_dev` — migrations 001–020 applied
- NIDP DB (port 5433, TimescaleDB): `nidp` — migrations 001–047 applied

### TASK-005 — Redis setup ✅ DONE
`nidp-redis` running on VM port 6380. `services/redis_client.py` exists.

### TASK-006 — NIDP DAAS API client SDK ✅ DONE
The NIDP DAAS API **IS** the SDK. Already deployed at Cloud Run + running locally on VM:8083.
- 20 routers: prices, mf, financials, features, intelligence, flows, macro, snapshots, announcements, etc.
- Auth (X-API-Key), rate limiting, pagination all in place.
- **Copilot agents call DAAS endpoints directly** — no separate Python SDK needed.
- Existing `services/nidp_query_client.py` and `services/nidp_vm_query.py` are thin wrappers.

### TASK-007 — Primitive store ✅ DONE (table exists, needs data)
`nidp.stock_features_daily` on VM has 58 columns including all technical indicators.
Schema: `(symbol, as_of_date, source)` PK + close, sma20/50/100/200, rsi14, macd, atr14, bb_width/pos, returns, volume metrics, fundamentals.
Currently **0 rows** — populated by TASK-011 (technical indicator engine).

### TASK-008 — Langfuse observability ⏭ DEFER
Wire after core agent loop works.

### TASK-009 — Alembic migration management ✅ DONE
47 NIDP migrations + 20 app migrations applied and tracked in `nidp.schema_migrations`.

### TASK-010 — Shared Pydantic schemas 🔨 BUILD
`AgentResponse`, `ToolResult`, `ChatMessage` schemas needed for LangGraph agents.
**Target**: `backend/nidp/services/copilot_agent/schemas.py`

---

## EPIC 2: Technical Analytics Engine (Option B — Parallel Service)

> **Architecture decision**: Build a standalone `technical_indicator_engine` service that reads from
> `nidp.prices_eod` (3,425 symbols, up to 2026-05-11) and writes to `nidp.stock_features_daily`.
> The DAAS API `/v1/features/stocks/{symbol}/latest` then serves this data to copilot agents.
> No separate analytics microservice — DAAS is the read layer.

### TASK-011 — Technical indicator engine: calculator ✅ DONE → see implementation
**Target**: `backend/nidp/services/technical_indicator_engine/calculator.py`
Pure numpy implementations:
- SMA (20, 50, 100, 200) + SMA50 slope
- EMA (12, 26, 9 for MACD)
- RSI-14 (Wilder's smoothing)
- MACD line + signal + histogram
- ATR-14 + ATR%
- Bollinger Bands (20, 2σ) — width and position
- Returns (5d, 20d, 60d)
- Volume: avg_20, vol_z20
- Delivery: avg_20, linear trend slope
- Swing high/low (20-period), pivot breakout flag
- 52w high/low distances, distance from 200DMA

### TASK-012 — Technical indicator engine: service + backfill ✅ DONE → see implementation
**Target**: `backend/nidp/services/technical_indicator_engine/service.py`
- Bulk fetches all price history from `nidp.prices_eod` in one query per symbol batch
- Processes 3,425 symbols concurrently (batch of 100)
- Upserts to `nidp.stock_features_daily` with `source='COPILOT_TI_ENGINE'`
- Supports: single-date compute, date-range backfill, full history backfill

### TASK-013 — Technical indicator engine: CLI + deployment ✅ DONE → see implementation
**Target**: `backend/nidp/services/technical_indicator_engine/__main__.py`
- `--date YYYY-MM-DD` (default: yesterday)
- `--backfill-days N` (backfill last N trading days)
- `--symbols RELIANCE,TCS` (default: all EQ series)
- Deployed as Cloud Run Job `nidp-technical-indicators`

### TASK-014 — Verify backfill populated stock_features_daily ✅ DONE
Confirmed: 3,425 symbols × N dates in `nidp.stock_features_daily`.
DAAS `/v1/features/stocks/RELIANCE/latest` returns RSI, MACD, SMA values.

### TASK-015 — Technical DAAS tool wrapper for copilot agents ✅ DONE
**Target**: `backend/nidp/services/copilot_agent/tools/technical_tools.py`
```python
@tool async def get_technical_analysis(symbol: str) -> dict
```
Calls `GET /v1/features/stocks/{symbol}/latest` on DAAS, returns typed ToolResult.

### TASK-016 to TASK-019 — Technical batch scheduling + screening tools 🔨 BUILD
- **016**: Nightly Cloud Scheduler trigger for technical indicator engine (runs after bhavcopy)
- **017**: Technical screener tool — screen stocks by RSI range, MACD signal, SMA crossover
- **018**: Technical signal classifier — convert raw indicators to human-readable signals
- **019**: Integration tests for technical tool pipeline

---

## EPIC 3: Fundamental Analytics Engine

### TASK-020 — NSE financials data audit ✅ DONE (data exists, needs enrichment)
`nidp.nse_financials_quarterly` exists on VM. `nidp.stock_features_daily` already has
`pe_ttm`, `pb`, `roe_pct`, `debt_to_equity`, `revenue_growth_yoy_pct`, `pat_growth_yoy_pct`, `eps_growth_yoy_pct`
columns — currently NULL. DAAS `/v1/financials/{symbol}` serves quarterly data.

### TASK-021 — Fundamental metrics computation service ✅ DONE
**Target**: `backend/nidp/services/fundamental_engine/service.py`
Reads from `nidp.nse_financials_quarterly` → computes pe_ttm, pb, roe, debt_to_equity,
revenue/PAT/EPS growth → upserts into `nidp.stock_features_daily` fundamental columns.
Also computes Piotroski F-Score and Altman Z-Score.

### TASK-022 — Fundamental DAAS tool wrapper ✅ DONE
**Target**: `backend/nidp/services/copilot_agent/tools/fundamental_tools.py`
```python
@tool async def get_fundamental_analysis(symbol: str) -> dict
@tool async def get_valuation_metrics(symbol: str) -> dict
```

### TASK-023 to TASK-025 — Fundamental extensions ✅ DONE
- **023**: Sector peer comparison (sector median PE/PB from stock_features_daily)
- **024**: Valuation signal ("undervalued"/"fairly_valued"/"overvalued" vs sector median)
- **025**: Integration tests

---

## EPIC 4: Mutual Fund Analytics Engine

> **Data available**: `nidp.mf_nav_daily` — 4.9M rows (2006–2026-05-12), 14,362 schemes.
> `nidp.mf_holdings_monthly`, `nidp.mf_scheme_master`. DAAS `/v1/mf/*` serves all.

### TASK-026 — MF returns computation service ✅ DONE
**Target**: `backend/nidp/services/mf_analytics_engine/returns.py`
Reads from `mf_nav_daily` → computes point-to-point and rolling returns:
1m, 3m, 6m, 1y, 2y, 3y, 5y CAGR. Writes to new `analytics.mf_performance` table.

### TASK-027 — MF risk metrics (Sharpe, Sortino, Alpha, Beta, MaxDD) ✅ DONE
**Target**: `backend/nidp/services/mf_analytics_engine/risk_metrics.py`
Uses `mf_nav_daily` and `nidp.index_eod` as benchmark.

### TASK-028 — MF overlap calculator ✅ DONE
**Target**: `backend/nidp/services/mf_analytics_engine/overlap.py`
Reads `nidp.mf_holdings_monthly` → pairwise overlap matrix.
Already has `OverlapRevealWidget` in frontend waiting for this.

### TASK-029 — MF peer comparison + category ranking ✅ DONE
**Target**: `backend/nidp/services/mf_analytics_engine/peer_comparison.py`

### TASK-030 — MF DAAS tool wrappers ✅ DONE
**Target**: `backend/nidp/services/copilot_agent/tools/mf_tools.py`
```python
@tool async def get_mf_performance(scheme_code: str) -> dict
@tool async def get_fund_overlap(scheme_codes: list[str]) -> dict
@tool async def compare_funds(scheme_codes: list[str], metric: str) -> dict
@tool async def get_top_funds(category: str, risk_band: str) -> dict
```

### TASK-031 to TASK-033 — MF analytics extensions 🔨 BUILD
- **031**: SIP calculator tool
- **032**: MF analytics nightly batch
- **033**: Integration tests

---

## EPIC 5: Portfolio Analytics Engine

> **Data available**: `portfolio.user_holdings_snapshot`, `portfolio.user_intelligence_snapshot`,
> `nidp.portfolio_holdings_sync` pipeline already running. `services/portfolio_health.py`,
> `services/tax_engine.py`, `services/decision_engine.py` all exist.

### TASK-034 — XIRR calculator ✅ DONE
**Target**: `backend/services/copilot_tools/portfolio.py`
Reuse/wrap existing `services/portfolio_health.py` XIRR logic.

### TASK-035 — Portfolio analytics tool wrappers ✅ DONE
```python
async def get_portfolio_summary(user_id: str) -> PortfolioResult
async def get_portfolio_xirr(user_id: str) -> PortfolioResult
async def get_rebalance_plan(user_id: str) -> PortfolioResult
async def get_portfolio_overlap(user_id: str) -> PortfolioResult
```
Wire to existing `services/decision_engine.py` and `services/portfolio_intelligence.py`.

### TASK-036 — Stress test tool ✅ DONE
`StressTestWidget` exists in frontend — backend `run_stress_test()` built in `portfolio.py`.
covid_2020 (−38%), gfc_2008 (−60%), rate_shock (+200bps) scenarios implemented.

### TASK-037 — Tax harvest tool ✅ DONE
`TaxHarvestWidget` exists — wired to `services/tax_engine.loss_harvesting_candidates()`.
`tax` intent in orchestrator now hits real data (was stub).

### TASK-038 — Rebalance plan tool ✅ DONE
`RebalancePlanWidget` exists — wired via `get_rebalance_plan()` in `portfolio.py`.
`rebalance` intent in orchestrator now returns real actions.

### TASK-069 — Wire FY 2025-26 Capital Gains Engine into Portfolio Analysis ✅ DONE

**Context**: `backend/services/capital_gains_engine.py` (859 lines) was built from the
official PDF rulebook and covers all 13 asset categories, grandfathering, loss set-off,
surcharge cap, and cess correctly. The current `get_tax_harvest_candidates()` in
`copilot_tools/portfolio.py` still calls the old `services/tax_engine.loss_harvesting_candidates()`
which uses simplified heuristics (old ₹1,00,000 exemption, no grandfathering, no surcharge).

**What to build**:

1. **`copilot_tools/portfolio.py` — upgrade `get_tax_harvest_candidates()`**
   - Call `capital_gains_engine.quick_tax_estimate()` per holding instead of old heuristic
   - Return per-holding: `{name, gain_type (LTCG/STCG), unrealised_gain, tax_if_sold, tax_saved_if_harvested}`
   - Add a new `get_full_tax_report(user_id)` function:
     - Converts user holdings into `capital_gains_engine.Transaction` objects
     - Calls `compute_capital_gains(transactions, slab_rate=…)` for the complete picture
     - Returns `CapitalGainsResult.to_dict()` — all buckets, exemptions, total tax liability

2. **`copilot_agent/nodes/portfolio.py` — upgrade tax branch**
   - When user asks about tax: call `get_full_tax_report()` (not just harvest candidates)
   - Surface `total_tax_payable`, `equity_ltcg_exemption_applied`, `tax_saving_opportunities`
   - Widget: `TaxHarvestWidget` with the richer row structure

3. **`services/copilot_rag/orchestrator.py` — upgrade `tax` intent retrieval**
   - Replace `PORT.get_tax_harvest_candidates()` call with `PORT.get_full_tax_report()`
   - Add LLM formatter that explains: total liability → exemptions applied → net payable → harvest savings

4. **Tests** — at least 5 assertions:
   - Grandfathered equity holding computes correct deemed cost
   - SGB RBI redemption shows zero tax
   - LTCG exemption of ₹1,25,000 (not old ₹1,00,000) applied correctly
   - `get_full_tax_report` returns `CapitalGainsResult`-shaped dict
   - `TaxHarvestWidget` rows contain `tax_if_sold` field

**Files touched**:
- `backend/services/copilot_tools/portfolio.py`
- `backend/nidp/services/copilot_agent/nodes/portfolio.py`
- `backend/services/copilot_rag/orchestrator.py`
- `backend/nidp/services/copilot_agent/tests/test_tax_engine_integration.py` (new)

**Depends on**: `capital_gains_engine.py` ✅, `TASK-037` ✅, `TASK-051` ✅

---

## EPIC 6: Risk Analytics Engine

> V3 scoring engine (`services/v3_scoring.py`) already computes quality, health, exit, add,
> portfolio_fit, switch scores for MFs. `services/instrument_scoring.py` for stocks.

### TASK-039 — Risk suitability tool wrapper ✅ DONE
`services/copilot_tools/risk.py` — `get_risk_suitability()`.
Fetches user risk profile from DB, computes equity %, small/mid cap exposure,
weighted portfolio beta (from DAAS `volatility_20d`), detects misalignments vs
profile bounds (conservative/moderate/aggressive). Returns `RiskResult` with
risk_rating (LOW/MEDIUM/HIGH/VERY HIGH), risk_score_0_to_10, misalignment list.

### TASK-040 — Portfolio VaR tool ✅ DONE
`services/copilot_tools/risk.py` — `get_portfolio_var(user_id, confidence=0.95)`.
Parametric VaR: weighted portfolio daily vol × z-score × √holding_period.
Stocks use DAAS `volatility_20d`; MFs use equity_allocation_pct blend proxy
(equity 18% / debt 4% annual vol). Returns 1d and 10d VaR at 95% and 99%.

### TASK-041 — Risk tools integration tests ✅ DONE
44 tests in `nidp/services/copilot_agent/tests/test_risk_tools.py`. All 170
tests across all 5 test files pass together (stub isolation via autouse fixture
save/restore pattern).

---

## EPIC 7: Recommendation Engine

### TASK-042 — Composite recommendation scorer ✅ DONE
`services/copilot_tools/recommendation.py` — `composite_score()` + `composite_score_batch()`.
Weights: Technical 25%, Fundamental 30%, Valuation 15%, Risk Suitability 15%, Portfolio Fit 15%.
Signal: BUY ≥7.0, HOLD ≥4.5, AVOID <4.5. Respects user risk profile + portfolio sector weights.

### TASK-043 — Stock screener tool ✅ DONE
`screen_stocks()` in recommendation.py — calls DAAS `/screener/stocks` with RSI/PE/Piotroski/
valuation/ROE/D/E filter params. Returns `ScreenerResult(ok, rows, total_scanned, filter_summary)`.

### TASK-044 — MF recommendation tool ✅ DONE
`recommend_mf()` in recommendation.py — risk band → category mapping (conservative→Liquid,
moderate→Balanced Advantage, aggressive→Mid Cap) + quality filters (min_return_1y, min_sharpe, max_ter).

### TASK-045 — Recommendation engine tests ✅ DONE
60 tests, 60 passing: component scorers (tech/fund/val/risk/fit), composite_score (BUY/HOLD/AVOID,
weights, DAAS errors), composite_score_batch (sorted, top_n, error exclusion),
screen_stocks (params, error handling), recommend_mf (risk bands, quality filters, DAAS errors).

---

## EPIC 8: LangGraph Copilot Agent Framework

> Current chat: `routes/chat.py` uses direct OpenAI SSE streaming via `services/ai_engine.py`.
> Goal: Replace the LLM call inside `stream_chat` with a LangGraph graph invocation
> while keeping the existing SSE transport intact — zero frontend changes needed.

### TASK-046 — LangGraph state schema + graph skeleton ✅ DONE
**Target**: `backend/nidp/services/copilot_agent/graph.py`
`CopilotState(Pydantic BaseModel)` + `StateGraph` with 9 nodes.
Compiled with `MemorySaver` checkpointer. `get_graph()` singleton for FastAPI.

### TASK-047 — Intent classifier node ✅ DONE
**Target**: `backend/nidp/services/copilot_agent/nodes/intent.py`
Two-tier: regex (7 patterns, <1ms) → LLM structured-output fallback.
Routes to 7 specialist agents. Extracts symbol, scheme_code, scenario slots.

### TASK-048 — Market Analyst agent node ✅ DONE
**Target**: `backend/nidp/services/copilot_agent/nodes/market.py`
Calls DAAS `/v1/indices/summary`, `/v1/flows/fii-dii`, `/v1/macro/latest`.

### TASK-049 — Stock Analyst agent node ✅ DONE
**Target**: `backend/nidp/services/copilot_agent/nodes/stock.py`
Calls `copilot_tools.technical` + `copilot_tools.fundamental`.

### TASK-050 — MF Analyst agent node ✅ DONE
**Target**: `backend/nidp/services/copilot_agent/nodes/mf.py`
Calls `copilot_tools.mf` — performance, overlap, top funds.

### TASK-051 — Portfolio Analyst agent node ✅ DONE
**Target**: `backend/nidp/services/copilot_agent/nodes/portfolio.py`
Fetches summary + XIRR always; conditionally adds rebalance/tax/stress/overlap.

### TASK-052 — Risk Analyst agent node ✅ DONE
**Target**: `backend/nidp/services/copilot_agent/nodes/risk.py`
Runs COVID + GFC stress tests as risk proxies; surfaces StressTestWidget.

### TASK-053 — Goal Planner agent node ✅ DONE
**Target**: `backend/nidp/services/copilot_agent/nodes/goal.py`
Calls `services.goal_engine` (with graceful fallback); includes SIP calculator.

### TASK-054 — Recommendation agent node ✅ DONE
**Target**: `backend/nidp/services/copilot_agent/nodes/recommendation.py`
Stock screener (RSI<65 filter on Nifty50 basket) + MF top-funds by category.

### TASK-055 — Compliance filter + hallucination guard nodes ✅ DONE
**Target**: `backend/nidp/services/copilot_agent/nodes/compliance.py`
Disclaimer injection + numeric grounding check (>3 unmatched 4-digit figures).
400-word trim + caveat prefix if grounding fails.

### TASK-056 — Wire LangGraph into existing chat stream endpoint ✅ DONE
**Target**: `backend/routes/chat.py` `stream_chat()`
Gated behind `USE_LANGGRAPH_AGENT=true` env var.
`graph.astream_events()` replaces `copilot_rag.answer()` in investor path.
SSE transport unchanged — zero frontend changes needed.

### TASK-057 — Agent unit tests (mocked tools) ✅ DONE
`backend/nidp/services/copilot_agent/tests/test_agent_graph.py`
30 tests, 30 passing: schemas, intent routing (10 queries), portfolio node,
risk node, compliance node, graph topology.

### TASK-058 — End-to-end agent test — 10 sample queries across all agents ✅ DONE

---

## EPIC 9: Frontend (Largely Complete)

### TASK-059 — Wire WidgetRenderer to LangGraph tool output ✅ MOSTLY DONE
`WidgetRenderer.jsx` exists. All 8 widgets built. Wire `AgentResponse.charts` data
from LangGraph response to widget props.

### TASK-060 — Chat.jsx + ChatView.js SSE streaming ✅ DONE
Full streaming chat UI working. Sessions, pinning, renaming, markdown, charts all done.

### TASK-061 — NiveshV2 dark shell ✅ DONE
`NiveshV2.jsx` + `V2Layout.jsx` + `V2HomeScreen.jsx` complete.

### TASK-062 — Portfolio dashboard wire-up ✅ DONE
`ActionablePortfolioView.js` — `PortfolioRiskPanel` component added above the holdings
table. Calls `POST /api/copilot/widgets/risk_suitability` and `portfolio_var` in parallel;
shows risk rating badge, equity %, small/mid %, beta, 1-day VaR, annual vol, and
misalignment alert count inline. Two new backend endpoints added to `copilot_widgets.py`.

### TASK-063 — Insights feed wire-up ✅ DONE
`InsightsView.js` — `DailyMarketBriefing` component added at top of AI Overview tab.
Calls `POST /api/copilot/widgets/market_brief`; shows market regime badge, Nifty/BankNifty
with Δ%, FII/DII flows, and bullet summary. Risk tab upgraded: suitability card + VaR card
above the stress-test widgets; "WIP" badge removed from Risk tab.

---

## EPIC 10: Security, Observability & Production

### TASK-064 — Rate limiting middleware ✅ DONE
Existing `services/redis_client.py` + request middleware in place.

### TASK-065 — Audit trail 🔨 BUILD
`agent_audit_log` table migration + fire-and-forget insert in compliance node.

### TASK-066 — Langfuse tracing 🔨 BUILD
Wire after LangGraph graph works end-to-end.

### TASK-067 — Prometheus metrics endpoint 🔨 BUILD
`/metrics` endpoint for Grafana (which is already running on VM port 3000).

### TASK-068 — Production hardening + load test 🔨 BUILD
P95 latency < 5s under 50 concurrent users.

---

## EPIC 11: Copilot Chat UX + Dashboard Recommendations (May 2026)

### TASK-070 — Strip routing JSON leak from chat bubbles ✅ DONE
Intent classifier LLM now tagged `intent_internal`; SSE consumer in `routes/chat.py` filters those tokens. Frontend keeps a transitional `LEADING_ROUTE_JSON` regex guard (see TASK-077).
**Branch**: `feat/copilot-persona-prompts` (commits `beaa236`, `d369c4e`).

### TASK-071 — Split routing metadata into dedicated SSE `route` event ✅ DONE
Backend emits `event: route` with `{agent, confidence, symbol, scheme_code}` from `on_chain_end` of intent_node. Frontend ChatView consumes it to stamp the bubble's agent ribbon.

### TASK-072 — Drop duplicate SEBI disclaimer + add per-agent `follow_ups` ✅ DONE
`compliance_node` strips any in-body disclaimer the LLM volunteered and projects 3 default follow-up chips per agent. Footer below input box stays as the single canonical disclaimer.

### TASK-073 — Per-message toolbar (copy, regen, 👍/👎) + feedback API ✅ DONE
`MessageToolbar` component in ChatView; `POST /api/copilot/feedback` persists to `db.copilot_feedback`.

### TASK-074 — Shared persona/agent registry (single source of truth) ✅ DONE
New `frontend/src/components/copilot/shared/agentRegistry.js` exports `AGENT_REGISTRY` + `resolveAgent()`. Resolves the "Market Strategist" vs "Market Analyst" label-drift bug.

### TASK-075 — Dashboard `top_recommendations` orchestrator ✅ DONE
New `backend/services/dashboard_recommendations.py` composes `copilot_tools.portfolio` + `risk` + `mf_intelligence` + `recommendation` into a unified ranked list. Surfaces: OVERLAP, STOCK/SECTOR/AMC_CONCENTRATION, REBALANCE, COST_REDUCTION, TAX_HARVEST, RISK_MISALIGNMENT, WEAK_MF, WEAK_STOCK. Exposed at `/api/intelligence/portfolio` alongside legacy `ai_insights`.
**Note**: No new calculators built — composes existing copilot tools (the deterministic, DAAS-grounded functions used by LangGraph agents). See [feedback_reuse_copilot_tools.md](memory:feedback_reuse_copilot_tools).

### TASK-076 — Quick Actions deep-link to InsightsView tabs ✅ DONE
`personaActions.js` exports `INSIGHTS_TAB` constants; each action carries a `tab` field. V2HomeScreen writes `sessionStorage.v2_insights_target_tab` before screen-switching; InsightsView's `useState` initializer consumes + clears it on mount.

### TASK-077 — Remove transitional `LEADING_ROUTE_JSON` regex guard 🔨 BUILD
Frontend keeps a regex stripping any leading routing JSON envelope from the first token chunk as a belt-and-braces guard. Safe to delete from `ChatView.js` once the backend `route` SSE event has been live in all environments for at least one release.

### TASK-078 — Stock-investor sector-peer comparison widget 🔨 BUILD
Backend endpoint `/api/intelligence/sector-peers/{symbol}` already exists (returns V3-scored same-sector peers via `stock_intelligence.get_nidp_screener`). Frontend widget for the dashboard's stock-investor Quick Action is NOT yet built.
**Acceptance**: a `SectorPeerComparisonWidget.jsx` that takes a held symbol and renders a side-by-side fundamental + technical comparison table.

### TASK-079 — Admin UI to read `copilot_feedback` 🔨 BUILD
The `POST /api/copilot/feedback` endpoint persists thumbs up/down to `db.copilot_feedback`, but there is no admin view to browse, filter, or aggregate the feedback yet. Wire into the admin console alongside the other moderation views.

### TASK-080 — Backend persona-label consolidation 🔨 BUILD
`AgentName` enum in `backend/nidp/services/copilot_agent/schemas.py` is canonical, but several Python files still hardcode display strings like "Market Analyst" per-agent. Consolidate into one labels module so any future rename touches one place.

### TASK-081 — NIDP snapshot endpoint wiring 🔨 BUILD
Per [project_nidp_copilot_ownership.md](memory:project_nidp_copilot_ownership) — `/v1/intelligence/portfolio/{user_id}/snapshot` exists but isn't called from Copilot. Dashboard + chat should consume the snapshot rather than recomputing `equity_pct` / `beta` / `top_sector` locally.

### TASK-082 — Fix volatility_20d gap 🔨 BUILD
Per [project_volatility_20d_gap.md](memory:project_volatility_20d_gap) — blank Risk ribbon root-caused to missing column in `nidp.stock_features_daily`. `technical_indicator_engine` never computes vol; no scheduler config. Add column + job. Block Copilot from synthesising the value (see deterministic-no-duplication feedback).

### TASK-083 — Persona-aware Copilot pipeline + 5-category prompt taxonomy (P1) ✅ DONE
**Branch**: `feat/copilot-persona-prompts` (commit `beaa236`, 19 files, +1715/−60)
- `models.PersonaType` extended with `active_trader`, `parents_planning`, `conservative_investor` so the 10 product personas map 1:1 to enum values.
- `CopilotState` gained `persona`, `risk_profile`, `age_band`, `journey_type` fields hydrated at chat-route entry by new `persona_loader.load_persona_context()` against `user_profiles`.
- New `persona_framing.py` — 15 framing blocks prepended to every specialist's system prompt (portfolio, mf, risk, goal, stock, market, recommendation).
- New `routes/copilot_prompt_catalog.py` — **99 persona-tagged templates** (10 personas × ~10 questions; active_trader Q5 hidden until P3). Existing 10 universal templates in `copilot_prompts.py` tagged with `intent_category` ∈ {portfolio_health, performance, risk_diversification, tax, goal_planning}.
- `/api/copilot/suggested-prompts` accepts `persona` + `category` query params and filters before scoring. Response exposes `persona`, `category_filter`, `persona_prompts_enabled`.
- `nodes/intent.py` regex coverage extended for FD, overlap(ping), IDCW, tax-loss harvesting, P&L, market-falls-X%, manage risk, child education, withdrawal rate, annuity, PMS/AIF, DTAA, international ETFs, swing trading. **91% routing accuracy** on a 23-question persona sample.
- Frontend: 5-category chip filter row in `ChatView.js`, `CategoryChip` on `CopilotPromptCard.jsx` hero + compact variants.
- Feature flag `copilot_persona_prompts_enabled` (default everyone) gates the new behaviour.
- Catalog spec: `docs/COPILOT_PROMPT_CATALOG.md` (109 entries: 100 persona + 10 universal, minus 1 trader Q5 hidden until P3).

### TASK-084 — Copilot persona P2: capability gap tools 🔨 BUILD
The persona catalog references five tools that don't exist yet — the catalog routes correctly but those answers fall back to generic phrasing until each ships.
- `compare_to_fd(period)` — XIRR vs prevailing FD rate constant.
- `run_market_drop_scenario(drop_pct)` — parameterised market-down stress test (reuse `goal_engine.scenario_matrix`).
- `compare_idcw_vs_growth(scheme_code)` — small wrapper over `capital_gains_engine`.
- `get_currency_exposure()` — NRI INR vs foreign-denominated share from holdings.
- `trading_metrics.realized_pnl` block in `get_portfolio_summary` (derived from `capital_gains_engine` FIFO output).

### TASK-085 — Copilot persona P3: educator knowledge base + test matrix 🔨 BUILD
- Curated `backend/nidp/services/copilot_agent/knowledge_base.md` (~30 short entries) for the 32 educator-routed prompts (PMS/AIF, estate planning, tax treaties, "what is P/E", etc.). `recommendation` agent grounds answers in this markdown via lightweight RAG.
- `backend/tests/copilot/test_persona_qa_matrix.py` — seeds 10 synthetic persona profiles, fires each persona's 10 questions through `/api/copilot/ask`, asserts intent routes to the expected agent and the response is grounded in at least one expected tool output. Un-hide active_trader Q5 (win-rate / risk-reward) once the underlying primitive ships.

### TASK-086 — FE persona-key map (P1.5 polish) 🔨 BUILD
`detectPersona()` in `V2CopilotWelcome.jsx` returns keys like `mf_investor` / `trader` / `new_investor` that don't 1:1 match `PersonaType.value`. Add a small FE→backend map so heuristic personas (post-CAS-upload, pre persona_engine write) can drive the catalog immediately. Backend currently reads `user_profiles.persona` authoritatively, so this only matters for the moment between CAS-upload and persona-engine completion.

### TASK-087 — Market Dashboard polish + positional engine scheduling + health diagnostics ✅ DONE
**Branch**: `docs/persona-task-registry` (to be merged into `main`)

Three issues reported on `/dashboard#market`: (a) translucent card backgrounds clashed with the rest of the app's opaque slate-800 cards, (b) Positional Picks stayed empty even after admin clicked **Run engine**, (c) no automated daily refresh after NIDP feeds completed.

Fixes shipped:
- **Color scheme** — `MarketDashboard.jsx` section bg `bg-white/60 dark:bg-slate-800/60` → `bg-white dark:bg-slate-800`; sticky nav `bg-white/85 dark:bg-slate-950/85` → `bg-[#F8FAFC] dark:bg-slate-950`. `MarketTodaysTake.jsx` sticky strip same fix. Removes the see-through "MACRO V1" look.
- **Positional engine cron** — engine had **no scheduled runs**; the only trigger was the admin **Run engine** button. New `scripts/run_positional_engine.py` (standalone runner, no FastAPI/auth) + `deploy/nivesh-app/positional-engine.cron` (06:00 IST Mon–Sat re-score, 20:00 IST Mon–Fri full run with fresh NSE bhavcopy) + idempotent `install-positional-engine.sh` (mirrors `install-error-triage.sh`).
- **"Run engine returned nothing" debugging** — root cause: when the run fires before NSE publishes bhavcopy (18:00–19:30 IST), today's OHLCV row count is 0, `universe_for(today)` returns `[]`, pipeline reports `empty_universe`, UI shows a generic warning. Fixed by:
  - `POST /api/positional/run-full` walks back up to 3 weekdays when today's bhavcopy is missing (unless caller pinned a date); returns `fallback_used` + per-attempt details.
  - New `GET /api/positional/health` returns freshness/row-count for `stock_ohlcv` / `chartink_scan_hits` / `stock_technical_features` / `positional_signals` + scan-config status.
  - `PositionalPicks.jsx` empty state now embeds `EngineHealthPanel` showing the 4 tables' freshness — admins can see at a glance which table is stale.
- **NIDP feed health audit** — new `scripts/check_nidp_feed_health.py` calls the existing NIDP Query API `/feeds` proxy and flags `never-succeeded` / `last_run_failed` / `stale (Nd > Td)` / `consec_fail≥3`. Exit code 2 if anything's flagged (cron-friendly).

**Deferred (per user direction)**: auto-refresh of dashboard widgets after NIDP feed completion — current polling cadence (60s during market hours, 5 min after) is sufficient until SSE / WebSocket layer is added.

**Files touched**:
- Frontend: `frontend/src/components/MarketDashboard.jsx`, `MarketTodaysTake.jsx`, `PositionalPicks.jsx`
- Backend: `backend/routes/positional.py` (new `/health` endpoint, `run-full` weekday fallback)
- New scripts: `backend/scripts/run_positional_engine.py`, `backend/scripts/check_nidp_feed_health.py`
- New cron + installer: `deploy/nivesh-app/positional-engine.cron`, `install-positional-engine.sh`

**Deployment**: `sudo bash /opt/nivesh/repo/deploy/nivesh-app/install-positional-engine.sh` on `nivesh-app-vm`, then redeploy frontend container.

---

## Execution Order (next up)

```
DONE:  TASK-011–015     — technical indicator engine + tool wrapper
DONE:  TASK-021–030     — fundamental + MF analytics engines + tool wrappers
DONE:  TASK-034–038     — portfolio tools (XIRR, stress test, tax harvest, rebalance)
DONE:  capital_gains_engine.py — full FY 2025-26 tax engine (13 asset categories)

DONE:  TASK-010         — shared Pydantic schemas
DONE:  TASK-046–057     — full LangGraph framework (graph, 7 agent nodes, compliance, tests)
DONE:  TASK-056         — wired into stream_chat (USE_LANGGRAPH_AGENT=true flag)
DONE:  TASK-069         — FY 2025-26 capital gains engine wired into portfolio tools (15 tests)
DONE:  TASK-058         — end-to-end agent tests, 21/21 passing across all 7 agent types
DONE:  TASK-070–076     — Copilot chat UX + dashboard recommendations orchestrator (May 2026)
DONE:  TASK-083         — Persona-aware Copilot pipeline + 5-category prompt taxonomy (P1, May 2026)
DONE:  TASK-087         — Market Dashboard polish + positional engine cron + NIDP/positional health diagnostics (May 2026)

NOW:   TASK-077         — remove transitional LEADING_ROUTE_JSON guard (post-deploy cleanup)
NOW:   TASK-078         — stock-investor sector-peer comparison widget
NOW:   TASK-081         — wire /v1/intelligence/portfolio/{user_id}/snapshot from Copilot
NOW:   TASK-082         — fix volatility_20d gap in nidp.stock_features_daily
NOW:   TASK-084         — Copilot persona P2 capability tools (FD compare, market drop, IDCW, currency, realized P&L)
THEN:  TASK-085         — Copilot persona P3 educator KB + test matrix
THEN:  TASK-086         — FE persona-key map (P1.5 polish)
THEN:  TASK-079         — admin UI for copilot_feedback
THEN:  TASK-080         — backend persona-label consolidation
THEN:  TASK-031         — SIP calculator tool
THEN:  TASK-039–041     — risk suitability + VaR tools
DONE:  TASK-042–045     — recommendation engine (composite scorer, screener, MF recommender, 60 tests)
THEN:  TASK-062–063     — frontend wire-up
THEN:  TASK-065–068     — observability + production hardening
```
