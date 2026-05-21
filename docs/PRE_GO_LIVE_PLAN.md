# Nivesh.ai + NIDP — Pre-Go-Live Project Plan

**Top 50 prioritised recommendations and a sequenced 6-month execution plan**
*Principal Architect Review · May 2026*

Companion to [APP_ARCHITECTURE.md](APP_ARCHITECTURE.md) and [DB_ARCHITECTURE.md](DB_ARCHITECTURE.md).
Review notes in [PRE_GO_LIVE_PLAN_REVIEW.md](PRE_GO_LIVE_PLAN_REVIEW.md).

---

## 1. Framing & Definitions

Two framing decisions must be explicit:

**What "go live" means here:** public launch beyond the beta whitelist — open signups, paying users handling real money decisions, with regulatory (DPDP, advisor compliance) exposure. If "go live" means something narrower (e.g., expand the whitelist 5x), several P0s can drop to P1.

**The bar being set:** a fintech that can survive a VM failure, a developer mistake, a malicious user, a regulatory audit, and a 10x traffic spike in the first six months. Table stakes, not aspirational.

---

## 2. Priority Tiers — Summary

| Tier | Timing | Items | Severity Definition |
|---|---|---|---|
| **P0** | Before launch | 15 | If missing, creates (a) an unrecoverable data incident, (b) a compliance violation, or (c) a security event that ends the company. |
| **P1** | First 30 days post-launch | 17 | High-severity gaps that don't block launch but degrade the system rapidly under real traffic. |
| **P2** | First 90 days | 12 | Compounding technical debt — each month delayed, cost to fix grows. |
| **P3** | First 180 days | 6 | Scale enablers, pulled when the data says they're the bottleneck. |

---

## 3. P0 — Launch Blockers (15 items)

If missing on day one, creates a class of incident the company may not recover from. Every item must be "done with evidence" before launch.

| # | Item | Domain | Effort | Why P0 |
|---|---|---|---|---|
| 1 | **Automated backups** for Mongo, Nivesh PG, NIDP PG with offsite cross-region encrypted storage | Infra | 5d | Data loss without backup = company-ending |
| 2 | **First successful restore drill** of all 3 DBs, with documented RTO/RPO | Infra | 3d | Untested backups aren't backups |
| 3 | Move all **secrets out of Mongo `system_config`** into GCP Secret Manager | Security | 3d | Mongo-as-secrets-store violates basic security hygiene |
| 4 | Add **SCA + container scanning + Dependabot** to CI | Security | 2d | A `pillow` / `urllib3` CVE will land silently otherwise |
| 5 | **End-to-end DPDP delete test** across Mongo + both PG + Redis + NIDP | Compliance | 5d | DPDP is enforceable; non-compliant delete = legal exposure |
| 6 | **Idempotency keys** on all financial write paths (CAS upload, broker orders, plan execution, broker callbacks) | Backend | 5d | Duplicate orders/imports are silent data corruption |
| 7 | Replace **in-memory rate limiting with Redis-backed** sliding window | Backend | 3d | Survives restarts; required for any horizontal scale |
| 8 | Add **explicit timeouts** to every external HTTP call (NIDP, Groww, brokers, LLMs, scrapers) | Backend | 3d | Default-infinite timeouts are how outages propagate |
| 9 | **Migration tracking table** for Nivesh PG (copy NIDP `schema_migrations` pattern) | Database | 1d | Without tracking, prod drift is invisible |
| 10 | **MFD impersonation audit hardening** — log every `active_profile_id` change, adversarial tests for cross-workspace access | Security | 5d | Privilege escalation surface in a fintech |
| 11 | **Critical alerts wired**: API 5xx rate, DB connection saturation, LLM error rate, scheduler job failure, disk usage | Observability | 3d | You cannot operate without alerts |
| 12 | **PII redaction in LLM prompt builders** — single function used by all three LLM paths | Security | 4d | PAN/holdings going to Anthropic/OpenAI/Google unredacted is a breach |
| 13 | **CAS Redis cache key fix** — include `user_id` in hash OR strip PII from cached value | Privacy | 2d | Cross-user PII leakage via shared cache |
| 14 | **AES-256-GCM key management audit** — keys in GSM, unique IV per record, rotation procedure documented | Security | 3d | GCM with reused IV is broken cipher |
| 15 | `/health` and `/ready` endpoints distinct, with `/ready` checking Mongo + PG + Redis + NIDP reachability | Infra | 2d | Liveness ≠ readiness; load balancer needs the difference |

**P0 total effort:** ~50 person-days. Achievable in 4–6 weeks with 2 engineers.

---

## 4. P1 — First 30 Days Post-Launch (17 items)

