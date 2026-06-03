# Checklist — TASK: Bug Fix / Debug

**Use when:** something is broken in running code.
**Target env:** ☐ Staging   ☐ Prod
**Status:** `NOT STARTED` → `IN PROGRESS` → `DONE` | `🔴 BLOCKED`
**Roles:** FULL_STACK_DEV (root-cause + fix) → QA (verify)  ·  output: Reproduce→Evidence→Root cause→Fix→Prevention

## 0. INTAKE
- [ ] Restated the bug + expected vs actual.
- [ ] Loaded `.claude/roles/FULL_STACK_DEVELOPER.md`.
- [ ] Read canonical `docs/` / inspected logs (Loki, Cloud Logging) for evidence — did not guess.
- [ ] Unknown repro steps / intended behavior → `NEEDS-INPUT`, not assumed.

## 1. PRE-FLIGHT
- [ ] **Reproduced the failure** and showed the failing behavior/output — NOT a guessed fix.
- [ ] Gathered evidence (logs, response body, stack trace, DB row) — shown.

## 2. EXECUTE
- [ ] Built hypotheses; eliminated alternatives against the most specific evidence.
- [ ] Identified **root cause** (not symptom); smallest fix at the cause.
- [ ] Noted a prevention step (test/guard) so it can't silently regress.

## 3. VERIFY — STAGING
- [ ] The **original failing case now passes** — before/after shown.
- [ ] Regression test added that fails without the fix — shown.
- [ ] `make verify` / relevant suite green — shown.
- [ ] **Data test** if data-related: real DB / `nidp.validation_findings` clean — shown.
- [ ] `curl .../api/healthz` ok — shown.

## 4. VERIFY — PROD
- [ ] Fix VERIFIED on staging first; merged via PR.
- [ ] No destructive prod action to "reproduce" (read-only only).
- [ ] `/api/health` (+ NIDP health) green — shown; the prod symptom is gone — shown.
- [ ] Rollback path confirmed.

## DONE-GATE
- [ ] Root cause stated; original case passes WITH evidence; regression test present.
- [ ] App test AND data test shown; no claim beyond evidence.
- [ ] All true → **DONE**; else → **IN PROGRESS**.
- [ ] Can't reproduce / blocked → `🔴 REAL BLOCKER:` what / why / needed. Do NOT ship a guessed fix.
