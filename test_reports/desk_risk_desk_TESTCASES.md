# Risk Desk tab (desk redesign step 4): test cases

- **Branch:** feat/desk-risk-desk (from feat/desk-redesign-shell)
- **Date:** 2026-10-27
- **Written:** before implementation, after reading the routes (backend/routes/risk_controls.py on the shell branch)
- **Scope:** Smart trading desk, tab 04 Risk Desk (`?tab=risk&view=limits|controls|log`), paper risk only.
- **Spec:** `frontend-v5/e2e/tests/copilot-app-desk-risk-desk.spec.ts` (every `/api/*` answer MOCKED, written by hand in the routes' shapes).

Routes read: `GET /api/risk/profile`, `GET /api/risk/freshness[?symbol=]`, `GET /api/risk/status`, `PUT /api/risk/halt`,
`PUT /api/risk/kill-switch`, `GET /api/risk/audit`, `PUT /api/risk/profile`, `GET /api/risk/live-readiness`,
`GET /api/risk/decisions`, `GET /api/risk/decisions/{id}/lineage`, `POST /api/risk/decisions/{id}/replay`,
`GET /api/admin/risk/jobs/check_desk_alerts`, `GET /api/admin/risk/jobs/positional_engine`, `GET /api/auth/me` (is_admin).

| ID | View | Scenario | Type | Expected |
|----|------|----------|------|----------|
| RD-1 | all | The three views open from the view switcher and from the URL; one h1 per view; "Paper only" and "nothing is sent to a broker" are said | e2e | `risk-desk` root with `data-view` = limits / controls / log; one `h1`; wording present |
| RD-2 | Limits | The owner's 8 limits from GET /api/risk/profile, each with its value, used and left: per-trade 0.5% · open risk 3% · position 10% · sector 25% · daily loss 2% · weekly loss 4% · drawdown 10% from peak · min R:R 1.5 | e2e | 8 rows in the route's order; used / left worked out from `live` (open risk ₹/equity, largest sector ₹/equity, day and week loss ÷ start equity, drawdown); per-entry limits say "judged per entry" with the rupee budget |
| RD-3 | Limits | Open risk reserved at entry | e2e | "Open risk reserved ₹X of ₹Y (3%)" from `live.open.risk_rs` and `live.budgets_rs.open_risk` |
| RD-4 | Limits | Open positions n of 10 | e2e | "Open positions n of 10 (fixed limit, not in your profile)"; n from `live.open.positions` |
| RD-5 | Limits | Regime factor from GET /api/risk/freshness: BEAR → "BEAR regime (as of 23 Oct): size limits ×0.5"; not BEAR → no cut; VIX ≥ 25 adds ×0.5; unknown regime says the rule is skipped | e2e | the line names the regime, its as-of date and the factor |
| RD-6 | Limits | Input freshness: market state, last close and sector, each with as-of, age in sessions and ok / stale / unknown; last close and sector are per share (checked for the newest decision's symbol, or a typed one) | e2e | rows with status; a stale input shows its reason; typing a symbol re-reads `?symbol=` |
| RD-7 | Limits | "Correlation is not checked; sector exposure is the concentration control." and the footnote "These limits govern paper trades only. Your real holdings' risk checks are in My portfolio." with a working My portfolio link | e2e | text present; the link opens `?tab=portfolio` |
| RD-8 | Limits | Unknown figures read "unknown", never 0: a profile whose live block has an error | edge | used / left say unknown; no ₹0 |
| RD-9 | Controls | Kill switch and halt: on with a reason, blocks new entries only, open positions untouched, only an admin can switch it off; the audit list is beside them | e2e | the rule line; one PUT with `{enabled:true, reason}`; afterwards "Only an admin can turn the kill switch off."; the audit list shows the new row |
| RD-10 | Controls | The profile change form: a reason is required, tightening applies now, loosening asks an admin; the change log | e2e | the rule sentence; no PUT without a reason; a tightening PUT `{changes, reason}` |
| RD-11 | Controls | "Live trading: not available" with the readiness rows from GET /api/risk/live-readiness | e2e | the headline and one row per condition, each fail with its evidence |
| RD-12 | Controls | No risk sliders anywhere in the Risk Desk | e2e | zero `input[type=range]` / `role=slider` in all three views |
| RD-13 | Log | Every decision with outcome (allow / reduce / block), reasons, estimate (gross / costs / gap), budgets, policy and limits version | e2e | rows newest first; Allowed / Reduced / Blocked; the counts headline |
| RD-14 | Log | A click opens the decision: estimate and budgets, versions, lineage steps (GET …/lineage) and a replay (POST …/replay) | e2e | detail panel; lineage nodes; replay result "Match"; exactly one POST |
| RD-15 | Log | No decisions / a failing decisions read | failure | empty state; an error with Retry, nothing invented |
| RD-16 | all | Admin-only job-health strip: shown for an admin (`is_admin` true) with each job's state and reason; absent for a non-admin, and the admin routes are not called | e2e | strip with two jobs; for a non-admin no strip and no `/api/admin/risk/jobs` request |
| RD-17 | all | No "Policy & runtime" view, no strategy variants, no runtime controls, no autonomous-agents panel | e2e | the view switcher has exactly three views |
| RD-18 | all | Phone 390 px: no horizontal page scroll on any view, with long reasons | e2e | scrollWidth − innerWidth ≤ 1 |
| RD-19 | all | Paper only: the Risk Desk makes no write except the two control PUTs, the profile PUT and the replay POST, each on a user action | e2e | recorded writes match exactly |

Regression to run with it (mocked): `copilot-app-desk-risk-controls`, `-desk-risk-phase1`, `-fnolab-governance`,
`-desk-shell`, `-desk-decision-cards`. Old assertions that name the old Risk Desk layout follow the screens to their new
places (the shell's own rule).
