# Nivesh Autonomous Trading Desk: prototype description

> Owner-supplied, 5 Nov 2026 ("Please find it here. the designs with description"). Copied verbatim from
> "Trading Desk - App Description.html". The clickable prototype it describes (`Trading Desk.dc.html`) is not in
> the repo yet. Every number in it is sample data for 5 Nov 2026, not live data.

A clickable prototype of the Autonomous Trading Desk module described in PRD v2.0 (§15 screens, §32 simulator). It is
built in the Nivesh V5 design system and grounded in the existing V5 Copilot and Paper Trading designs from
`amitporwal107/nivesh.ai@dev`.

Entry file: `Trading Desk.dc.html`. Every number, name and time is sample data for the NSE session of Thursday
5 Nov 2026. It is not live data.

---

## 1. What the app is

A trader sets objectives, capital and risk appetite. Five AI agents then find opportunities, build plans, check risk
and route approvals. Deterministic services reserve capital, execute and manage positions.

The prototype shows one trader's desk at 11:42 IST. It covers:
- **Paper · Desk A:** autonomous paper trading, ₹1.00 Cr starting capital.
- **Zerodha · ZX4821:** assisted live trading, ₹25.0 L. Every live entry needs the account owner.
- **ICICI Direct · IX2207:** research only; its session has expired.

Core rule, visible on every screen: **AI recommends, deterministic services validate and control, and a human approves
anything outside delegated authority.**

## 2. Design system and visual language

- **Theme:** Nivesh V5, dark-first with a matched warm-cream light theme. Mint means good or primary, amber caution,
  indigo informational or simulated, danger risk.
- **Typography:** Instrument Serif for headlines and big numbers, Inter Tight for body text, JetBrains Mono for
  uppercase labels, pills and figures.
- **Headlines:** every screen opens with a one-sentence serif synthesis with one accent word, then two lines of prose,
  then structured data.
- **Formatting:** Indian money formatting (₹1.02 Cr, ₹4.96 L, ₹10,927) and tabular numerals.
- **Iconography:** the न mark plus Unicode glyphs; no emoji.

## 3. Shell and navigation

**Desktop**
- **Sidebar (236 px):**
  - The न mark and wordmark.
  - Account cards with mode pills.
  - 12 screens in three groups: Desk, Positions and Control.
  - Live badges: signals, pending approvals, open trades, SIM, and an incident count.
- **Glass status bar:**
  - NSE OPEN, a ticking IST clock, and NIFTY 24,012.35, BANKNIFTY 55,742.60 and VIX 12.84.
  - Agent health ("4/5 agents healthy", which links to Reliability) and the Kite feed status.
  - **Stop new entries**, the global kill switch.

**Mobile (390 × 844 phone frame)**
- Status bar and an app header with the screen title, the clock and a STOP NEW button.
- Every screen in a single column, with tables turned into cards.
- A glass bottom tab bar: Desk, Trades, Approve (with a badge), P&L and More. More opens a sheet listing all 12 screens.

**Prototype controls (bottom right):** ▶ Walkthrough, Dark/Light and Desktop/Mobile.

**State shared across screens**
- **Approval decisions:** approve, reject or request revision on the Approval queue. The decision updates the overview
  headline and actions, the sidebar badge, the reservations on Capital & risk, the middle office audit search and the
  trade list. Approving APR-3107 adds TRD-1195 to Active trades as ORDER_SUBMITTED.
- **Stop new entries:**
  - Adds a red banner on every screen and blocks "Generate strategy" in the scanner.
  - Warns in the workbench.
  - Mirrors as the first emergency control on Policies.
  - Protective stops and exits keep running.

**Tweaks:** theme, device, start screen, and `autoTour`, which starts the walkthrough on load.

## 4. The 12 screens

### 01 · Desk overview
**Headline:** "Every position is inside its limits. Three approvals are waiting on you; the first expires at 12:10."
- **Needs you, ranked by ₹ at risk:** the top three action rows. They are RELIANCE (₹13,860 risk to stop), the Bank
  Nifty roll (₹11,799) and the Nifty spread (₹10,927 max loss), with the ICICIBANK near-stop item next. Each row opens
  the relevant approval or trade.
- **Ten status tiles from PRD §15.2:** operating mode, market session, agents (4 · 1 · 0), paper and live trades,
  pending approvals, open orders, capital deployed and available, open risk and margin, realized and unrealized P&L,
  and critical exceptions.
- **Net P&L card:** +₹9,888 with a sparkline and the paper/live split. It links to Real-time P&L.
- **Broker and data feeds:** Kite live, Zerodha OK, paper engine, option chain, the BSE feed lag and ICICI sign-in.
- **Five agent cards** with their current task.
- **Recent agent activity:** each row gives what happened, why, which policy authorized it and the quantity affected
  (PRD §15.11). Rows show as a table on desktop and cards on mobile.

