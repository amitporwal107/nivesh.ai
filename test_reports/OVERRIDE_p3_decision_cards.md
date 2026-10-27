# OVERRIDE — p3_decision_cards (staging verification not run)

REASON: The brief for `feat/p3-decision-cards` forbids staging writes, pushes, PRs and deploys, so the branch cannot run
on staging, and a signed-in staging check would also need a user session token. Everything that can run locally ran:
- backend pytest: the focused run, 95 passed and 1 skipped; the desk/plan/risk subset, 1854 passed on the branch against
  1828 on plain origin/dev, with 0 failures on either;
- Playwright: 691 passed on the branch against 666 on dev. The same 32 `strategy-graphs` cases fail on both; the
  "fails on branch, passes on dev" list is empty.

The full output is in `test_reports/p3_decision_cards_20261027.md`.

Still to do after a deploy:
- `GET /api/desk/trade-plans/{id}` returns `risk_decision` for a plan the user has submitted;
- the AI watchlist day carries `notes.scan_basis` and `carried`;
- `GET /api/admin/risk/jobs/positional_engine` answers for the scanner's records.

Open finding (not overridden): the plan's size and the risk service's approved size differ. The plan leaves out gap
stress and the account's equity. See the report's "Findings" section.
