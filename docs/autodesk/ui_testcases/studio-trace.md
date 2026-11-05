# Simulation studio · Agent trace — UI test cases (written before the view code)

Design: `docs/autodesk/design/prototype/studio/SimTrace.dc.html`. View: `frontend-v5/src/autodesk/studio/views/Trace.tsx`
(route `/autodesk/studio/trace`, root `data-testid="studio-trace"`). Spec: `frontend-v5/e2e/tests/autodesk-studio-trace.spec.ts`
(route mocks from `autodesk-fixtures-studio-trace.ts`, shapes of the real API). This view sends no POST.

Layer: E = Playwright against the production build with route mocks.

Data sources: the run is `?sim=` (else the newest, `GET /simulations`); `GET /simulations/{sid}/workflows` (its
TRADE_PROPOSAL workflows), `GET /trade-plans?simulation_id=` and `GET /signals?simulation_id=&limit=2000` (names of the
chains), `GET /desk/workflows/{id}` (workflow + full agent_tasks rows + handoffs) for the chain on screen and the cards.

A chain is replayed as messages: the AI Trader's handoff of the signal to the Trading Assistant (from the inbound
handoff + the signal row), then one message per agent task in created order (Trading Assistant → Risk & Operations →
… → Middle Office): who → whom (the task's agent → the receiver of its outbound handoff, else the orchestrator), type
from the task and its structured result, the agent's `result_summary` (or `error`) as written, time, latency, input
refs, the structured output (`result`), tool calls with ms, validation, state and retries, handoff. Reservation,
orders and fills after the approval are Phase 2.

Autoplay as designed (one message every 1.4 s, Pause / Play / ‹ › / Restart); with `prefers-reduced-motion: reduce` the
replay starts paused (the specs use it to step deterministically).

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-UI-150 | E | Run with 7 proposal workflows over 2 sessions at 1280×800 | Eyebrow "Agent trace replay · {sid}", pill "Structured messages only", the design's headline and sub line; task cards for the first six workflows in order (trade id or workflow id, "N STEPS" from the detail, "INSTRUMENT · Strategy", "session · outcome"); the revised ADANIPORTS chain (plan_version 2) is picked by default and highlighted |
| AD-UI-151 | E | Step through the ADANIPORTS chain (reduced motion) | Starts at "STEP 1 OF 6" showing one message "AI TRADER → TRADING ASSISTANT · SIGNAL" with the signal (ADANIPORTS, score); aside "Step 1 · SIGNAL" with the signal's fields; › reveals "TRADING ASSISTANT → RISK & OPERATIONS · PLAN" with the agent's summary as written, its time and latency (572 ms); aside: structured output (decision PLAN, instrument, strategy, max loss), tool calls (market.options ok 412 ms …), Inputs `signal://…`, Validation "Schema ✓ · domain ✓", State COMPLETED · 0 retries, Handoff "Risk & Operations · TRD-…"; the risk REDUCE step shows the amber verdict and the violation; ‹ goes back; clicking a message selects it; progress bar width follows the step |
| AD-UI-152 | E | Last step and Restart | At step 6 (Middle Office NEEDS HUMAN → Orchestrator) the waiting box is gone; the workflow outcome is shown ("Workflow WAITING_HUMAN · WAITING HUMAN …") with a Phase 2 note for reservation, orders and fills; Restart returns to "STEP 1 OF 6" with one message |
| AD-UI-153 | E | Autoplay (no reduced motion) | The replay plays by itself to "STEP 6 OF 6" (Pause shown while playing, then "Replay"); Pause stops it before the end |
| AD-UI-154 | E | Pick other cards | HINDALCO (NO_TRADE at the strategy stage) → 2 steps, the Trading Assistant's "no plan for HINDALCO: …" summary as written; DLF (risk task FAILED with an error) → the FAILED verdict and the error text as written in the message and the aside |
| AD-UI-155 | E | More than six proposals | "Other proposals" select lists every workflow; picking the 7th shows its chain and adds its card |
| AD-UI-156 | E | Empty states | A run with no TRADE_PROPOSAL workflows → "No trade proposals in this run yet …"; no runs → empty state with "New simulation ›" |
| AD-UI-157 | E | Load errors | `GET /simulations/{sid}/workflows` 500 → ErrorBox with the API message; `GET /desk/workflows/{id}` 404 → ErrorBox with "not found: …" |
| AD-UI-158 | E | Phone 390×844 | Single column (aside below the messages), controls wrap, no horizontal overflow, no console errors, no sample ids (SIM-0418, PLN-S-, SCN-, AXISBANK) |
| AD-UI-159 | E | `?sim=` decides the run | Opening `/studio/trace?sim={other}` loads that run's workflows (`GET /simulations/{other}/workflows`) and shows its id in the eyebrow |
