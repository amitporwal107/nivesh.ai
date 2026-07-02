# Release Process — Generic Template

> Generic, reusable skeleton interpreted from `release_process_staging_production.md`.
> Fill every `<...>` token. This template defines the **structured content model** the
> in-app authoring form renders (see `docs/release-management/DESIGN.md` → Data Model).

**Document type:** `release_process`
**Release version (semver):** `<MAJOR.MINOR.PATCH>`

---

## 1. Overview

| Item | Detail |
|---|---|
| Release Version | <version> |
| Release Type | <Minor — Features + Bug Fixes> |
| Staging Window | <date / time UTC> |
| Production Window | <date / time UTC (low-traffic)> |
| Estimated Downtime | <zero / minutes> |
| Rollback SLA | <e.g. < 15 min> |

## 2. Prerequisites & Readiness Checklist

### 2.1 Code & QA Readiness
- [ ] All feature branches merged into `release/<version>`
- [ ] CI/CD pipeline green
- [ ] Code review approved (≥ N engineers per PR)
- [ ] Static analysis — zero critical issues
- [ ] Dependency scan — zero Critical/High CVEs
- [ ] QA sign-off (≥ target pass rate)
- [ ] Security scan approved
- [ ] Release Notes finalized

### 2.2 Infrastructure Readiness
- [ ] Staging mirrors production
- [ ] DB migration scripts reviewed
- [ ] Secrets/env updated (staging + prod)
- [ ] Feature flags configured (OFF by default)
- [ ] Monitoring dashboards + alerts configured
- [ ] On-call rotation confirmed

### 2.3 Approvals Required
- [ ] QA Lead · [ ] Tech Lead · [ ] Product Manager · [ ] Security Officer · [ ] VP Eng (prod only)

## 3. Environment Architecture

| Property | Staging | Production |
|---|---|---|
| URL | <staging url> | <prod url> |
| Infrastructure | <...> | <...> |
| DB | <...> | <...> |
| API Pods | <n> | <n> |
| CDN | <...> | <...> |
| Secrets | <...> | <...> |
| Feature Flags | <...> | <...> |

## 4. Roles & Responsibilities

| Role | Person | Responsibilities |
|---|---|---|
| Release Manager | | Owns process; go/no-go |
| DevOps | | Executes deploy commands |
| QA Lead | | Staging verification + sign-off |
| DBA | | DB migrations |
| Security Officer | | Security gate |
| Product Manager | | UAT sign-off; comms |
| On-Call | | Post-deploy monitoring; rollback |

## 5. Stage 1 — Code Freeze & Branching
- **Owner:** <role> · **Timeline:** <T-48h>
- Steps: <freeze announcement, cut `release/<version>`, version bump, build & tag artifacts>
- **Exit criteria:** <branch protected, CI green, artifacts pushed>

## 6. Stage 2 — Staging Deployment
- **Owner:** <role> · **Timeline:** <date/time>
- Steps: <notify, DB migration, deploy API, deploy frontend, enable flags>
- **Exit criteria:** <tasks on new version, migrations applied, health 200>

## 7. Stage 3 — Staging Verification & Sign-Off
- Smoke tests · Regression · Per-feature verification · Bug-fix verification · Load/perf baseline
- **Sign-off gate:** <all suites pass; QA + PM + Security sign-off; no Sev-1/Sev-2 open>

## 8. Stage 4 — Production Deployment
- **Owner:** <role> · **Timeline:** <low-traffic window>
- Steps: <pre-deploy checks, notify, DB snapshot + migration, blue/green 10%→50%→100%, frontend, gradual flags>
- **Exit criteria:** <version live, error rate within threshold, no Sev-1 alerts>

## 9. Stage 5 — Post-Deployment Monitoring
- **Owner:** <role> · **Timeline:** <24h>
- Real-time monitoring thresholds · Synthetic monitoring · Business metrics · Post-deploy review

## 10. Rollback Procedure
- **Triggers:** <error rate / latency / payment failure / Sev-1 / data integrity / security>
- **Steps (target < N min):** <disable flags → shift traffic to previous → revert frontend → rollback migration → verify health>
- **Post-rollback:** <notify, Sev-1 ticket, preserve logs, RCA>

## 11. Communication Plan
| Event | Channel | Audience | Owner |
|---|---|---|---|
| Code freeze | | | |
| Staging deploy | | | |
| Prod deploy | | | |
| Rollback | | | |

## 12. Release Checklist Summary
- [ ] Stage 1 complete · [ ] Stage 2 complete · [ ] Stage 3 sign-off · [ ] Stage 4 complete · [ ] Stage 5 review done
