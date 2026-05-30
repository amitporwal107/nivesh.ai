# Checklist — TASK: New Feature

**Use when:** building a net-new user-facing capability.
**Target env:** ☐ Staging   ☐ Prod
**Status:** `NOT STARTED` → `IN PROGRESS` → `DONE` | `🔴 BLOCKED`
**Roles:** PRODUCT (spec) → FULL_STACK_DEV (build) → QA (verify) → DESIGN (UI) → PROJECT (sequence)

## 0. INTAKE
- [ ] Restated the feature; scope clear.
- [ ] Loaded the relevant role guide(s).
- [ ] Read canonical `docs/` (PRD, API, SCHEMA) — did not guess.
- [ ] Missing requirement/acceptance criteria → `NEEDS-INPUT` to user, not assumed.

## 1. PRE-FLIGHT
- [ ] PRD exists with **checkable acceptance criteria** (docs/PRD_TEMPLATE.md); else stop → PRODUCT.
- [ ] On `dev`/`feat/*`; design surface (V2/V5) confirmed; feature-flag name chosen.

## 2. EXECUTE
- [ ] Built behind a feature flag (`disabled` → `allowlist` → `everyone`).
- [ ] Backend (routes/services), data model (migration if needed), UI — each follows existing patterns.
- [ ] Edge/error/empty states handled; no unlabeled mocks; no secrets.

## 3. VERIFY — STAGING
- [ ] `make verify`, `yarn build`, `playwright test`, `pytest --cov` (crit ≥95/overall ≥80) — all shown.
- [ ] Each acceptance criterion demonstrated on staging — shown.
- [ ] UI rendered on staging with real data + states — shown.
- [ ] **Data test:** feature's data correct in real DB / no `BLOCK` findings — shown.
- [ ] `curl https://staging.niveshcopilot.com/api/healthz` ok — shown.

## 4. VERIFY — PROD
- [ ] Staging acceptance evidence linked; merged to `main` via PR.
- [ ] Flag `allowlist` verified on real users → then `everyone`.
- [ ] `/api/health` (+ `/daas/health` if NIDP) green — shown; Grafana clean.
- [ ] Rollback = flag off; path confirmed.

## DONE-GATE
- [ ] All acceptance criteria green WITH evidence for the target env.
- [ ] App test AND data test shown; no claim beyond evidence.
- [ ] All true → **DONE**; else → **IN PROGRESS**.
- [ ] Blocked → `🔴 REAL BLOCKER:` what / why / needed.
