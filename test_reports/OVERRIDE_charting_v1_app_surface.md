# OVERRIDE — charting v1 app surface (chart API, drawings API, Research → Charts tab)

REASON: staging verification is BLOCKED, not skipped by choice. (1) Deploying to staging requires a `dev` push, which rebuilds images on nivesh-app-vm — whose disk is shared with PROD and currently has 4.1 GB free (reported by session app-6e, 2026-09-21), below the 6 GB safety floor after which earlier dev pushes crashed prod Mongo three times; a disk resize is an owner decision. (2) The owner also required no commit, push or deploy without their say-so. (3) Authenticated staging API + Playwright runs need an admin session_token for this session.

What IS verified (local, real output in `charting_v1_app_surface.md`): research engine 386 passed; backend chart/drawings/flag 37 passed (FastAPI TestClient); real-app router mount (7 routes); frontend build with a separate chart chunk; Playwright 89 passed / 1 skipped against mocked contract-shaped responses; real-data snapshot checks (513 patterns, schema-complete, no future dates, TC-24 0 mismatches).

What is NOT verified: any behaviour on staging; real session/allowlist enforcement end-to-end; real Mongo for drawings; Playwright against the live API.

To clear: resize app-vm disk (≥6 GB free) → owner approves commit + PR to dev → staging deploy → re-run TC-1..TC-24 against staging with a session_token → set the report's final line to `## Verdict: PASS`.
