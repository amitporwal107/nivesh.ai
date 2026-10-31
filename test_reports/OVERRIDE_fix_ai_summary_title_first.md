# OVERRIDE: fix_ai_summary_title_first (branch fix/ai-summary-title-first)

REASON: Staging HTTP/UI evidence needs the user's staging session_token cookie, which I do not have; the change is also inert on staging until the backend process is restarted (bind-mounted code is not loaded code).

Evidence (this session, real output):
- pytest (staging image): tests/test_event_ai_insight.py + tests/test_filings_provenance.py `15 passed` (R5 updated, R5b added).
- Staging Mongo (read-only): 23 Oct IST event_ai_analysis: 1,747 filter_v1 + 180 single_full; newest 21:29 IST. Filings whose filter title mentions results/revenue/profit: 312, of which 81 kept and 231 dropped as routine (scores 50-58 for examples: DCB Bank, SBI Life, ACC, Laurus Labs, Tata Consumer, Atul).
- nidp.documents for 23 Oct: 536 parsed, 27 failed.
- Test cases: test_reports/fix_ai_summary_title_first_TESTCASES.md.

NOT fixed here (outside this repo): the importance filter's keep threshold (research/event_direction/ai_analysis). Whether results declarations should always get the full analysis is a decision for its owner.
UNVERIFIED: the Event Intelligence screen after a backend restart.
