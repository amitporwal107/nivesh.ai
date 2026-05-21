# Pre-Go-Live Plan — Engineering Review

Reviewing [PRE_GO_LIVE_PLAN.md](PRE_GO_LIVE_PLAN.md) against the actual codebase state captured in [APP_ARCHITECTURE.md](APP_ARCHITECTURE.md), [DB_ARCHITECTURE.md](DB_ARCHITECTURE.md), [SECURITY_GAP_ANALYSIS.md](SECURITY_GAP_ANALYSIS.md), and [TASK_REGISTRY.md](TASK_REGISTRY.md).

**TL;DR — the plan is sound.** Tier calibration is correct, item descriptions match the actual code (file sizes, file paths, table names check out), and the Go/No-Go gate with evidence-per-item is the right operational discipline. Notes below are additions and tightening, not disagreements.

---

## 1. What the plan gets right

- **P0 ladder calibration.** Backups, DPDP delete, secrets-out-of-Mongo, AES-IV reuse, MFD impersonation — these are exactly the items that would end the company if missing. Nothing on P0 is busywork.
- **Codebase grounding.** Specific file references (`InsightsView` 95KB, `ChatView` 77KB, `ClientSnapshot` 102KB) match what's actually in `/frontend/src/`. `fno_bhavcopy` at 2.5M rows/day matches [DB_ARCHITECTURE.md §4.2](DB_ARCHITECTURE.md). The NIDP intelligence-snapshot duplication (P1 #23) matches the gap recorded in memory `project_nidp_copilot_ownership`.
- **Evidence-per-P0.** The binary done/not-done gate is exactly how launch readiness stays honest. Most teams use yellow; that's how things ship missing.
- **Cost realism.** $2.3–4.5K/mo at 1K DAU is honest. Most fintechs underestimate; this doesn't. The LLM line ($1.5–3K) is the right ballpark — see §3 below for a fan-out caveat.
- **Week-8 retro recommendation.** P1 always slips after launch. Forcing a week-8 review is a non-obvious, correct call.

---

## 2. P0 items I would tighten or add

### 2.1 Items where effort estimate looks light

| # | Item | Estimate | Concern |
|---|---|---|---|
| 10 | MFD impersonation audit hardening | 5d | Adversarial test suite for cross-workspace access is itself ~3d; logging hooks across every route that reads `active_profile_id` is another ~3d; the privilege escalation matrix (workspace × profile × shadow user_id) should be threat-modeled before coding. Realistic: 7–10d. |
| 12 | PII redaction in LLM prompt builders | 4d | Plan says "single function used by all three LLM paths." There are actually **five** LLM call sites — V1 RAG (`copilot_rag/orchestrator.py`), V2 LangGraph (`nidp/copilot_agent/nodes/*`), Claude CAS parser (`claude_cas_parser.py`), OpenAI CAS parser (`openai_cas_parser.py`), and document classifier (`announcement_classifier`). Vision parsers pass *images of CAS PDFs* — redaction model is different. Realistic: 6–8d. |
| 14 | AES-256-GCM key management audit | 3d | Audit + key migration to GSM + IV uniqueness test + rotation runbook + re-encryption of existing tokens (gmail_tokens, broker_accounts collections) is closer to 5d. Don't underestimate the re-encryption migration. |

### 2.2 P0 items I would add

