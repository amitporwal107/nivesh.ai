# SPT UI — Trade Desk › Paper Trading: Opportunities · Analytics · Settings — test cases

Owner decision, 5 Nov 2026 ~07:00 IST: "Build in current workspace — plain, functional screens on real data inside today's
Trader workspace: Opportunities + Analytics + Settings under Trade Desk › Paper Trading (next to the P&L dashboard) …".
Owner decision, 5 Nov ~06:50 IST (config): SPT limits default from the user's risk profile; a user can TIGHTEN, only an ADMIN
can loosen; an admin can edit any user.

Requirements: PRD §12.5, §13, §16.1, §19.3, §19.7, §26; Workflow §11, §23.1; docs/scanner_paper_trading/DESIGN.md (D4 modes,
D10 wording). Screens: `?tab=trade&view=paper&sub=opportunities|analytics|settings`.

Backend contracts read from code (never guessed): `backend/routes/spt_signals.py`, `spt_risk.py`, `spt_accounts.py` (the
integration worktree's in-progress version with `overrides` / `defaults` / admin routes), `spt_paper.py`;
`services/spt/policy.py` (`public()`), `services/spt/settings.py`, `services/spt/proposals.py`, `services/spt/pipeline.py`,
`services/spt/risk.py`, `services/spt/outcomes/analytics.py`.

Automated in `frontend-v5/e2e/tests/copilot-app-desk-spt-paper.spec.ts` with MOCK bodies (every one labelled
`// MOCK — not real data`). Mocked APIs, production build. A mocked e2e proves the screen renders and sends the right
requests; it does NOT prove the backend answers these shapes — the integrator verifies that against staging.

| ID | Case | Expected |
|---|---|---|
| SPT-UI-P-01 | Paper Trading sub-views | Chips read Live desk · Trade journal · P&L dashboard · Opportunities · Analytics · Settings; each new chip sets `sub=` and renders its screen (`spt-opps`, `spt-analytics`, `spt-settings`) |
| SPT-UI-P-02 | Opportunities: mode banner | Shows the account's mode from `GET /api/v1/paper/accounts` (e.g. APPROVAL) with its one-line meaning and a "Change in Settings" link that opens `sub=settings` |
| SPT-UI-P-03 | Opportunities: the note and the score label | "Rule-based levels for your paper account. Not investment advice; no accuracy is claimed." is shown; the score column says "not a probability" |
| SPT-UI-P-04 | Opportunities: table | One row per opportunity, joined to the user's proposal by `opportunity_id`: symbol, direction, horizon, state, sources (count + names), score; with a proposal: entry / stop loss / target 1 / target 2, R:R, quantity "sized by your limits", capital, planned risk, risk decision + reason codes, proposal state |
| SPT-UI-P-05 | Opportunities: a proposal whose opportunity is not in the list | Still shown as a row (from the proposal's own fields) |
| SPT-UI-P-06 | Opportunities: filters | State and horizon/direction filters are sent to `GET /api/v1/opportunities` as `state=`, `horizon=`, `direction=`; the symbol search narrows the rows |
| SPT-UI-P-07 | Opportunities: detail drawer | Row click opens a dialog with the original signals (scanner, time, score), validation (decision, reason codes, explanations), the proposal (entry type, exit plan), the risk decision (planned / stressed risk, portfolio before → after) |
| SPT-UI-P-08 | Approve | In APPROVAL mode a proposal AWAITING_USER_APPROVAL shows Approve, Reject and the expiry countdown; Approve POSTs `/api/v1/opportunities/{id}/approve` and shows the resulting order state |
| SPT-UI-P-09 | Approve refused | A 409 `{detail:{code, message, reason_codes}}` shows the code, the server's message and the reason codes; no success is shown |
| SPT-UI-P-10 | Reject needs a reason | Reject with an empty reason sends nothing and says a reason is required; with a reason it POSTs `/reject` `{reason}` |
| SPT-UI-P-11 | Auto / tracking modes | No Approve button; the row says what happened (order created and its state / tracked, no order) |
| SPT-UI-P-12 | Opportunities: errors and empty | A failing opportunities read shows the problem with Retry; an empty list says so (no invented rows) |
| SPT-UI-P-13 | Analytics: scanner outcomes | `GET /api/v1/analytics/scanners` rows per scanner / category / score band with signals, per-horizon n, hit rate with its 95 % interval, average return; small samples flagged with the API's note; "Counts of what happened, not probabilities" shown; changing the kind sends `kind=` |
| SPT-UI-P-14 | Analytics: paper results | From `GET /api/v1/paper/trades` only: trades, win rate, average win / loss, expectancy (R), profit factor, net P&L, average holding, exit reasons, by scanner (from the trade's signal ids), with the formulas shown; numbers match a hand calculation of the mock |
| SPT-UI-P-15 | Analytics: empty state | No closed SPT trade → "No closed paper trade from scanner opportunities yet"; no metric invented |
| SPT-UI-P-16 | Settings: mode change | Mode buttons with one-line meanings; picking Tracking PUTs `{mode:"tracking", expected_version}`; picking Auto first asks for confirmation and PUTs only after Confirm |
| SPT-UI-P-17 | Settings: limits form | Every leaf shows its effective value, default, source (risk profile vs SPT default) and whether it is overridden; Save sends ONLY the changed leaves |
| SPT-UI-P-18 | Settings: reset to default | "Reset to default" on an overridden leaf, then Save, sends that leaf as `null` |
| SPT-UI-P-19 | Settings: loosening needs an admin | A 403 `{detail:{code:"admin_required", loosened:[…]}}` shows "Loosening needs an admin" with the field(s) |
| SPT-UI-P-20 | Settings: concurrent change | A 409 `concurrent_change` asks to reload, and Reload re-reads the config |
| SPT-UI-P-21 | Settings: version history | The account detail's `config_versions` are listed (version, when, who, changed fields, reason) |
| SPT-UI-P-22 | Settings: admin panel only for admins | Not shown when `/api/auth/me` has `is_admin:false`; shown when true |
| SPT-UI-P-23 | Settings: admin edits a user | Load user id → `GET /api/admin/spt/{uid}/config`; Save without a reason is refused in the UI; with a reason PUTs `/api/admin/spt/{uid}/config` `{extras, reason, expected_version}` |
| SPT-UI-P-24 | Settings: market-wide settings | `GET /api/admin/spt/settings` values + sources; Save PUTs `{values:{changed}, reason, expected_version}` |
| SPT-UI-P-25 | Old config shape | A config without `overrides` / `defaults` still renders the effective values; reset is not offered |
| SPT-UI-P-26 | Phone 390 px | All three screens: cards, no page-level sideways scroll |
| SPT-UI-P-27 | Wording | No "pick", "recommend", "suggest" on any of the three screens |
| SPT-UI-P-28 | Regression | `copilot-app-desk-pnl`, `-pnl-exits`, `-trade-desk`, `compliance-wording` specs stay green |
