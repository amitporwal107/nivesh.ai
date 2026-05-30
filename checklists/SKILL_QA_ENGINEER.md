# Checklist — SKILL: QA / Test Engineer

**Use when:** verifying behavior, writing/fixing tests, coverage, regressions, ship sign-off.
**Target env:** ☐ Staging   ☐ Prod *(prod = read-only)*
**Status:** `NOT STARTED` → `IN PROGRESS` → `DONE` | `🔴 BLOCKED`

## 0. INTAKE
- [ ] Restated the task; pass/fail criterion stated in one sentence ("works iff X").
- [ ] Loaded `.claude/roles/QA_ENGINEER.md`.
- [ ] Read canonical `docs/` for expected behavior — did not guess.
- [ ] Ambiguous behavior → asked PRODUCT (`NEEDS-INPUT`), not assumed.

## 1. PRE-FLIGHT
- [ ] Identified critical paths in scope (auth, portfolio, plans, goals, V3, ingesters).
- [ ] Confirmed I will test the requirement, not just that a function returns something.

## 2. EXECUTE
- [ ] Wrote/updated unit + integration + edge (empty/max/wrong-type/unauthorized) + failure tests.
- [ ] Confirmed each new assertion FAILS when the behavior is broken (has teeth).

## 3. VERIFY — STAGING
- [ ] `playwright test` + `pytest` against staging — output shown.
- [ ] Coverage measured (`pytest --cov`): critical ≥95% / overall ≥80% — shown.
- [ ] **Data correctness:** `nidp.job_log`, `nidp.v_feed_status`, `nidp.validation_findings` —
      row counts in 30-day band, no `BLOCK` in 24h, V3 scores fresh — shown.
- [ ] Load/failure tests (if any) run on staging only.

## 4. VERIFY — PROD  *(read-only)*
- [ ] No write / load / destructive tests against prod.
- [ ] Smoke `/api/health`, `/daas/health`, `/query/health` — shown.
- [ ] DaaS DQ envelope `data_quality.dq_status` as expected; gate verdict reviewed — shown.
- [ ] Read-only spot-check of real prod data matches expectation — shown.

## DONE-GATE
- [ ] Verdict given: **SHIP / DON'T SHIP / UNVERIFIED** with reason.
- [ ] App test shown AND data test shown; coverage numbers from real tool output.
- [ ] No green that proves nothing; no claim beyond evidence.
- [ ] All true → **DONE**; else → **IN PROGRESS**.
- [ ] Blocked / prod-only failure → `🔴 REAL BLOCKER:` what / why / needed → hand to dev. No "retry til green".
