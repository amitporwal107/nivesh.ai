# Checklist — TASK: DB Migration

**Use when:** any schema change (Nivesh PG `nivesh_prod`, Mongo, or NIDP TimescaleDB `nidp`).
**Target env:** ☐ Staging   ☐ Prod
**Status:** `NOT STARTED` → `IN PROGRESS` → `DONE` | `🔴 BLOCKED`
**Roles:** FULL_STACK_DEV  ·  Canonical: docs/DATABASE_SCHEMA.md

## 0. INTAKE
- [ ] Restated the change; which DB + tables.
- [ ] Loaded `.claude/roles/FULL_STACK_DEVELOPER.md`.
- [ ] Read `docs/DATABASE_SCHEMA.md` + the actual migration files — did not guess current schema.
- [ ] Any ambiguity in intended shape → `NEEDS-INPUT`, not assumed.

## 1. PRE-FLIGHT
- [ ] **Forward-only**; written with `IF NOT EXISTS`. Not editing an applied migration.
- [ ] Destructive change (drop/rename/type-change)? → 🔴 REAL BLOCKER + explicit sign-off + backup plan.
- [ ] On `dev` branch.

## 2. EXECUTE
- [ ] New migration file added (next number); follows naming convention.
- [ ] App: registered for `post_deploy_migrate`. NIDP: registered in `source_registry`/deploy path if needed.

## 3. VERIFY — STAGING
- [ ] Ran against staging DB — app `127.0.0.1:5532` / NIDP `127.0.0.1:5434` (`nidp_staging`) — **applied output shown**.
- [ ] `schema_migrations` shows it applied — shown.
- [ ] Dependent code/query works post-migration (run it) — shown.
- [ ] **Data test:** row counts / integrity sane after migration — shown.

## 4. VERIFY — PROD
- [ ] Staging apply VERIFIED; merged via PR.
- [ ] **PG snapshot taken** before any downgrade-capable/destructive change.
- [ ] Applied via `post_deploy_migrate` / NIDP `deploy/vm/deploy.sh`; output shown.
- [ ] `SELECT filename FROM <schema>.schema_migrations ORDER BY applied_at` confirms it — shown.
- [ ] Health green; rollback = snapshot restore / `alembic downgrade -1` (only with snapshot).

## DONE-GATE
- [ ] Migration ran on the target DB AND output shown (never "should apply").
- [ ] App test AND data test shown; no destructive change without sign-off + snapshot.
- [ ] All true → **DONE**; else → **IN PROGRESS**.
- [ ] Blocked → `🔴 REAL BLOCKER:` what / why / needed.
