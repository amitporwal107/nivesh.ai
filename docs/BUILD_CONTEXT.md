# Nivesh AI Copilot — Build Context
## What Was Done, How, Critical Path, Assumptions & Improvement Notes

> Last updated: 2026-05-13
> Branch: `nidp`
> Covers: All tasks completed as of TASK-057

---

## 1. Technical Indicator Engine (TASK-011 → 015)

### What was built
A standalone background service that computes 28 technical indicators for all 3,425 NSE EQ-series symbols daily and writes them to `nidp.stock_features_daily`. A DAAS tool wrapper then serves these to copilot agents.

### Files
| File | Purpose |
|------|---------|
| `backend/nidp/services/technical_indicator_engine/calculator.py` | Pure-numpy indicator functions |
| `backend/nidp/services/technical_indicator_engine/service.py` | Batch processor + DB upsert |
| `backend/nidp/services/technical_indicator_engine/__main__.py` | CLI (`--date`, `--backfill-days`, `--symbols`) |
| `backend/services/copilot_tools/technical.py` | `TechnicalResult` dataclass + `get_technical_analysis(symbol)` |

### How it works
1. `service.py` bulk-fetches `nidp.prices_eod` for all symbols in batches of 100 (concurrent `asyncpg` queries).
2. `calculator.py` receives a `(closes, highs, lows, volumes, deliv_pcts)` array set and computes all indicators in one pass using numpy — no per-indicator DB read.
3. Results are upserted into `nidp.stock_features_daily` with `source='COPILOT_TI_ENGINE'`.
4. DAAS router `/v1/features/stocks/{symbol}/latest` serves the most-recent row.
5. `copilot_tools/technical.py` calls DAAS, interprets raw numbers into human-readable signals (e.g., "RSI oversold", "MACD bullish crossover"), and returns a `TechnicalResult` with `ok`, `summary`, `signals`, `data`.

### Indicators computed
SMA(20/50/100/200), SMA50 slope, EMA(12/26), RSI-14 (Wilder smoothing), MACD+signal+histogram, ATR-14+%, Bollinger Band width+position, Returns(5d/20d/60d), Volume avg+z-score, Delivery avg+slope, Swing high/low(20-period), Pivot breakout flag, 52-week high/low distances, Distance from 200DMA.

### Critical path
`prices_eod` must be populated before running the engine. The engine is designed to run nightly after the bhavcopy ingest pipeline. **TASK-016 (Cloud Scheduler trigger) is not yet done** — the engine must be triggered manually or as a one-off Cloud Run Job until then.

### Assumptions
- `nidp.prices_eod` has at least 200 trading days of history per symbol for SMA200 to be meaningful. Symbols with < 20 rows get `NULL` for most indicators.
- Delivery % data (`deliv_pcts`) comes from NSE bhavcopy. If absent (e.g. F&O-only symbols), delivery stats are `NULL`.
- DAAS `X-API-Key` auth is always required — the tool wrapper reads `NIDP_DAAS_BASE_URL` + `NIDP_DAAS_API_KEY` from env.

### Known improvements needed
- **TASK-016**: Wire nightly Cloud Scheduler to trigger `nidp-technical-indicators` Cloud Run Job after bhavcopy completes.
- **TASK-017**: Build a proper screener tool — current `recommendation_node` uses a hardcoded Nifty50 basket as a proxy.
- yfinance 180-day backfill is needed for SMA200 and true 52-week levels on symbols with sparse `prices_eod` history.

---

## 2. Fundamental Analytics Engine (TASK-021 → 025)

### What was built
A service that reads `nidp.nse_financials_quarterly` and computes financial ratios, writing them into `nidp.stock_features_daily`. Includes Piotroski F-Score and Altman Z-Score. A DAAS tool wrapper exposes fundamental data to copilot agents with sector peer comparison and valuation signals.

### Files
| File | Purpose |
|------|---------|
| `backend/nidp/services/fundamental_engine/calculator.py` | PE, PB, ROE, D/E, growth rates, Piotroski, Altman |
| `backend/nidp/services/fundamental_engine/service.py` | Reads financials → upserts stock_features_daily |
| `backend/nidp/services/fundamental_engine/__main__.py` | CLI runner |
| `backend/services/copilot_tools/fundamental.py` | `get_fundamental_analysis(symbol)`, valuation signal |

