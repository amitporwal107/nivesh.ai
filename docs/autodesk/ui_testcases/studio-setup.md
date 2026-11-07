# Simulation studio · New simulation — UI test cases (written before the view code)

Design: `docs/autodesk/design/prototype/studio/SimSetup.dc.html`. View: `frontend-v5/src/autodesk/studio/views/Setup.tsx`
(route `/autodesk/studio/new`, root `data-testid="studio-new"`). Spec: `frontend-v5/e2e/tests/autodesk-studio-setup.spec.ts`
(route mocks from `autodesk-fixtures-studio-setup.ts`, shapes of the real API). Request contracts:
`frontend-v5/e2e/fixtures/autodesk/requests/studio-setup.json` (posted to the real FastAPI app by
`backend/tests/autodesk/test_ui_request_contracts.py`).

Layer: E = Playwright against the production build with route mocks; C = the request body the UI sends equals a
contract that the backend test posts to the real FastAPI app.

Data sources: `GET /desk/status` (`market_data.latest_cash_session` → default sessions, as the desk's New simulation
dialog: the weekday before the latest cash session → that session), `GET /policies` (Policy section),
`GET /agents` (current version of each agent). Actions: `POST /simulations` (SimulationConfig: name, mode, start_date,
end_date, starting_capital_rs, operating_mode, policy_id, max_proposals_per_session, symbols, seed, speed — extra fields
are refused), then `POST /simulations/{sid}/start`, and for an accelerated replay `POST /simulations/{sid}/run`.

Phase 1 truth: HISTORICAL_REPLAY (stepped phase by phase) and ACCELERATED_REPLAY (runs to the end in the background)
only; SCENARIO is Phase 3 and LIVE_SHADOW Phase 4 (the API refuses both with 422); no execution model (Phase 2), no
scenario injections or checkpoints (Phase 3), no speed multiplier, no agent-version pinning. Only 2026 sessions replay
(the NSE holiday list has no 2025 / 2027 rows) — the API's 422 message is shown.

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-UI-120 | E | Open `/autodesk/studio/new` (desk status: latest cash session 4 Nov 2026; one policy "Desk default" v3; registry with an older RISK_OPS version) at 1280×800 | Eyebrow "New simulation", pill "Draft", the design's headline "Set up a run. Same inputs and seed give the same result, every time."; sections in the design's order 01 Mode · 02 Session · 03 Universe · 04 Capital and account · 05 Agent versions · 06 Policy · 07 Execution model · 08 Playback and seed · 09 Scenario injections; defaults: Historical replay selected, first/last session 2026-11-03 → 2026-11-04, six weekday chips ending Wed 4 Nov, F&O stocks selected, ₹1.00 Cr, Auto paper, Desk default · v3 selected, 5 plans per session, seed 42; 05 lists five agents with the CURRENT version from `GET /agents` (autodesk-risk-ops-v1, not v0); aside "Run summary" with the name field (default "Historical replay · 3 Nov – 4 Nov 2026") and rows Sessions / Universe / Capital / Account mode / Policy / Agents / Plans per session / Execution / Injections / Seed / Playback; ISOLATED note; "Create and start" enabled; no sample ids (SIM-0419, P-PAPER, SCN-) and no console errors |
| AD-UI-121 | E | Blocks Phase 1 cannot serve keep their place | 02 "Pre-open auction" and "Post-close reconciliation" chips disabled, marked "Not in Phase 1"; 03 Nifty 50 / Nifty 200 / Index options disabled (Nifty 500 and Nifty Total Market are enabled since package 5: AD-SC-33/34 in testcases_scoring_v21.md) ("Not a separate universe in Phase 1"); 05 note that versions cannot be pinned (the run stores the versions running at create time); 07 Execution model is a "Fixed for now" note with the real fill assumptions (half spread, slippage, volume share, latency, price checks; they cannot be changed per run); 08 speed multipliers and checkpoints "Not in Phase 1"; 09 Scenario injections is a Phase 3 note and "Edit in scenario library ›" opens `/studio/scenarios` keeping `?sim=`; summary Execution "Simulated fills · no broker", Injections "None · Phase 3" |
| AD-UI-122 | E+C | Historical replay: type the name "Studio replay" → Create and start | POST `/simulations` equals contract `studio-setup.create` (`mode HISTORICAL_REPLAY`, `speed STEP`, `policy_id` of the selected policy, `seed 42`, capital 10000000, AUTONOMOUS_PAPER, 5 per session, start/end = the default sessions); then POST `/simulations/{new}/start` with no body (`studio-setup.start`); no `/run`; URL becomes `/autodesk/studio?sim={new}` and the Trading day tab is current |
| AD-UI-123 | E+C | Accelerated replay with a weekday chip (Tue 3 Nov), "Your symbols" PETRONET, GRASIM, ₹50 L, Assisted, 3 per session, re-rolled seed replaced by a typed seed 8841 → Create and start | POST `/simulations` equals `studio-setup.create_accelerated` (`mode ACCELERATED_REPLAY`, `speed ACCELERATED`, `symbols [PETRONET, GRASIM]`, start = end = 2026-11-03 …); then `studio-setup.start`, then POST `/simulations/{new}/run` with no body (`studio-setup.run`, 202); URL `/studio?sim={new}`. Summary rows follow the choices (2 symbols, ₹50.00 L, Assisted, Runs to the end in the background) |
| AD-UI-124 | E | Client validation | Empty name, last session before first, "Your symbols" with none typed, 51 symbols → "Needs …" lists each problem and Create and start is disabled; nothing is POSTed |
| AD-UI-125 | E | Mode chips Scenario simulation / Live shadow | A Phase 3 note (scenario: the API refuses SCENARIO) / Phase 4 note (live shadow) appears under the mode row; Create and start disabled; switching back to Historical replay enables it; no POST |
| AD-UI-126 | E | Create refused by the API (422 `{"error":"INVALID","message":"the NSE holiday list (segment CM) has no rows for 2025"}`) | The API's message shown in the aside; no `/start` POST; URL unchanged |
| AD-UI-127 | E | Created, but start refused (409 "simulation is RUNNING; cannot move to RUNNING") | The message is shown with "Open the run in Trading day ›" linking to `/studio?sim={new}`; POST `/simulations` sent once |
| AD-UI-128 | E+C | `GET /policies` and `GET /agents` fail (500) | ErrorBoxes with the API messages in sections 06 and 05; summary Policy "Account default"; Create and start sends the body without `policy_id` (`studio-setup.create_default_policy`) |
| AD-UI-129 | E | Phone 390×844 | Single column (aside below the sections), no horizontal overflow, Create and start reachable; no console errors |