| # | Add | Domain | Effort | Rationale |
|---|---|---|---|---|
| **P0+a** | **Git history secret scan** + immediate rotation of any live tokens | Security | 2d | Memory `security_repo_remote_pat` and `security_posture` both flag live tokens in the repo. Rotating *after* GSM migration leaves a window where the old tokens still grant access. |
| **P0+b** | **`ref.security_master` reconciliation watchdog** | Database | 2d | The NIDP `ref.security_master` UUID is the soft join key for cross-DB joins (mongo `holdings.ticker` → PG `instrument_master.isin` → NIDP `ref.security_master`). If it drifts, every analytics surface returns wrong answers silently. A daily diff is cheap; missing it is expensive. |
| **P0+c** | **NIDP migration idempotency fix (BUG-010)** | Database | 2d | `phase6_robust.sh` is not idempotent per memory. First time a deploy half-applies, the team will discover this at 3am. Fix before launch. |
| **P0+d** | **Log scrubbing for PII** | Security | 2d | Plan covers PII to LLMs (P0 #12) but not PII to logs. `RequestLoggingMiddleware` logs structured request bodies; PAN/mobile/email will land in Cloud Logging unredacted. Either redact at log boundary or scope logging to non-body fields. |
| **P0+e** | **AMC scrapers triage** | Data | 3d | Memory `project_amc_scrapers_broken` says 10 AMC scrapers are 404'ing — 4 MF scoring primitives stay 0% covered. If the plan's launch assumes MF scoring works, this is a P0. If not, downgrade documentation explicitly. |

### 2.3 Items I would move

- **P1 #16 (APScheduler extraction) → arguably P0.** The plan's reasoning ("blocks horizontal scale") is correct but understates the risk: with APScheduler in-process and N>1 API instances, every cron fires N times. That means N-times duplicate NAV ingest, N-times duplicate Groww drain, N-times duplicate V3 rescore. If launch goes to >1 instance, this isn't a 30-day item, it's a launch blocker. Decision: keep at P1 only if launch stays at N=1; otherwise promote.

---

## 3. P1–P3 observations

### 3.1 LLM cost (P1 #21, P2 #37) — fan-out caveat

The plan estimates $1.5–3K/mo at 1K DAU. The V2 LangGraph path fans out: a single user message can fire intent_node → 1–3 specialist nodes → recommendation_node → compliance_node. If average specialists invoked = 2, real cost is 4× a naive chat call. At 1.5 turns/DAU/day that's ~$3–6K/mo, not $1.5–3K.

**Recommendation:** add a P0 sub-item "LLM cost back-of-envelope based on actual V2 fan-out measurement" before launch, even if instrumentation (P1 #21) lands later. Cheap to measure, painful to find out post-facto.

### 3.2 Outbox pattern (P2 #35) — sequencing

Outbox is the right answer to cross-DB writes (Mongo → PG → NIDP). But sequencing matters: doing #35 before #36 (`instrument_id` migration) means the outbox carries the polymorphic `ticker` field; then #36 changes the schema and the outbox has to be reworked. Suggest: **#36 first, then #35**. The plan's calendar (Weeks 15–18 for both, in parallel) bakes in rework.

### 3.3 `instrument_id` migration (P2 #36) — biggest risk in P2

4–6 weeks is right for the engineering, but the data backfill is the harder part. Every Mongo `holdings`, `cas_transactions`, `action_plans.actions[].asset_name`, MFD `mfd_profile_signal_cache`, and `pg_mirror_*` document needs `instrument_id` resolved. Recommend: do the dual-write phase (write both `ticker` and `instrument_id`) for 2 weeks before flipping reads. Plan doesn't call this out.

### 3.4 Reconciliation job (P1 #17) — scope

"Diff Mongo `holdings` vs PG `portfolio_snapshot_*`" — but PG snapshots are point-in-time and Mongo `holdings` is live. The diff has to be against the latest snapshot per user. Add: also reconcile NIDP `portfolio.user_holdings_snapshot` → catches the second dual-write seam (PG → NIDP) that the plan elides.

### 3.5 Frontend god components (P2 #41) — pair with #49

Decomposing god components without `react-query`/SWR first means re-deriving fetch+loading+error patterns 5 times. Suggest: pull #49 forward into P2 alongside #41 — they share infrastructure.

### 3.6 PWA on V3 (P3 #47) — sequencing with mobile

Capacitor is already on V3 per [APP_ARCHITECTURE.md §2.3](APP_ARCHITECTURE.md). PWA + native shell coexist but require deciding which is the install vector for which user segment. Decision needed before #47; otherwise you ship both and confuse users.

---

## 4. What's missing from the plan entirely

| Gap | Why it matters | Suggested tier |
|---|---|---|
| **NIDP DaaS API key rotation procedure** | Per-caller API keys exist via `python -m nidp.cli daas-keygen`. There's no documented rotation cadence. A leaked key gives read access to the entire intelligence warehouse. | P1 |
| **Mobile crash reporting (Sentry/Bugsnag for Capacitor)** | Capacitor wraps V3 in WebView; native-shell crashes won't surface in web error tracking. | P1 |
| **Backup verification (not just restore drill)** | P0 #1 + #2 cover initial drill. Ongoing weekly automated restore-to-staging is what catches silent backup corruption. | P1 |
| **pgvector embedding drift monitoring** | NIDP S5 embedder writes pgvector embeddings for announcements. Embedding model upgrades or chunking changes can silently degrade RAG quality. | P2 |
| **Cookie-policy / SameSite explicit decision** | `COOKIE_SAMESITE` is configurable per env var but not standardised. Capacitor WebView vs browser have different defaults; if not pinned, MFD impersonation in mobile can break. | P1 |
| **Database connection pool sizing audit** | asyncpg + motor pool sizes are defaults. With APScheduler in-process + N API instances, pool exhaustion is the most likely first scale failure. | P1 |
| **Mongo index audit specifically** | P1 #18 says "index inventory per DB" — Mongo indexes need their own pass. Plan doesn't call out that ~45 Mongo collections probably ship without explicit indexes today. | Part of P1 #18 |
| **Capacitor app submission timeline** | Plan explicitly excludes (§10), but if mobile launch is in scope, the Apple review cycle is 1–2 weeks and TestFlight needs ~3 weeks of prior testing. Plan it in parallel. | Out-of-scope OK |

---

## 5. Numeric sanity check

- **P0:** 50 person-days / 2 engineers / 5 working days/week = 5 weeks. Plan allocates 4–6 weeks. Plausible if the 2 engineers are senior and dedicated. Tight if either is junior or part-time.
- **P1:** 70 person-days / 2.5 engineers / 5 days = ~5.6 weeks. Plan allocates 8 weeks (Weeks 7–14). Includes slack for unknowns — reasonable.
- **P2:** ~28 engineer-weeks / 3 engineers = 9.3 calendar weeks. Plan allocates 12 (Weeks 15–26). Slack for the `instrument_id` migration unknowns — reasonable.
- **P3:** 14 engineer-weeks. Plan says "pulled when data says it's the bottleneck" — correct framing; no fixed calendar.

Totals add up. No padded estimates, no missing weeks.

---

## 6. Recommended changes to apply

1. **Add P0+a through P0+e** above (5 items, ~11 engineer-days). New P0 total: 61 days, 5.5–7 weeks with 2 engineers.
2. **Bump P0 #12 effort from 4d → 6–8d** to cover all five LLM call sites including vision parsers.
3. **Bump P0 #14 effort from 3d → 5d** to cover re-encryption of existing encrypted tokens.
4. **Add log-PII-scrubbing (P0+d)** to the evidence checklist: code scan shows no request body fields in structured logs.
5. **Sequence P2: #36 before #35**, not in parallel. Re-flow the Weeks 15–22 Gantt accordingly.
6. **Add weekly automated restore-to-staging** as a P1 follow-on to P0 #2.
7. **Promote P1 #16 to P0** if launch architecture is N>1 API instances. Otherwise document explicitly that launch is N=1.

---

## 7. What I would *not* change

- Tier definitions (P0/P1/P2/P3 + their severity language).
- The Go/No-Go binary gate. Don't add yellow.
- The week-8 forced retro.
- The cost section. It's right.
- The "what this plan does not cover" boundaries. They're the right boundaries.
- The 6-month horizon. Longer plans are fiction; shorter plans skip P2.

---

## 8. Open questions for the author

1. **What is "go live"?** §1 defines two scenarios — confirm which one applies. If launch = "expand whitelist 5x," several P0s legitimately become P1.
2. **Target N for API instances at launch?** Drives whether P1 #16 (APScheduler extraction) is actually P0.
3. **Mobile launch in scope for week 6?** If yes, Capacitor + TestFlight timeline competes with backend P0 work.
4. **Who owns the P0 dashboard?** Plan says "public within the team." Suggest naming an owner — typically EM or the senior-most backend engineer, not the CEO.

---

*Review compiled against current branch `feature/v3-mobile-web-redesign` (commit context May 2026) and the architecture documents in this folder. Any item above can be expanded into a detailed spec on request — particularly the `instrument_id` dual-write sequencing (#36), the outbox-after-keys ordering (#35 after #36), or the threat model for MFD impersonation (#10).*