### How it works
1. `service.py` reads the latest 8 quarters per symbol from `nse_financials_quarterly`.
2. `calculator.py` computes TTM values (trailing 4-quarter sums for revenue, PAT, EPS), derives PE/PB from current price and book value, and computes YoY growth rates.
3. Piotroski F-Score (9 binary signals on profitability, leverage, operating efficiency) and Altman Z-Score (5-factor bankruptcy predictor) are computed where data is sufficient.
4. `copilot_tools/fundamental.py` calls DAAS `/v1/financials/{symbol}`, derives sector peer median PE/PB from `stock_features_daily`, and returns a valuation signal: `undervalued` / `fairly_valued` / `overvalued`.

### Critical path
Depends on `nse_financials_quarterly` being populated by the NSE financials ingest pipeline (already live). Sector median PE/PB requires the fundamental engine to have run for at least the full NSE universe (so peer comparisons have enough data points).

### Assumptions
- Sector classification uses the `sector` column in `nse_equity_master`. Symbols without a sector are excluded from peer comparison.
- Altman Z-Score is computed only for manufacturing companies (non-financial). Financial sector stocks get `altman_z = NULL`.
- Revenue and PAT are assumed to be in ₹ Crores as stored in `nse_financials_quarterly`.

### Known improvements needed
- MCA/SEBI balance sheet data would improve book value accuracy for PB ratio computation.
- The F-Score currently lacks the "change in shares outstanding" signal (dilution check) due to missing data.
- Sector median should be recomputed weekly and cached, not recomputed on every DAAS request.

---

## 3. Mutual Fund Analytics Engine (TASK-026 → 030)

### What was built
Three computation services (returns, risk metrics, overlap + peer comparison) that read from `nidp.mf_nav_daily` (4.9M rows, 14,362 schemes) and a DAAS tool wrapper for copilot agents.

### Files
| File | Purpose |
|------|---------|
| `backend/nidp/services/mf_analytics_engine/calculator.py` | CAGR, returns, Sharpe, Sortino, Alpha, Beta, MaxDD |
| `backend/nidp/services/mf_analytics_engine/service.py` | Batch processor |
| `backend/nidp/services/mf_analytics_engine/__main__.py` | CLI runner |
| `backend/services/copilot_tools/mf.py` | `get_mf_performance()`, `get_top_funds()`, `get_portfolio_overlap()` |

### How it works
- **Returns**: Point-to-point CAGR for 1M, 3M, 6M, 1Y, 2Y, 3Y, 5Y computed from `mf_nav_daily`. Formula: `(nav_end/nav_start)^(1/years) - 1`.
- **Risk metrics**: Daily log returns computed → annualised volatility, Sharpe (risk-free 6.5%), Sortino (downside deviation), Max Drawdown. Alpha and Beta relative to `nidp.index_eod` (Nifty 50 as benchmark).
- **Overlap**: Pairwise Jaccard similarity on `mf_holdings_monthly` stock sets. Written to `analytics.mf_overlap` table.
- **Peer comparison**: Funds ranked by 3Y CAGR within their AMFI category. Percentile rank stored.
- `copilot_tools/mf.py` calls DAAS `/v1/mf/performance/{scheme_code}` and `/v1/mf/top-funds?category=` to serve results.

### Critical path
`mf_nav_daily` is populated by the AMFI NAV ingest pipeline (live). `mf_holdings_monthly` is populated monthly by the AMFI disclosure ingest. **TASK-032 (nightly batch) is not yet done** — returns and risk metrics must be recomputed periodically.

### Assumptions
- Nifty 50 (`NIFTY50` in `nidp.index_eod`) is used as the universal benchmark for all fund categories including debt and gold. This is incorrect for debt funds (should be CRISIL Composite Bond) — flagged as an improvement.
- Funds with < 365 days of NAV history are excluded from CAGR computation for periods > available data.
- AMFI scheme codes are used as the canonical identifier. Scheme name matching is approximate.

### Known improvements needed
- Use category-appropriate benchmark: CRISIL Short Duration for debt, MCX Gold for gold ETFs.
- **TASK-032**: Nightly batch via Cloud Scheduler to keep `analytics.mf_performance` fresh.
- Rolling 3M/1Y alpha/beta (not just full-history) would give more actionable signals.
- `get_top_funds()` currently returns all qualifying schemes without a hard limit — should default to top 5.

---

## 4. Portfolio Analytics Tools (TASK-034 → 038)

