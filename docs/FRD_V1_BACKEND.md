# Functional Requirements Document — NIVESH V1 BACKEND
**Layer:** Nivesh V1 Backend (Base Platform Layer)
**Status:** VALIDATED AGAINST CODE — May 2026
**Validation Source:** `/app/backend/routes/`, `/app/backend/services/`, `/app/backend/models.py`, `/app/backend/repository.py`, `/app/backend/tests/`

---

## DOCUMENT NOTES — What "V1 Backend" Means

> **IMPORTANT:** There is no separate V1 codebase. The current backend is a single FastAPI monolith that is layered:
> - **V1 = Base platform features** — authentication, user management, CAS upload, basic portfolio CRUD, basic scoring heuristics, basic insights (deterministic rules), goals, and the core infrastructure (middleware, logging, error handling, rate limiting, CORS, session management).
> - **V2 = Advanced engine features** — 38-primitive V3 scoring, action plan rules engine, portfolio intelligence, health scoring — documented in `FRD_V2_BACKEND.md`.
>
> This document covers all V1 base-platform requirements, validated against actual code as of May 2026.

---

## 1. Module: Authentication & Session Management

### FR-AUTH-001 — Google OAuth Sign-In
| Field | Value |
|---|---|
| **Requirement ID** | FR-AUTH-001 |
| **Module** | Authentication |
| **Feature** | Google OAuth Login |
| **Priority** | Critical |
| **Source** | `routes/auth.py`, `deps.py` |
| **Status** | Live |

**Description:** Users authenticate using Google OAuth 2.0. Backend exchanges a Google `id_token` (sent by frontend) for a validated session cookie.

**Actors:** Unauthenticated user, Google OAuth service

**API:** `POST /api/auth/google`

**Inputs:**
- `credential` (string) — Google id_token from Google Identity Services JS SDK

**Processing Logic:**
1. Verify `id_token` via Google tokeninfo endpoint
2. Extract `email`, `name`, `picture`, `sub` (Google user ID)
3. Check `whitelisted_users` collection — reject if email not found or `status != "approved"`
4. Upsert user record in `users` collection (idempotent)
5. Create `user_sessions` record with `session_token` (UUID), `expires_at` = now + 7 days
6. Set HttpOnly cookie `session_token` with configured `Secure`, `SameSite` flags
7. Record DPDP audit log entry for login event

**Business Rules:**
- Whitelist check is mandatory — no open registration
- Session TTL = 7 days; no sliding-window extension in V1
- Cookie attributes configurable via env: `COOKIE_SECURE`, `COOKIE_SAMESITE`

**Error Conditions:**
- `401` — invalid or expired Google token
- `403` — email not on whitelist
- `500` — database error during user upsert

**Acceptance Criteria:**
- Valid Google token + whitelisted email → 200, session cookie set, user returned
- Valid Google token + non-whitelisted email → 403 with `NOT_WHITELISTED` code
- Invalid/malformed token → 401
- Re-login by existing user does not duplicate user record

---

### FR-AUTH-002 — Get Current Session User
| Field | Value |
|---|---|
| **Requirement ID** | FR-AUTH-002 |
| **Module** | Authentication |
| **Feature** | Current User Profile |
| **Priority** | Critical |
| **Source** | `routes/auth.py` |
| **Status** | Live |

**API:** `GET /api/auth/me`

**Processing Logic:**
1. Read `session_token` from HttpOnly cookie
2. Look up `user_sessions` — reject if expired or not found
3. Fetch user from `users` collection
4. Return user object + profile flags (onboarding_completed, role, risk_profile)

**Acceptance Criteria:**
- Valid unexpired session → 200 with user profile
- Missing/invalid/expired session → 401

---

### FR-AUTH-003 — Logout
| Field | Value |
|---|---|
| **Requirement ID** | FR-AUTH-003 |
| **Module** | Authentication |
| **Feature** | Session Logout |
| **Priority** | High |
| **Source** | `routes/auth.py` |
| **Status** | Live |

