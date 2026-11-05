# Simulator (screen 10) — UI test cases (written before the screen code)

Design: `docs/autodesk/design/prototype/TDSimulator.dc.html`. Screen: `frontend-v5/src/autodesk/screens/Simulator.tsx`.
Spec: `frontend-v5/e2e/tests/autodesk-simulator.spec.ts` (route mocks from `autodesk-fixtures-simulator.ts`, shapes of
the real API). Request contracts: `frontend-v5/e2e/fixtures/autodesk/requests/simulator.json`.

Layer: E = Playwright against the production build with route mocks; C = the request body the UI sends equals a
contract that the backend test posts to the real FastAPI app.

Data sources: `GET /simulations`, `GET /simulations/{sid}` (row + `background_run`), `GET /simulations/{sid}/results`,
`/agents`, `/workflows`, `/timeline` (clock + events, paged with `after_seq`), `GET /desk/workflows/{wid}` (tasks of the
trade-proposal workflow in the dependency graph). Actions: `POST /simulations`, `/start`, `/step`, `/run`, `/pause`,
`/resume`, `/stop`.

Phase 1 truth shown on screen: replay of past sessions phase by phase (PREMARKET 08:30 → SCAN → PROPOSALS → OPEN →
CLOSE → EOD) on end-of-day data; no orders, fills, positions or P&L; SCENARIO and LIVE_SHADOW are refused by the API.

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-UI-60 | E | Deep link `/autodesk/simulator/{sid}` to a COMPLETED 2-session replay of 2–3 Nov 2026 at 1280×800 | Eyebrow "10 · Trading desk simulator", indigo pill "Simulated · isolated · no broker route", pill "{sid} · seed 42"; headline names the replayed sessions; mode chip "Historical replay" active; clock = last `clock_sim_time` in IST (18:00:00), status pill COMPLETED, progress 12 of 12 steps; data-as-of row from the session's pre-market check; counters from `/results`: Signals 476, Proposals 6 (bull call spread 3 · bear put spread 3), Approvals 6 (6 by Middle Office), Policy violations 0; Orders / Positions / Stop · target · trail / Capital deployed tiles show "—" with "Phase 2"; "Agents in this run" = five agents with task counts from `/agents`; the results' limitations listed as written |
| AD-UI-61 | E | Agent communication, exceptions and dependency graph | Newest-first rows from `/timeline` events: time (sim time, or the phase the event ran in), "FROM → TO · TYPE" for handoffs, task results with the agent's summary as written, signals, plans, approvals, clock steps; "Show more" adds rows; "Exceptions and recovery" lists failed / retried tasks (RECOVERED when the task later completed) or "No exceptions in this run"; final reconciliation says it needs fills (not in Phase 1); the dependency graph shows the latest trade-proposal workflow: Signal, Proposal, Risk report, Revision, Authorization with states from its tasks, nodes 6–13 marked "Phase 2" |
| AD-UI-62 | E | Blocks the API cannot serve | Simulated P&L, Policy comparison and Live activation gate render a Phase note (no ₹ figures, no "18 of 20", no "v7"/"v8"); the speed multipliers and the scenario select / Inject scenario are disabled with the reason; the policy the run used (`versions.policy`) is named |
| AD-UI-63 | E+C | New simulation… → defaults (sessions = previous weekday → latest cash session from `/desk/status`) → Create | POST `/simulations` equals contract `simulator.create` `{name, mode: "HISTORICAL_REPLAY", start_date, end_date, starting_capital_rs, operating_mode, max_proposals_per_session}`; 201 → URL `/simulator/{new sid}`, status pill NOT STARTED, Start enabled. With symbols typed (`PETRONET, GRASIM`) the body equals `simulator.create_symbols` |
| AD-UI-64 | E+C | CREATED → Start → Step phase → Step session | POST `/simulations/{sid}/start` (no body, contract `simulator.start`); POST `/step` `{"unit":"PHASE"}` (`simulator.step_phase`); POST `/step` `{"unit":"SESSION"}` (`simulator.step_session`); after each, the clock / phase / step counter show the API's new values |
| AD-UI-65 | E+C | Run to end, polling, pause, resume, stop | POST `/run` (no body, 202, `simulator.run`) → while `background_run` the screen polls `GET /simulations/{sid}` and shows RUNNING until COMPLETED; Pause / Resume / Stop send `simulator.pause` / `simulator.resume` / `simulator.stop` (no body); after Stop the banner "Stopped at … no further step runs" shows and Start / Step / Run are disabled. An accelerated-replay run's Start also sends `run` |
| AD-UI-66 | E | Action errors | Create 422 (`{"error":"INVALID","message":"no trading sessions in the chosen date range"}`) shows the message in the dialog and nothing is created; step 409 ("simulation is PAUSED; it does not step") and run 409 show the API message under the controls; the row is unchanged |
| AD-UI-67 | E | Mode chips Scenario simulation / Live shadow | A Phase note says the API refuses SCENARIO (Phase 3) and LIVE_SHADOW (Phase 4); no POST is sent; Historical / Accelerated replay chips open the New simulation dialog with that mode |
| AD-UI-68 | E | Empty and failing loads | No simulations → empty state with "New simulation…", no clock / counters; `GET /simulations` 500 → ErrorBox with the API message; deep link to an unknown sid → the API's 404 message |
| AD-UI-69 | E | Phone 390×844 and Export | Single column, no horizontal overflow; Export downloads `{sid}-results.json` holding the simulation row and `/results`; no console errors; only desk API / auth / live-quote URLs requested |
