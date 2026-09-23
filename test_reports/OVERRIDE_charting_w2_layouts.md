# OVERRIDE — W2-LAYOUTS staging verification

REASON: Staging verification of `/api/research/chart-layouts` needs (1) this package merged into a deploy branch and
a backend deploy (per the host rules in force for this task, no deploy was run from this session — this package's
scope was the backend route + its local pytest suite only), and (2) a fresh owner/allowlisted staging session token
(held only in a 0600 scratch file, never in argv/logs), neither of which this session has. Local pytest is real and
green (53/53, see `test_reports/charting_w2_layouts.md`, `## Verdict: PASS`), and covers the gate, per-user
ownership, CSRF origin check, validation reason codes and the full round-trip (AC9) against an in-memory fake Mongo
collection — the same method `test_research_drawings.py` already uses for the sibling endpoint, which itself later
verified clean on staging (17/17 API checks, PR #134-#141). No real Mongo or staging host was touched from this
session (host rule).

Next step once unblocked: after this package's PR is merged and deployed, run
`STAGING_COOKIE_HEADER=<0600 file> curl` (or the existing `research.charting.tools.verify_staging_api`-style
checker, extended with `chart-layouts` cases) against `POST/GET/PATCH/DELETE
https://staging.niveshcopilot.com/api/research/chart-layouts[/{layout_id}]` with an allowlisted owner cookie, and
confirm the stored Mongo document (`research_chart_layouts` on the staging DB) round-trips symbol/timeframe/
chart_type/indicators/panes/visible_range as asserted locally in TC-144.