### What was built
Six async tool functions that wrap existing `services/portfolio_health.py`, `services/portfolio_intelligence.py`, `services/tax_engine.py`, and `services/decision_engine.py` into a unified `PortfolioResult` dataclass. These are consumed by both the RAG orchestrator and the new LangGraph portfolio agent node.

### Files
| File | Purpose |
|------|---------|
| `backend/services/copilot_tools/portfolio.py` | All 6 tool functions + `PortfolioResult` dataclass |

### Functions built

| Function | What it does |
|----------|-------------|
| `get_portfolio_xirr(user_id)` | Computes per-holding XIRR via `_holding_xirr()`, weighted portfolio XIRR by invested amount |
| `get_portfolio_summary(user_id)` | Calls `compute_portfolio_intelligence()` — allocation, sector, overlap count, effective stocks |
| `get_portfolio_overlap(user_id)` | Pairwise fund overlap from portfolio intelligence |
| `get_rebalance_plan(user_id)` | Equity/debt split vs 65/35 target; flags SELL/BUY/HOLD/SWITCH actions |
| `get_tax_harvest_candidates(user_id)` | Calls old `tax_engine.loss_harvesting_candidates()` — **will be replaced by TASK-069** |
| `run_stress_test(user_id, scenario)` | Applies scenario drops per asset class; three built-in scenarios |

### Stress test scenarios
```
covid_2020  : equity −38%, debt −2%, recovery 1.2 years
gfc_2008    : equity −60%, debt −5%, recovery 4.0 years
rate_shock  : equity −12%, debt −7%, recovery 1.5 years
```

### How holdings are loaded
`_load_holdings()` tries `db.holdings` first, falls back to `db.portfolio_holdings`. Holdings are expected to have `asset_type`, `current_value`, `invested_amount`, `quantity`, `buy_price`, `current_price`, `buy_date`.

### Critical path
`services/portfolio_intelligence.py` and `services/portfolio_health.py` must be running (they are). The tax harvest function will be upgraded by TASK-069 to use `capital_gains_engine.py`.

### Assumptions
- Rebalance target is hardcoded as 65% equity / 35% debt. This should come from the user's risk profile (improvement noted below).
- Stress test applies flat drops per broad asset class — no fund-specific sensitivity. An HDFC Equity fund and a small-cap fund both get the same −38% equity drop in covid_2020.
- XIRR Newton-Raphson solver uses a 0.0001 tolerance with 100 max iterations.

### Known improvements needed
- Rebalance target should be derived from the user's risk profile (e.g., aggressive → 80/20, conservative → 40/60).
- Stress test should use fund-specific beta to equity index for more accurate sensitivity.
- XIRR fails gracefully to `None` when cash flows are all same-sign — could return estimated CAGR as fallback.

---

## 5. Capital Gains Engine (standalone — feeds TASK-069)

### What was built
A complete FY 2025-26 (AY 2026-27) Indian capital gains tax engine built from the official PDF rulebook. Handles all 13 asset categories, 10-step computation order, grandfathering, loss set-off, surcharge cap, and cess.

### File
`backend/services/capital_gains_engine.py` — 859 lines, no external dependencies beyond Python stdlib.

### Key constants
```python
EQUITY_LTCG_EXEMPTION  = 125_000      # ₹1,25,000 (NOT old ₹1,00,000)
EQUITY_STCG_RATE       = 0.20         # Sec 111A
EQUITY_LTCG_RATE       = 0.125        # Sec 112A
NON_EQUITY_LTCG_RATE   = 0.125        # post-budget 2024 unified rate
CESS_RATE              = 0.04         # 4% health + education cess
GRANDFATHERING_DATE    = 2018-01-31   # FMV reference date
DEBT_MF_SLAB_CUTOVER   = 2023-04-01  # debt MF acquired on/after → always slab, no LTCG
```

### 13 Asset Categories
`LISTED_EQUITY`, `EQUITY_MF`, `DEBT_MF_POST23`, `DEBT_MF_PRE23`, `HYBRID_EQUITY`, `HYBRID_NON_EQUITY`, `GOLD_ETF`, `SGB_EXEMPT` (RBI redemption = fully tax-free), `SGB_EXCHANGE` (12-month threshold), `REIT_INVIT`, `BOND`, `PROPERTY`, `UNLISTED_EQUITY`.

