# Screen designs → backend coverage

Source: `PROTOTYPE_DESCRIPTION.md` (owner, 5 Nov 2026). This maps each of the 12 screens to the `/api/v1` backend of
the separate app (`backend/autodesk`). It is the plan for the UI build, not a status claim.

Legend: **P1** = served by the Phase 1 backend; **P1+** = small addition made in Phase 1 because the design needs it;
**P2–P4** = needs a later backend phase (DESIGN.md §7). Live broker execution is not in any phase yet (see "Conflicts").

## Contract changes made in Phase 1 because of the designs

| Design element | Change |
|---|---|
| "Stop new entries" kill switch on every screen (§3, §12 emergency controls) | P1+: desk control per tenant. While active, no new SESSION_CYCLE proposal phase or TRADE_PROPOSAL starts and no approval is granted; read-only screens and simulations of past sessions keep working. Activate/lift are audited events. |
| Approval binding shows "trade and plan hash" (§05, PRD §10.3) | P1+: `ApprovalScope.plan_hash` = sha256 of the canonical plan version body; a decision is refused if the hash no longer matches. |

## Screen by screen

| # | Screen | Served by Phase 1 | Needs a later phase |
|---|---|---|---|
| 01 | Desk overview | operating mode, agents (status counts), pending approvals, recent agent activity (events with policy id/version), signals, plans, desk status, kill switch | paper/live trades, open orders, capital deployed, open risk and margin, P&L card (P2 paper engine); broker/feed tiles (P3 Tech Support health); live accounts (not planned) |
| 02 | Agent command centre | 5 agents + 7-status legend, current task, recent decisions, errors/retries, decision trace (task rows: requester, receiver, inputs, structured output, evidence refs, tool calls, validation, timing, retries, handoffs), permissions/tools, versions, workflows in flight | heartbeat/queue depth from a running worker pool (P3); "Step n of 13" needs a step index on TRADE_PROPOSAL workflows — computed from task states in the UI build |
| 03 | Opportunity scanner | signals with score bar, separate calibrated probability ("Not calibrated" in P1), 8-dimension breakdown, evidence, entry zone → invalidation, levels, provenance, status, filters; scan statistics from the SCAN report | OI/volume confirmation as its own column (in evidence today), LTP (live quotes), signal history hit rate / average R (needs P2 outcomes) |
| 04 | Strategy workbench | template plans with legs, Greeks, max loss/profit, breakevens, sizing to a budget, version history, submit for risk validation (`/trade-plans/{id}/validate`) | interactive builder API (pick template, change strikes/lots, recompute) — add with the UI build; plain-English prompt needs an LLM (DESIGN §10 Q4); scenario grid, chance-of-profit model, backtest (P2) |
| 05 | Approval queue | pending + decided approvals, why a human is needed, countdown to `expires_at`, binding (§10.3 incl. plan hash), approve / reject / request revision with reason, risk report checks, portfolio impact (book before/after), audit history | capital reservation ledger (P2), stress rows (P2) |
| 06 | Active trade management | — | all of it: orders, fills, lifecycle states, trailing, partial exits (P2 paper execution + lifecycle manager) |
| 07 | Real-time P&L | — | all of it (P2 paper engine; the repo's paper P&L v2 screen is the visual model) |
| 08 | Capital & risk | policy limits, commitments of approved plans, sector exposure of commitments, effective policy | the nine capital measures, reservations, Greeks exposure, stress, strategy budgets (P2) |
| 09 | Middle office | accounts table (mode, pending approvals, breaches = FAIL assessments), workflow replay (tasks + handoffs of one workflow), audit search over events | reconciliation (P3, needs fills), broker links (not planned) |
| 10 | Simulator | create / start / step / run / pause / resume / stop, clock and phase, timeline, workflows, agents in the run, counters (signals, proposals, risk checks, approvals), results with limitations, export JSON | orders/fills/positions/P&L curve in a run (P2), scenario injection and policy A/B (P4), live-shadow (P4), certification gate (P4) |
| 11 | Agent fleet & reliability | agent registry with versions and status; quarantine/release can set `agent_registry.status` | instances, uptime, p95, services list, incidents (P3 Tech Support + monitoring) |
| 12 | Policies & permissions | operating mode by account (audited), effective policy (most restrictive wins), autonomy rules, version history, "Stop new entries" | roles matrix (needs app roles beyond admin/user), other 7 emergency controls (P2/P3 — they act on orders and positions) |

## Conflicts and questions for the owner

1. **Live trading.** The design has a Zerodha account in "assisted live", an "Autonomous live" mode with an activation
   gate, and Live P&L. This app has no LIVE account kind and no order path: brokers are read-only. Owner decision of
   24 Oct allows live F&O execution through Kite Connect in the user's own session, but not for this desk yet. Phase 1
   keeps live out; the UI will show live parts as "not connected" until the owner decides.
2. **Wording.** The design uses standard words on screen (stop, target, T1/T2, SL) as on the paper P&L screens; this
   answers DESIGN §10 Q5 for labels. Text written by the agents (thesis, rationale) stays neutral unless the owner
   says otherwise.
3. **Prototype file.** Only the description is in the repo. `Trading Desk.dc.html` is needed for exact layouts.
