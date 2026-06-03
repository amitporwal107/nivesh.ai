# PROJECT_PLAN.md — Nivesh.ai / NIDP

> Owned by PROJECT_MANAGER role. Honesty rule: status = verified reality. "DONE" only if the
> owning role's env checklist is green with evidence. Estimates are ranges with assumptions.

## 1. Status model
Per task: `NOT STARTED · IN PROGRESS · ON STAGING (verified) · IN PROD (verified) · 🔴 BLOCKED`.
Nothing is `IN PROD` unless it was `ON STAGING (verified)` first and merged to `main` via PR.

## 2. Known roadmap (from validated doc, 2026-05-29)

### A. NIDP 7-Gate Data Quality system — TECHNICAL_ARCHITECTURE §16
Current: Gate 3 tables live (migration 077); Gate 4 LIVE (migration 075). Rest PLANNED.
Rollout Q3–Q4 2026; each gate: Shadow (2w) → Canary (1w) → Progressive (2w) → Full.

| Phase | Weeks | Gates | Status |
|---|---|---|---|
| 1 | 1–4 | Gate 3 (Snapshot Completion) ⭐ | PARTIAL (tables live) |
| 2 | 5–8 | Gate 5 (Warm-Tier Export) | PLANNED |
| 3 | 9–14 | Gate 6 (API Output) + Copilot DQ | PLANNED |
| 4 | 15–22 | Gates 1+2 (Ingestion + Stream) | PLANNED |
| 5 | 23–26 | Gate 4 polish + Gate 7 SLO migration | PARTIAL (Gate 4 live) |

### B. Security hardening (DEVOPS gaps)
| Item | Severity | Status |
|---|---|---|
| Rotate any tokens in git history | CRITICAL | ONGOING |
| PAN AES-256 at rest | HIGH | PLANNED |
| gitleaks in CI | HIGH | PLANNED |
| Admin MFA | MEDIUM | PLANNED |

### C. Scaffolded / not implemented (Admin console §18)
NIDP Diagnostics (SCAFFOLDED) · Grafana embed (SCAFFOLDED) · audit-log viewer (NOT IMPL) ·
data-retention sweeps (NOT IMPL) · DPO alerting (NOT IMPL) · SIEM (NOT IMPL) ·
`staging-data.niveshcopilot.com` CNAME (NOT LIVE) · V5 frontend prod rollout (staging only) ·
Sentry SDK instrumentation in app code (datasource only today).

## 3. Workstream template (per initiative)
| Task | Owner role | Depends on | Verify by | Status |
|---|---|---|---|---|
| ⟨…⟩ | FULL_STACK_DEVELOPER / QA_ENGINEER / DESIGN_ENGINEER | ⟨…⟩ | ⟨role env checklist⟩ | NOT STARTED |

## 4. Deploy-ordering rule
`dev` → staging verify (role checklist green, evidence) → PR → `main` → prod verify. No task
reaches prod before staging verification. Report blockers as `🔴 REAL BLOCKER`, never softened.

## 5. Risks & blockers
| Risk / blocker | Likelihood | Impact | Mitigation / unblock | Owner |
|---|---|---|---|---|
| Bad data → V3 scores → Copilot (pre-Gate-1/2) | M | H | Prioritize Gate 3; data-test in QA | — |
| Secrets in git history | M | H | Rotate; add gitleaks (planned) | — |
