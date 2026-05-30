# Checklist — SKILL: Project Manager

**Use when:** sequencing, dependencies, status reporting, blockers, multi-role coordination.
**Target env:** ☐ Staging   ☐ Prod
**Status:** `NOT STARTED` → `IN PROGRESS` → `DONE` | `🔴 BLOCKED`

## 0. INTAKE
- [ ] Restated the objective and what "reached" means for each milestone.
- [ ] Loaded `.claude/roles/PROJECT_MANAGER.md`.
- [ ] Read canonical `docs/PROJECT_PLAN.md` — did not guess status.
- [ ] Any unknown date/dependency raised as `NEEDS-INPUT`, not invented.

## 1. PRE-FLIGHT
- [ ] Work broken into ordered, independently-verifiable steps.
- [ ] Each step assigned an owning role → its checklist → its verification gate.

## 2. EXECUTE  (plan)
- [ ] Dependencies + critical path explicit.
- [ ] Risks/blockers listed with mitigation + owner. Estimates as ranges with assumptions (or "no basis").

## 3. VERIFY — STAGING  (status is observed, not assumed)
- [ ] Each task status reflects evidence: `ON STAGING (verified)` requires the role's staging checklist green.
- [ ] No "complete" rests on an unverified claim from another role.

## 4. VERIFY — PROD
- [ ] Deploy ordering held: `dev` → staging verify → PR → `main` → prod verify. No step jumped staging.
- [ ] `IN PROD (verified)` only after staging-verified + PR-merged, with evidence.

## DONE-GATE
- [ ] Every reported status backed by seen evidence (no green over a blocker).
- [ ] Blockers shown as `🔴 REAL BLOCKER`, not softened to "mostly done".
- [ ] No invented timeline / %-complete.
- [ ] All true → report status accurately; plan **DONE** only when its steps are verified-done.
