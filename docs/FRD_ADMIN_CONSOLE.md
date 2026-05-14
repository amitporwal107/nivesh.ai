# Functional Requirements Document — ADMIN CONSOLE
**Layer:** Admin Console (Internal Configuration & Operations)
**Status:** VALIDATED AGAINST CODE — May 2026
**Validation Source:** `routes/admin.py`, `routes/admin_data_pipeline.py`, `routes/admin_nidp.py`, `routes/admin_nidp_backfill.py`, `routes/admin_nidp_replay.py`, `routes/admin_rules.py`, `routes/admin_v3_master.py`, `routes/admin_v3_weights.py`, `routes/admin_v3_stock.py`, `routes/admin_datastores.py`, `routes/admin_users.py`, `src/components/admin/`, `src/components/AdminView.js`

---

## DOCUMENT NOTES

> The Admin Console is a **privileged operational surface** accessible only to users with `role = "admin"` or `is_admin = true`. It provides live control over all system parameters, data pipeline jobs, V3 scoring engine configuration, user management, and NIDP data warehouse operations — without requiring code deployment.
>
> All admin routes use `Depends(require_admin(request))`. The frontend AdminView.js gates the tab behind role check.

---

## 1. Module: Secrets Management

### FR-ADM-001 — Secrets CRUD
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-001 |
| **Module** | Secrets |
| **Feature** | Runtime Credential Management |
| **Priority** | Critical |
| **Source** | `routes/admin.py`, `src/components/admin/SecretsSection.jsx` |
| **Status** | Live |

**API:** `GET/POST/DELETE /api/admin/secrets`

**Description:** All application secrets (API keys, DB URLs, OAuth credentials) are stored in MongoDB `system_config.secrets` document and hydrated into memory at startup. The admin can CRUD secrets via this interface.