**API:** `POST /api/auth/logout`

**Processing Logic:**
1. Read session_token from cookie
2. Delete session record from `user_sessions`
3. Clear cookie (set Max-Age=0)
4. Record DPDP audit log entry for logout event

**Acceptance Criteria:**
- Logout → session deleted, cookie cleared, subsequent `/me` returns 401

---

### FR-AUTH-004 — Role-Based Access Control (RBAC)
| Field | Value |
|---|---|
| **Requirement ID** | FR-AUTH-004 |
| **Module** | Authentication |
| **Feature** | Role Enforcement |
| **Priority** | Critical |
| **Source** | `deps.py` — `require_role()`, `_is_role()` |
| **Status** | Live |

**Roles Defined:**
| Role | Permissions |
|---|---|
| `user` | Own data only |
| `advisor` | Own + assigned client data |
| `support` | Limited masked read access |
| `admin` | All operations including admin console |

**Business Rules:**
- Legacy `is_admin: bool` field supported alongside new `role` enum (migration path)
- `require_admin()` = shorthand for `require_role("admin")`
- All protected routes use `Depends(require_role(...))` FastAPI dependency injection

---

### FR-AUTH-005 — Rate Limiting
| Field | Value |
|---|---|
| **Requirement ID** | FR-AUTH-005 |
| **Module** | Security |
| **Feature** | Per-path Rate Limiting |
| **Priority** | High |
| **Source** | `middleware.py` — `RateLimitMiddleware` |
| **Status** | Live |

**Rate Limits:**
| Path Pattern | Limit |
|---|---|
| `/chat/warmup` | Exempt (idempotent fire-and-forget) |
| `/chat/stream` | 30 req/min |
| `/chat/*`, `/insights/*` | 200 req/min |
| All other paths | 300 req/min |

**Implementation:** In-memory sliding-window per session/IP/auth header. Returns `429` with standard error envelope on breach.

---

## 2. Module: User Onboarding & Profile

### FR-USER-001 — Journey Type Selection
| Field | Value |
|---|---|
| **Requirement ID** | FR-USER-001 |
| **Module** | User Onboarding |
| **Feature** | Journey Selection |
| **Priority** | High |
| **Source** | `routes/user.py` |
| **Status** | Live |

**API:** `POST /api/user/journey`

**Inputs:**
- `journey_type` (enum): `existing_investor` | `new_investor` | `mfd_advisor`

**Processing Logic:** Record journey type in `user_profiles` collection. Determines subsequent UX flow.

---

### FR-USER-002 — Risk Profile Questionnaire
| Field | Value |
|---|---|
| **Requirement ID** | FR-USER-002 |
| **Module** | User Onboarding |
| **Feature** | Risk Assessment |
| **Priority** | Critical |
| **Source** | `routes/user.py` |
| **Status** | Live |

**API:** `POST /api/user/risk-profile`

**6-Question Assessment:**
| # | Question | Options |
|---|---|---|
| 1 | Market drops 20% — what do you do? | Buy more / Hold / Sell some / Sell all |
| 2 | Investment horizon | < 1yr / 1–3yr / 3–5yr / 5–10yr / 10yr+ |
| 3 | Acceptable loss on ₹1L investment | Up to ₹50K / ₹25K / ₹10K / None |
| 4 | Income stability | Very stable / Stable / Somewhat / Unstable |
| 5 | Investment knowledge | Expert / Intermediate / Basic / Beginner |
| 6 | Primary investment goal | Aggressive growth / Growth / Preservation / Capital safety |

**Scoring Formula:** Weighted answers → numeric score (10–90 scale)

**Risk Categories (output):**
| Score Range | Category |
|---|---|
| 70–90 | Aggressive |
| 55–69 | Moderately Aggressive |
| 40–54 | Moderate |
| 25–39 | Moderately Conservative |
| 10–24 | Conservative |

**Output:** Risk score + category + recommended asset allocation (equity/debt/gold/cash percentages)

