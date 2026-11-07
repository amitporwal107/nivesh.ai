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

## Scoring v2 — versioned signal hierarchy [core] (5 Nov, before the code)

Owner 5 Nov: build the revised hierarchy as a versioned, configurable scoring framework; keep v1 live; v2 in shadow; bearish
signals only as risk / exit warnings; horizon-aware (positional on, swing and intraday off); explainable; walk-forward
validation before promotion. Spec: docs/signal_intelligence/SIGNAL_TIER_HIERARCHY.md §11.

| ID | Layer | Case | Expected | Ref |
|---|---|---|---|---|
| AD-SC-01 | U | Versions registry | v1 ACTIVE, v2-positional SHADOW, v3-intraday DISABLED; v2 dimension maxima 45/30/15/10 sum to 100 | §11 |
| AD-SC-02 | U | Only v1 may be active | asking for another active version raises; nothing promotes without a code change | §11 |
| AD-SC-03 | U | Relative-strength breakout | fires when stock ÷ Nifty closes above its prior 250-session maximum; not with < 251 aligned sessions ("insufficient history") | §11 |
| AD-SC-04 | U | Higher highs + higher lows / lower highs + lower lows | zig-zag uptrend → HH-HL state; downtrend → LH-LL warning; swing points used only 2 bars after they form | §11 |
| AD-SC-05 | U | No look-ahead | score at bar t from the full series equals the score from the series cut at t (sampled t, random walks) | §8 |
| AD-SC-06 | U | Overlap rule | when HH-HL is the primary signal, the trend dimension does not score HH-HL again; RS dimension halves when the RS breakout is primary | §11 |
| AD-SC-07 | U | Bearish signals | never give an entry tier; listed as warnings; a bullish candidate with a bearish warning loses 10 | §11 |
| AD-SC-08 | U | No chasing penalty; RSI 75–80 positive | a stock 4 ATR above EMA20 is not penalised; RSI 77 earns the top momentum points | §10 |
| AD-SC-09 | U | Volume is not rewarded beyond 1.5× | 10× and 1.6× volume earn the same volume points | §10 |
| AD-SC-10 | U | Bands and attribution | score → Exceptional / Strong / Developing / Weak / Avoid; every point carries a dimension, weight and reason | §1 |
| AD-SC-11 | I | AI Trader with shadow scoring | v1 `signal_score` and breakdown identical with shadow on and off; each signal carries `shadow_scores[v2-positional]` | §11 |
| AD-SC-12 | I | Scan report | `shadow` block lists v2 candidates (including stocks v1 did not signal) without publishing them; v1 signals unchanged | §11 |
| AD-SC-13 | A | GET /api/v1/scoring/versions | 401 signed out; lists versions, status, weights, horizon, validation state | §11 |
| AD-SC-14 | U | Old signal bodies | a stored signal without `shadow_scores` still parses | §11 |
| AD-SC-15 | S | Walk-forward shadow check (study data) | v2 bands sort 20-session excess returns in the test period (Oct 2025 – Nov 2026), reported before any promotion | §8 |

## Desk fixes from the 5 Nov walk-through [core+ui] (7 Nov, before the code)

Source: test_reports/autodesk_staging_walkthrough_20261105.md (Findings 1-4 and the "where can I see the plans" gap) plus
the unbounded-list finding. Six fixes, F1..F6. Layers: U unit, I integration (throwaway Postgres), A API (FastAPI app),
E Playwright on the production build with route mocks (MOCK, shapes of the real API). Owner rule behind F1/F2: no stale
market data; the point-in-time rule stays strict (no look-ahead) for simulations.

### F1 - data-arrival times (cash 19:30 IST, F&O 22:45 IST)