### 02 · Agent command centre
- **Status legend** with counts for all seven agent statuses (IDLE, BUSY, SCALING, DEGRADED, MAINTENANCE, QUARANTINED,
  OFFLINE).
- **Five agent cards:**
  - Status, heartbeat, current task, queue depth and last success.
  - Three recent decisions, and errors and retries.
  - The five agents are AI Trader, Trading Assistant, Risk Guardian, Middle Office and Tech Support (degraded).
- **Selected agent detail:**
  - Decision trace in the PRD §32.4 fields: requester, receiver, inputs, structured output, evidence, tool calls,
    validation, time and retries, handoff, and decision. It states that hidden model reasoning is neither stored nor
    shown.
  - Permissions and tool access (allowed and denied).
  - Model and config version, and the human escalation rule.
- **Workflows in flight:** each against the 13-step proposal workflow (PRD §7.1), showing where it stands. Examples:
  "Step 5 · waiting on you" and "Step 8 · 200 of 600 still working".

### 03 · Opportunity scanner
- **Scanner statistics:** universe 712, coverage 99.1%, 46 published, 8 above 55, 4 duplicates suppressed, 9 expired.
- **Filters:** direction, segment and minimum score.
- **Eight ranked signals:** RELIANCE, NIFTY, HDFCBANK, BEL, TATASTEEL, INFY, ICICIBANK and SBIN.
  - Columns: score bar, calibrated probability shown separately ("Not calibrated" or "0.57 · n = 412"), entry →
    invalidation, targets, OI and volume confirmation, age and expiry, and status (In approval, Traded, Revision,
    Rejected, Strategist building, Watch only).
- **Expanded row:**
  - Score breakdown across the eight weighted dimensions.
  - Evidence chips, LTP, liquidity and similar-setup history.
  - Provenance: signal ID, data timestamp, model and rule version, expiry.
  - An action button such as "Open approval", "Open in workbench" or "Open trade".
- **Signal history cards:** 30-session hit rate and average R after costs.

### 04 · Strategy workbench
- **Plain-English builder** (glass composer) with three example prompts. "Build plan" picks a template and sizes the
  lots to the stated maximum loss; for example, "risk at most ₹12,000" gives 2 lots. It then shows the parsed view,
  underlying, horizon and budget.
- **Templates:** bull call spread, long call, bull put spread and iron condor.
- **Leg builder:**
  - Side, quantity, contract, mid price, IV and delta.
  - Lots stepper; for the call spread, short-strike chips (24100, 24200, 24300).
- **Payoff chart:** expiry payoff with profit and loss areas, today's curve (dashed), the ±343 expected-move band, the
  spot line and breakeven markers.
- **Six metrics:** max profit, max loss, breakeven, reward to risk, margin estimate, and chance of profit (lognormal
  model, labelled as a model).
- **Greeks for the whole position:** delta, gamma, theta per day, vega per vol point.
- **Scenario grid:** Nifty −2% to +2% against now, tomorrow, IV −2, IV +2 and expiry.
- **Backtest and assumptions:** n 186, 52% win rate, +0.21R after costs, with the cost and fill model and a
  no-guarantee note.
- **Plan version comparison:** v1, v2 and a live v3 draft.
- **Submit panel:**
  - "In approval · APR-3107" when the plan matches v2.
  - Otherwise "Draft v3", with **Submit for risk validation**, which queues RSK-5534.
- Everything recalculates live with Black–Scholes pricing on the 11:42 chain.

### 05 · Approval queue
- **Pending list:**
  - APR-3107: Nifty spread, live, expires 12:10.
  - APR-3106: RELIANCE 330 shares, paper, above the ₹4.00 L autonomous limit, expires 12:30.
  - APR-3104: Bank Nifty roll to 29 Dec, extends the holding, expires 14:00.
  - Each item shows a live mm:ss countdown.
- **Decided earlier:** APR-3101 approved automatically, APR-3100 needs revision, APR-3099 rejected.
- **Detail header:** ID, plan, mode, account, why a human is needed, a large countdown and the thesis.
- **Approve…** reveals the approval binding from PRD §10.3: tenant and account, trade and plan hash, instrument and
  strategy, maximum quantity, notional and risk, mode and allowed actions, and expiry. **Confirm approval** then
  records the decision.
