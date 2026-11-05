# Simulation studio · Trading day — UI test cases (written before the view code)

Design: `docs/autodesk/design/prototype/studio/SimDay.dc.html` (inside the studio frame `Simulation Studio.dc.html`).
View: `frontend-v5/src/autodesk/studio/views/Day.tsx` (+ `views/day/`). Route `/autodesk/studio` (`?sim=` selects the run,
default = newest run). Spec: `frontend-v5/e2e/tests/autodesk-studio-day.spec.ts` (route mocks from
`autodesk-fixtures-studio-day.ts`, shapes of the real API). Request contracts:
`frontend-v5/e2e/fixtures/autodesk/requests/studio-day.json`.

Layer: E = Playwright against the production build with route mocks; C = the request the UI sends equals a contract
that the backend test (`backend/tests/autodesk/test_ui_request_contracts.py`) posts to the real FastAPI app.

Data sources: `GET /simulations` (studio frame + run list), `GET /simulations/{sid}` (row: status, clock, config,
versions, `background_run`), `GET /simulations/{sid}/results` (policy violation attempts), `GET /simulations/{sid}/timeline`
(clock rows + events, read incrementally with `after_seq`). Actions: `POST /simulations/{sid}/start`, `/run`, `/pause`,
`/resume` (no body).

Phase 1 truth shown on the view: a run replays past NSE sessions phase by phase — PREMARKET 08:30, SCAN 08:45,
PROPOSALS 09:00, OPEN 09:15, CLOSE 15:30, EOD 18:00 (IST) — on end-of-day data. The clock moves by phase, not by minute.
There are no orders, fills, positions, P&L, scenario injection, speed multipliers or checkpoints. Per-day counters,
lane dots and end-of-day counts come from the run's own events, bucketed by the clock step they ran in.

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-UI-110 | E | `/studio?sim={sid}` on a COMPLETED 2-session replay (2–3 Nov 2026) at 1280×800 | Eyebrow "Full trading day · {sid}"; indigo pill "Historical replay · Tue 3 Nov 2026 · session 2 of 2"; pill "{run name}"; pill "{policy_id} v1 · seed 42" from `versions.policy` + `config.seed`; headline from the clock phase (EOD → "The bell has rung." + "Every session of this run is replayed."); clock card: 18:00:00, pill COMPLETE, "End of day · Tue 3 Nov 2026 · step 12 of 12" and the EOD description; counters of the shown day (3 Nov) from its events: Signals 3, Plans 3, Risk checks 3, Approvals 3, Recovered 1 (the risk task that went RETRY_PENDING then COMPLETED); Fills "—" Phase 2, Exits "—" Phase 3, Shocks "—" Phase 3 |
| AD-UI-111 | E | "The day, agent by agent" track | Eyebrow "08:00 → 18:30 · click the track to jump"; header bands PRE-MARKET 08:00, PRE-OPEN 09:00, INTRADAY 09:15, CLOSE AND POST-CLOSE 15:30, EVENING 18:00; nine lanes in the design's order (AI Trader, Trading Assistant, Risk & Operations, Middle Office, Tech Support, Lifecycle manager, Sim exchange, Orchestrator, Scenarios); dots only where an agent produced events in a reached phase (AI Trader at 08:45, Trading Assistant / Risk & Operations / Middle Office at 09:00, Tech Support at 08:30), the risk lane's 09:00 dot amber (a retried task); Lifecycle manager and Scenarios lanes say Phase 3, Sim exchange says Phase 2, none of them has a dot; legend keeps DECISION / clock / ◆ INJECTED SCENARIO (Phase 3) / FAILED · BLOCKED / FAINT = SCHEDULED, NOT YET REACHED; the session select switches to 2 Nov and the counters change to that day's events (Recovered 0) |
| AD-UI-112 | E | Event feed + Jump to | "Event feed · Newest first · structured messages": rows newest first with sim time (HH:MM), "WHO · TYPE" and the event text as written (agent summaries untouched); 10 rows then "Show more"; Jump to chips All day / Pre-market / Scan / Proposals / Open / Close / End of day: a chip filters the feed to that phase of the shown day (Proposals → plan, risk, approval, handoff rows only, all at 09:00); the chip toggles back; clicking the track near 09:15 filters to Open; unreached phases' chips are disabled |
| AD-UI-113 | E | Blocks Phase 1 cannot serve, End of day, links | "Net P&L, simulated" and "Positions" keep their place with a Phase 2 note and no ₹ figure; End of day: pill SESSION CLOSED / RUN COMPLETE; rows Orders · fills · breaks, Gross · charges, Net P&L after costs, Max drawdown "—" (Phase 2), Assertions "—" (Phase 3), Policy violations 0 from `/results`, Signals expired at the close and Approvals expired at the close counted from the EOD step's events; "Compare with other runs" → `/studio/runs?sim={sid}` when another run exists, otherwise disabled "No other run to compare"; "Replay a task trace" → `/studio/trace?sim={sid}` |
| AD-UI-114 | E+C | CREATED run → Play; RUNNING in the background → Pause; PAUSED → Play | Play sends POST `/simulations/{sid}/start` then `/run` (contracts `studio-day.start`, `studio-day.run`, no body); while `background_run` the button reads Pause and the status pill RUNNING; Pause sends `studio-day.pause`; status PAUSED; Play sends `studio-day.resume` then `studio-day.run` |
| AD-UI-115 | E | Controls with no API | Restart day and the speed chips 60× / 120× / 300× / 600× are disabled with the reason; a Phase 3 note under the bar says the clock moves one phase at a time; a COMPLETED run's button reads "Day done" (disabled); a 409 from `/run` shows the API's message in an alert and the row is unchanged; STOPPED and FAILED runs show their banner (FAILED with `error` as written) |
| AD-UI-116 | E | Empty and failing loads | No simulations → empty state with a "New simulation" link to `/studio/new`, no clock / track; `GET /simulations` 500 → ErrorBox with the API message; `?sim=` of an unknown run → the API's 404 message in an ErrorBox; `/timeline` 500 → ErrorBox inside the event feed, the clock card still renders |
| AD-UI-117 | E | A run playing in the background | The view polls `GET /simulations/{sid}` while `background_run` is true; the clock and step move with the API's values; the timeline is re-read with `after_seq` = the last seq already held (incremental), and new events appear at the top of the feed |
| AD-UI-118 | E | Phone 390×844 | Header, controls and blocks stack in one column; counters in two columns; the lane track scrolls inside its own box; no horizontal overflow of the page |
| AD-UI-119 | E | No sample data, wording, hygiene | The page never shows the prototype's sample ids or figures (SIM-0418, SIM-0417, SCN-0…, P-PAPER-v8, seed 8841, ₹16,734, RELIANCE 300…); explanatory text uses none of: buy, sell, stop loss, SL, target, entry, accumulate, book profit, upside, price target, recommend, pick; no console errors; every API call matched a mock (no unexpected endpoint) |
