# Checklist — SKILL: Product Manager

**Use when:** deciding what/why to build — scope, value, requirements, acceptance criteria.
**Target env:** ☐ Staging *(acceptance)*   ☐ Prod *(rollout)*
**Status:** `NOT STARTED` → `IN PROGRESS` → `DONE` | `🔴 BLOCKED`

## 0. INTAKE
- [ ] Restated the problem (who has what pain — retail investor / MFD).
- [ ] Loaded `.claude/roles/PRODUCT_MANAGER.md`.
- [ ] Read canonical `docs/` (BUSINESS_SPECIFICATION, PRD_TEMPLATE) — did not guess.
- [ ] Any user/market claim sourced OR labeled ASSUMPTION; load-bearing ones asked (`NEEDS-INPUT`).

## 1. PRE-FLIGHT
- [ ] Scope explicit: in / out / not-now.
- [ ] Cheapest version that delivers the value (real MVP) identified.

## 2. EXECUTE  (write the spec — use docs/PRD_TEMPLATE.md)
- [ ] Acceptance criteria written as objectively checkable pass/fail conditions.
- [ ] Tradeoffs + at least one cheaper alternative named; success measure defined.

## 3. VERIFY — STAGING  (acceptance proven before prod)
- [ ] QA demonstrated acceptance criteria met on staging — evidence linked.
- [ ] No assumption presented as a finding; no invented research.

## 4. VERIFY — PROD  (rollout)
- [ ] Staging acceptance evidence exists and is linked.
- [ ] Rolled out behind feature flag: `allowlist` first (verified), then `everyone`.
- [ ] Success measure instrumented (or gap flagged); rollback = flag off, trigger stated.

## DONE-GATE
- [ ] Recommendation explicit: **BUILD / DON'T BUILD / NEEDS-INFO** with reasoning.
- [ ] No assumption-as-fact; acceptance criteria are checkable; evidence shown.
- [ ] All true → **DONE**; else → **IN PROGRESS**.
- [ ] Blocked / missing data → `🔴 REAL BLOCKER` or `NEEDS-INPUT` to the user. No guessing.