High-severity gaps that degrade the system rapidly under real traffic.

| # | Item | Domain | Effort | Why P1 |
|---|---|---|---|---|
| 16 | **Extract APScheduler from API process** to dedicated worker container with leader election (or Cloud Scheduler + Cloud Tasks) | Backend | 1–2w | Blocks horizontal scale of the API |
| 17 | **Reconciliation job**: nightly diff between Mongo `holdings` and PG `portfolio_snapshot_*`; alert on >1% drift | Database | 1w | Detects cross-DB dual-write drift |
| 18 | **Index inventory per DB**, committed to repo, regenerated weekly; add missing indexes per actual slow query log | Database | 1w | Largest passive perf gain available |
| 19 | **Prometheus / Cloud Monitoring metrics**: request rate, latency p50/p95/p99 by route, error rate, DB pool saturation | Observability | 1w | Cannot SLO what you cannot see |
| 20 | **OpenTelemetry tracing** end-to-end, Cloud Trace export, `correlation_id` propagated | Observability | 4d | Critical for diagnosing cross-DB and external-call slowness |
| 21 | **LLM cost + token instrumentation** per user per route per model; daily per-user token ceiling with admin override | AI/Cost | 5d | LLM cost trajectory is unbounded otherwise |
| 22 | **API versioning** — adopt `/api/v1/*` prefix for all new routes; document deprecation policy | API | 3d | Without versioning, every change is breaking |
| 23 | **Wire NIDP intelligence snapshot endpoint** and delete duplicated `equity_pct` / `beta` / `top_sector` in Copilot | AI/Data | 5d | Two-answers-for-same-question erodes trust |
| 24 | **V3 chat SSE parity with V2** — restore streaming UX | Frontend | 3d | Sync POST is the worst possible chat UX |
| 25 | **Pin auth transport**: session cookies for web, Bearer for mobile (Capacitor); reject mixed mode per endpoint | Security | 4d | Halves CSRF + token-theft surface |
| 26 | **Reduce session lifetime to 7 days** with sliding refresh + reauth gate on sensitive actions | Security | 3d | 30d sessions are too long for a fintech |
| 27 | **Status page + on-call rotation + incident runbook** for top 10 scenarios | Ops | 1w | First incident at 3am decides whether you're a company that survives |
| 28 | **Retry-with-backoff wrappers (tenacity)** on all external clients | Backend | 4d | Currently try/except → fallback; that's not the same as retry |
| 29 | **Circuit breakers** on NIDP HTTP calls + LLM providers + broker APIs | Backend | 5d | Fail-fast when downstream is degraded |
| 30 | **Webhook security**: HMAC verification + replay protection + idempotency on all broker callbacks | Security | 5d | Webhook spoofing is a real attack vector |
| 31 | **File upload hardening**: MIME validation, size cap, optional malware scan, no shell-out on uploaded files | Security | 4d | CAS PDFs are user-controlled binary input |
| 32 | **Slow query logs** enabled and reviewed weekly: `pg_stat_statements`, Mongo profiler, Redis SLOWLOG | Observability | 2d | Where performance work actually lives |

**P1 total effort:** ~70 person-days. Achievable in 8–10 weeks with 2–3 engineers.

---

## 5. P2 — First 90 Days Post-Launch (12 items)

Compounding technical debt. Each month delayed, the cost to fix grows.

| # | Item | Domain | Effort | Why P2 |
|---|---|---|---|---|
| 33 | **Migrate self-managed Mongo + Nivesh PG to Atlas + Cloud SQL** with HA + automated backups | Infra | 4w | Removes the largest operational burden and the single-VM SPOF |
| 34 | **Memorystore Redis with HA** (replacing self-managed Redis on the app VM) | Infra | 1w | Removes cache-stampede risk on restart |
| 35 | **Outbox pattern for cross-DB writes** (Mongo → PG) — durable retry, eventual consistency, replayable | Backend | 3w | Right long-term answer to the dual-write problem |
| 36 | Introduce **`instrument_id` UUID as canonical cross-DB key**; migrate Mongo `holdings.ticker` to explicit `instrument_id` + `isin` + `nse_symbol` | Database | 4–6w | Eliminates the polymorphic-key class of bugs |
| 37 | **LLM gateway service** — single ingress for Claude/Gemini/GPT with redaction, cost ceiling, retries, fallback | AI | 2w | Currently 3+ paths; unifying gives observability + safety |
| 38 | **SLO definitions + error budgets** for top 10 user-facing endpoints | Ops | 1w | Without SLOs, prioritisation is opinion-based |
| 39 | **Retention policies per NIDP hypertable**; especially `fno_bhavcopy` (2.5M rows/day) | Database | 1w | Storage cost will compound; some data must age out |
| 40 | **Partition `portfolio_snapshot_holdings` by date** | Database | 2w | At 10K users × 30 holdings × daily = 110M rows/year |
| 41 | **Decompose top 5 god components on frontend** (`InsightsView` 95KB, `ActionablePortfolioView` 93KB, `ChatView` 77KB, `ClientSnapshot` 102KB, `CasTimeMachine` 44KB) | Frontend | 3w | Re-render perf + maintainability |
| 42 | **Mongo schema versioning** — add `_schema_v` field on writes; pick a migration runner | Database | 2w | Enables future safe migrations |
| 43 | **DPDP consent ledger versioning** + audit log captures PII reads (not just changes) | Compliance | 1w | Required for any regulatory audit |
| 44 | **CAS parser hallucination defense**: strict Pydantic schemas on LLM JSON output with type + range + cross-field validation; quarantine non-conforming responses | AI/Safety | 1w | Closes the prompt-injection-via-PDF surface |

