# nivesh.ai - Product Requirements Document

## Implemented Features (Latest)

### Feb 2026 — Groww MF Data Fetcher Phase 1
- [x] **Deterministic parser** (`services/groww_client.py`) — scoped to `holdings_row__*` CSS classes; extracts name, stock slug, sector, instrument type, pct per holding, plus AUM, NAV, expense ratio from metadata divs
- [x] **Search-API slug fallback** — when deterministic slug 404s, calls Groww `st_query` endpoint to resolve canonical search_id (e.g., "SBI Small Cap" → `sbi-small-midcap-fund-direct-growth`). Concurrent lookups coalesced per scheme_name + process-lifetime memo
- [x] **Pluggable Postgres + Redis layer** — lazy pools driven by admin-managed secrets `POSTGRES_URL`, `REDIS_URL` (new category: "data"). Auto-rebuilds on secret change.
  - `services/pg_client.py`: `lookup_instrument(symbol|isin|type)`, `search_mf_by_name` (ILIKE), `latest_nav`, `ping`
  - `services/redis_client.py`: `get/set_holdings`, `get/set_slug`, `ping` (15-day TTL)
- [x] **Tiered cache resolver** (`fund_data_resolver.py`) — Redis primary → Mongo durable fallback; 15-day TTL; ISIN-first canonical instrument_key (ISIN → SCHEME → NAME)
- [x] **Off-hours gate** — Mon-Fri 09:00-16:00 IST = market hours (enqueue only); all other times allow inline scrape. Admin endpoint `/api/admin/mf/scrape-now` bypasses gate
- [x] **Endpoints** (prefix `/api/mf`, `/api/admin/mf`):
  - GET `/mf/holdings` (user) — scheme_name + optional scheme_code/isin/slug/force
  - GET `/mf/lookup` (user) — resolve instrument → {instrument_key, id, symbol, isin, latest_nav}
  - GET `/admin/mf/db-status` — probe pg + redis connectivity
  - GET `/admin/mf/scrape-queue`, POST `/admin/mf/drain-queue`, POST `/admin/mf/scrape-now`
- [x] **Admin secret tests** — POST `/api/admin/secrets/POSTGRES_URL/test` and `/REDIS_URL/test` ping live connections
- [x] 26 backend tests passing (8 unit + 18 API integration)
- Dependencies added: `asyncpg==0.31.0`, `redis==7.4.0`
- Cache collections: `db.fund_holdings_cache`, `db.scrape_queue`

### Feb 2026 - Generic Admin Config Panel (Secrets + Feature Flags)
- [x] **Unified Secrets Registry** (`backend/helpers/secrets.py`)
  - DB-first with env fallback, module-level cache
  - Pre-registered: CASPARSER_API_KEY, EMERGENT_LLM_KEY, OPENAI_API_KEY, GOOGLE_CLIENT_ID, GMAIL_OAUTH_CLIENT_ID, CASPARSER_BASE_URL
  - Admin can add arbitrary custom secrets
  - Plain-text storage in `db.system_config.{key:"secrets"}.values` (TODO: Fernet encryption in Phase 2)
- [x] **DB-backed Feature Flags** (`backend/feature_flags.py`)
  - 3 modes per flag: `off` / `allowlist` / `everyone`
  - Pre-registered: ai_copilot, gmail_import, chat_streaming
  - Per-user email allowlist management
  - `/api/user/profile` returns `features: {key: enabled_bool}` for frontend gating
- [x] **Admin endpoints**: GET/PUT/DELETE `/api/admin/secrets/{key}` + POST test, GET/PUT `/api/admin/feature-flags/{flag}` + POST/DELETE users
- [x] **Frontend**: `SecretsSection.jsx` (grouped by category, mask/show/edit/test/delete/add-custom), `FeatureFlagsSection.jsx` (mode dropdown, allowlist chip editor)
- [x] Server startup hydrates both from DB (survive restarts)
- [x] Legacy `/admin/cas-config` endpoints kept for backward compat

### Feb 2026 - Admin CAS Parser API Key Management (superseded by Secrets)
- [x] Migrated into unified Secrets registry

### Feb 2026 - AI Copilot Phase 2
- [x] Custom Scenario Builder (sliders), Rebalance Plan, Save/Load scenarios, Apply → pending_actions
- [x] "Your Applied Action Plans" card with expand/collapse, mark-done, delete

### Feb 2026 - AI Copilot Phase 1 MVP
- [x] `/api/scenarios/suggest` + `/simulate` + `/rebalance-plan`
- [x] PortfolioContextHeader, ScenarioCard, SimulationPanel, AICopilotView
- [x] Real CAGR quick win (per-holding annualized return, fallback to static)
- [x] Feature-flag gated to aporwal107@gmail.com (now managed via Feature Flags UI)

### Feb 2026 - Mobile-First Responsive Overhaul
- [x] All screens mobile-first, body `overflow-x: hidden`, `min-w-0` on Dashboard shell
- [x] Horizontal scroll for tabs, donut+legend stacks, ChatView sidebar hidden by default
- [x] Suppressed cross-origin "Script error." overlays

### Apr 2026 - Enhanced AI Insights Engine
- [x] Full portfolio context in OpenAI prompt (overexposure, overlap, cost data)
- [x] Specific ₹/% citations in insights

### Prior UX & Architecture
- [x] server.py refactored into 10 route modules
- [x] SSE streaming chat, action intent cards, MF category cards, P&L heatmap
- [x] True look-through allocation via OpenAI gpt-4o-mini
- [x] Motilal Oswal-inspired dark/light dual theme

## Backlog

### P0
- Fernet-encrypt secrets at rest (SECRETS_ENCRYPTION_KEY env)
- Fix `/api/insights/generate` Action Plan still 1-step
- Security hardening: replace hardcoded test secrets with env, remove `eval()`, MD5→SHA-256 in analytics.py
- PAN encryption + consent logging + audit trails (DPDP)

### P1
- **Groww Phase 2**: APScheduler off-hours queue, admin panel for queue mgmt, bulk seed from user portfolios
- **Groww Phase 3**: wire ISIN-level overlap + true sector exposure into AI Copilot + InsightsView (replaces static category-proxy)
- AI Copilot Phase 3: chat-as-secondary, color system polish, icon library
- Fund & Stock Rating System (Morningstar-style)
- React hook dependency & array-index key cleanup
- Split oversized components (InsightsView 2122 lines, OnboardingView 904, DashboardOverview 861)
- CAS parser enhancement to preserve purchase dates → unlocks real CAGR coverage
- Goal-based planning (Retirement, Child Edu, SIPs)
- Stock-level overlap via AMFI disclosure data

### P2
- Historical-backtest CAGR model
- Real "Apply Changes" with broker integration
- Portfolio versioning (delta tracking)
- PostgreSQL migration
- Android wrap via Capacitor
- Admin audit log for secrets/flags changes (who changed what, when)
- Pending-plan badge on Dashboard sidebar

## Data Model Additions
- `db.system_config` — admin-managed config
  - `{key: "secrets", values: {KEY: value}, updated_at, updated_by}`
  - `{key: "feature_flags", flags: {flag_key: {mode, allowlist}}, updated_at, updated_by}`
  - `{key: "cas_parser", use_sandbox: bool, ...}` (legacy sandbox toggle)
- `db.saved_scenarios` — named scenario saves
- `db.pending_actions` — applied rebalance plans
- `db.scenario_simulations` — every simulate click log
