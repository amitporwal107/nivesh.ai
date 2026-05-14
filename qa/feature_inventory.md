# NIVESH — Feature Inventory
**Generated:** May 2026 | **Branch:** nivesh-v2-copilot | **Source:** All 8 FRDs

---

## Summary

| # | Module Code | Module Name | Features | Priority | Layer |
|---|---|---|---|---|---|
| 1 | AUTH | Authentication & Session | 5 | Critical | V1 Backend |
| 2 | ONBOARD | User Onboarding & Risk Profile | 4 | Critical | V1 Backend |
| 3 | PORTFOLIO | Portfolio Management & CAS Upload | 6 | Critical | V1 Backend |
| 4 | INSIGHTS | Deterministic Portfolio Insights | 1 | Critical | V1 Backend |
| 5 | GOALS | Goals-Based Planning | 4 | High | V1 Backend |
| 6 | BROKER | Broker Integration (Read-Only) | 1 | High | V1 Backend |
| 7 | COMPLIANCE | DPDP Compliance | 3 | High | V1 Backend |
| 8 | NAV | AMFI NAV Ingestion | 1 | Critical | V1 Backend |
| 9 | V3SCORE | V3 Scoring Engine (38 Primitives) | 9 | Critical | V2 Backend |
| 10 | PLAN | Action Plan Engine (V2.5 Rules) | 10 | Critical | V2 Backend |
| 11 | INTEL | Portfolio Intelligence & Look-Through | 2 | Critical | V2 Backend |
| 12 | HEALTH | Portfolio Health Score | 1 | High | V2 Backend |
| 13 | TAX | Tax Engine & Capital Gains | 3 | Critical | V2 Backend |
| 14 | ENRICH | Enriched Holdings API | 1 | Critical | V2 Backend |
| 15 | COPILOT | AI Copilot V1 (RAG) | 19 | Critical | Copilot V1 |
| 16 | COPILOT2 | AI Copilot V2 (LangGraph) | 15 | High | Copilot V2 |
| 17 | ADMIN | Admin Console | 19 | Critical | Admin |
| 18 | NIDP | NIDP Data Warehouse | 25 | High | NIDP |
| 19 | UI_SHELL | Frontend Shell & Routing | 3 | Critical | V1 Frontend |
| 20 | UI_LAND | Landing Page | 1 | Critical | V1 Frontend |
| 21 | UI_DASH | Dashboard Overview | 1 | Critical | V1 Frontend |
| 22 | UI_PORT | Portfolio UI (Holdings, CAS, Connect) | 3 | Critical | V1 Frontend |
| 23 | UI_RISK | Risk Profile UI | 1 | High | V1 Frontend |
| 24 | UI_INS | Insights UI | 1 | Critical | V1 Frontend |
| 25 | UI_GOALS | Goals UI | 1 | High | V1 Frontend |
| 26 | UI_MFD | MFD Advisor Workspace | 1 | High | V1 Frontend |
| 27 | UI_MKT | Market Dashboard | 1 | High | V1 Frontend |
| 28 | UI_PLAN | Plan Board (V2 UI) | 7 | Critical | V2 Frontend |
| 29 | UI_V2INS | V2 Insights Layer | 7 | Critical | V2 Frontend |
| **TOTAL** | | | **156 features** | | |

---

## Module Detail

### AUTH — Authentication & Session Management
| Feature | Business Objective | User Roles | Dependencies |
|---|---|---|---|
| Google OAuth Login | Allow whitelisted investors to authenticate | All | Google GIS SDK, whitelist DB |
| Session Validation (GET /me) | Maintain secure session state | All | Session cookie, MongoDB |
| Logout | Destroy session securely | All | Session cookie |
| RBAC Enforcement | Restrict endpoints by role | All | `deps.py`, user.role field |
| Rate Limiting | Prevent API abuse | All | In-memory sliding window |

### ONBOARD — User Onboarding
| Feature | Business Objective | User Roles | Dependencies |
|---|---|---|---|
| Journey Type Selection | Route user to correct UX flow | user, advisor | user_profiles collection |
| Risk Profile Questionnaire | Compute investor risk category | user | 6-question scoring formula |
| Quick Setup (New Investor) | SIP projection for new investors | user | FV formula, allocation rules |
| Onboarding Completion | Gate dashboard access | user | onboarding_completed flag |

### PORTFOLIO — Portfolio Management
| Feature | Business Objective | User Roles | Dependencies |
|---|---|---|---|
| Multi-Portfolio Creation | Support family/joint accounts | user | MongoDB |
| CAS PDF Upload | Import holdings from CAMS/NSDL | user | 3-provider fallback chain |
| Holdings CRUD | Manual holding entry/edit | user | PostgreSQL instrument_master |
| Instrument Search | Find stocks/funds by name/ticker | user | instrument_master (735 instruments) |
| CSV Export | Download portfolio for offline use | user | Holdings data |
| Snapshots (Time-Machine) | Track portfolio at any past date | user | cas_snapshot_engine |

