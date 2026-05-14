# NIVESH — Test Strategy
**Version:** 1.0 | **Date:** May 2026 | **Author:** QA Framework

---

## 1. Scope

Functional acceptance testing for the NIVESH wealth-management platform covering all 8 FRDs:
V1 Backend · V1 Frontend · V2 Backend · V2 Frontend · Copilot V1 · Copilot V2 · Admin Console · NIDP

**In scope:** All implemented (IMPLEMENTED) and partial (PARTIAL) requirements.
**Out of scope:** PLANNED requirements (FR-COP2-014, FR-COP2-015); performance/load testing; mobile native (Capacitor scaffolded only).

---

## 2. Test Approach

### 2.1 BDD-Style Test Cases
All test cases follow the Given / When / Then structure to ensure business traceability and direct conversion to Playwright/Cucumber scenarios.

```
Given  [system state + preconditions]
When   [user performs specific action]
Then   [system produces specific observable result]
```

### 2.2 Test Types by Module Priority

| Test Type | AUTH | PORTFOLIO | TAX | PLAN | COPILOT | ADMIN |
|---|---|---|---|---|---|---|
| Positive (happy path) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Negative (error paths) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Boundary | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| Security / RBAC | ✓ | ✓ | — | — | ✓ | ✓ |
| Integration | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Regression | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

---

## 3. Risk-Based Priority

### Critical (must pass before any release)
- Google OAuth login and whitelist enforcement
- CAS PDF upload and holdings extraction (all 3 providers)
- Capital gains tax computation (LTCG/STCG rates FY2025-26)
- Action plan generation (6 rules + 4 guardrails)
- V3 scoring engine determinism (same input = same output)
- Admin secrets management and RBAC (403 for non-admin)
- LLM PII safety screening (PAN/Aadhaar never reach OpenAI)

### High
- Holdings CRUD + buy-date tax reclassification
- Goal creation (Monte Carlo, max-4 limit)
- Switch score formula correctness
- Regular→Direct Rule 1 detection
- Copilot intent routing (deterministic, < 1ms)
- Plan state machine (preview→active→archived)
- Feature flag enforcement

### Medium
- CSV export correctness
- Instrument search fuzzy matching
- Market dashboard cache behaviour
- Advisor impersonation data isolation

### Low
- UI collapse/expand localStorage persistence
- INR number formatting edge cases
- Admin prompt sandbox sandbox mode

---

## 4. Test Data Strategy

| Dataset | Contents | Reuse |
|---|---|---|
| `td_user_ahaan` | email: ahaanporwal16@gmail.com, whitelisted, role=user | All auth tests |
| `td_user_admin` | email: admin@nivesh.in, role=admin | Admin tests |
| `td_user_advisor` | email: advisor@nivesh.in, role=advisor | MFD tests |
| `td_cas_nsdl` | Valid NSDL CAS PDF, 15 holdings | CAS upload tests |
| `td_cas_cams` | Valid CAMS CAS PDF, 8 MF holdings | CAS fallback tests |
| `td_portfolio_overlap` | 2 large-cap funds with 70% overlap | Overlap rule tests |
| `td_portfolio_amc_conc` | 60% HDFC AMC, 5 funds | AMC concentration tests |
| `td_portfolio_regular_direct` | HDFC Flexi Cap Regular + Direct held | Rule 1 tests |
| `td_portfolio_debt_gap` | 0% debt, user risk=aggressive | Rule 5 tests |
| `td_holding_stcg` | Equity bought 3 months ago | STCG tax tests |
| `td_holding_ltcg` | Equity bought 18 months ago | LTCG tax tests |
| `td_holding_elss` | ELSS bought 2 years ago | Lock-in tests |
| `td_goals_retirement` | target=₹5Cr, horizon=25yr, sip=₹25K/mo | Goal tests |
| `td_chat_pan` | Message containing "My PAN is ABCDE1234F" | PII safety tests |

---

## 5. Naming Convention

```
TC_<MODULE>_<NNN>
```

Examples:
- `TC_AUTH_001` — Authentication test #1
- `TC_PORTFOLIO_023` — Portfolio test #23
- `TC_TAX_005` — Tax test #5
- `TC_PLAN_011` — Action Plan test #11
- `TC_COPILOT_007` — Copilot test #7
- `TC_ADMIN_003` — Admin test #3

---

## 6. Module Codes

| Code | Module |
|---|---|
| AUTH | Authentication & Session |
| ONBOARD | User Onboarding & Risk Profile |
| PORTFOLIO | Portfolio Management & CAS |
| INSIGHTS | Deterministic Insights |
| GOALS | Goals-Based Planning |
| BROKER | Broker Integration |
| COMPLIANCE | DPDP Compliance |
| V3SCORE | V3 Scoring Engine |
| PLAN | Action Plan Engine |
| INTEL | Portfolio Intelligence |
| HEALTH | Portfolio Health |
| TAX | Tax Engine |
| ENRICH | Enriched Holdings |
| COPILOT | AI Copilot V1 |
| COPILOT2 | AI Copilot V2 |
| ADMIN | Admin Console |
| NIDP | NIDP Data Warehouse |
| UI | Frontend (all UI modules) |

---

## 7. Entry & Exit Criteria

### Entry Criteria
- All FRDs reviewed and approved
- Test environment running (FastAPI + React + MongoDB + PostgreSQL + Redis)
- Test data seeded (whitelist, holdings, NAV data)
- API accessible at base URL

### Exit Criteria
- 100% Critical test cases passed
- 0 open blocker (P0) defects
- ≥ 90% High test cases passed
- Requirement coverage = 100% (all 106 FRD requirements have at least one test)

---

## 8. Automation Approach

Phase 1 — API layer (Playwright API testing):
- AUTH, PORTFOLIO, TAX, PLAN, V3SCORE (all deterministic, stable)

Phase 2 — UI smoke (Playwright browser):
- Login flow, CAS upload, dashboard render, plan board render

Phase 3 — Full E2E regression:
- Critical-path journeys: Login → Upload CAS → Generate Plan → Mark Action Done

### Playwright Conversion Pattern
Each BDD test case maps directly:
```typescript
test('TC_AUTH_001 — Whitelisted user can login via Google OAuth', async ({ page }) => {
  // Given: user is on landing page, Google token is valid
  // When: POST /api/auth/google with valid credential
  // Then: 200 returned, session cookie set, user.email matches
});
```

---

## 9. Defect Severity Definition

| Severity | Definition | Example |
|---|---|---|
| Critical | Blocks core workflow, data loss, security breach | Wrong tax rate applied |
| High | Major feature broken, no workaround | CAS upload fails for all PDFs |
| Medium | Feature degraded, workaround exists | CSV export missing one column |
| Low | Cosmetic, no functional impact | Wrong colour on progress bar |

---

## 10. Tools

| Purpose | Tool |
|---|---|
| Test case management | Google Sheets (from this Excel export) |
| Bug tracking | GitHub Issues |
| API testing | Playwright API / curl / Postman |
| UI automation | Playwright |
| CI integration | GitHub Actions |
| Reporting | Allure Report |
