# Simulation studio · Run history — UI test cases (written before the view code)

Design: `docs/autodesk/design/prototype/studio/SimRuns.dc.html`. View: `frontend-v5/src/autodesk/studio/views/Runs.tsx`
(route `/autodesk/studio/runs`, root `data-testid="studio-runs"`). Spec: `frontend-v5/e2e/tests/autodesk-studio-runs.spec.ts`
(route mocks from `autodesk-fixtures-studio-runs.ts`, shapes of the real API). This view sends no POST.

Layer: E = Playwright against the production build with route mocks.

Data sources: `GET /simulations` (the studio's list, newest first), `GET /policies` (policy names),
`GET /simulations/{sid}/results` for runs A and B (counters), and for the decision comparison of A and B:
`GET /simulations/{sid}/workflows` (TRADE_PROPOSAL workflows: session, input.signal_id, outcome result / trade_id /
plan_version), `GET /trade-plans?simulation_id=` (instrument, strategy), `GET /signals?simulation_id=&limit=2000`
(instrument, direction, category, session).

Phase 1 truth: runs record signals, plans, risk reports and approvals — no trades, fills, P&L, drawdown, win rate or
slippage (Phase 2) and no assertions (scenarios, Phase 3). "Where the two runs decided differently" is computed from
the two runs' records on the sessions both replayed: per session the signal count and the signals only one run found,
and per instrument the proposal (only in one run), the strategy, the outcome and the plan revisions.

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-UI-140 | E | Three runs (B newest: same sessions 2–3 Nov and seed 42 as A; C older on 29–30 Oct, seed 7, accelerated) at 1280×800 | Eyebrow "Run history", pill "3 runs · newest first"; table header A · B, Run, Type · session, Policy · seed, Status, Trades, Net P&L, Max DD, Assertions; rows newest first with id, when (IST), type (Historical / Accelerated replay), range (2 Nov – 3 Nov), policy name and version from `GET /policies` + `versions.policy`, "SEED 42 · STEP", status pill; Trades / Net P&L / Max DD / Assertions cells "—" and a Phase 2 note under the table; default B = the newest run, A = the most recent other run with the same sessions and seed (A and B buttons pressed); no console errors |
| AD-UI-141 | E | Comparison of the like-for-like pair | Title "{A} (Desk default v1) against {B} (Desk default v2)", pill "SAME SESSIONS · SAME SEED", headline "{A} against {B}: 6 differences in what the agents decided."; measures A · B · B − A from `/results`: Signals 7 · 6 · −1, Trade plans 4 · 4 · 0, Proposals rejected 0 · 0 · 0, Approved 4 · 3 · −1, Human approvals 0 · 1 · +1, Agent task failures 0 · 0 · 0, Policy violations 0 · 0 · 0; Trades / Net P&L after costs / Max drawdown / Win rate / Slippage paid show "—" and "Phase 2", Assertions "—" and "Phase 3"; the net P&L chart place is a Phase 2 note; no ₹ figure anywhere in the comparison |
| AD-UI-142 | E | "Where the two runs decided differently" | Rows (session, text, tag) in order: 2 Nov ADANIPORTS strategy (bull call spread vs bull put spread) · STRATEGY; 2 Nov GRASIM outcome (A approved it, B sent it to a person) · OUTCOME; 2 Nov HINDALCO only B proposed (made no plan) · B ONLY; 3 Nov signals A 3, B 2 · −1; 3 Nov signals only A found: DLF · A ONLY; 3 Nov TATASTEEL plan revisions v1 vs v2 · REVISIONS |
| AD-UI-143 | E | Pick A = run C (different sessions and seed) | A button of C pressed; pill "DIFFERENT INPUTS"; headline "These two runs are not like for like. Read the differences with care."; diff row "Different sessions: there is no decision-by-decision match to show."; metrics show C's counters |
| AD-UI-144 | E | Same sessions and identical decisions | Diff list says "No differences: on every session both runs found the same signals and made the same proposals with the same outcome."; headline "… the same decisions on every shared session." |
| AD-UI-145 | E | Only one run / no runs | One run: table with one row; the comparison area says a second run is needed with "New simulation ›" (keeps `?sim=`); no runs: empty table text and the same link |
| AD-UI-146 | E | Load errors | `GET /simulations` 500 → ErrorBox with the API message; `GET /simulations/{B}/results` 500 → ErrorBox in the comparison with the message, the table still shows |
| AD-UI-147 | E | `?sim=` picks B; a RUNNING run (results null) | With `?sim={A}` B defaults to A's row and A to B's like-for-like partner; a RUNNING row shows the indigo RUNNING pill and its counters come from `GET /results` |
| AD-UI-148 | E | Phone 390×844 | No horizontal overflow of the page (the table scrolls inside its box), comparison single column; no console errors; no sample ids (SIM-0416/0417/0418, P-PAPER, SCN-) |
