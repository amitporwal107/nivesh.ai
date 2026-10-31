# OVERRIDE — Desk Copilot floating window (feat/copilot-floating-window): staging pass after merge

REASON: FW-10 (a manual Float / drag / resize / Lock pass on staging with a session) can only run after the merge. FW-1 …
FW-9 pass in mocked Playwright on a production build (93 passed, 0 failed), and tsc is clean; see
`test_reports/copilot_floating_window_20261029.md`. This branch carries PR #404's commit (both edit CopilotDock.tsx):
merge #404 first.
To finish: after the deploy, check the served bundle has "Copilot floating", then do the manual pass with a session.
Paste the result, set the verdict to PASS and delete this file.
Owner-visible: yes. Date: 2026-10-29. Session 3d5d2da4.
