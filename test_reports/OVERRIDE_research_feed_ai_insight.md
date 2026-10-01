# OVERRIDE — Research feed insights on Claude

REASON: The staging endpoint check (TC-R12) needs this PR merged to dev, which is a live staging deploy, and a logged-in
session_token. Everything else ran and passed: 34 + 5 backend tests, 66 Playwright tests, tsc, and a real data
write to staging PG (UPDATE 4866, rollback CSV saved). The status is IN PROGRESS, not done. See
test_reports/research_feed_ai_insight_20260930.md.