**Acceptance Criteria:**
- All 6 questions answered → score computed → category returned
- Score stored in `user_profiles`
- Category drives debt floor rules in action plan engine (see FR-PLAN-005 in V2 FRD)

---

### FR-USER-003 — Quick Setup (New Investor)
| Field | Value |
|---|---|
| **Requirement ID** | FR-USER-003 |
| **Module** | User Onboarding |
| **Feature** | Quick Portfolio Setup |
| **Priority** | Medium |
| **Source** | `routes/user.py` |
| **Status** | Live |

**API:** `POST /api/user/quick-setup`

**Inputs:**
- `age` (int, 18–100)
- `goal` (enum): `retirement` | `house` | `education` | `travel` | `wealth` | `emergency`
- `risk` (enum): `conservative` | `moderate` | `aggressive`
- `horizon` (enum): `short` | `medium` | `long` | `very_long`
- `monthly_investment` (float, INR)

**Processing Logic:**
1. Derive asset allocation (equity/debt/gold/cash) from age + risk profile
2. Compute SIP projection: `FV = PMT × [((1+r)^n − 1) / r]` where r = monthly rate, n = months
3. Return allocation + projected corpus + recommended fund categories

**Acceptance Criteria:**
- Age 25 + aggressive + 20yr → high equity allocation
- Age 55 + conservative + 5yr → high debt allocation
- SIP projection formula matches standard financial calculator output

---

### FR-USER-004 — Onboarding Completion
| Field | Value |
|---|---|
| **Requirement ID** | FR-USER-004 |
| **Module** | User Onboarding |
| **Feature** | Onboarding Status Flag |
| **Priority** | Medium |
| **Source** | `routes/user.py`, `deps.py` |
| **Status** | Live |

**API:** `POST /api/user/complete-onboarding`

Sets `onboarding_completed = true` in `user_profiles`. Founder accounts are auto-seeded as already onboarded.

---

## 3. Module: Portfolio Management

### FR-PORT-001 — Create Portfolio
| Field | Value |
|---|---|
| **Requirement ID** | FR-PORT-001 |
| **Module** | Portfolio |
| **Feature** | Multi-Portfolio Creation |
| **Priority** | High |
| **Source** | `routes/portfolio.py` |
| **Status** | Live |

**API:** `POST /api/portfolios`

**Inputs:**
- `name` (string) — portfolio label
- `member_name` (string) — account holder name (supports family portfolios)
- `relationship` (enum): `Self` | `Spouse` | `Child` | `Parent` | `Sibling` | `Other`

**Business Rules:**
- Each user can have multiple portfolios (family/joint account support)
- Portfolio is the top-level container; holdings belong to a portfolio

---

### FR-PORT-002 — CAS PDF Upload & Parsing
| Field | Value |
|---|---|
| **Requirement ID** | FR-PORT-002 |
| **Module** | Portfolio |
| **Feature** | CAS Import |
| **Priority** | Critical |
| **Source** | `routes/upload.py`, `services/cas_api_client.py`, `services/cas_parser.py` |
| **Status** | Live |

**API:** `POST /api/portfolio/cas-upload`

**Three-Provider Fallback Chain:**
| Priority | Provider | Mechanism |
|---|---|---|
| 1 (default) | Nivesh Parser | Google Document AI — parallel 3-worker chunked processing, ≤12 pages/chunk |
| 2 (fallback) | Claude Vision | Anthropic Claude Sonnet — page-by-page base64 PNG extraction, 6 pages/batch, max 24 pages |
| 3 (final fallback) | casparser.in API | External REST API; supports NSDL/CDSL/CAMS/KFintech format variants |

**What Gets Extracted:**
- Investor name, PAN, email, statement date
- All mutual fund folios: scheme name, AMFI code, plan type, ISIN, units, NAV, value
- All equity holdings: ISIN, symbol, quantity, value
- All transactions: buy/sell/SIP/switch/IDCW, dates, amounts, NAV
- SGBs, ETFs, bonds, preference shares