### Computation flow
1. `classify_asset()` → `AssetCategory` (uses name keywords + equity_allocation_pct threshold of 65%)
2. `compute_single_gain(txn)` → `GainRecord` (applies grandfathering if pre-2018, computes holding days, classifies STCG/LTCG)
3. `compute_capital_gains(transactions, slab_rate, brought_forward_losses, total_income_rs, taxes_paid)` → `CapitalGainsResult`
   - Aggregates all GainRecords into category buckets
   - Applies STCL set-off → STCG first, then LTCG; LTCL set-off → LTCG only
   - Applies ₹1,25,000 LTCG exemption shared across listed equity + equity MF + REIT/InvIT
   - Computes surcharge (15% cap for special-rate gains per Finance Act 2023)
   - Applies 4% cess
4. `quick_tax_estimate(holding, ltcg_used, slab_rate, exit_fraction)` → per-holding tax estimate dict

### Grandfathering logic
For listed equity or equity MF acquired before 31-Jan-2018:
```
deemed_cost = max(actual_cost, min(FMV_31Jan2018, sale_price))
```
This ensures the cost basis is never higher than the sale price (preventing artificial losses).

### Why a new engine was needed
The existing `services/tax_calculator.py` had:
- ₹1,00,000 exemption (wrong — should be ₹1,25,000 since Budget 2024)
- No SGB RBI redemption exemption
- No hybrid MF equity-allocation classification
- No grandfathering computation
- No surcharge / cess computation
- No loss set-off logic

The new engine keeps `tax_calculator.py` intact for backward compatibility.

### Critical path
TASK-069 must wire this engine into `copilot_tools/portfolio.py` and the portfolio agent node. Until then, the tax copilot responses use the old heuristic.

### Assumptions
- `fmv_31jan2018` must be supplied by the caller for pre-2018 holdings. If not supplied, grandfathering is skipped (conservative: actual cost used, may overstate gains).
- SGB redemption type (`redemption_via_rbi` boolean) must be set correctly by the caller.
- Surcharge brackets apply as of Budget 2025: 10% (₹50L–1Cr), 15% (₹1Cr–2Cr), 15% cap for special-rate gains (Sec 111A/112A).

### Known improvements needed
- FMV for 31-Jan-2018 needs to be sourced from a data provider (NSE historical data). Currently the caller must supply it — not automated.
- Indexation for property and pre-2023 debt MF (LTCG before Budget 2024 changes) is not yet implemented.
- The engine does not handle Section 54/54F exemptions (reinvestment in property).

---

## 6. RAG Orchestrator Upgrades (intents: tax, portfolio_perf, stress_test, rebalance)

### What was built
Extended the existing `services/copilot_rag/` pipeline with four new intent branches and two new regex patterns in the intent router.

### Files modified
| File | Change |
|------|--------|
| `backend/services/copilot_rag/intent_router.py` | Added `_STRESS_TEST` and `_PORTFOLIO_PERF` regex patterns; added steps 0d/0e in `classify_intent()` |
| `backend/services/copilot_rag/orchestrator.py` | Added `PORT` import; wired retrieval + LLM formatters for `tax`, `portfolio_perf`, `stress_test`, `rebalance` |

### New intent routing (priority order excerpt)
```
0a  mf_analysis          — MF-specific queries
0b  fundamental_analysis — stock fundamentals
0c  technical_analysis   — RSI/MACD/chart queries
0d  portfolio_perf       — XIRR, portfolio return, performance
0e  stress_test          — crash scenarios, COVID/GFC/rate-shock
1   concentration        — sector/AMC/asset-class breakdown
2   invest_fresh / plan  — fresh investment, goal planning
3   ranking / overlap    — top/worst holdings, fund overlap
4   tax                  — tax harvest, LTCG/STCG
5   drift / goals        — rebalancing, goal tracking
6   health               — portfolio health score
fallback: generic
```

### `_STRESS_TEST` regex — key fix
Initial pattern failed on "2008-style crash" (hyphen) and "What would I lose" (vs "How much would I lose"). Fixed to:
```python
r"2008[\s\-]+(?:style|crash|crisis|scenario)"  # hyphen-aware
r"(?:how\s+much|what)\s+(?:would|will)\s+i\s+lose"  # both forms
```
Final: 15/15 intent routing tests passing.

### Critical path
The RAG orchestrator is the default path for `stream_chat()` (investor mode). The LangGraph path is the future replacement, currently gated by `USE_LANGGRAPH_AGENT=true`.

---

## 7. LangGraph Copilot Agent Framework (TASK-010, 046–057)

### What was built
A complete multi-agent LangGraph graph with 9 nodes that replaces the single-LLM RAG orchestrator with a specialist-agent architecture. Wired into `routes/chat.py` behind a feature flag.

