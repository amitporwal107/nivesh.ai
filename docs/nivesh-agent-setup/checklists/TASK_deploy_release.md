# Checklist — TASK: Deploy / Release

**Use when:** shipping code to staging or promoting to prod.
**Target env:** ☐ Staging   ☐ Prod
**Status:** `NOT STARTED` → `IN PROGRESS` → `DONE` | `🔴 BLOCKED`
**Roles:** FULL_STACK_DEV + PROJECT  ·  Canonical: docs/BUILD_AND_DEPLOYMENT.md

## 0. INTAKE
- [ ] Restated what's being released + target env.
- [ ] Loaded `.claude/roles/FULL_STACK_DEVELOPER.md` (+ PROJECT_MANAGER for ordering).
- [ ] Read `docs/BUILD_AND_DEPLOYMENT.md` — did not guess commands.
- [ ] Any uncertainty about scope/approval → `NEEDS-INPUT`, not assumed.

## 1. PRE-FLIGHT
- [ ] All changes verified locally: `make verify`, `yarn build`, `playwright`, `pytest` green — shown.
- [ ] No secrets in diff (`git diff --name-only | grep -E '\.env|\.key|\.pem'` empty).
- [ ] Migrations forward-safe; destructive ones signed off + snapshot planned.
- [ ] **Deploy ONCE** (fixed all issues first). Deploy via git (`redeploy.sh`/`deploy.sh`), not rsync (manual).

## 2. EXECUTE — STAGING
- [ ] On `dev`; deployed to staging via `redeploy.sh` / NIDP `deploy/vm/deploy.sh --branch=dev`.

## 3. VERIFY — STAGING
- [ ] `curl -sf https://staging.niveshcopilot.com/api/healthz` ok — shown.
- [ ] Tailed logs ~5 min, no errors.
- [ ] Latest feed OK in `nidp.v_feed_status` (if NIDP) — shown.

## 4. VERIFY — PROD
- [ ] Staging verified; promoted via **PR merge to `main`** (no direct/force push); CI green on release commit.
- [ ] Deployed via documented path; `curl https://niveshcopilot.com/api/health` → ok — shown.
- [ ] NIDP: `/daas/health` + `/query/health` 200 — shown.
- [ ] Grafana Job Health checked; no new Sentry frontend errors — shown.
- [ ] **Rollback path confirmed available** (git checkout SHA + redeploy / `rollback.sh` / Cloud Run revision).

## DONE-GATE
- [ ] Health green on the target env WITH shown output; logs clean.
- [ ] Reached prod only after staging-verified + PR; rollback confirmed.
- [ ] All true → **DONE (deployed & verified on <env>)**; else → **IN PROGRESS**.
- [ ] Failure mid-deploy → `🔴 REAL BLOCKER:` what / why / needed → roll back, don't push forward blindly.
