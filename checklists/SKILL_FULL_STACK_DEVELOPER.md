# Checklist — SKILL: Full Stack Developer

**Use when:** any task that changes code that runs (feature, API, DB, auth, ingester, bug).
**Target env:** ☐ Staging   ☐ Prod
**Status:** `NOT STARTED` → `IN PROGRESS` → `DONE` | `🔴 BLOCKED`

## 0. INTAKE
- [ ] Restated the task in my own words; scope is clear.
- [ ] Loaded `.claude/roles/FULL_STACK_DEVELOPER.md` (+ any other role guide).
- [ ] Read the canonical `docs/` for facts I need — did not guess.
- [ ] Any required assumption raised as `NEEDS-INPUT` and confirmed — not assumed silently.

## 1. PRE-FLIGHT
- [ ] On `dev`/`feat/*` branch — confirmed, not `main`.
- [ ] Read neighboring files; will follow existing patterns (`backend/services|routes`, `backend/nidp/services/<svc>`, React V2/V5).
- [ ] Smallest change at the root cause identified (no drive-by refactor).

## 2. EXECUTE
- [ ] One logical change; edge + error paths handled (no empty catch, no stray `TODO`).
- [ ] No new dependency without stated reason; no secrets in code; mocks (if any) labeled `// MOCK`.

## 3. VERIFY — STAGING
- [ ] `make verify` (12 smoke tests) green — output shown.
- [ ] If FE: `REACT_APP_BACKEND_URL=https://niveshcopilot.com PUBLIC_URL=/v2 CI=false yarn build` ok — shown.
- [ ] If BE: `python3 -m py_compile backend/server.py` (+ all `.py`) clean.
- [ ] If ingester: `./test_locally.sh <service>` over 30-day range — shown.
- [ ] `playwright test` E2E green — shown.
- [ ] No secrets in diff: `git diff --name-only | grep -E '\.env|\.key|\.pem'` empty.
- [ ] `curl -sf https://staging.niveshcopilot.com/api/healthz` → ok — shown.
- [ ] **Data test:** queried staging DB / `nidp.v_feed_status`; no `severity='BLOCK'` in 24h — shown.

## 4. VERIFY — PROD
- [ ] Already VERIFIED on staging (evidence linked).
- [ ] Reached `main` via PR merge (no direct push, no force-push).
- [ ] No destructive op against prod data (else 🔴 REAL BLOCKER + ask for sign-off).
- [ ] `curl -sf https://niveshcopilot.com/api/health` → `{"status":"ok"}` — shown.
- [ ] If NIDP: `/daas/health` + `/query/health` → 200 — shown.
- [ ] Grafana Job Health checked; latest feed OK in `nidp.v_feed_status` — shown.
- [ ] Rollback path confirmed (git checkout SHA + redeploy / `rollback.sh` / Cloud Run revision).

## DONE-GATE
- [ ] Every box for the target env green AND evidence shown.
- [ ] App test shown AND data test shown.
- [ ] No unlabeled mock data; no claim beyond evidence ("staging" ≠ "prod").
- [ ] All true → **DONE**; else → **IN PROGRESS**.
- [ ] Blocked → `🔴 REAL BLOCKER:` what / why / needed. No workaround, mock, or guess.