**Post-Parse Processing:**
1. Holdings deduplication — Regular + Direct variants of same scheme collapsed
2. Cost basis reconstruction — FIFO matching from transaction history
3. Buy-date inference — earliest transaction date per folio
4. SIP detection — recurring transactions at consistent intervals tagged as SIPs
5. Portfolio snapshot — each upload frozen as time-machine snapshot

**Validation Rules:**
- File must be PDF format (MIME validated)
- File size limit enforced (max 25 MB)
- Auto-fallback on provider failure — first non-empty result wins
- `BudgetExceededError` (Claude token budget) treated as fallback-eligible, not fatal

**Acceptance Criteria:**
- Valid NSDL CAS PDF → holdings extracted, deduplicated, inserted to MongoDB
- Provider fallback: if provider 1 fails → provider 2 auto-tried → provider 3 if still empty
- Empty parse result → user shown error, no holdings inserted
- Duplicate CAS upload → existing holdings updated/merged, not duplicated
- Password-protected CAS → hint shown to user (password = PAN)

---

### FR-PORT-003 — Holdings CRUD
| Field | Value |
|---|---|
| **Requirement ID** | FR-PORT-003 |
| **Module** | Portfolio |
| **Feature** | Manual Holdings Management |
| **Priority** | High |
| **Source** | `routes/portfolio.py`, `repository.py` |
| **Status** | Live |

**APIs:**
- `GET /api/portfolio/holdings` — list all holdings with live prices
- `POST /api/portfolio/holdings` — add single holding
- `PUT /api/portfolio/holdings/{id}` — edit holding (qty, price, buy_date)
- `DELETE /api/portfolio/holdings/{id}` — remove holding
- `DELETE /api/portfolio/holdings-all` — clear all holdings (destructive)

**Holdings Schema:**
```
holding_id, user_id, portfolio_id, name, ticker, asset_type, 
quantity, buy_price, current_price, buy_date, sector, category, 
instrument_id (FK to PostgreSQL instrument_master)
```

**Asset Types Supported:**
`equity` | `mutual_fund` | `etf` | `bond` | `gold` | `fd` | `other`

**Business Rules:**
- `buy_date` edit triggers LTCG/STCG recalculation in tax engine
- `buy_price = 0` triggers `tax_impact_pending = True` flag in plan actions
- `current_price` updated by live price polling service

**Acceptance Criteria:**
- Add holding → immediately visible in holdings list
- Edit buy_date → tax classification updates (LTCG/STCG re-evaluated)
- Delete holding → removed from all downstream analytics

---

### FR-PORT-004 — Instrument Search
| Field | Value |
|---|---|
| **Requirement ID** | FR-PORT-004 |
| **Module** | Portfolio |
| **Feature** | Instrument Lookup |
| **Priority** | Medium |
| **Source** | `routes/portfolio.py` |
| **Status** | Live |

**API:** `GET /api/search/instruments?q=<query>&type=<asset_type>`

**Processing:** Fuzzy search across `instrument_master` (735 instruments: 712 equity + 23 MF). Returns matched instruments with ISIN, symbol, name, type.

---

### FR-PORT-005 — Portfolio Export
| Field | Value |
|---|---|
| **Requirement ID** | FR-PORT-005 |
| **Module** | Portfolio |
| **Feature** | CSV Export |
| **Priority** | Medium |
| **Source** | `routes/portfolio.py` |
| **Status** | Live |

**API:** `GET /api/portfolio/export/csv`

Returns holdings as CSV with all fields including buy_price, current_price, ISIN, category, sector.

---

### FR-PORT-006 — Portfolio Time-Machine Snapshots
| Field | Value |
|---|---|
| **Requirement ID** | FR-PORT-006 |
| **Module** | Portfolio |
| **Feature** | Historical State |
| **Priority** | High |
| **Source** | `services/cas_snapshot_engine.py` |
| **Status** | Live |

**Description:** Every CAS upload creates a frozen point-in-time snapshot. Each snapshot stores holdings, valuations, asset allocation at that date.

