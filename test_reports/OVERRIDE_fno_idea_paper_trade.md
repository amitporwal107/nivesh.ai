# OVERRIDE: fno_idea_paper_trade (branch fix/fno-idea-paper-trade)

REASON: The branch is not deployed to staging and no session token is available, so the one signed-in staging check (S-2: click "Paper trade" on a staging F&O idea and see 201) has not been run. It also writes a paper trade and reserves paper cash, so it needs the owner's go-ahead.

Evidence (this session, real output, in test_reports/fno_idea_paper_trade_20261027.md):
- Reproduced first: the old body through the real validator → `REFUSED code = invalid_signal`.
- pytest (staging image): the contract test sends the exact bodies the browser sends (shared fixture) through the real route → 201 with the signal stored; the pre-fix body → 422 `invalid_signal`; related suites `233 passed`.
- Playwright (production build, mocked API): `169 passed, 2 skipped`; the browser's body equals the shared contract on Top by regime, the Top 10 row, the lab focus and the AI watchlist.
- Staging, read only: 10/10 real stored F&O ideas of 2026-10-26 get valid levels from the deployed engine and their bodies pass the deployed validator; the branch's job dry run (in memory, nothing written) stores valid levels for all 10.

UNVERIFIED: the signed-in click on the deployed build; the first nightly run that stores levels (next 20:15 IST after deploy).
