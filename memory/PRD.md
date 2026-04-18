# nivesh.ai - Product Requirements Document

## Implemented Features (Latest)

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