**API:** `GET /api/portfolio/snapshots`

**Business Rules:**
- Snapshots are append-only (never modified after creation)
- Default view = latest snapshot
- Historical snapshots queryable by date (useful for tax filing)
- Nightly EOD snapshot created at 23:30 IST

---

## 4. Module: Basic Portfolio Insights (Deterministic Rules)

### FR-INS-001 — Generate Deterministic Insights
| Field | Value |
|---|---|
| **Requirement ID** | FR-INS-001 |
| **Module** | Insights |
| **Feature** | Rule-Based Portfolio Insights |
| **Priority** | Critical |
| **Source** | `routes/insights.py` lines 166–449, `_deterministic_insights()` |
| **Status** | Live |

**API:** `POST /api/insights/generate`

**NOTE:** LLM was removed from this path in Feb 2026. All insights are now deterministic Python rules. The old LLM system prompt (lines 1–164 of insights.py) is retained as a comment but is no longer invoked.

**Insight Categories Generated:**
| Category | Trigger Condition | Output Type |
|---|---|---|
| AMC Concentration | Single AMC > 30% of portfolio | Warning |
| Category Concentration | Single SEBI category > 35% of MF AUM | Warning |
| Fund Overlap | Pairwise stock overlap > 50% | Warning |
| Regular→Direct Cost Leak | Annual savings > ₹5,000 available | Opportunity |
| Expense Ratio Outlier | Fund ER > 1.5× category median | Warning |
| Allocation Gap | Debt < risk-profile floor | Opportunity |
| Stale Data | No NAV update > 30 days | Info |
| Underperformer Alert | ret_3y < category avg by > 3pp | Warning |
| High Drawdown | max_drawdown > 35% | Warning |
| Turnover Alert | turnover_ratio > 100% | Info |

**Business Rules:**
- Insights are deterministic — same input always produces same output
- No LLM in analytics path
- Insights stored in `ai_insights` MongoDB collection
- Each insight has: type, title, description, impact, effort, current_value, target_value, affected_funds

**Acceptance Criteria:**
- Portfolio with 60% HDFC AMC → AMC Concentration insight generated
- Portfolio with Regular plan + Direct plan of same fund → Cost Leak insight generated
- Fund with 0% debt in aggressive-risk profile → Allocation Gap opportunity generated
- Re-running insights with identical portfolio → identical results (deterministic)

---

## 5. Module: Goals-Based Planning

### FR-GOAL-001 — Financial Snapshot
| Field | Value |
|---|---|
| **Requirement ID** | FR-GOAL-001 |
| **Module** | Goals |
| **Feature** | Financial Profile Capture |
| **Priority** | High |
| **Source** | `routes/goals.py` |
| **Status** | Live |

**API:** `PUT /api/goals/snapshot`

**Inputs:**
- `age` (int)
- `monthly_income` (float, INR)
- `monthly_expenses` (float, INR)
- `total_corpus` (float, INR)
- `total_liabilities` (float, INR)
- `risk_profile` (string)

Stored in PostgreSQL `user_financial_snapshots` table.

---

### FR-GOAL-002 — Create Investment Goal
| Field | Value |
|---|---|
| **Requirement ID** | FR-GOAL-002 |
| **Module** | Goals |
| **Feature** | Goal Creation |
| **Priority** | High |
| **Source** | `routes/goals.py`, `services/goal_engine.py` |
| **Status** | Live |

**API:** `POST /api/goals`

**Inputs:**
- `goal_type` (enum): `retirement` | `house` | `education` | `emergency` | `custom`
- `goal_name` (string)
- `target_amount_rs` (float)
- `horizon_years` (int)
- `current_corpus_rs` (float, optional)
- `monthly_sip_rs` (float, optional)

**Processing Logic:**
1. Validate max 4 active goals per user (forces prioritization)
2. Auto-allocation based on risk profile + horizon
3. Auto-pick funds per allocation bucket
4. Run Monte Carlo simulation → compute `on_track_pct` (success probability)
5. Store goal in PostgreSQL `user_goals` table

