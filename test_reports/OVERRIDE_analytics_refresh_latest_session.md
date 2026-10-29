# OVERRIDE — analytics_refresh latest session (fix/analytics-refresh-latest-session)

REASON: the real run writes to the shared staging warehouse (`analytics.refresh_all` deletes and re-inserts rows), so it
runs only after the merge, at the 00:10 IST cron, or on a manual run the owner approves. AR-1 … AR-5 pass: 4 unit tests,
plus the read-only staging check that the latest snapshot is 2026-10-29 while `analytics.stock_card` stops at 2026-10-12.
See `test_reports/analytics_refresh_latest_session_20261030.md`.
To finish: after the next run, check `nidp.job_log` (`analytics_refresh` OK with rows > 0) and
`max(as_of_date)` of `analytics.stock_card`. Then set the verdict to PASS and delete this file.
Owner-visible: yes. Date: 2026-10-30. Session 3d5d2da4.
