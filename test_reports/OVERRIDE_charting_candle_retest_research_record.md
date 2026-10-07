# OVERRIDE — charting candle/retest quality moved to the research record (2026-09-22)

REASON: staging verification (TC-101: `research.charting.tools.verify_staging_api` +
`frontend-v5/e2e/tests/staging-research-charts.spec.ts`, confirming the served snapshot no
longer carries `body_pct`/`close_location`/`retest_quality`) needs the owner to merge and
deploy this PR, then a fresh staging session token. Every local and data check passes —
see `charting_candle_retest_research_record.md`: research suite 1018/1018, backend chart
suite 38/38, snapshot diff vs the pre-move on-disk snapshot shows ONLY the 3 removed keys
differing (1219 occurrences across 50 symbols, nothing else), and the re-exported pattern
content is byte-identical to the PR #140 snapshot (`b33cefffef`, before these fields ever
existed) across all 50 committed symbols. The only product-path change is snapshot data
under `backend/services/research_chart_snapshot/` plus `research/charting/patterns.py` /
`research/charting/enrich.py`; no backend route/service or frontend code changed.

To clear: after merge + deploy, run `python -m research.charting.tools.verify_staging_api`
and the staging Playwright spec, confirm the served pattern JSON has no `body_pct` /
`close_location` / `retest_quality` keys, paste the output into
`charting_candle_retest_research_record.md`, set `## Verdict: PASS`, and mark this file
SUPERSEDED.