**Business Rules:**
- Max 4 active goals per user
- Auto-allocation: equity % decreases as horizon decreases
- Monte Carlo: 500+ trials with ±σ CAGR variance

**Acceptance Criteria:**
- 5th goal creation attempt → rejected with `MAX_GOALS_REACHED` error
- Goal with 20yr horizon + moderate risk → ≥60% equity allocation
- on_track_pct computed and stored

---

### FR-GOAL-003 — Goal Tracking & SIP Reconciliation
| Field | Value |
|---|---|
| **Requirement ID** | FR-GOAL-003 |
| **Module** | Goals |
| **Feature** | Actual vs Planned SIP Tracking |
| **Priority** | High |
| **Source** | `routes/goals.py` |
| **Status** | Live |

**API:** `GET /api/goals`

**Processing Logic:**
- Compares planned SIP against actual CAS-ingested transactions (6-month lookback)
- Flags SIP gaps: "plan says ₹50K/mo but actual inflows are ₹5K/mo"
- Returns `on_track_pct` per goal

---

### FR-GOAL-004 — Goal Simulation & What-If
| Field | Value |
|---|---|
| **Requirement ID** | FR-GOAL-004 |
| **Module** | Goals |
| **Feature** | Monte Carlo Simulation |
| **Priority** | Medium |
| **Source** | `routes/goals.py`, `services/goal_engine.py` |
| **Status** | Live |

**APIs:**
- `POST /api/goals/{goal_id}/simulate` — fresh Monte Carlo + scenario analysis
- `POST /api/goals/{goal_id}/what-if` — preview hypothetical adjustments without persisting

---

## 6. Module: Broker Integration

### FR-BROKER-001 — Read-Only Portfolio Connect
| Field | Value |
|---|---|
| **Requirement ID** | FR-BROKER-001 |
| **Module** | Broker Integration |
| **Feature** | Broker Holdings Import |
| **Priority** | High |
| **Source** | `routes/broker_connect.py`, `services/broker_connect.py` |
| **Status** | Live |

**Supported Brokers (read-only):**
Zerodha, Upstox, Angel One, Dhan, Fyers, 5Paisa, Kotak Securities, IIFL, HDFC Securities

**Architecture:** Each broker adapter in `backend/routes/broker_connect.py` + `backend/routes/broker_native.py` handles OAuth flow, holdings fetch, and data normalization to Nivesh schema.

**Security Rules:**
- Read-only scopes only — NO order placement
- Broker tokens stored encrypted per-user
- Tokens never logged
- OpenAlgo SPC reverse-proxy: broker credentials never leave user's local instance

**Data Flow:** Broker holdings → normalize → upsert to MongoDB holdings → same scoring pipeline as CAS-parsed holdings

---

## 7. Module: Compliance (DPDP Act 2023)

### FR-COMP-001 — Consent Management
| Field | Value |
|---|---|
| **Requirement ID** | FR-COMP-001 |
| **Module** | Compliance |
| **Feature** | DPDP Consent Log |
| **Priority** | High |
| **Source** | `routes/compliance.py` |
| **Status** | Scaffolded |

**API:** `POST /api/compliance/consents`

Logs explicit, timestamped consent per data category. Required for DPDP Act 2023 compliance.

---

### FR-COMP-002 — Data Export (Right to Access)
| Field | Value |
|---|---|
| **Requirement ID** | FR-COMP-002 |
| **Module** | Compliance |
| **Feature** | Data Audit Export |
| **Priority** | High |
| **Source** | `routes/compliance.py` |
| **Status** | Scaffolded |

**API:** `POST /api/compliance/audit-export`

Generates full data audit trail for the requesting user. Includes all holdings, insights, plans, audit events.

---

### FR-COMP-003 — Right to Be Forgotten
| Field | Value |
|---|---|
| **Requirement ID** | FR-COMP-003 |
| **Module** | Compliance |
| **Feature** | Data Deletion |
| **Priority** | High |
| **Source** | `routes/compliance.py` |
| **Status** | Scaffolded |