**P2 total effort:** ~28 weeks of engineering work, parallelisable. ~13 weeks calendar with 3 engineers.

---

## 6. P3 — First 180 Days (6 items)

Scale enablers — pulled when the data says they're the bottleneck.

| # | Item | Domain | Effort | Why P3 |
|---|---|---|---|---|
| 45 | **Auto-discovery of routers** + repackage 140+ flat services into bounded contexts (`decision/`, `fund/`, `tax/`, etc.) | Backend | 3w | Maintainability ceiling for the team |
| 46 | **Read replicas** for Mongo + Nivesh PG; route analytic queries to replicas | Infra | 2w | Read scale headroom |
| 47 | **PWA + service worker on V3** for mobile retention | Frontend | 2w | Mobile UX parity |
| 48 | **Postgres checkpoint saver for LangGraph** (replace `MemorySaver`) | AI | 1w | Chat history survives restarts |
| 49 | **react-query/SWR introduction** on top 10 fetch-heavy V3 screens; remove duplicated fetch+loading+error code | Frontend | 3w | Shrinks god components 30–50% with no behavior change |
| 50 | **Multi-region read failover** for portfolio data (Mongo + PG read replicas in different region) | Infra | 3w | Disaster recovery readiness |

---

## 7. Sequenced 6-Month Project Plan

Calendar assumes **2.5 backend engineers + 1 frontend + 0.5 SRE/DevOps + 0.25 security reviewer** available. Adjust if your team is smaller.

### Pre-Launch — Weeks 1–6 (P0 items)

```
                                W1   W2   W3   W4   W5   W6
─────────────────────────────────────────────────────────
Backups + restore drill         ████████
Secrets to GSM                  ████
SCA / Dependabot / scan         ████
DPDP delete test                    █████
Idempotency keys                    ████████
Redis-backed rate limit             ████
External call timeouts                  ████
Nivesh PG migration tracking            █
MFD impersonation audit                 ████████
Critical alerts wired                       ████
PII redaction in LLM                        ████
CAS cache key fix                               ██
AES-256-GCM audit                               ████
/health vs /ready                                   ██
LAUNCH READINESS REVIEW                                ●
```

**Milestone — Week 6: Go/No-Go Gate.** The gate is binary. Each P0 item is either "done with evidence" or "not done." No yellow. Items not done block launch.

### Evidence required per P0 item

| Item | Required evidence |
|---|---|
| Backup | Timestamp of last successful restore drill + documented RTO/RPO numbers |
| Secrets | Zero secrets remaining in Mongo (verification script passes) |
| SCA | CI pipeline passing with vulnerability gates active |
| DPDP delete | Test user fully deleted; audit confirms 0 rows across all stores |
| Idempotency | Tests for replay safety on all financial writes |
| Rate limit | Load test with N=2 backend instances showing correct limiting |
| Timeouts | Code scan shows zero infinite-timeout HTTP calls |
| Migration tracking | `applied_migrations` table populated; dev/staging/prod matched |
| MFD audit | Adversarial test suite passing |
| Alerts | At least 5 critical alerts firing into PagerDuty/Slack |
| PII redaction | Tests covering PAN, mobile, email |
| CAS cache | Privacy review sign-off |
| GCM | Key in GSM, IV uniqueness verified by test |
| `/ready` | Load balancer health check pointing at it |

### Months 2–3 — P1 Items (Weeks 7–14)

