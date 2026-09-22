# SUPERSEDED 2026-09-22 — staging verified after #140 merged (API 17/17, UI 4/4, data 513/110/37 match); see charting_fixes_costs_context.md

# OVERRIDE — charting fixes / costs / index data / snapshot re-export (2026-09-22)

REASON: staging verification (TC-39: API 17/17 + UI 4/4) needs the owner to merge and deploy the PR first, then a fresh staging
session token for the Playwright run. All local and data checks pass (research 771, backend 38, real snapshot served for 50/50
symbols) — see `charting_fixes_costs_context.md`. The only product-path change is snapshot data under
`backend/services/research_chart_snapshot/`; no route, service or frontend code changed.

To clear: after deploy, run `research/charting/tools/verify_staging_api.py` and
`STAGING_SESSION_FILE=… npx playwright test e2e/tests/staging-research-charts.spec.ts`, paste the output into the report, set its
verdict to `## Verdict: PASS`, and mark this file SUPERSEDED.