**API:** `POST /api/compliance/data-deletion`

Wipes all PII and analytics data for the user. Cascades to 21 MongoDB collections + Redis caches.

---

## 8. Module: Market Data (MF NAV)

### FR-NAV-001 — Daily NAV Ingestion
| Field | Value |
|---|---|
| **Requirement ID** | FR-NAV-001 |
| **Module** | Market Data |
| **Feature** | AMFI NAV Refresh |
| **Priority** | Critical |
| **Source** | `services/mf_scheduler.py`, `services/amfi_nav.py` |
| **Status** | Live |

**Schedule:** Daily at 22:00 IST (APScheduler, Asia/Kolkata)

**Processing:** Fetches 14,000 EOD NAVs from AMFI `NAVAll.txt`. Upserts to `mutual_fund_nav_history` PostgreSQL table. Audit record written to `amfi_nav_fetch_log`.

**Current Data:** 33,994+ NAV rows across all schemes.

---

## 9. Infrastructure Requirements

### FR-INFRA-001 — Structured Logging
| Field | Value |
|---|---|
| **Requirement ID** | FR-INFRA-001 |
| **Module** | Infrastructure |
| **Feature** | Correlation-ID Logging |
| **Priority** | High |
| **Source** | `core/logging_config.py`, `core/correlation.py` |
| **Status** | Live |

**Log Format:** JSON to stdout with fields: `ts`, `level`, `logger`, `msg`, `service`, `env`, `correlationId`, `elapsed_ms`

**Sensitive Masking:** Automatic masking of: password, token, pan, aadhaar. Email masked as `a***@domain.com`.

---

### FR-INFRA-002 — Standard Error Envelope
| Field | Value |
|---|---|
| **Requirement ID** | FR-INFRA-002 |
| **Module** | Infrastructure |
| **Feature** | Error Handling |
| **Priority** | High |
| **Source** | `core/error_handlers.py`, `core/exceptions.py` |
| **Status** | Live |

**Error Envelope:**
```json
{
  "timestamp": "ISO8601",
  "status": 400,
  "error": "VALIDATION_ERROR",
  "code": "VAL-001",
  "message": "Human-readable message",
  "details": [{"field": "email", "message": "Invalid format"}],
  "correlationId": "uuid4",
  "path": "/api/users"
}
```

**Exception Hierarchy:**
- `ValidationException` → VAL-001, 400
- `BusinessException` → BIZ-001, 422
- `ResourceNotFoundException` → RES-001, 404
- `IntegrationException` → INT-001, 502
- `AuthenticationException` → AUTH-001, 401
- `AuthorizationException` → AUTHZ-001, 403
- `RateLimitException` → RATE-001, 429
- `SystemException` → SYS-001, 500

---

### FR-INFRA-003 — Security Headers (OWASP)
| Field | Value |
|---|---|
| **Requirement ID** | FR-INFRA-003 |
| **Module** | Security |
| **Feature** | HTTP Security Headers |
| **Priority** | High |
| **Source** | `middleware.py` — `SecurityHeadersMiddleware` |
| **Status** | Live |