- **Reject and Request revision** ask for a reason chip, then record the decision.
- **Sections below:**
  - Proposed trade and capital allocation (reservation).
  - Risk report: four tiles plus stress rows.
  - Portfolio impact: before, after and limit.
  - Required approvals chain, which updates with your decision.
  - 12 policy checks (pass, warning, fail).
  - Audit history, which appends your decision.

### 06 · Active trade management
- **Stop-to-target ladder** for all positions: stop, average fill, T1, T2 and an LTP dot, with P&L and R multiple.
  Filter by All, Paper or Live; selecting a row opens it below.
- **Seven positions, plus TRD-1195 once APR-3107 is approved:**
  - BEL, ACTIVE_POSITION.
  - HDFCBANK Nov future, RISK_MANAGEMENT, stop trailed 984 → 991.
  - Bank Nifty 55000/54500 put spread, with leg table and Greeks.
  - LT, PARTIAL_EXIT: T1 triggered at 3,970, filled at 3,968.50, stop moved to breakeven.
  - DLF, PARTIALLY_FILLED 400 of 600, with the working limit order shown.
  - ICICIBANK (live), near its stop.
  - SUNPHARMA (live).
- **Trade detail:**
  - Lifecycle stepper (approved → submitted → filled → active → risk management → partial exit → exit pending →
    closed).
  - Price chart with the stepped stop line, target lines and labels. Actual fills are solid dots; trigger prices are
    hollow diamonds.
  - **Next action** box, with links to the related approval where relevant.
  - Twelve fields from PRD §15.8: entry and fills, current price, filled and remaining, open orders, stop and targets,
    trailing state, realized and unrealized, remaining risk, capital and margin, Greeks or OI, last risk evaluation,
    and approval.
  - Event timeline.

### 07 · Real-time P&L (follows the repo's paper P&L v2 design)
- **Header:** title, Live feed pill, account pills (Paper OK, Zerodha OK, ICICI Direct SIGN IN), IST clock,
  **Pause/Resume** (freezes the figures), and a "display only" note.
- **Glass filter bar:** All, Paper or Live; account; segment; search (filters the table only).
- **Headline figure:** consolidated net P&L after estimated charges (+₹9,888.00), return on capital, and "Gross −
  charges (est. · booked)". An amber note explains that ICICI Direct is not in the total.
- **2 × 2 KPIs:** realized, unrealized, estimated charges, open positions (winning and losing).
- **Paper (indigo) and Live (mint) cards.** Clicking one switches the mode filter.
- **Intraday net P&L curve** from 09:15, with HIGH and LOW, a dashed zero line and an end dot.
- **Open positions table:** one row per share position and per option leg.
  - Columns: mode and account, instrument, side and quantity, average, LTP, unrealized, realized, net, SL/target, risk
    used, status.
  - Sort chips (Net P&L, Return %, Exposure) and **Export CSV**, which downloads a file.
  - Rows expand to P&L breakdown, fills and actions.
- **Risk monitor:** meters and alerts.
- **"Points to review":** a rule-based reading of the figures, never phrased as advice.
- **Folded section:** P&L by segment, closed trades (COFORGE stop, LT partial) and waiting entries.

### 08 · Capital & risk
- **Account switch:** Desk A or ZX4821.
- **Nine separate capital measures from PRD §9.2:** net liquidation, available cash, used margin, reserved, deployed
  notional, buying power, open risk, realized/unrealized, pending commitments.
- **Allocation limits** with meters, including HDFCBANK at 91% of its 6% instrument cap.
- **Seven-level guardrail hierarchy.**
- **Sector concentration** against the 25% limit line.
- **Portfolio exposure and Greeks.**
- **Stress scenarios.**
- **Reservations ledger:** status changes with approval decisions (HELD, CONVERTING ON FILL or RELEASED).
- **Strategy budgets:** mean reversion shown as suspended.

### 09 · Middle office
- **Eight tiles:** accounts, agent health, trades, pending approvals, breaches, capital used, broker links and
  reconciliation.
- **Accounts table:** mode, equity, open trades, pending approvals, breaches, reconciliation and broker status.
- **Reconciliation item REC-0418:** ICICIBANK average price differs from the broker by ₹0.05. Use **Accept broker
  figure** or **Wait for contract note**.
- **Risk breaches:** 0 hard, 2 soft. Agent health list.
- **Workflow replay of WF-88412** (the BEL trade) through all 13 steps, each with actor, input and output, and timing.
  Replay animates it; ‹ › steps through.
- **Audit search:** live filtering of audit records, including your own decisions.

### 10 · Simulator (PRD §32)
- **Banner:** "Simulated · isolated · no broker route". Mode chips: historical replay, accelerated replay, scenario
  simulation, live shadow.