### V3SCORE — V3 Scoring Engine
| Feature | Business Objective | User Roles | Dependencies |
|---|---|---|---|
| Quality Score | Rate fund quality (0-100) | system | 13 performance/risk primitives |
| Health Score | Rate fund stability | system | 6 health primitives |
| Exit Score | Signal when to exit a fund | system | Overlap + tax + quality-inverse |
| Add Score | Signal when to buy a fund | system | Gap-fit + overlap + quality |
| Portfolio-Fit Score | Measure portfolio-level fit | system | Diversification + concentration |
| Switch Score | Quantify switch value | system | Formula: Q_new-Q_old + overlap + cost-tax |
| Danger Classification | Label funds CRITICAL/WARNING/OK | system | Q<40 or H<40 = CRITICAL |
| 38 Primitive Data Sources | Source all scoring inputs | system | Groww scrape + NAV history |
| NAV Analytics Sweep | Nightly computed primitives | system | APScheduler 22:30 IST |

### PLAN — Action Plan Engine (V2.5)
| Feature | Business Objective | User Roles | Dependencies |
|---|---|---|---|
| Generate Action Plan | Orchestrate 6 rules + V3 enrichment | system | PostgreSQL + MongoDB |
| Rule 1: Regular→Direct | Eliminate cost-leak duplicates | system | Fund name normalisation |
| Rule 2: AMC Concentration | Reduce single-AMC overexposure | system | amc_exposure > 15% |
| Rule 2b: Category Concentration | Reduce SEBI category overexposure | system | category > 35% |
| Rule 3: Underperformer Replacement | Exit poor performers, add peers | system | quality<6.5, ret_1y<8% |
| Rule 4: Overlap Consolidation | Reduce duplicate fund exposure | system | pairwise overlap > 60% |
| Rule 5: Debt Allocation Gap | Enforce risk-profile debt floor | system | debt_pct < floor |
| Rule 6: Cost-Leak Switch | Switch Regular to Direct | system | annual_leak > ₹10K |
| Four Guardrails | Block harmful actions | system | Quality/tax/age/confidence |
| Plan State Machine | preview→active→archived lifecycle | user | MongoDB plan document |

### TAX — Tax Engine
| Feature | Business Objective | User Roles | Dependencies |
|---|---|---|---|
| Capital Gains (LTCG/STCG) | Compute tax per holding | system | FY2025-26 rates, FIFO |
| Switch Cost Calculator | Full cost/benefit of switching | system | tax + load + alpha math |
| Tax Harvesting Suggestions | Optimize LTCG ₹1.25L exemption | user | Unrealized gain calculation |

### COPILOT — AI Copilot V1 (RAG)
| Feature | Business Objective | User Roles | Dependencies |
|---|---|---|---|
| Chat Session Management | Multi-turn conversation | user | MongoDB chat_sessions |
| Context Warmup | Sub-second first response | user | Redis 5-min cache |
| Intent Classification | Route queries deterministically | system | keyword-based, 8 intents |
| Context Retrieval (5 blocks) | Inject real data into LLM | system | Portfolio + plan + goals + health |
| RAG Orchestrator | Retrieval + LLM pipeline | system | GPT-4o-mini via Emergent |
| Chart Spec Generation | Server-side chart JSON | system | 4 chart types, never LLM-generated |
| Streaming Chat (SSE) | Real-time token streaming | user | SSE, 30/min limit |
| LLM Safety / PII Scrubbing | Prevent PAN/Aadhaar in LLM | system | llm_safety.py |
| Goal-Level Copilot | Per-goal AI advisor | user | goal_copilot.py |
| Scenario Engine | Pre-built scenario cards | user | AICopilotView.jsx |

### ADMIN — Admin Console
| Feature | Business Objective | User Roles | Dependencies |
|---|---|---|---|
| Secrets Management | Runtime credential control | admin | system_config.secrets |
| Feature Flags | Gradual feature rollout | admin | MongoDB flags |
| Rules Config (13 params) | Live-tune decision engine | admin | action_plan_manager |
| Custom DSL Rules | Extend rules without deploy | admin | Safe AST evaluator |
| LLM Prompt Sandbox | Edit/test prompts safely | admin | LLM + mock data |
| Data Pipeline Monitor | Observe scheduled jobs | admin | APScheduler + job logs |
| V3 Scoring Weights | Tune scoring composites | admin | v3_scoring.py |
| User Management | Add/remove/promote users | admin | users collection |
| Whitelist Management | Control access | admin | whitelisted_users |
| NIDP Job Control (13) | Operate data warehouse | admin | NIDP Cloud Run |
| NIDP Data Quality | Monitor DQ failures | admin | Validation engine |