**Headers Applied:**
- `Content-Security-Policy` — allows Google OAuth + self origin
- `Strict-Transport-Security` — only when HTTPS
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Permissions-Policy` — blocks camera, microphone, geolocation, payment

---

## 10. Gap Analysis — V1 Backend (Docs vs Code)

| Documented Requirement | Code Status | Notes |
|---|---|---|
| Mobile OTP Login (FR-AUTH-002 in Security PRD) | **NOT IMPLEMENTED** | Only Google OAuth in code; OTP login not found |
| PAN AES-256 Encryption (SECURITY_PRD) | **NOT IMPLEMENTED** | PAN stored plaintext; P1 backlog |
| Virus scanning of uploads (FR-UPLOAD-002) | **NOT IMPLEMENTED** | MIME validation only; no AV scan |
| JWT access tokens (FR-AUTH-004) | **NOT IMPLEMENTED** | Session cookies used, not JWTs |
| Refresh token rotation (FR-AUTH-005) | **NOT IMPLEMENTED** | No refresh token mechanism |
| MFA for admin (FR-RBAC-004) | **NOT IMPLEMENTED** | Admin role-check only; no MFA |
| DPDP formal compliance | **SCAFFOLDED ONLY** | Routes exist, consent versioning incomplete |
| 99.9% uptime SLA | **NOT MEASURED** | No uptime monitoring configured |

---

## 11. Requirement Traceability Matrix

| Req ID | Feature | Status | API Endpoint | Test File | Priority |
|---|---|---|---|---|---|
| FR-AUTH-001 | Google OAuth | IMPLEMENTED | POST /api/auth/google | test_auth.py | Critical |
| FR-AUTH-002 | Current User | IMPLEMENTED | GET /api/auth/me | test_auth.py | Critical |
| FR-AUTH-003 | Logout | IMPLEMENTED | POST /api/auth/logout | test_auth.py | High |
| FR-AUTH-004 | RBAC | PARTIAL | (dependency) | test_rules_admin.py | Critical |
| FR-AUTH-005 | Rate Limiting | IMPLEMENTED | (middleware) | — | High |
| FR-USER-001 | Journey Type | IMPLEMENTED | POST /api/user/journey | — | High |
| FR-USER-002 | Risk Profile | IMPLEMENTED | POST /api/user/risk-profile | — | Critical |
| FR-USER-003 | Quick Setup | IMPLEMENTED | POST /api/user/quick-setup | — | Medium |
| FR-USER-004 | Onboarding | IMPLEMENTED | POST /api/user/complete-onboarding | — | Medium |
| FR-PORT-001 | Create Portfolio | IMPLEMENTED | POST /api/portfolios | — | High |
| FR-PORT-002 | CAS Upload | IMPLEMENTED | POST /api/portfolio/cas-upload | — | Critical |
| FR-PORT-003 | Holdings CRUD | IMPLEMENTED | GET/POST/PUT/DELETE /api/portfolio/holdings | — | High |
| FR-PORT-004 | Search | IMPLEMENTED | GET /api/search/instruments | — | Medium |
| FR-PORT-005 | Export | IMPLEMENTED | GET /api/portfolio/export/csv | — | Medium |
| FR-PORT-006 | Snapshots | IMPLEMENTED | GET /api/portfolio/snapshots | — | High |
| FR-INS-001 | Insights | IMPLEMENTED | POST /api/insights/generate | test_deterministic_insights.py | Critical |
| FR-GOAL-001 | Snapshot | IMPLEMENTED | PUT /api/goals/snapshot | — | High |
| FR-GOAL-002 | Create Goal | IMPLEMENTED | POST /api/goals | — | High |
| FR-GOAL-003 | Goal Tracking | IMPLEMENTED | GET /api/goals | — | High |
| FR-GOAL-004 | Simulation | IMPLEMENTED | POST /api/goals/{id}/simulate | — | Medium |
| FR-BROKER-001 | Broker Connect | PARTIAL | routes/broker_connect.py | — | High |
| FR-COMP-001 | Consent | SCAFFOLDED | POST /api/compliance/consents | — | High |
| FR-COMP-002 | Data Export | SCAFFOLDED | POST /api/compliance/audit-export | — | High |
| FR-COMP-003 | Deletion | SCAFFOLDED | POST /api/compliance/data-deletion | — | High |
| FR-NAV-001 | AMFI NAV | IMPLEMENTED | (scheduler) | — | Critical |
| FR-INFRA-001 | Logging | IMPLEMENTED | (middleware) | test_core_logging.py | High |
| FR-INFRA-002 | Error Envelope | IMPLEMENTED | (middleware) | test_core_exceptions.py | High |
| FR-INFRA-003 | Security Headers | IMPLEMENTED | (middleware) | — | High |

---

*Document generated May 2026. Validated against commit on branch `nivesh-v2-copilot`.*