```
                            W7   W8   W9   W10  W11  W12  W13  W14
─────────────────────────────────────────────────────────────────
APScheduler extraction      ████████
Reconciliation job          ████
Index inventory             ████
Prometheus metrics          ████████
OpenTelemetry tracing            ████
LLM cost instrumentation         █████
API versioning                       ███
NIDP snapshot wiring                 █████
V3 chat SSE parity                       ███
Auth transport pinning                   ████
Session lifetime trim                        ███
Status page + on-call                        ██████
Retries (tenacity)                              ████
Circuit breakers                                █████
Webhook security                                    █████
File upload hardening                                ████
Slow query logs                                          ██
```

**Milestone — Week 14: First Production Audit.** External pen test commissioned, first quarterly backup restore drill, first SLO review, first on-call rotation completed.

### Months 4–6 — P2 Items (Weeks 15–26)

```
                                W15-18    W19-22    W23-26
──────────────────────────────────────────────────
Atlas + Cloud SQL migration     ██████████
Memorystore Redis               ████
Outbox pattern                       ██████████
instrument_id migration              ██████████████
LLM gateway service                       ████████
SLO + error budgets                       ████
NIDP retention policies                   ████
Snapshot partitioning                     ████████
Frontend god components                       ████████████
Mongo schema versioning                       ████████
DPDP consent ledger                                ████
CAS parser strict schemas                          ████
```

**Milestone — Week 26: Scale Readiness Review.** Capacity test against 5x current peak load. DR drill: simulate full Nivesh VM loss; recovery within RTO. Cost review: LLM spend, infra spend, projected at 10x users. Tech debt scorecard re-run vs baseline.

### Months 7–12 — P3 Items (as capacity permits)

P3 items are pulled based on signal. Don't batch them; do each when the data says it's the bottleneck.

---

## 8. Team Loading & Hiring

If you have less than 2.5 backend + 1 frontend + 0.5 SRE available full-time, the calendar stretches. Specifically:

- **Without an SRE**, P0 backups + alerts + `/ready` slip — these are not afternoon tasks.
- **Without dedicated security review time**, items 3, 10, 12, 14, 25, 30, 31 all become someone's side quest and quality drops.
- **Solo backend engineer scenario:** P0 takes 10–12 weeks instead of 6.

### Hiring recommendation

1. A dedicated **SRE / Platform engineer** before P0 work starts. The infrastructure migration in P2 alone justifies the hire.
2. A part-time **external security consultant** for the pre-launch audit + post-launch pen test.

---

## 9. Cost Implications

The current ~$42–60/mo infrastructure spend cannot sustain this plan. Realistic post-launch infra cost:

| Item | Monthly cost (est) |
|---|---|
| Cloud SQL Postgres (Nivesh, HA) | $150–250 |
| Cloud SQL Postgres (NIDP, HA) | $200–350 |
| Mongo Atlas M20 + backups | $200–300 |
| Memorystore Redis (HA) × 2 | $100–150 |
| GCE VM (app, smaller after DB migration) | $50–100 |
| Cloud Run NIDP ingesters | $50–150 |
| Cloud Monitoring + Trace + Logging | $50–150 |
| GSM, KMS, IAM | $20 |
| LLM spend (1K DAU, V2 LangGraph) | $1,500–3,000 |
| Pen test (one-time) | $5,000–15,000 |
| **Recurring total** | **~$2,300–4,500/mo at 1K DAU** |

This is the realistic floor. Plan for it; don't treat it as optional.

---

## 10. Scope Boundaries & How to Use This Plan

### What this plan does *not* cover

- Product-market-fit work and feature development — out of scope. This plan assumes feature work continues at ~50% team velocity in parallel.
- Regulatory advisor licensing (SEBI RIA, etc.) — depends on business structure; consult a fintech lawyer.
- Customer support tooling — important but not architecture.
- Marketing site / SEO / growth tech — separate workstream.
- iOS App Store / Play Store submission — Capacitor exists; submission process is its own checklist.

### Three suggestions for using this plan

1. **Don't negotiate P0.** The temptation to ship without P0 #1 (backups), #5 (DPDP delete), or #14 (GCM keys) is enormous because they're not visible to users. Resist. The first incident makes you wish you hadn't.
2. **Track P0 as a public dashboard** within the team. 15 items, binary done/not-done with evidence. The CEO should be able to see this at any time. This is how launch readiness reviews stay honest.
3. **Schedule the post-launch retro for week 8, not week 26.** The pattern is: P0 lands, launch happens, the team feels relief and stops doing P1. Force the review.

---

*Companion to the Application Architecture and Database Architecture reviews. Any of these 50 items can be expanded into a detailed engineering spec on request — particularly the outbox pattern (#35), the APScheduler extraction (#16), the `instrument_id` migration (#36), or the DPDP delete cascade (#5).*
