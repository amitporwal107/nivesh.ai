# SPT UI — Risk Desk screens (Trading overview · Capital allocation · Portfolio risk): test cases

Owner decision, 5 Nov 2026 ~07:00 IST: plain, functional screens on real data inside today's Trader workspace; Overview /
Allocation / Portfolio Risk under Risk Desk (`/v5/app/trader/desk?tab=risk&view=overview|allocation|portfolio`).
Requirements: PRD §12.1, §12.3, §12.4, §19.2, §19.4, §19.5; Workflow §9, §18, §19. Backend contracts read from
`backend/routes/spt_risk.py`, `spt_accounts.py`, `spt_paper.py`, `spt_signals.py` (branch feat/spt-integration).

Authored before the implementation. Playwright spec: `frontend-v5/e2e/tests/copilot-app-desk-spt-risk.spec.ts`
(every API body there is a hand-written MOCK in the routes' shapes — `// MOCK — not real data`). Staging API verification
against the real backend is the integrator's step (the backend is changed in a different worktree).

| ID | View | Case | Expected |
|---|---|---|---|
| SPT-UI-R-01 | overview | Account figures | Equity (with the API's `equity_basis` text), available cash, deployed, reserved (with the pending-entry count), unrealized P&L (sum of the open positions' `mark.unrealized_net_rs`), realized P&L (sum of `realized_net_rs` of every SPT position) and the day's P&L are shown as the mock's numbers in ₹ |
| SPT-UI-R-02 | overview | Risk vs limits | SPT planned and stressed risk; open risk vs its cap and limit %; daily / weekly loss used vs limit %; drawdown with the ladder band word and the API's band text; the four thresholds; kill-switch state and its text; the SPT mode |
| SPT-UI-R-03 | overview | Counts and links | Qualified opportunities, proposals awaiting approval, open positions, pending orders = the mock counts; positions n of max and new today n of max; the two links go to `tab=trade&view=paper&sub=opportunities` and `sub=pnl` |
| SPT-UI-R-04 | overview | Active risk warnings | Every `kill_switch.reasons[].text`, the equity-unknown reasons and the unpriced SPT entries are listed; TRIGGERED reads as blocked (danger tone) |
| SPT-UI-R-05 | overview | Mode off, empty account | Mode off text from the API, counts 0, no positions, no warnings list crash; nothing invented ("—" where the API sends null) |
| SPT-UI-R-06 | allocation | Capital vs risk separated | Two separately headed sections, "Capital allocation" and "Risk allocation"; buckets equity_positional / equity_intraday / fno with cap vs used and the reserve (unallocated) row |
| SPT-UI-R-07 | allocation | Exposure by sector and instrument | Sector rows (exposure, % of equity, limit %), unclassified exposure; instrument rows; risk side: open-risk budget used/left, SPT planned vs stressed, risk by sector and by instrument from the stress test's positions |
| SPT-UI-R-08 | allocation | Ranked opportunities | Rank, symbol, opportunity score, R:R, quantity sized by your limits, capital, planned risk, the allocation decision and the reduce / reject reason as the API sends them; rows with `outcome ≠ ok` show the explanation |
| SPT-UI-R-09 | allocation | Recalculate | Button POSTs `/api/v1/allocation/recalculate/{account_id}` once; result list shows each proposal's quantity before → after and the decision; the ranked list is re-read |
| SPT-UI-R-10 | allocation | No qualified opportunities | Empty state text, no table, the capital/risk sections still render |
| SPT-UI-R-11 | portfolio | Risk totals | SPT planned vs stressed risk, open risk vs cap, daily and weekly loss utilisation bars, drawdown + ladder band |
| SPT-UI-R-12 | portfolio | Sector concentration | Each sector's exposure (% of equity vs the sector limit) and its planned / stressed risk |
| SPT-UI-R-13 | portfolio | Stress scenarios | Table rows: gap through stop (planned vs stressed), sector shock (worst sector and loss), market −3 % and −5 % (loss, beta assumed) — figures = the mock |
| SPT-UI-R-14 | portfolio | Positions at risk | Symbol, quantity, stop, current price, risk from the current price to the stop = (price − stop) × qty; a position without a live mark shows "—" and says why |
| SPT-UI-R-15 | portfolio | Not available panels | Correlation matrix, F&O Greeks and margin utilisation each say "not available in this release" with the reason; no number is drawn for them |
| SPT-UI-R-16 | portfolio | No positions | Empty positions state; stress scenarios with zero totals still render |
| SPT-UI-R-17 | all | Account id | Every account-scoped call uses the `account_id` from `GET /api/v1/paper/accounts` (asserted on the request paths) |
| SPT-UI-R-18 | all | API failure | `/risk/account` 503 → an error block with retry; no figures invented |
| SPT-UI-R-19 | all | Phone 390 px | No page-level sideways scroll on the three views |
| SPT-UI-R-20 | all | Existing Risk Desk | The existing Risk Desk specs stay green; the switcher shows the three new labels |
| SPT-UI-R-21 | all | Wording | No "recommend…", "pick(s)" or "suggested" in the visible text, aria-labels, titles or placeholders of the three views |
| SPT-UI-R-22 | all | Read-only | Opening the three views makes no write request; only the Recalculate click POSTs |