**30+ Registered Secrets (by category):**
| Category | Secrets |
|---|---|
| CAS Parsing | `GOOGLE_DOCAI_CREDENTIALS_JSON`, `GOOGLE_DOCAI_PROJECT`, `GOOGLE_DOCAI_PROCESSOR`, `CASPARSER_API_KEY`, `CASPARSER_SANDBOX_KEY` |
| LLM | `EMERGENT_LLM_KEY` |
| Auth | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GMAIL_OAUTH_CLIENT_ID` |
| Datastores | `POSTGRES_URL`, `REDIS_URL`, `NIDP_POSTGRES_URL` |
| Market Data | `CHARTINK_WEBHOOK_SECRET`, `YFINANCE_API_KEY` |
| Broker APIs | Per-broker API keys (9 brokers) |

**UI Behaviour:**
- Values masked in UI (show/hide toggle via eye icon)
- Changes take effect immediately (no restart required)
- Deletion prompts confirmation modal

**Acceptance Criteria:**
- Non-admin access → 403 on all admin endpoints
- Secret added → immediately available in `secrets_manager.get(key)`
- Secret value masked by default, reveals on toggle
- Delete secret → removed from system_config + invalidated in memory

---

## 2. Module: Feature Flags

### FR-ADM-002 — Feature Flag Management
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-002 |
| **Module** | Feature Flags |
| **Feature** | Gradual Feature Rollout |
| **Priority** | High |
| **Source** | `routes/admin.py`, `src/components/admin/FeatureFlagsSection.jsx` |
| **Status** | Live |

**API:** `GET/POST /api/admin/feature-flags/{flag}/toggle`

**Flag Modes:**
| Mode | Behaviour |
|---|---|
| `disabled` | Feature off for everyone |
| `allowlist` | Feature on for specified email list |
| `everyone` | Feature on for all users |

**Each Flag Has:**
- `flag_name` (string identifier)
- `mode` (disabled/allowlist/everyone)
- `allowlist` (comma-separated emails for beta access)
- `description` (human-readable purpose)

**Known Flags in Use:**
- `enable_positional_scanner` — positional trading engine
- `enable_goals_planning` — goals module
- `enable_mfd_workspace` — advisor workspace
- `USE_LANGGRAPH_AGENT` — Copilot V2 path
- `enable_nidp_copilot` — NIDP market context in copilot

**Acceptance Criteria:**
- Toggle flag `disabled` → feature returns 404 or empty state for all users
- Toggle to `allowlist` + add email → only that email can use feature
- Toggle to `everyone` → feature available to all authenticated users
- Changes take effect without server restart

---

## 3. Module: Rules Configuration

### FR-ADM-003 — Action Plan Rules Thresholds
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-003 |
| **Module** | Rules Config |
| **Feature** | Live-Tunable Decision Engine Parameters |
| **Priority** | Critical |
| **Source** | `routes/admin_rules.py`, `src/components/admin/RulesConfigSection.jsx` |
| **Status** | Live |

**API:** `GET/PATCH /api/admin/rules-config`

**Configurable Parameters:**
| Parameter | Default | Rule Affected |
|---|---|---|
| `amc_concentration_threshold_pct` | 15% | Rule 2 (AMC Concentration) |
| `category_concentration_threshold_pct` | 35% | Rule 2b (Category Concentration) |
| `debt_floor_conservative_pct` | 30% | Rule 5 (Debt Gap) |
| `debt_floor_moderate_pct` | 20% | Rule 5 (Debt Gap) |
| `debt_floor_aggressive_pct` | 10% | Rule 5 (Debt Gap) |
| `cost_leak_minimum_rs` | 10,000 | Rule 6 (Cost-Leak Switch) |
| `min_switch_score` | 1.0 | Rule 6 guardrail |
| `high_quality_protection_quality_threshold` | 75 | Guardrail 1 |
| `high_quality_protection_health_threshold` | 70 | Guardrail 1 |
| `overlap_override_pct` | 80% | Guardrail 1 exception |
| `recent_investment_lockout_months` | 6 | Guardrail 3 |
| `underperformer_ret_1y_threshold_pct` | 8% | Rule 3 |
| `underperformer_ret_3y_threshold_pct` | 10% | Rule 3 |

**Acceptance Criteria:**
- Change `amc_concentration_threshold_pct` from 15% to 20% → Rule 2 only fires when AMC > 20% on next plan generation
- All changes logged with timestamp and admin user
- No server restart required for changes to take effect

---

### FR-ADM-004 — Custom Rules DSL
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-004 |
| **Module** | Rules Config |
| **Feature** | Admin-Defined Custom Rules |
| **Priority** | Medium |
| **Source** | `routes/admin_rules.py` — `POST /api/admin/rules-config/custom` |
| **Status** | Live |

**Description:** Admin can define additional action plan rules using a safe AST DSL (whitelisted abstract syntax tree — no `eval()`). Rules are applied after the 6 built-in rules via `_apply_custom_rules()`.

**Use Case:** Onboarding a new advisory partner may require custom rules without code deployment.

---

## 4. Module: LLM Prompts Management

### FR-ADM-005 — Prompt Management & Sandbox
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-005 |
| **Module** | Prompts |
| **Feature** | LLM Prompt Editing + Testing |
| **Priority** | High |
| **Source** | `routes/admin_rules.py`, `src/components/admin/PromptsSection.jsx` |
| **Status** | Live |

**API:** `GET/POST /api/admin/prompts/{id}/test`

**7 Managed Prompts:**
| Prompt ID | Purpose |
|---|---|
| `copilot_system` | Main copilot persona + grounding instructions |
| `plan_summary` | Converts structured plan to 200-word plain English |
| `insight_narrative` | Portfolio insight description text |
| `goal_advice` | Goal-based investment guidance |
| `risk_profile_intro` | Risk questionnaire preamble |
| `whatsapp_export` | Mobile-friendly plan summary |
| `mfd_client_report` | Advisor report narrative |

**Sandbox Mode:**
- Admin provides mock data payload + test query
- System runs prompt against LLM
- Completion shown in sandbox pane
- Iterate without affecting live users

---

## 5. Module: Data Pipeline Monitor

### FR-ADM-006 — Scheduler & Job Monitoring
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-006 |
| **Module** | Data Pipeline |
| **Feature** | Pipeline Observability |
| **Priority** | High |
| **Source** | `routes/admin_data_pipeline.py`, `src/components/admin/DataPipelineMonitor.jsx` |
| **Status** | Live |

**API:** `GET /api/admin/data-pipeline/status`

**Three-Panel View:**
1. **Job Status Tiles** — for each scheduled job:
   - AMFI NAV (daily 22:00 IST)
   - Analytics Sweep (daily 22:30 IST)
   - V3 Rescore (daily 22:45 IST)
   - Nifty100 Refresh (weekly)
   - Stale Refresh (weekly Wed 03:00 IST)
   - Shows: last run time, status (OK/FAILED), rows processed, duration ms

2. **Recent Runs Log** — last 20 rows from `nav_analytics_job_log` table: job_name, started_at, processed, failed, duration_ms, error_msg

3. **Scheduler Status** — APScheduler next-fire times for each job

4. **Redis Key Count** — live count of `v3:score:*` cache keys (shows cache health)

**Manual Trigger:**
- API: `POST /api/admin/data-pipeline/trigger/{job}` (job = amfi_navs / analytics_sweep / v3_rescore / nifty100_refresh)
- On-demand button in UI for each job
- Useful for: forcing refresh after market data anomaly, debugging pipeline failures

**Cache Invalidation:**
- API: `POST /api/admin/cache/invalidate`
- "Clear all V3 cache" button → drops all `v3:score:*` Redis keys
- Triggers: after major scoring weight change; forces fresh compute on next request

**Acceptance Criteria:**
- Job status tiles show correct last-run time from `nav_analytics_job_log`
- Manual trigger → job runs immediately and status tile updates
- Cache invalidation → Redis `v3:score:*` count drops to 0

---

## 6. Module: V3 Engine Configuration

### FR-ADM-007 — V3 Scoring Weights (MF)
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-007 |
| **Module** | V3 Engine |
| **Feature** | MF Scoring Weight Editing |
| **Priority** | High |
| **Source** | `routes/admin_v3_weights.py`, `src/components/admin/V3WeightsSection.jsx` |
| **Status** | Live |

**API:** `GET /api/admin/v3-weights` / `PUT /api/admin/v3-weights` / `POST /api/admin/v3-weights/reset`

**Editable Weights Per Composite:**
- Quality: Performance / Risk-Adjusted / Consistency / Drawdown / Cost / AUM-Age (must sum to 100%)
- Health: Manager / AUM-Stability / Turnover / Concentration / Downside / Expense-Trend (must sum to 100%)
- Exit: Overlap / Tax / Quality-inverse / Cost / Portfolio-Fit (must sum to 100%)
- Add: Gap-Fit / Low-Overlap / Quality / Need / Cost (must sum to 100%)
- Portfolio-Fit: Diversification / Overlap / AMC / Cost / Asset-Alloc (must sum to 100%)

**Validation:** Weight values must sum to 100 per composite. Negative weights rejected.

**Reset:** Restores factory defaults from `v3_scoring.py` constants.

---

### FR-ADM-008 — V3 Stock Weights
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-008 |
| **Module** | V3 Engine |
| **Feature** | Stock Scoring Weight Editing |
| **Priority** | Medium |
| **Source** | `routes/admin_v3_stock.py`, `src/components/admin/V3StockWeightsSection.jsx` |
| **Status** | Live |

**API:** `GET/PUT /api/admin/v3-stock-weights`

Editable weights for 5-dimension stock scorer (Technical / Fundamental / Valuation / Risk / Portfolio-Fit)

---

### FR-ADM-009 — V3 Master Fund Catalogue
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-009 |
| **Module** | V3 Engine |
| **Feature** | Fund Master Data Browser |
| **Priority** | Medium |
| **Source** | `routes/admin_v3_master.py`, `src/components/admin/V3MasterFundsSection.jsx` |
| **Status** | Live |

**API:** `GET /api/admin/v3-master-funds` / `GET /api/admin/v3-master-funds/export.xlsx`

Browsable catalogue of all funds in V3 master with their computed primitives and composite scores. XLSX export for offline audit.

---

## 7. Module: Datastores Management

### FR-ADM-010 — Datastore Service Control
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-010 |
| **Module** | Datastores |
| **Feature** | PostgreSQL/Redis Service Control |
| **Priority** | High |
| **Source** | `routes/admin_datastores.py`, `src/components/admin/DatastoreSection.jsx` |
| **Status** | Live |

**API:** `GET /api/admin/datastores/status` + service start/stop/restart endpoints

**Shows:**
- PostgreSQL: connection status, table counts (instrument_master rows, NAV history rows, etc.)
- Redis: connection status, key counts (`v3:score:*`, `session:*`, `intelligence:*`)
- NIDP PostgreSQL: connection status, migration level

**Restart Buttons:**
- Useful for recovering from connection drops without server restart
- `POST /api/admin/datastores/postgres/restart` — reconnects asyncpg pool
- `POST /api/admin/datastores/redis/restart` — reconnects Redis client

---

## 8. Module: CAS Parser Configuration

### FR-ADM-011 — CAS Provider Toggle
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-011 |
| **Module** | CAS Config |
| **Feature** | Parser Provider Selection |
| **Priority** | High |
| **Source** | `src/components/admin/CasConfigSection.jsx` |
| **Status** | Live |

**Three Provider Configuration:**
| Provider | Toggle | Status Indicator |
|---|---|---|
| Nivesh Parser (Google Document AI) | Enable/Disable | Shows credential status |
| Claude Vision (Anthropic) | Enable/Disable | Shows API key status |
| casparser.in API | Enable/Disable + Sandbox toggle | Shows API key + sandbox mode |

**Sandbox Mode (casparser.in):** Test parsing against a sandbox API endpoint without consuming production quota.

---

## 9. Module: User Management

### FR-ADM-012 — User Administration
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-012 |
| **Module** | User Management |
| **Feature** | User Listing & Operations |
| **Priority** | High |
| **Source** | `routes/admin_users.py`, `routes/admin.py`, `src/components/admin/UserManagementSection.jsx` |
| **Status** | Live |

**API:** `GET /api/admin/users?q=email_prefix`

**User Table Shows:** email, total corpus value, holdings count, plan count, last active, active session flag

**Per-User Actions:**
- **Promote to Admin** — `POST /api/admin/users/{id}/promote-admin` — sets `is_admin=true`
- **Force Logout** — invalidates all sessions
- **Reset Portfolio** — `POST /api/admin/users/{id}/reset-portfolio`
  - Wipes 21 user-scoped MongoDB collections
  - Clears all Redis caches for user
  - Gated by **email-confirmation modal** showing exact deletion scope
  - CANNOT be undone

---

### FR-ADM-013 — Whitelist Management
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-013 |
| **Module** | User Management |
| **Feature** | Access Whitelist |
| **Priority** | Critical |
| **Source** | `routes/admin.py` |
| **Status** | Live |

**APIs:**
- `GET /api/admin/whitelist` — list all whitelisted emails with status
- `POST /api/admin/whitelist/add` — add single email
- `POST /api/admin/whitelist/bulk-upload` — CSV/text upload for bulk adds

**Whitelist Entry Fields:** email, status (approved/pending/blocked), is_admin flag, invited_at, registered_at

**Acceptance Criteria:**
- Email not on whitelist → login attempt returns 403
- Add email to whitelist → user can log in immediately
- Bulk upload CSV → all valid emails added atomically

---

## 10. Module: NIDP Admin Operations

### FR-ADM-014 — NIDP Jobs Control Panel
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-014 |
| **Module** | NIDP Admin |
| **Feature** | 13-Ingester Job Control |
| **Priority** | High |
| **Source** | `routes/admin_nidp.py`, `src/components/admin/NidpJobsPanel.jsx` |
| **Status** | Live |

**API:** `GET /api/admin/nidp/jobs` / `POST /api/admin/nidp/jobs/{ingester}/execute`

**13 Ingesters Controllable:**
1. bhavcopy (NSE daily OHLCV)
2. delivery (NSE delivery data)
3. index_close (NSE index closes)
4. fii_dii (FII/DII flows)
5. corporate_actions (splits, dividends)
6. bulk_deals (bulk/block deals)
7. rbi_yields (RBI yield curve)
8. fred_macro (FRED macro indicators)
9. yfinance (market data fallback)
10. amfi_nav (AMFI daily NAV)
11. index_constituents (index membership)
12. corporate_announcements (NSE+BSE filings)
13. documents (PDF parsing + chunking)

**Job Status Per Ingester:** last_run, status (OK/FAILED/RUNNING), rows_ingested, duration_ms, error_msg

---

### FR-ADM-015 — NIDP Diagnostics
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-015 |
| **Module** | NIDP Admin |
| **Feature** | Diagnostic Bundle |
| **Priority** | Medium |
| **Source** | `routes/admin_nidp.py` — `POST /api/admin/nidp/dump` |
| **Status** | Live |

Runs a full system diagnostic: connectivity checks, table row counts, last-ingestion dates, data freshness per feed. Returns structured JSON bundle.

---

### FR-ADM-016 — NIDP Backfill Control
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-016 |
| **Module** | NIDP Admin |
| **Feature** | Historical Backfill Orchestration |
| **Priority** | High |
| **Source** | `routes/admin_nidp_backfill.py`, `src/components/admin/NidpBackfillPanel.jsx` |
| **Status** | Live |

**API:** `GET /api/admin/nidp/backfill/readiness`

**Readiness Matrix:** Shows per-feed readiness status before triggering backfill:
- Feed name
- Current row count
- Earliest date available
- Gap days (days missing from target range)
- Ready to backfill (yes/no)

**Backfill Trigger:** SSH-driven Cloud Run job trigger for date-range backfill (`--from YYYY-MM-DD --to YYYY-MM-DD`)

---

### FR-ADM-017 — NIDP Replay Engine
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-017 |
| **Module** | NIDP Admin |
| **Feature** | Data Replay Policies |
| **Priority** | Medium |
| **Source** | `routes/admin_nidp_replay.py`, `src/components/admin/NidpReplayPanel.jsx` |
| **Status** | Live |

**API:** `GET /api/admin/nidp/replay/policies` (proxy with graceful fallback to built-in policies)

Allows replaying historical ingestion from raw archives (GCS) to reprocess data with updated parsers or validators.

---

### FR-ADM-018 — NIDP Data Quality Dashboard
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-018 |
| **Module** | NIDP Admin |
| **Feature** | Data Quality Monitoring |
| **Priority** | High |
| **Source** | `src/components/admin/NidpQualityDashboard.jsx` (53 KB — largest admin component) |
| **Status** | Live |

**Sections:**
1. **Validation Failures** — recent DQ failures by feed (BLOCK/FIX/WARN severity)
2. **Quality Trends** — pass rate % per feed over last 30 days
3. **DQ Rules** — all active validation rules with trigger conditions
4. **AI Suggestions** (`NidpDqAiPanel.jsx`) — AI-generated fix suggestions for active DQ issues

---

## 11. Module: Admin Frontend Shell

### FR-ADM-019 — Admin View Orchestrator
| Field | Value |
|---|---|
| **Requirement ID** | FR-ADM-019 |
| **Module** | Admin UI |
| **Feature** | Multi-Tab Admin Panel |
| **Priority** | High |
| **Source** | `src/components/AdminView.js` |
| **Status** | Live |

**Admin Tab Navigation (sub-tabs within admin area):**
| Tab | Section |
|---|---|
| Users | User table + whitelist |
| Rules | V2 engine rules + prompts |
| CAS | Parser config + sandbox |
| Feature Flags | Feature flag toggles |
| Data Pipeline | Scheduler + job monitor |
| NIDP Jobs | 13-ingester job panel |
| V3 Engine | MF weights / stock weights / master catalogue |
| Datastores | Postgres/Redis status + control |
| NIDP DQ | Quality dashboard |
| NIDP Backfill | Backfill readiness + trigger |

**Access Control:** Tab only rendered for `user.is_admin = true` or `user.role = "admin"` in frontend (double-gated — backend also enforces)

---

## 12. Gap Analysis — Admin Console (Docs vs Code)

| Documented Feature | Code Status | Notes |
|---|---|---|
| Audit log viewer UI | **NOT IMPLEMENTED** | Audit log data exists in MongoDB; viewer UI is roadmap item |
| Automated data retention sweeps | **NOT IMPLEMENTED** | Planned; no scheduler for CAS PDF deletion |
| DPO alerting on suspicious access | **NOT IMPLEMENTED** | Roadmap item |
| Admin MFA requirement | **NOT IMPLEMENTED** | Admin role-check only; no additional MFA step |
| SIEM integration | **NOT IMPLEMENTED** | Security PRD item; not in scope yet |
| Grafana dashboard embed | **SCAFFOLDED** | NidpGrafanaEmbed.jsx exists but no Grafana instance configured |

---

## 13. Requirement Traceability Matrix

| Req ID | Feature | Status | Backend Route | Frontend Component | Priority |
|---|---|---|---|---|---|
| FR-ADM-001 | Secrets | IMPLEMENTED | routes/admin.py | SecretsSection.jsx | Critical |
| FR-ADM-002 | Feature Flags | IMPLEMENTED | routes/admin.py | FeatureFlagsSection.jsx | High |
| FR-ADM-003 | Rules Config | IMPLEMENTED | routes/admin_rules.py | RulesConfigSection.jsx | Critical |
| FR-ADM-004 | Custom DSL Rules | IMPLEMENTED | routes/admin_rules.py | RulesConfigSection.jsx | Medium |
| FR-ADM-005 | Prompt Sandbox | IMPLEMENTED | routes/admin_rules.py | PromptsSection.jsx | High |
| FR-ADM-006 | Pipeline Monitor | IMPLEMENTED | routes/admin_data_pipeline.py | DataPipelineMonitor.jsx | High |
| FR-ADM-007 | V3 MF Weights | IMPLEMENTED | routes/admin_v3_weights.py | V3WeightsSection.jsx | High |
| FR-ADM-008 | V3 Stock Weights | IMPLEMENTED | routes/admin_v3_stock.py | V3StockWeightsSection.jsx | Medium |
| FR-ADM-009 | V3 Master Funds | IMPLEMENTED | routes/admin_v3_master.py | V3MasterFundsSection.jsx | Medium |
| FR-ADM-010 | Datastores | IMPLEMENTED | routes/admin_datastores.py | DatastoreSection.jsx | High |
| FR-ADM-011 | CAS Config | IMPLEMENTED | (routes/admin.py) | CasConfigSection.jsx | High |
| FR-ADM-012 | User Management | IMPLEMENTED | routes/admin_users.py | UserManagementSection.jsx | High |
| FR-ADM-013 | Whitelist | IMPLEMENTED | routes/admin.py | (UserManagementSection) | Critical |
| FR-ADM-014 | NIDP Jobs | IMPLEMENTED | routes/admin_nidp.py | NidpJobsPanel.jsx | High |
| FR-ADM-015 | NIDP Diagnostics | SCAFFOLDED | routes/admin_nidp.py | NidpDiagnosticsPanel.jsx | Medium |
| FR-ADM-016 | NIDP Backfill | IMPLEMENTED | routes/admin_nidp_backfill.py | NidpBackfillPanel.jsx | High |
| FR-ADM-017 | NIDP Replay | IMPLEMENTED | routes/admin_nidp_replay.py | NidpReplayPanel.jsx | Medium |
| FR-ADM-018 | NIDP DQ | IMPLEMENTED | (admin_nidp.py) | NidpQualityDashboard.jsx | High |
| FR-ADM-019 | Admin Shell | IMPLEMENTED | — | AdminView.js | High |

---

*Document generated May 2026. Validated against commit on branch `nivesh-v2-copilot`. All admin routes require `is_admin=true`.*
