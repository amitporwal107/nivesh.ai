# Autonomous Trading Desk — Phase 1 test cases (written before implementation)

Layer: U = unit, I = integration (throwaway Postgres), A = API (FastAPI app; real staging data run marked S),
E = edge, F = failure. Owner of the code under test in brackets. PRD/ARCH references in the last column.

## Store, schema, contracts [core]

| ID | Layer | Case | Expected | Ref |
|---|---|---|---|---|
| AD-01 | I | Apply migrations to an empty DB, then again; then change a migration file's content | 1st run applies 001; 2nd applies nothing; changed file → MigrationDrift | ARCH §13 |
| AD-02 | I | UPDATE / DELETE on events, trade_plan_versions, risk_assessments, approvals, policy_versions | refused by trigger | PRD §16.7 |
| AD-03 | I | Task path CREATED→ASSIGNED→ACCEPTED→RUNNING→RESULT_READY→VALIDATED→COMPLETED; then CREATED→COMPLETED | legal path ok, each step an event; illegal move → IllegalTransition | PRD §29.2 |
| AD-04 | U | TaskSpec GENERATE_STRATEGY addressed to RISK_OPS | ValidationError | PRD §29.5 |
| AD-05 | I | Tenant B reads tenant A's account / workflow / signal / plan / approval / simulation | NotFound for each | PRD §18.1 |
| AD-06 | I | Insert the same signal twice (same session/instrument/segment/direction/category) | second returns the first row, created=False | AT-013 |
| AD-07 | U+I | APPROVED decision without scope, or scope bound to another version; second answer to one pending request | ValidationError; Conflict | PRD §10.3 |
| AD-08 | I | SIMULATION account without simulation_id; account kind LIVE | CHECK violation both | PRD §5.2 |

## Market view [market]

| ID | Layer | Case | Expected | Ref |
|---|---|---|---|---|
| AD-10 | U | View at D 08:45 IST asks for D's cash bars; at D 18:29 / 18:31 IST; F&O at D 19:29 / 19:31 IST | LookAheadError before publication, visible after | PRD §28.4 |
| AD-11 | U | A 1:2 split dated after D: view at D sees unadjusted bars; view after the split sees bars before the split halved | as-of adjustment never uses later events | ARCH §10.5 |
| AD-12 | U | chain_snapshot with an untraded strike side | that side's close is None | data fact §5 |
| AD-13 | U | Agent calls a market method outside its allowlist | ToolNotAllowed | PRD §29.5 |
| AD-14 | S | PitMarketView at a past session on staging: daily bars end at D-1, F&O universe non-empty, buildup rows, lot sizes, expiries | real rows; every tool call recorded with as_of | PRD §14 |
| AD-15 | F | Data API down / 5xx | DataUnavailable (no empty-list-as-success) | PRD §20 |

## AI Trader [market]

| ID | Layer | Case | Expected | Ref |
|---|---|---|---|---|
| AD-20 | U | Crafted bars with a 20-session breakout on 2× volume | BREAKOUT, BULLISH; score_breakdown sums to signal_score; weights from the versioned rule | AT-004, AT-011 |
| AD-21 | U | Build-up rows long_buildup / short_buildup / short_covering / long_unwinding | categories + directions BULLISH / BEARISH / BULLISH / BEARISH | AT-005/006 |
| AD-22 | U | Missing index / VIX / delivery data | those dimensions available=False, 0 points, listed in missing_inputs | PRD §6.1 scoring |
| AD-23 | U | Signals' data_as_of ≤ as_of; session_date = the session being prepared; expires_at = that session's close | holds for all | PRD §28.3A |
| AD-24 | U | Same view twice | identical signals (ids excluded) | PRD §29.7 |

## Tech Support [market]

| ID | Layer | Case | Expected | Ref |
|---|---|---|---|---|
| AD-25 | U | D-1 cash + F&O present / F&O missing / cash missing | READY [CASH,FUTURES,OPTIONS] / DEGRADED [CASH] / BLOCKED [] | PRD §30.1 |

## Trading Assistant [control]

