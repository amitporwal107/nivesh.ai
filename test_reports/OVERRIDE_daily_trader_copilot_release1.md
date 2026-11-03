# OVERRIDE — Daily Trader Copilot Release 1 (feat/daily-trader-copilot): staging and live-session checks

REASON: this PR bundles four pieces, each already carrying its own OVERRIDE for the same reason — a live, signed-in
staging session, and a post-deploy look, are needed and I do not have a session token:
- `OVERRIDE_daily_trader_home.md` (the Trader home panel, served + signed-in look)
- `OVERRIDE_copilot_chat_p0.md` (a live walk of each of the 6 fixes; the scheduler lock under the real 4-worker deploy)

The visual-answer engine itself (`dtc_visual_backend_20261030.md`) is Verdict: PASS on its own scope: it ran on a
REAL staging capture (not mocked), and its only unverified items are the deployed endpoint and the specialist LLM's
prose, which also need a live session.

Everything verifiable without a session passes: 380 backend tests, 108 frontend tests, tsc clean, and the full CI
allowlist run against this branch gives the identical pre-existing failing-test set as `origin/dev` (no regression).
See `test_reports/daily_trader_copilot_release1_20261030.md`.

To finish: after the merge and deploy, (1) a signed-in look at the Trader home and the desk's Copilot panel, (2) one
signed-in question per visual-answer intent on staging, compared against the data-quality footer's own sources, (3)
one signed-in question per p0 fix, and (4) `nidp.job_log` after the next scheduled job tick shows one row, not four.
Paste the results, set the verdict to PASS, and delete this file and the three it supersedes.
Owner-visible: yes. Date: 2026-10-30. Session 3d5d2da4.
