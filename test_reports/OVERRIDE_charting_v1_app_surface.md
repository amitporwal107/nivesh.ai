# OVERRIDE — charting v1 app surface (chart API, drawings API, Research → Charts tab)

REASON: staging verification RAN (2026-09-21/22, after PRs #134 and #135) and is not fully green: API 17/17 pass; UI 3/4 staging tests pass; the fourth fails on one real defect — the provenance drawer shows `[object Object]` for manifest `source.files` (and for multi-output `warmup_period`). The fix is built and locally verified (PR #136, awaiting the owner's merge); staging re-verification needs that deploy plus a fresh session token. TC-1/TC-13 need a second account and remain covered only by the local TestClient suite.

What IS verified (local, real output in `charting_v1_app_surface.md`): research engine 386 passed; backend chart/drawings/flag 37 passed (FastAPI TestClient); real-app router mount (7 routes); frontend build with a separate chart chunk; Playwright 89 passed / 1 skipped against mocked contract-shaped responses; real-data snapshot checks (513 patterns, schema-complete, no future dates, TC-24 0 mismatches).

What is NOT verified: any behaviour on staging; real session/allowlist enforcement end-to-end; real Mongo for drawings; Playwright against the live API.

To clear: resize app-vm disk (≥6 GB free) → owner approves commit + PR to dev → staging deploy → re-run TC-1..TC-24 against staging with a session_token → set the report's final line to `## Verdict: PASS`.
