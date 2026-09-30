# OVERRIDE — Move odds filing analysis (PR #191)

REASON: Staging endpoint and UI checks (TC-12, TC-13) cannot run until the owner merges PR #191 to dev, which is a
live staging deploy on the shared app-vm. Everything that can run before that has run and passed: 25 backend tests,
50 Playwright tests, and a data check over the real pipeline output. Open owner decision: 4 of 114 real summaries use
words the page bans ("sell", "invest", "buy") in a factual sense. The status is IN PROGRESS, not done. See
test_reports/move_odds_filing_analysis_20260930.md.