- **Controls:**
  - Start, Pause, Resume and Stop. Stopping saves a consistent checkpoint.
  - Restart from 12:00, Step event and Step workflow.
  - Speed 1×, 10×, 30× or 60×.
  - **Inject scenario:** gap down, broker WebSocket drop, reject storm, stale option chain or LLM outage. Each adds a
    recovered exception.
  - **Export** downloads the results as JSON.
- **Simulation clock and session progress** with checkpoints, and a replayed market snapshot.
- **Live counters:** signals, proposals, risk checks, approvals, orders and fills, positions, lifecycle updates,
  capital, exceptions, policy violations.
- **Agents in this run.**
- **Agent communication timeline:** structured messages that advance with the clock.
- **Simulated P&L curve.**
- **Exceptions and recovery,** and final reconciliation status.
- **Workflow dependency graph:** 13 nodes.
- **Policy v7 against v8:** same inputs, same seed.
- **Live activation gate:** 18 of 20 scenario certifications.

### 11 · Agent fleet & reliability
- **Fleet tab:** nine agent instances with status, version, uptime, tasks per hour, 7-day success, p95 and queue.
  **Quarantine** and **Release** work; maintenance instances are locked.
- **Services tab:** 17 services and feeds, among them the orchestrator, policy service, capital engine, lifecycle
  manager, execution gateway, paper engine, broker adapters, market data, BSE feed (degraded), Postgres, Redis, event
  bus, dead-letter queue, scheduled jobs and LLM gateway (with its fallback behaviour).
- **Incidents tab:** INC-0311 (BSE feed lag) with impact, timeline and recovery evidence, and **Acknowledge** and
  **Escalate**. Two resolved incidents.

### 12 · Policies & permissions
- **Operating mode by account:** Research, Assisted, Autonomous paper, Autonomous live.
  - Changes are audited, with a note that open positions keep their original authority.
  - Disallowed modes are locked.
  - Autonomous live gate checklist: broker permission, 18 of 20 certifications, compliance approval, kill-switch drill.
- **Effective policy table:** tenant, account, strategy and instrument levels, with the binding level highlighted. The
  most restrictive value wins.
- **Autonomous action matrix:** auto, approval or never, by mode. Widening a stop and averaging down are never allowed.
- **Who must approve:** approval thresholds.
- **Roles and permissions matrix:** eight roles, with your role highlighted.
- **Eight emergency controls (PRD §10.4)** with activate, confirm and lift steps. "Stop new entries" is wired to the
  app-wide stop. None of them cancels protective stops.
- **Policy version history:** v8 in simulation, v7 active, P-LIVE-v3, and v6 retired.

## 5. Guided walkthrough (16 steps)

Press **▶ Walkthrough**. Each step lasts about 9 seconds, with Prev, Play/Pause, Next and End controls and a countdown.

1. The overview.
2. Agents.
3. Scanner.
4. Workbench.
5. APR-3107.
6. Approve it (scripted).
7. TRD-1195, ORDER_SUBMITTED.
8. HDFCBANK trailing stop.
9. Real-time P&L.
10. Capital & risk.
11. Middle office.
12. Simulator.
13. Late-feed incident.
14. Policies.
15. Stop new entries (scripted).
16. Entries resume.

The walkthrough resets decisions and the kill switch at the start, so it plays the same way every time.

## 6. Sample world

| Item | Value |
|---|---|
| Session | Thu 5 Nov 2026, 09:15–15:30 IST; desk clock starts at 11:42:18 |
| Market | NIFTY 24,012.35 · BANKNIFTY 55,742.60 · VIX 12.84 |
| Contract specs | Lot sizes NIFTY 65, BANKNIFTY 30, HDFCBANK 550 |
| Expiries | Nifty weekly Mon 9 Nov (10 Nov holiday); monthly Mon 23 Nov |
| Key plan | PLN-2041 v2, NIFTY 24000/24200 CE, 2 lots: debit 84.05, max loss ₹10,927, max profit ₹15,074, breakeven 24,084.05 |
| P&L today | Paper +₹9,376 · Live +₹512 · Combined +₹9,888 after ₹1,380 charges |

## 7. Coverage of the PRD and limits of the prototype

**Covered**
- PRD §15.2–§15.11 and the §32 simulator dashboard and controls.
- Approval binding (§10.3), lifecycle states (§8.2), capital measures (§9.2), the guardrail hierarchy and emergency
  controls (§10.4).

**Not designed in this round:** the Market Intelligence and Trade Journal navigation items.

**Limits**
- The prototype has no backend.
- Agent behaviour, prices and the simulator timeline are scripted.
- Option prices and Greeks are model calculations on fixed inputs.
- Clicking does not place or cancel any order.
