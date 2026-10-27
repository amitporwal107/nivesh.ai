# OVERRIDE — p3_decision_cards (staging verification not run)

REASON: The brief for `feat/p3-decision-cards` forbids staging writes, pushes, PRs and deploys, so the branch cannot run
on staging. A signed-in staging check would also need a user session token.

Everything that can run locally ran at head `a3b2568e`, against plain origin/dev `7a44f84c`:
- **Backend CI allowlist:** 6471 passed on the branch vs 6438 on dev. The same 3 environment-dependent failures appear
  on both, plus 1 strict xfail (the Phase 1 BEAR finding).
- **Playwright:** 695 passed on the branch vs 666 on dev. The same 32 `strategy-graphs` cases fail on both.
- "Fails on branch, passes on dev" is empty on both sides.

The full output is in `test_reports/p3_decision_cards_20261027.md`.

Still to do after a deploy:
- `GET /api/desk/trade-plans/{id}` returns `account_size` and `risk_decision`, and the card's size equals what a
  submission is approved at;
- the AI watchlist day carries `notes.scan_basis` and `carried`;
- `GET /api/admin/risk/jobs/positional_engine` answers for the scanner's records.

Open finding (not overridden): the Phase 1 governor re-applies its BEAR / VIX factor to a size already cut, so no desk
share entry is ever allowed in those regimes. See the report's findings.
