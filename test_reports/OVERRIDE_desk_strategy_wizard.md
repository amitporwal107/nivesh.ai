# OVERRIDE — Strategy Lab › Build a trade, the four-step wizard (PR to dev, not merged)

REASON: The branch is not deployed to staging. The brief is one PR to `dev`, not merged, with no deploy. So there is no staging API run and no Playwright run against real data. The real staging checks are still open:
- `GET /api/desk/strategy/templates` with the new fields;
- `POST /api/desk/paper-trades/check` on a real account;
- the wizard against the live NIFTY chain.

What was run (real output in `test_reports/desk_strategy_wizard_2026-10-28.md`):
- Backend unit tests in the `nivesh/backend:staging` image: the two new files and the related suites.
- tsc and the production build.
- Playwright on mocked APIs. The catalog and payoff fixtures are the real outputs of this branch's backend code. Everything else is labelled MOCK.

Still needed for a staging PASS:
1. Deploy the branch to staging; the backend process needs a restart, the frontend an image rebuild.
2. `curl` the templates route and check that the 13 entries carry intent, tags, direction and illustration.
3. POST a real bull call spread to `/api/desk/paper-trades/check` as a test user. Confirm that the outcome and reasons match a real paper-trade POST, and that no row lands in the decisions or trades collections.
4. Run the wizard on staging with Playwright: choose a template, configure, check, start one paper trade, and see it on the Live desk.
