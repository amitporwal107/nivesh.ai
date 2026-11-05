# Desk overview (screen 01) — UI test cases AD-UI-20..29

Design: `docs/autodesk/design/prototype/TDOverview.dc.html`. Screen: `frontend-v5/src/autodesk/screens/Overview.tsx`.
Spec: `frontend-v5/e2e/tests/autodesk-overview.spec.ts` (route mocks shaped like the real API; fixtures in
`autodesk-fixtures-overview.ts`, marked MOCK). Written before the screen code.

Layers: **E** = Playwright against the production build with route mocks · **C** = request contract (the overview
sends no POST of its own; the shell's Stop new entries is covered by AD-UI-08/09).

Data sources (Phase 1): `GET /desk/status`, `GET /approvals?pending=true` (desk only), `GET /approvals?limit=100`,
`GET /trade-plans/{trade_id}?version={n}` per pending approval, `GET /agents/{agent_key}/activity?limit=50` per agent
(desk tasks only: `simulation_id == null`), `GET /risk/assessments/{id}` for risk rows shown in the activity table,
`GET /api/live/quotes` (Kite feed, read-only). Nothing on this screen is sample data.

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-UI-20 | E | Header from real data: desk status `as_of` 5 Nov, one AUTONOMOUS_PAPER account "Desk A", 5 healthy agents, two desk approvals pending (first expires 12:10 IST) | eyebrow "01 · Desk overview · Thu 5 Nov 2026"; mint pill "Auto paper · Desk A"; headline "All 5 agents are healthy. *Two approvals* are waiting on you; the first expires at 12:10."; the sub-line says there is no P&L until paper execution (Phase 2) and gives the last pre-market status; the design's "Every position is inside its limits" never appears |
| AD-UI-21 | E | "Needs you · ranked by ₹ at risk" with three desk approvals + one simulation approval | simulation approval left out; each desk approval's plan version fetched (`GET /trade-plans/{id}?version=n`); rows ordered by the plan's `max_loss_rs` (highest first), at most 3, numbered 01..03; value = ₹ max loss with "Max loss"; sub-line = approval id · the Middle Office reasons as written · expiry; clicking a row opens `/approvals/{approval_id}` |
| AD-UI-22 | E | No approval pending | Needs-you box says "Nothing is waiting on you."; headline accent "No approvals" + "are waiting on you."; pending tile "0" with "Queue is clear" |
| AD-UI-23 | E | Ten design tiles plus "Last pre-market check" and "Open workflows" | operating mode (first account's mode, others listed), market session from the Kite feed ("Open", 09:15–15:30 IST, closes in …), agents "healthy · degraded · offline" counts from the registry, pending approvals + first expiry, last pre-market status + session, open workflows count — all from the API; Active trades / Open orders / Capital deployed / Open risk · margin / Realized · unrealized / Critical exceptions show "—" and "Phase 2" (capital tile names the real starting capital); no ₹ figure from the prototype; tiles with a target screen navigate there |
| AD-UI-24 | E | P&L card and "Broker & data feeds" card | P&L card keeps its eyebrow and "Real-time P&L ›" link but shows only a Phase 2 note (no figure, no sparkline); feeds rows: Kite feed (mode from `/api/live/quotes`), desk EOD cash and F&O sessions from desk status (or the API's `market_data.error` text, in red), pre-market check status, paper engine "Phase 2"; one line saying broker connections are not part of Phase 1; no Zerodha / ICICI rows |
| AD-UI-25 | E | "Agents · current task" | five cards in the design's order (AI Trader, Trading Assistant, Risk & Operations, Middle Office, Tech Support) with the registry status (BUSY mint, DEGRADED amber …) and the latest desk task from its activity (simulation tasks skipped): a non-terminal task reads "Working on …", a finished one "Last: …" with the agent's own summary; an agent without desk tasks says so; a failed activity call shows its message |
| AD-UI-26 | E | "Recent agent activity" (desktop table) | desk tasks of all five agents merged newest first, at most 8 rows; columns Time (IST) · Agent · What happened (task, entity, state) · Why (the agent's summary or error, verbatim) · Policy (policy id + version of the approval or risk assessment the task produced) · Quantity (approval scope max lots / risk sizing allowed of proposed); "—" where the task has no such field; no row is invented |
| AD-UI-27 | E | API errors | `/desk/status` 500 → ErrorBox with the API's message, other sections still render; pending approvals 500 → ErrorBox inside "Needs you"; a pending approval whose plan answers 404 → row shows "—" and the API message; agent activity 500 → each card shows the message |
| AD-UI-28 | E | Stop new entries active (desk status control row active) | headline starts "New plans are on hold." (computed from the control row) |
| AD-UI-29 | E | Phone 390×844 | headline 30 px; tiles two per row; activity rendered as cards (no table header row); no horizontal overflow (`scrollWidth ≤ innerWidth`); no console errors |