### Directory structure
```
backend/nidp/services/copilot_agent/
  __init__.py
  schemas.py          — Pydantic v2 models (CopilotState, ToolResult, AgentResponse, etc.)
  graph.py            — StateGraph builder + get_graph() singleton
  nodes/
    intent.py         — 2-tier classifier (regex → LLM fallback)
    market.py         — Market Analyst (indices, FII/DII, macro)
    stock.py          — Stock Analyst (technical + fundamental)
    mf.py             — MF Analyst (performance, overlap, top funds)
    portfolio.py      — Portfolio Analyst (XIRR, rebalance, stress, tax, overlap)
    risk.py           — Risk Analyst (stress test proxies for VaR)
    goal.py           — Goal Planner (SIP adequacy, goal tracking)
    recommendation.py — Recommendation Engine (screener, top funds)
    compliance.py     — Compliance filter (disclaimer, hallucination guard, trim)
  tools/
    daas_bridge.py    — Generic DAAS HTTP client for agent nodes
  tests/
    test_agent_graph.py — 30 unit tests, all passing
```

### Graph topology
```
START → intent_node
          ├→ market_node  ─┐
          ├→ stock_node    │
          ├→ mf_node       │
          ├→ portfolio_node ├→ compliance_node → END
          ├→ risk_node     │
          ├→ goal_node     │
          └→ recommendation_node ─┘
```

### Schemas (TASK-010)
All Pydantic v2 models with `ConfigDict`:
- `CopilotState` — LangGraph state; `messages` field uses `add_messages` reducer (append, not overwrite)
- `ToolResult` — `ok`, `tool_name`, `summary`, `data`, `rows`, `widget_type`, `error`
- `AgentResponse` — `agent`, `text`, `widget_type`, `widget_data`, `tool_results`, `grounding_ok`, `disclaimer`
- `IntentClassification` — `agent`, `confidence`, `symbol`, `scheme_code`, `scenario`, `extras`
- `ChatMessage` — `role`, `content`, `name`, `tool_call_id`, `timestamp`

### Intent node (TASK-047) — routing priority
```
1. RISK       — "portfolio risk", "VaR", "volatility", "drawdown"
2. GOAL       — "retirement", "on track", "SIP gap", "will I reach"
3. PORTFOLIO  — "my portfolio", "XIRR", "rebalance", "stress test", "tax harvest"
4. RECOMMENDATION — "recommend", "where should I invest", "screen stocks"
5. MF         — "mutual funds", "NAV", "SIP", "large cap funds"
6. MARKET     — "nifty", "sensex", "FII", "macro", "inflation"
7. STOCK      — "RELIANCE", "RSI", "MACD", "PE ratio", "analyse [SYMBOL]"
```
RISK is checked before PORTFOLIO so "portfolio risk" → Risk Analyst, not Portfolio Analyst.
MARKET is checked before STOCK so "What is Nifty?" → Market Analyst, not Stock Analyst (which has a `what\s+is\s+[A-Z]+` pattern).

### Compliance node (TASK-055)
Three guards applied in sequence:
1. **Trim**: responses > 400 words truncated with ellipsis
2. **Disclaimer**: SEBI disclaimer injected if not already present
3. **Hallucination guard**: extracts numbers ≥ 4 digits from LLM response; flags if > 3 numbers appear in response but not in tool data. Prepends caveat if flagged.

### Feature flag wiring (TASK-056)
```python
# In routes/chat.py
_USE_LANGGRAPH = os.environ.get("USE_LANGGRAPH_AGENT", "").lower() in ("1", "true", "yes")
```
- `USE_LANGGRAPH_AGENT=false` (default): investor path uses `copilot_rag.answer()` — existing RAG pipeline
- `USE_LANGGRAPH_AGENT=true`: investor path uses `graph.astream_events()` — tokens stream via `on_chat_model_stream` events
- Advisor (cross-client) mode always uses legacy `ai_engine.chat_stream()` regardless of flag
- SSE format is identical in both paths (`type: token`, `type: meta`, `type: done`) — zero frontend changes