| ID | Layer | Case | Expected | Ref |
|---|---|---|---|---|
| AD-30 | U | Bullish cash-only signal | LONG_EQUITY plan; all 19 mandatory fields; max_loss = loss at invalidation + costs (not price to zero) | PRD §6.2 |
| AD-31 | U | Bullish F&O signal | alternatives include LONG_FUTURES, BULL_CALL_SPREAD, BULL_PUT_SPREAD; legs priced from the chain; lot size from the bhavcopy; expiry ≥ min_days_to_expiry | PRD §6.2 |
| AD-32 | U | Chain where a strike did not trade | that strike is never used at a carried-forward close; if no traded strike fits, the structure is skipped ("no suitable traded strikes"); no guessed premium | data fact §5 |
| AD-33 | U | NEUTRAL index signal | IRON_CONDOR, 4 legs, loss_defined=True; shorts within one expected move, the widest pair whose credit after costs ≥ width/3 | PRD §6.2 |
| AD-36 | U | Loss of one structure at 1..10 lots | strictly rising (sizing relies on it; works around the shared estimate's worst-point tie, see sizing._options_loss) | found 5 Nov |
| AD-34 | U | Nothing viable | decision NO_TRADE with reasons | PRD §29.6 |
| AD-35 | U | REVISE_STRATEGY with violation per_trade_risk | smaller size; with a non-size violation → next alternative | PRD §30.3 |

## Risk engine / Risk & Ops [control]

| ID | Layer | Case | Expected | Ref |
|---|---|---|---|---|
| AD-40 | U | Plan loss > 0.5% equity, 1 lot fits | REDUCE with allowed_lots; none fits → FAIL per_trade_risk | PRD §6.3 |
| AD-41 | U | Bull put spread credit < width/3 after costs; ≥ width/3 | FAIL credit_terms; PASS | owner 28 Oct |
| AD-42 | U | Directional R:R 1.2 | FAIL reward_risk | risk profile |
| AD-43 | U | Naked short option leg | FAIL defined_risk (hard) | PRD §6.3 |
| AD-44 | U | data_as_of two sessions old | FAIL inputs_fresh | PRD §14.2 |
| AD-45 | U | SHORT_FUTURES with the default policy | FAIL strategy_allowed | PRD §10.1 |
| AD-46 | U | Approved unexpired plans already use 2.8% open risk; new plan ≈0.45% / 2.995% used | REDUCE to the lots that fit / FAIL open_risk | PRD §9.3 |
| AD-47 | U | Sector exposure incl. pending > 25% | FAIL sector | PRD §6.3 |
| AD-48 | U | Margin incl. pending > 25% | FAIL margin_utilization | owner 27 Oct |
| AD-49 | U | SUSPENDED account | FAIL account_active | PRD §10.4 |
| AD-50 | U | Same plan + book + policy twice | identical checks and verdict | ARCH §8.3 |
| AD-51 | U | daily_loss / weekly_loss / drawdown in Phase 1 | SKIPPED with reason "no positions until Phase 2" | honesty |

## Policy [control]

| ID | Layer | Case | Expected | Ref |
|---|---|---|---|---|
| AD-52 | I+A | Default policy = risk-profile defaults; user tightens per_trade_risk_pct 0.5→0.3; user loosens 0.5→1.0; admin loosens | new version; new version; 403; new version | SPT decision 2 |
| AD-53 | U | Tenant policy 0.5%, account policy 0.3% | effective 0.3% (most restrictive) | PRD §5.1 |

## Middle Office [control]

| ID | Layer | Case | Expected | Ref |
|---|---|---|---|---|
| AD-55 | U | Task in RESEARCH mode | REJECTED reason research_mode (orchestrator never sends it; defence in depth) | PRD §5 |
| AD-56 | U | ASSISTED, PASS assessment | NEEDS_HUMAN_APPROVAL | PRD §5 |
| AD-57 | U | AUTONOMOUS_PAPER inside autonomy rules | APPROVED; scope binds trade, version, lots, notional, risk, mode SIMULATION/PAPER; expiry = session close | PRD §10.3 |
| AD-58 | U | AUTONOMOUS_PAPER, risk above autonomy max | NEEDS_HUMAN_APPROVAL | PRD §26 Q10 |
| AD-59 | U | Assessment missing / for another version / FAIL / REDUCE | REJECTED / REJECTED / REJECTED / NEEDS_REVISION | PRD §6.4 |

## Orchestrator [core]

| ID | Layer | Case | Expected | Ref |
|---|---|---|---|---|
| AD-60 | I | TRADE_PROPOSAL happy path | TA→RO→MO tasks persisted before run; 2 handoffs in the same workflow; plan APPROVED; outcome APPROVED_NO_EXECUTION; events ordered | PRD §7.1 |
| AD-61 | I | Risk FAIL then PASS after revision; FAIL after 2 revisions | approval after v2; NO_TRADE with plan REJECTED | PRD §29.6 |
| AD-62 | I | Agent exceeds its deadline once; every time | retried then COMPLETED; ESCALATED and workflow FAILED, no approval | PRD §20 |
| AD-63 | I | Agent returns output failing its schema | RETRY_PENDING; never used downstream | PRD §29.5 |
| AD-64 | I | Pre-market BLOCKED | SESSION_CYCLE BLOCKED; no scan, no proposals | PRD §30.1 |
| AD-65 | I | Start the same SESSION_CYCLE twice (same idempotency key) | one workflow | PRD §7 |
| AD-66 | I+A | WAITING_HUMAN → approve → plan APPROVED; answer twice → 409; reject → plan REJECTED | as stated | PRD §15.7 |
| AD-67 | I | Middle Office asked to review a FAIL plan | REJECTED; plan never APPROVED | PRD §11.4 |
| AD-68 | I | A task left ASSIGNED / ACCEPTED / RUNNING by a crash; service restarts | recovery fails closed: task → ESCALATED ("interrupted by restart"), its workflow → FAILED, plan never approved; the account can start a new cycle. Resuming mid-workflow is Phase 3 | PRD §8.8, §20.2 |

## Simulator [core]

| ID | Layer | Case | Expected | Ref |
|---|---|---|---|---|
| AD-70 | I+A | Create simulation; end < start; LIVE_SHADOW; SCENARIO | SIMULATION account bound to it; 422; 422; 422 | PRD §32.1 |
| AD-71 | I | Step through one session | phases in order, clock events stored, sim_time strictly increasing | PRD §28.4 |
| AD-72 | I+S | After a SCAN step on session D | every stored tool call reads data ≤ D-1; a deliberate read of D raises LookAheadError | PRD §35.2 |
| AD-73 | I+A | Pause then step; resume; stop then step | 409; ok; 409 | PRD §32.2 |
| AD-74 | I | Desk lists vs simulation lists; mode change on a sim account | never mixed; Conflict | PRD §35.20 |
| AD-75 | I | Two simulations, same config and data | identical normalised outputs | PRD §35.19 |
| AD-76 | I+S | Run 2 sessions to the end | COMPLETED; results with counts, data coverage, versions, limitations | PRD §35.23 |
| AD-77 | I | EOD step | unused signals EXPIRED; unanswered approvals expired; waiting workflows completed as expired | PRD §30.6 |

## API [core]

| ID | Layer | Case | Expected | Ref |
|---|---|---|---|---|
| AD-80 | A | Every route without a session | 401 | PRD §17 |
| AD-81 | A | Another tenant's ids | 404 | PRD §18.1 |
| AD-82 | A+S | Create account, list, mode change | 201/200; ACCOUNT_MODE_CHANGED event | PRD §5.2 |
| AD-83 | S | SESSION_CYCLE on staging data for the latest session | completes; workflow detail shows tasks + handoffs | PRD §7.1 |
| AD-84 | A+S | GET /agents; /agents/AI_TRADER/activity | 5 agents with versions; tasks listed | PRD §15.3 |
| AD-85 | S | Simulation create / step / timeline / results on staging data | real signals and plans for a past session | PRD §34 |
| AD-86 | A | Approval decision API | see AD-66 | PRD §17.3 |
| AD-87 | A+S | GET /desk/status | mode, agents, pending approvals, data freshness | PRD §15.2 |

## Safety [core]

| ID | Layer | Case | Expected | Ref |
|---|---|---|---|---|
| AD-90 | U | tests/test_order_path_guard.py | passes (no order calls added) | owner rule |
| AD-91 | U | Static scan of backend/autodesk | no reference to paper_accounts / paper_account_ledger / desk_paper_trades / risk_decisions / spt_ collections, nor risk_gate.service.enter/gather/enforce, risk_book.read, plan_sizing.size_for | D2 |
| AD-92 | U | Agent narrative text (thesis, rationale, risk warnings, summaries, reasons) | none of: buy, sell, stop loss, SL, target, entry, exit, accumulate, book profit, upside, price target, recommend, pick (whole words, case-insensitive) | owner 3 Nov |

## Additions from the owner's screen designs (5 Nov) [core]

| ID | Layer | Case | Expected | Ref |
|---|---|---|---|---|
| AD-93 | I | Activate STOP_NEW_ENTRIES, run a desk SESSION_CYCLE | premarket + scan run, signals stored; proposals held back (`proposed: 0`, `held_back`); ENTRIES_STOPPED event | design §3, PRD §10.4 |
| AD-94 | I | STOP_NEW_ENTRIES active, start a TRADE_PROPOSAL for a desk signal | Conflict (409 over the API); signal stays DETECTED | design §3 |
| AD-95 | I | STOP_NEW_ENTRIES active, a person approves a pending request | Conflict; REJECT still works; after lift, APPROVE works | design §3 |
| AD-96 | I | STOP_NEW_ENTRIES active, a simulation steps through a past session | proposals run as usual (simulations not affected) | design §10 |
| AD-97 | I+A | Activate twice, lift once | one ACTIVATED + one LIFTED event; second press `changed: false`; GET /desk/controls and /desk/status show the state | PRD §10.4 |
| AD-98 | U+I | Approval binding | APPROVED scope carries `plan_hash` = sha256 of the plan version body; a person's decision with a stale `plan_hash` → Conflict; GET /trade-plans/{id} returns `plan_hash` | design §05, PRD §10.3 |

## Desk web app (UI) — written 5 Nov before the UI code [ui]

Design source: the owner's clickable prototype "Nivesh Trading Desk (2).html" (5 Nov), screens extracted to
docs/autodesk/design/prototype/ (TD*.dc.html, _shell.html). The app is served at /autodesk/ (same origin as the API at
/autodesk/api/v1 and the main app's /api). Phase 1 fills overview, agents, scanner, approvals, simulator and policies
with real data; workbench, trades, P&L, capital & risk, middle office and fleet show a labelled Phase 2 screen.

Layers: E = Playwright on the production build (`vite preview`), API answered by route mocks whose bodies copy the
real API's shapes (marked MOCK in the spec); C = contract — every request body the UI sends is captured in the E run,
written to frontend-v5/e2e/fixtures/autodesk/ui-requests.json, and posted to the real FastAPI app by a backend test;
S = staging with a real sign-in (needs the owner's session token).

Rules every screen follows: no number without a source (an API field or the live feed); nothing from a later phase
is shown as if it existed (a labelled "Phase 2" state instead); an API failure shows the error, never a blank or a
sample; agent-written text is shown as written; labels may use the design's standard words.

### Shell [ui]

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-UI-01 | E | Open /autodesk/ signed in (desk/status 200) at 1280×800 | sidebar 236 px with brand, accounts card, 12 numbered items in Desk / Positions / Control groups; sticky header; Desk overview active |
| AD-UI-02 | E | desk/status answers 401 | a sign-in screen with a link to /v5/login; no shell data, no sample numbers |
| AD-UI-03 | E | Accounts card | one row per non-simulation account from GET /accounts with its mode pill (RESEARCH → Research, ASSISTED → Assisted, AUTONOMOUS_PAPER → Auto); no broker rows (brokers are not desk accounts in Phase 1) |
| AD-UI-04 | E+C | No accounts → "New paper account" → name + capital → Create | POST /accounts `{name, operating_mode: "RESEARCH", starting_capital_rs}`; the card lists the new account |
| AD-UI-05 | E | Header market strip, live feed answering mode "live", session "open" | "NSE open" mint pill; IST clock ticks; NIFTY 50 / NIFTY BANK / INDIA VIX values and % change from GET /api/live/quotes; "Kite feed live" |
| AD-UI-06 | E | Live feed mode "closed" / "not_connected" / request fails | "NSE closed" pill; closed shows the day's close marked "close"; not connected or failure hides the numbers and says "Index quotes unavailable" — never a sample value |
| AD-UI-07 | E | Agents pill | "{healthy}/{total} agents healthy" from desk/status agents (healthy = IDLE or BUSY); amber when any is not healthy; click → Agent fleet & reliability |
| AD-UI-07b | E | The registry holds an older version of an agent (status OFFLINE) after its newest row | the pill counts each agent once by its newest version: "5/5 agents healthy"; no fleet badge |
| AD-UI-08 | E+C | "Stop new entries" → dialog with a reason → Confirm | POST /desk/controls/STOP_NEW_ENTRIES `{active: true, reason}`; red "ENTRIES STOPPED" banner with the time and the person from the control row, saying new plans are not proposed or approved until resumed and simulations are not affected; button becomes "Resume entries" |
| AD-UI-09 | E+C | "Resume entries" → Confirm | POST `{active: false, reason}`; banner gone |
| AD-UI-10 | E | Control POST fails (500 / 403) | the dialog shows the API's message; state unchanged |
| AD-UI-11 | E | Nav badges | Approval queue = pending approvals (amber, hidden at 0); Simulator "SIM" (indigo) |
| AD-UI-12 | E | Phase 2 items (workbench, trades, P&L, capital & risk, middle office, fleet) | a screen titled as in the design saying what it will show and that it needs paper execution (Phase 2); no sample figures |
| AD-UI-13 | E | Phone 390×844 | top bar with title + "STOP NEW"; 5-tab bottom bar Desk / Trades / Approve / P&L / More; Approve badge = pending count; More opens the sheet with all 12 items |
| AD-UI-14 | E | Deep link /autodesk/approvals and reload | the approval queue renders (SPA fallback) |
| AD-UI-15 | E | Light theme toggle | data-theme="light" on the frame; choice kept after reload |
| AD-UI-16 | E | Any screen | no console errors; no request outside /autodesk/api/v1, /api/auth/me and /api/live/quotes |

### Screens [ui]
Per-screen cases (overview AD-UI-20.., agents 30.., scanner 40.., approvals 50.., simulator 60.., policies 70..) are
in docs/autodesk/ui_testcases/ — each written before that screen's code.

### Hosting [ui]

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-UI-90 | E | Production build with base /autodesk/ | index.html references /autodesk/assets/*; no request to /v5/ |
| AD-UI-91 | E | Container nginx: /autodesk → 301 /autodesk/; /autodesk/x/y → index.html; /autodesk/assets/* immutable | as stated (throwaway nginx container on the built image layout) |
| AD-UI-92 | E | Edge nginx: /autodesk/api/v1/health still reaches the desk API; /autodesk/ reaches the frontend container; /v5/ unchanged | `nginx -t` passes on the real files; routing test in a throwaway nginx |
| AD-UI-93 | S | After merge + deploy: https://staging.niveshcopilot.com/autodesk/ | 200, the desk app's index.html |

### Simulation studio — frame [ui] (5 Nov, from the owner's design pack, before the code)

Design: docs/autodesk/design/prototype/studio/ (Simulation Studio.dc.html + SimDay / SimSetup / SimScenarios / SimRuns /
SimTrace). A page of its own at /autodesk/studio, beside the desk. Per-view cases: docs/autodesk/ui_testcases/studio-*.md
(Trading day AD-UI-110.., New simulation 120.., Scenario library 130.., Run history 140.., Agent trace 150..).

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-UI-100 | E | Open /autodesk/studio signed in | studio header (mark, "Simulation studio", "Nivesh · trading desk simulator"), indigo pill "Simulated · isolated · no broker route", five tabs in the design's order with Trading day active, Dark/Light switch, "Trading desk ›" link to /autodesk/; no desk sidebar |
| AD-UI-101 | E | Click each tab | URL /studio, /studio/new, /studio/scenarios, /studio/runs, /studio/trace; that tab active (indigo); its view renders |
| AD-UI-102 | E | /autodesk/studio/runs?sim=SIM-1, then click another tab | the `sim` parameter is kept on every tab |
| AD-UI-103 | E | GET /simulations answers 401 | the sign-in screen, no studio data |
| AD-UI-104 | E | Light / Dark switch | data-theme changes; the choice is shared with the desk and kept after reload |
| AD-UI-105 | E | Deep link /autodesk/studio/trace and reload; unknown /autodesk/studio/x | the trace view renders after reload; the unknown path goes to Trading day |
| AD-UI-106 | E | Phone 390×844 | header wraps, tabs reachable, no horizontal overflow |
| AD-UI-107 | E | Desk routes after the change | /autodesk/ and /autodesk/simulator still render inside the desk shell |
