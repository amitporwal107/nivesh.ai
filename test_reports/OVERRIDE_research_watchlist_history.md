# OVERRIDE — Research Watchlist dated lists / historical view

REASON: 13 of 14 test cases passed on staging with real output (see research_watchlist_history_20261012_2355.md). TC-14 (switching between two lists in the picker) cannot run until a second list exists on staging; that list (2026-10-12) is waiting for the user's approval of the candidates and I will not put placeholder picks on a public page to satisfy a test. Two-list behaviour is covered meanwhile by the unit tests (7 passed).

To close: publish the approved 2026-10-12 list, re-run frontend-v5/e2e/tests/watchlist-unauth.spec.ts (TC-14 then stops skipping), and set the report's verdict.