### Test coverage (TASK-057) — 30 tests
- **Schema tests (5)**: `ToolResult.as_llm_context()`, `AgentResponse` defaults, `CopilotState` message accumulation, enum serialisation
- **Intent routing tests (10)**: portfolio, market, stock, MF, goal, risk, recommendation; symbol extraction, COVID/GFC scenario extraction, empty message fallback
- **Portfolio node tests (2)**: response structure, stress-test keyword triggers extra fetch
- **Risk node tests (1)**: response contains expected content
- **Compliance node tests (5)**: disclaimer injection, no-duplicate-disclaimer, word-limit trim, no-tool grounding pass, hallucination detection
- **Graph topology tests (3)**: all 9 nodes present, memory checkpointer compiles, singleton pattern

### Critical path
LangGraph is gated behind a feature flag — the existing RAG path is live and unaffected. To enable: set `USE_LANGGRAPH_AGENT=true` in the deployment env and restart the FastAPI server. Both paths produce the same SSE format.

### Assumptions
- Each specialist node makes one LLM call (`gpt-4o-mini`, temperature 0.1–0.2). No multi-turn within a node.
- `MemorySaver` is in-process — conversation history is lost on server restart. A Postgres checkpointer (`langgraph-checkpoint-postgres`) is the production upgrade path.
- The `daas_bridge.py` client does not retry on failure — it returns `ok=False` and lets the LLM handle missing data gracefully.
- `goal_node` falls back silently if `services.goal_engine` is not importable.

### Known improvements needed
- **TASK-058**: End-to-end test with real LLM calls across all 7 agent types.
- Replace `MemorySaver` with Postgres checkpointer (`psycopg3` async pool) for persistence across restarts.
- Add token budget tracking — `CopilotState.tokens_used` field exists but no node writes to it yet.
- Streaming from LangGraph (`on_chat_model_stream`) only fires for nodes that call an LLM. Tool-only nodes (e.g., data fetch) produce no stream events — the frontend shows a blank screen until the LLM call begins. A progress event (`type: thinking`) should be emitted after intent classification.
- The hallucination guard threshold (> 3 unmatched 4-digit numbers) is arbitrary — tune against real query logs.

---

## 8. Dependency Map

```
capital_gains_engine.py
    └── TASK-069 (pending): wire into portfolio.py + portfolio node + orchestrator

copilot_tools/portfolio.py
    ├── used by: copilot_rag/orchestrator.py   (tax, perf, stress, rebalance intents)
    └── used by: copilot_agent/nodes/portfolio.py (LangGraph portfolio node)

copilot_agent/graph.py
    ├── nodes/intent.py
    ├── nodes/{market, stock, mf, portfolio, risk, goal, recommendation}.py
    │     └── each calls copilot_tools/{technical, fundamental, mf, portfolio}.py
    └── nodes/compliance.py
          └── called by all specialist nodes before END

routes/chat.py (stream_chat)
    ├── [default]  → services/copilot_rag/orchestrator.py
    └── [USE_LANGGRAPH_AGENT=true] → copilot_agent/graph.py
```

---

## 9. Environment Variables Required

| Variable | Used by | Notes |
|----------|---------|-------|
| `OPENAI_API_KEY` | All LLM nodes + orchestrator | Required |
| `NIDP_DAAS_BASE_URL` | `daas_client.py`, `daas_bridge.py` | e.g. `http://34.93.x.x:8083` |
| `NIDP_DAAS_API_KEY` | Same | Issued via DAAS admin |
| `USE_LANGGRAPH_AGENT` | `routes/chat.py` | `true` to enable LangGraph path |
| `DATABASE_URL` | All DB services | App Postgres connection string |
| `NIDP_DATABASE_URL` | NIDP pipeline services | TimescaleDB connection string |

---

## 10. What Is NOT Done Yet

| Area | Tasks | Blocker |
|------|-------|---------|
| Capital gains engine wiring | TASK-069 | None — ready to build |
| E2E agent test | TASK-058 | Needs live OPENAI_API_KEY |
| SIP calculator | TASK-031 | None |
| MF nightly batch | TASK-032 | Cloud Scheduler setup |
| Risk VaR tool | TASK-040 | `stock_features_daily.volatility_20d` must be populated |
| Recommendation scorer | TASK-042–045 | Needs populated `stock_features_daily` fundamentals |
| Nightly scheduler | TASK-016 | GCP Cloud Scheduler config |
| Portfolio dashboard | TASK-062 | Needs `/v1/portfolio/{user_id}` API endpoints |
| Audit trail | TASK-065 | Migration + compliance node write |
| Langfuse tracing | TASK-066 | LangGraph must be in production first |
| Prometheus metrics | TASK-067 | FastAPI middleware |
| Load test | TASK-068 | Everything else first |
