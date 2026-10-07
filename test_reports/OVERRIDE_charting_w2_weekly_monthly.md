# OVERRIDE — W2-EXPORT weekly/monthly bars (2026-09-23)

REASON: staging verification (real `GET /api/research/chart/{symbol}/ohlcv?timeframe=1W|1M` +
`.../indicators?timeframe=...` against the deployed API, and the Playwright staging spec once the
frontend package that consumes these timeframes lands) needs the owner to merge and deploy this
change, then a fresh staging session token. This worktree has no network egress and no deployed
staging build of this branch, so staging cannot be reached from here.

Every local and data check passes — see `charting_w2_weekly_monthly.md`: research suite
1034/1034 (1018 pre-existing + 16 new), backend chart suite 44/44 (38 pre-existing + 6 new),
weekly/monthly OHLCV values independently verified against real NSE data (including a named real
holiday and a real short month) by code written separately from `research/charting/resample.py`,
the snapshot re-export is byte-identical to the previously-committed snapshot in every field
except the new `timeframes` key (patterns still 513/513, config_hash unchanged), and a real
in-process FastAPI call through the actual route file against the actual installed production
snapshot confirms `timeframe=1D|1W|1M` works end-to-end (200 with correct bar counts, 400
`unknown_timeframe` for a bad value, default unaffected).

The only product-path changes are `research/charting/export.py`, the new
`research/charting/resample.py`, `backend/routes/research_chart.py`,
`backend/services/research_chart.py`, and the re-exported/installed snapshot data under
`backend/services/research_chart_snapshot/`. No frontend code was touched (out of scope for this
package; owned by other in-flight W0/W1/W2-LAYOUTS agents).

To clear: after merge + deploy, run the staging API checks (`curl`/`pytest` against
`staging.niveshcopilot.com` with a session token) for `timeframe=1D|1W|1M` on both `/ohlcv` and
`/indicators`, and the relevant Playwright staging spec once the frontend timeframe UI exists;
paste the output into `charting_w2_weekly_monthly.md`, set `## Verdict: PASS`, and mark this file
SUPERSEDED.
