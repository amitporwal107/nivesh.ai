# Simulation studio · Scenario library — UI test cases (written before the view code)

Design: `docs/autodesk/design/prototype/studio/SimScenarios.dc.html` (inside the studio frame).
View: `frontend-v5/src/autodesk/studio/views/Scenarios.tsx` (+ `views/scenarios/`). Route `/autodesk/studio/scenarios`.
Spec: `frontend-v5/e2e/tests/autodesk-studio-scenarios.spec.ts` (route mocks from `autodesk-fixtures-studio-scenarios.ts`).

Layer: E = Playwright against the production build with route mocks.

Phase 1 truth: the desk API cannot run scenarios. `SimulationConfig` refuses `mode: "SCENARIO"` with 422 ("SCENARIO
simulations are Phase 3 and not available yet"); there is no scenario catalogue, schedule or injection endpoint. The
design's catalogue (ids, severities, PASS / FAIL results, schedule) is sample content and is not shown. The page keeps
the design's structure — header, "Schedule for the next run" (09:15 → 15:30), the library by category, the builder —
and fills the library with the kinds of shock the PRD plans (PRD v2.0 §31 scenario library, §20.1 required failure
scenarios), labelled as planned for Phase 3. Nothing is sent: the only request is the studio frame's `GET /simulations`.

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-UI-130 | E | `/studio/scenarios` at 1280×800 | Eyebrow "Scenario library"; pill "{n} planned kinds · 3 categories" (n = the kinds listed); amber pill "Nothing scheduled · Phase 3"; the design's headline "Each scenario names the shock and the behaviour it must produce."; the sub line says scenario runs come in Phase 3 and the API refuses a SCENARIO run today |
| AD-UI-131 | E | "Schedule for the next run" | Amber-bordered block with "09:15 → 15:30" and the axis ticks 09:15 … 15:15; no scheduled diamond, no row with Remove; an empty line "Nothing is scheduled" and a Phase 3 note |
| AD-UI-132 | E | Library | Three categories in the design's order: Market, Execution, Operational; each card shows the PRD section it comes from, "PHASE 3", the kind's name, the behaviour it must produce and a "PLANNED" pill; no SCN- id, no severity HIGH / MEDIUM, no PASS / FAIL / WARN result, no SIM- run id |
| AD-UI-133 | E | Builder | Shows the selected kind (first by default); clicking another card (or Enter on it) selects it and the builder follows; INJECT AT time chips and the add button are disabled; the button reads "Scenario runs come in Phase 3"; clicking it sends nothing (no POST, no request beyond `GET /simulations`) |
| AD-UI-134 | E | Way out | "Replay a past session instead" links to `/studio/new` and keeps `?sim=` |
| AD-UI-135 | E | Phone 390×844 | Library and builder in one column (builder not sticky), cards one per row, no horizontal overflow |
| AD-UI-136 | E | No sample data, wording, hygiene | None of the design's sample ids or results appear (SCN-001…SCN-015, SIM-0412, SIM-0418, "PASS · ", "FAIL · RETRY BUDGET", "WARN · 2.4 s", "SCHEDULED 6 NOV"); explanatory text uses none of: buy, sell, stop loss, SL, target, entry, accumulate, book profit, upside, price target, recommend, pick; no console errors; every API call matched a mock |
| AD-UI-137 | E | Independent of the run list | With `GET /simulations` answering 500 the library, schedule and builder still render (the page needs no run data) |
