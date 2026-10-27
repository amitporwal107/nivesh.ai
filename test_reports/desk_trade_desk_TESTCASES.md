# Trade Desk tab (desk redesign step 3): test cases

Written 2026-10-27, **before the implementation**, after the API and UI design below. Spec:
`frontend-v5/e2e/tests/copilot-app-desk-trade-desk.spec.ts` (Playwright, mocked API, production build).

Plan and decisions: `docs/desk_redesign_20261027/PLAN.md` (owner, 27 Oct: Trade Desk uses `/api/desk/paper-trades`; same-bar
stop and target = stop first, flagged, no AMBIGUOUS state; only an admin clears the kill switch). Requirements:
`REVIEW_workspace_vs_phases.md` §A "2 Trade Desk", "What makes navigation harder", §2, §3; `REVIEW_lab_v5_prototype.md` §(d).

## Design (API + UI)

URL: `/app/trader/desk?tab=trade&view=open|closed|new`. `view=paper` (the shell's old view) redirects to `open`.
A plan ticket opens with `&tp=<plan_id>` (optionally `src_kind`, `src_bucket`, `src_date`, the params the desk already uses
for a source signal).

| Part | Route(s) | Notes |
|---|---|---|
| Header strip, every view | `GET /api/desk/paper-account` (cash, capital at risk = `blocked_rs`, starting capital); `GET /api/risk/profile` (`live.equity.equity_rs`, `live.open.risk_rs`, `profile.limits.max_open_risk_pct`); `GET /api/desk/exit-job-status` | Equity is not in `/paper-account`; it is the risk profile's paper equity. Unknown is "unknown" with the reason, never 0. The shell's "These are paper trades… My portfolio" line stays. |
| Open & pending | `GET /api/desk/paper-trades?status=all` (once per load; it applies exits) | pending = open trades whose entry is `waiting`; open positions; F&O structures with every leg. |
| F&O structure figures | `POST /api/desk/strategy/payoff` with the trade's stored legs and entry premiums (payoff-v2, a pure calculation) | max profit and max loss at expiry, worst loss after costs, breakevens. Greeks: the paper-trade record has none, shown as unavailable. Days to expiry: calendar days to the leg's stored expiry. |
| Roll | `GET`/`POST /api/desk/paper-trades/{id}/roll` (RollAction) | |
| Journal drawer | the same list (transitions, fills, `costs_breakdown`, `stop_history`, `flags`, strategy `events`) | No extra call. Chart: `tab=market&view=research&sym=`. Plan: `GET /api/desk/trade-plans/{id}` (DecisionCardById). |
| Closed & journal | the same list | net P/L before income tax. |
| New trade · ticket | `GET /api/desk/trade-plans/{id}` (`account_size`), `POST /api/desk/paper-trades` with `Idempotency-Key` | size = `account_size.quantity`, no slider and no size input; allow / reduce ("Accept N?") / block; 409 duplicate and 422 `entry_not_tradable` in plain words. |
| New trade · F&O builder | the F&O lab's builder (FnoTab `strategies`), `GET /api/desk/strategy/templates` | tiles limited to the backend catalog; the owner's first wave marked available / not in the catalog yet. |
| New trade · Strategy Builder | unchanged (StrategyBuilder) | |
| New trade · Backtest | `GET /api/strategy-builder/strategies`, `POST /api/strategy-builder/strategies/{id}/backtest` | provenance: universe basis and rule (liquid-eq-v1, point-in-time), code version, data to, cost model, slippage sweep; survivorship warning for an index universe. |

## Test cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TD-1 | header | account strip on Open, Closed and New | e2e | cash, capital at risk (blocked), equity from the routes; starting capital "simulation default" |
| TD-2 | header | open-risk chip | e2e | "Open risk 1.2% of 3%" = `risk_rs / equity_rs` against `max_open_risk_pct` |
| TD-3 | header | exit job ok | e2e | "Exits checked after the 26 Oct close" |
| TD-4 | header | exit job missed / late / route down | e2e+failure | "Exit check missed" with the route's message; late says so; a failed read says the status is unavailable |
| TD-5 | header | paper vs real line | e2e | the shell's line and its My portfolio link are on every Trade Desk view |
| TD-6 | header | equity unknown | edge | "Equity unknown" with the route's reason; the chip says open risk is unknown; never ₹0 |
| TD-7 | nav | views and redirect | e2e | three views Open & pending (default), Closed & journal, New trade; `view=paper` lands on `open` |
| TD-8 | open | pending entries | e2e | "Break above ₹1,655.00 · valid 3 sessions", state "Waiting for entry", plan id |
| TD-9 | open | open positions | e2e | lifecycle state "Position open", qty, entry, stop in force, target, last close, net P/L after costs, plan id |
| TD-10 | open | F&O structure | e2e | every leg (side, contract, expiry, lots, entry, mark, P/L); net P/L; payoff-v2 max profit / max loss / worst loss after costs / breakevens from the payoff route with the stored legs; Greeks "unavailable"; days to expiry |
| TD-11 | open | roll | e2e | Roll on the F&O row shows the preview; a refused roll shows the route's reason |
| TD-12 | open | marks missing | edge | a trade without a mark shows "—" and "no mark"; the list says prices could not be read; nothing is 0 |
| TD-13 | open | no trades | edge | empty state with links to Market Overview and New trade |
| TD-14 | drawer | open / close | e2e | a row click opens a dialog; Escape and Close shut it |
| TD-15 | drawer | lifecycle timeline | e2e | each transition: from → to, time, session, source, rule version |
| TD-16 | drawer | fills | e2e | entry fill (requested vs simulated) and exit fill with the session |
| TD-17 | drawer | P/L bridge, desk-cost-v2 | e2e | gross, brokerage, STT, exchange, SEBI, stamp, GST, slippage, total, net; "net, before income tax" |
| TD-18 | drawer | stop history | e2e | each stop version with its session and reason |
| TD-19 | drawer | exit flags | e2e | `both_in_range` → "Stop and target both touched on 24 Oct: stop assumed"; `gap_through_stop` → "Gapped through the stop: filled at the open"; no "AMBIGUOUS" |
| TD-20 | drawer | links | e2e | Chart → `tab=market&view=research&sym=`; plan → the decision card |
| TD-21 | drawer | F&O drawer | e2e | legs, payoff figures, lifecycle events, roll |
| TD-22 | closed | closed list | e2e | exit reason, net P/L before income tax; a row opens the same drawer |
| TD-23 | closed | summary | e2e | net realised before tax from the route's summary |
| TD-24 | new | no plan | edge | the ticket says to open an idea from Market Overview › Top AI ideas, with the link |
| TD-25 | new | ticket size | e2e | quantity = `account_size.quantity` (666, the risk service's), with its basis; no slider, no range input, no size field |
| TD-26 | new | allowed | e2e+contract | the POST body equals `contract-decision-card.json` `cash.allowed.sent`, with an Idempotency-Key; "Allowed" with the decision |
| TD-27 | new | reduced | e2e+contract | 409 `risk_reduce` → "Reduced 113 → 83" with the reasons and "Accept 83?"; accepting sends the same body with 83 |
| TD-28 | new | blocked | e2e | 409 `risk_blocked` → "Blocked" with the reason; no accept button |
| TD-29 | new | duplicate | e2e | 409 `duplicate_open_trade` → the route's sentence, "not added twice" |
| TD-30 | new | impossible fill | e2e | 422 `entry_not_tradable` → the route's sentence, "not recorded" |
| TD-31 | new | F&O builder | e2e | the F&O builder is mounted; its tiles are only the backend catalog's structures |
| TD-32 | new | templates | e2e | the catalog list from `GET /api/desk/strategy/templates`; first wave: iron condor available; covered call, bull put, bear call, protective put / collar "not in the backend catalog yet" |
| TD-33 | new | backtest provenance | e2e | universe liquid-eq-v1 point-in-time, code version, data to, cost model, slippage sweep; an index universe shows the survivorship warning |
| TD-34 | data | one paper-trades call | e2e | one `GET /api/desk/paper-trades` per Trade Desk load across view switches and drawer opens |
| TD-35 | layout | 390 px | e2e | no horizontal page scroll on Open, Closed, New and in the drawer; the leg table scrolls inside its own box |
| TD-36 | wording | ideas, paper | e2e | no "pick", "recommend", "suggest" in the Trade Desk panel; "nothing is sent to a broker" |
| REG-1 | regression | existing desk, portfolio, decision-card, strategy-builder, lab and shell specs | e2e | same result as the base branch (feat/desk-redesign-shell) |
| STG-1 | staging | after merge and deploy | data | the routes answer for a real user; one paper-trades call per load in the browser log |