Real loads on the data platform: cash bhavcopy 19:00:04 IST, F&O bhavcopy 22:15:21 IST (nidp.v_feed_status); the desk
used 18:30 / 19:30 and a cycle at 18:50 IST was BLOCKED for "0 cash rows for 2026-11-05".

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-FX-01 | U | `published_at(D, "cash")` and `published_at(D, "fno")`; constants | cash D 19:30 IST, F&O D 22:45 IST (UTC 14:00 and 17:15) |
| AD-FX-02 | U | Pit view on D at 19:29 / 19:31 IST (cash) and 22:44 / 22:46 IST (F&O); also 18:50 IST for cash; FrozenMarketView at the same instants | D's cash is LookAheadError until 19:30, visible after; D's F&O until 22:45; at 18:50 `latest_session("cash")` is the previous session; a Monday-morning view sees Friday for both kinds (rewrites AD-10's instants) |
| AD-FX-03 | I | Simulations after the change: AD-70..77 (replay, no look-ahead, identical reruns) | all still pass; every stored tool call reads data <= D-1 (AD-72) |

### F2 - F&O and cash freshness against the session being prepared

Rule: the data must be for the session immediately before the session being prepared. F&O older than that -> `fno_eod`
DEGRADED, cash only. Cash older than that -> `cash_eod` BLOCKED, with the date in the detail. The detail never says
"target" or other banned narrative words (AD-92).

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-FX-04 | U | Pre-market for 6 Nov at 08:45 IST, cash and F&O for 5 Nov, enough rows | READY [CASH, FUTURES, OPTIONS] (AD-25 unchanged) |
| AD-FX-05 | U | Same, F&O day is 4 Nov (two sessions before 6 Nov) with >= 50 underlyings | `fno_eod` DEGRADED, detail "F&O data is for 2026-11-04; the 2026-11-06 session needs 2026-11-05", status DEGRADED, allowed [CASH] |
| AD-FX-06 | U | Pre-market for 6 Nov at 5 Nov 18:50 IST (cash for 5 Nov is not published yet, latest cash is 4 Nov) | `cash_eod` BLOCKED, detail "Cash data is for 2026-11-04; the 2026-11-06 session needs 2026-11-05", status BLOCKED, allowed [] |
| AD-FX-07 | U | Session after a weekend (Mon 9 Nov needs Fri 6 Nov) and after a holiday (Wed 11 Nov after the 10 Nov holiday needs Mon 9 Nov) | Friday's / Monday's data READY; the session before that is stale in both kinds |
| AD-FX-08 | U | The session before the one being prepared cannot be determined (calendar unavailable) | `cash_eod` BLOCKED "cannot tell which session precedes ...", `fno_eod` DEGRADED; never READY by default |
| AD-FX-09 | U | `previous_session` on the Pit view and on the Frozen view; Pit with a holiday between | the last session before the day (holiday skipped), never a look-ahead read; recorded as a tool call |

### F3 - a blocked cycle must not use up the session

Idempotency key stays `{account}:{session}:cycle` for the first attempt; a new request after a cycle that ended BLOCKED
with no scan and no proposals opens `...:cycle:attempt-2`, then `:attempt-3`. The earlier workflow stays for audit.

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-FX-10 | I | Desk cycle ends BLOCKED at pre-market; request the cycle again for the same account and session | a new SESSION_CYCLE workflow (key `...:cycle:attempt-2`); the first stays BLOCKED with its outcome; two workflows listed |
| AD-FX-11 | I | The second attempt is BLOCKED too; request again | third attempt (`:attempt-3`); then a COMPLETED attempt: a further request returns that same workflow (no attempt-4) |
| AD-FX-12 | I | COMPLETED cycle, or one still RUNNING; request again (AD-65 stays) | the same workflow, nothing created |
| AD-FX-13 | U+I | Which cycles may be re-attempted | only state BLOCKED with neither `scan` nor `proposals` in the outcome; FAILED, COMPLETED, RUNNING and a BLOCKED row that has a scan are not; a cycle opened with an explicit idempotency key (simulations) is never re-attempted |
| AD-FX-14 | A | POST /desk/workflows (wait) with a pre-market that BLOCKS, then again | second answer has another workflow_id; GET /desk/workflows lists both; the second is not the first's id |
| AD-FX-15 | E | Scanner whose newest cycle is BLOCKED | "Run session cycle" is enabled; click posts `{kind, account_id}` (contract unchanged); the new attempt shows as running; the "already ran" message is not shown |
| AD-FX-16 | E | POST answers with a BLOCKED, scan-less cycle in a terminal state (nothing re-opened) | no "already ran" text; the blocked panel (AD-FX-20) is shown for it; COMPLETED still says it already ran (AD-UI-46 unchanged) |

### F4 - why a cycle was blocked

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-FX-20 | E | Latest cycle BLOCKED; `outcome.premarket.checks` = cash_eod BLOCKED ("Cash data is for 2026-11-04; ..."), fno_eod DEGRADED, vix DEGRADED, desk_db READY | a panel "Pre-market check blocked this session" lists the three failed or degraded checks, each with its plain name (Cash end-of-day data, F&O end-of-day data, India VIX), its state word and its detail text; the READY check is not listed; says nothing was scanned and no plan made, and that Run session cycle can be used again once the data is in |
| AD-FX-21 | E | Same cycle right after the run (cycle-status watch) and after a reload (newest cycle from the list) | same panel in both; the one-line status keeps "BLOCKED" |
| AD-FX-22 | E | BLOCKED cycle whose premarket has a `reason` and no checks (the check did not complete) | the reason is shown as written |
| AD-FX-23 | E | COMPLETED cycle whose premarket is DEGRADED (cash only) | the degraded checks are shown as a note ("Pre-market degraded ..."), not as blocked; a READY cycle shows no panel |
| AD-FX-24 | U | Tech Support detail strings | none of the banned narrative words (AD-92 extended to the new details) |

### F5 - "Open full plan" link in the Simulation studio

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-FX-30 | E | Agent trace of a run; approvals of the run answer GET /approvals?simulation_id=SIM | each card whose proposal made a plan shows "Open full plan"; its href is /autodesk/approvals/{approval_id} of the NEWEST approval row of that trade; a NO_TRADE card has no link; one approvals request for the run, not one per card |
| AD-FX-31 | E | Click the link | the URL becomes /autodesk/approvals/APR-..., the approval detail renders labelled as a simulation; the click does not change the selected card |
| AD-FX-32 | E | The selected chain's detail | the link is also in the chain's outcome box |
| AD-FX-33 | E | Trading day feed rows of APPROVAL_* events (payload has approval_id) | "Open full plan" on the row, href as above; rows without an approval id have none |
| AD-FX-34 | E | The approvals request fails (500) | cards and replay still work; a visible note names the failure; no link guessed |
| AD-FX-35 | A | GET /approvals?simulation_id=&trade_id= for a simulated plan | the approval rows of that trade, newest first (the id the UI links to) |

### F6 - lists return the newest rows

Choice: `/desk/workflows` newest-first (like /approvals, /trade-plans, /signals); `/events` and `/simulations/{id}/timeline`
keep ascending order but, with no `after_seq`, return the NEWEST `limit` rows; with `after_seq` (the cursor the UI always
sends) they return the next rows after the cursor, oldest first, exactly as before.

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-FX-40 | I | `store.list_events` with 30 events, limit 10 | no cursor: seq 21..30 ascending; `after_seq=0`: seq 1..10; `after_seq=10`: 11..20; walking the cursor until a short page reads all 30 |
| AD-FX-41 | A | GET /events?limit=N and GET /events?after_seq=0&limit=N on a tenant with more than N events | newest N ascending; oldest N ascending |
| AD-FX-42 | A | GET /simulations/{id}/timeline?limit=N (no after_seq) and with after_seq=0 | events as AD-FX-41; `clock` rows unchanged (all of them, ascending) |
| AD-FX-43 | I+A | `store.list_workflows(newest_first)` and GET /desk/workflows?limit=2 with 3 session cycles for different sessions | the two newest, newest first; account and kind filters apply; children of a workflow (GET /desk/workflows/{id}) stay in creation order |
| AD-FX-44 | E | UI consumers: scanner (newest cycle first), agents screen, Trading day / simulator timeline | existing specs pass unchanged; the timeline requests carry `after_seq` (cursor mode), so the UI still reads a run from its first event |
