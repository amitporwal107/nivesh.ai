# OVERRIDE — charting event dataset / regime features / candle + retest quality (2026-09-22)

REASON: staging verification (TC-49: API 17/17, UI 4/4, served patterns carry retest_quality and body_pct/close_location)
needs the owner to merge and deploy the PR, then a fresh staging session token. All local and data checks pass (research 924,
backend 38, snapshot diff = new keys only, real snapshot served for 50/50 symbols) — see `charting_events_regime_quality.md`.
The only product-path change is snapshot data under `backend/services/research_chart_snapshot/`; no route, service or frontend
code changed.

To clear: after deploy, run `python -m research.charting.tools.verify_staging_api` and the staging Playwright spec, check the
served fields, paste the output into the report, set `## Verdict: PASS`, and mark this file SUPERSEDED.
