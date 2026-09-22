# Functionality Verification Report — Charts: support/resistance as a default layer, patterns panel = chart patterns only

- **Branch:** (new, off origin/dev 56b48719)
- **Date:** 2026-09-22
- **Author:** Claude (orchestrator; DESIGN_ENGINEER + FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** staging (staging.niveshcopilot.com) — owner-only behind `require_feature("charting")`
- **Changed areas:** backend routes/services: no · frontend src: yes

## Summary
Owner feedback on staging (ADANIENT screenshot): the Patterns panel listed six identical "SUPPORT_RESISTANCE confirmed" rows. Support/resistance
levels are not chart patterns; two of the six were only formed (GEOMETRY_VALID), not confirmed; support levels drew nothing (the UI read
`support`/`resistance` while S/R records carry `level`/`kind`). Change: S/R levels move out of the Patterns panel into a "Support &
resistance" checkbox that is ticked by default and draws every level at its real price; the Patterns panel lists only chart patterns and
is blank (empty state) when none exist; pattern labels come from status, not population.

## Test Cases
> Authored UP FRONT — before implementation.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-25 | Patterns panel | symbol with a rectangle + S/R levels | e2e | panel lists the rectangle only; no SUPPORT_RESISTANCE rows | PASS (local, mocked) |
| TC-26 | Patterns panel | symbol with only S/R levels (TCS fixture / ADANIENT on staging) | e2e | panel shows the empty state, no rows | PASS (local, mocked) |
| TC-27 | S/R layer | open any symbol | e2e | "Support & resistance" checkbox ticked by default; one price line per level at `levels.level` for BOTH kinds; unticking removes all; count shown | PASS (local, mocked) |
| TC-28 | Labels | GEOMETRY_VALID pattern / PRICE_CONFIRMED pattern | e2e | "formed" vs "confirmed" — an unbroken pattern is never labelled confirmed | PASS (local, mocked) |
| TC-29 | Staging | real ADANIENT + one symbol with chart patterns | e2e (no mocks) | rows = served non-S/R patterns; S/R toggle checked; drawn level count = served S/R count | PENDING |

## Local evidence (2026-09-22)
- `npx tsc -b && npx vite build` → ✓ built; ChartsScreen 223.89 kB separate chunk.
- `npx playwright test research-charts research-move-odds research-paper-trades research-access research-qa --project=desktop-chrome`
  → **94 passed**, 5 skipped (staging-only). Includes TC-25..TC-28. One existing data-view test updated for the deliberate relabel
  (`RECTANGLE` → `Rectangle`) and extended to assert the new levels table.
- Backend `tests/test_research_chart.py` (incl. the UI-fixture contract guard) → 21 passed.
- Fixtures now carry real statuses (`PRICE_CONFIRMED`, `GEOMETRY_VALID`) and the real SUPPORT_RESISTANCE `levels` shape.
- TC-29 (staging) pending: needs the PR merged + a session token.

## Inputs required from user
- Admin `session_token` for the staging run (TC-29); owner merge of the PR.

## Verdict: BLOCKED
