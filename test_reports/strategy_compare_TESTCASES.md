# Compare structures side by side: test cases (authored before implementation)

Ask (user, 2026-10-24, "ok" to my proposal): compare the ready-made structures of one market view for the same underlying and expiry, on figures that are real: entry, max profit, max loss, reward:risk, net delta, theta, vega, margin and charges.
Deliberately NOT built: a ranking, a score or a "best" marker. A ranking needs a probability of profit and an expected-return model that do not exist, and weights no test has validated. The table is sorted only by the column the user picks.
Reads existing routes only (POST /api/desk/strategy/levels for the engine's figures, POST /api/fno/margin for Zerodha's calculator); the browser computes nothing.

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | the Compare mode lists the structures of the chosen view (bullish: Buy Call, Sell Put, Bull Call Spread, Bull Put Spread), each priced at the chain's closes | e2e | 4 rows |
| TC-2 | a vertical debit spread's figures are the route's: entry, max profit, max loss, reward:risk (hand-worked from the fixture closes) | e2e | numbers |
| TC-3 | a credit spread reads "credit" and its max loss is width minus credit | e2e | numbers |
| TC-4 | a structure the engine rejects (Sell Put: undefined risk) shows "not supported" and dashes, never a figure | e2e | text |
| TC-5 | clicking a column header sorts by it (and again reverses); nothing else reorders the rows; no row is marked best and the note says why | e2e | order, text |
| TC-6 | no Kite login today: margin reads "— (no Kite login today)" and the other columns still show | e2e | text |
| TC-7 | switching the view changes the rows; 390px: the table scrolls inside its box, no page overflow; tsc exit 0 | e2e | pass |
