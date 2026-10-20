# OVERRIDE — scan-rules.v2 — STATUS: IN PROGRESS, NOT COMPLETE

REASON: scan-rules.v2 is verified by unit tests, tsc, Playwright (mocked) and a run of the rules over the real staging snapshot of 2026-10-19, but not on the deployed staging API: the branch is uncommitted and unmerged, this session cannot push to dev, and the signed-in route needs a session token the user has not supplied. Evidence: test_reports/scan_rules_v2_20261020.md.
