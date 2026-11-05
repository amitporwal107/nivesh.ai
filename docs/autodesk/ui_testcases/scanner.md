# 03 · Opportunity scanner — UI test cases (AD-UI-40..49)

Written 5 Nov 2026 before the screen code. Design: `docs/autodesk/design/prototype/TDScanner.dc.html`. Screen:
`frontend-v5/src/autodesk/screens/Scanner.tsx` (route `/autodesk/scanner`). Spec: `frontend-v5/e2e/tests/autodesk-scanner.spec.ts`
with fixtures in `autodesk-fixtures-scanner.ts` (MOCK — shapes of the real API: `backend/autodesk/routers/api.py`, the
`Signal` model in `backend/autodesk/contracts.py`, rows of `autodesk.signals`, `autodesk.trade_plans`,
`autodesk.approvals`, `autodesk.workflows`). Request contracts: `frontend-v5/e2e/fixtures/autodesk/requests/scanner.json`.

Layers: E = Playwright on the production build with route mocks; C = request contract (the body the UI sends is checked
against scanner.json, and the backend test posts it to the real FastAPI app).

Data: the latest desk `SESSION_CYCLE` of the chosen desk account (`GET /desk/workflows?account_id=…&kind=SESSION_CYCLE`;
its `outcome.scan` gives universe, scanned, published; `outcome.proposals` the proposal results), the session's signals
(`GET /signals?account_id=…&session_date=…`), plan status (`GET /trade-plans?account_id=…`, matched on `signal_id`), the
latest approval per plan (`GET /approvals`, desk rows only), the policy minimum score (`GET /policies/{id}?version=` pinned
in the cycle input), stored-signal count of the scan task (`GET /agents/AI_TRADER/activity`, `result_ref`).

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-UI-40 | E | Header from real data | eyebrow "03 · Opportunity scanner"; "AI Trader · idle" pill (status from desk status) and the rule pill "autodesk-ait-v1 · ait-rules-v1" from the signals' `model_version`; headline "Five signals cleared the line for 5 Nov. *One* is already a plan waiting on you." (count of session signals at or above the policy minimum; count of signals whose latest approval is NEEDS_HUMAN_APPROVAL); the design's sub line saying the score is not a probability |
| AD-UI-41 | E | Six scanner statistics | Universe 224 (F&O underlyings), Coverage 98.7% with "3 symbols missing data" (scanned 221 of 224), Published 174, "Score 60+" = session signals ≥ the policy's `min_signal_score`, Duplicates suppressed = published − stored (`result_ref` "signals=N"), Expired unused = signals past `expires_at` with no plan (0 at 11:42 IST, 6 after the 15:30 close) |
| AD-UI-42 | E | Ranked signal rows | one row per session signal in score order: rank, instrument, "segment · timeframe", direction pill (bullish mint / bearish danger / neutral ink), score + bar, Calibrated P "—" / "Not calibrated", entry zone → invalidation, levels, confirmation = the derivatives (else volume) dimension detail as the agent wrote it, age · expiry (IST), status: Approved · APR…, In approval · APR…, Rejected · APR…, No plan (NO_TRADE), Watch only |
| AD-UI-43 | E | Expand a row | "Score breakdown · {score} of 100" with the eight dimensions (Trend confirmation … Liquidity) as points/weight, an unavailable dimension shown as "—/weight · missing input"; evidence chips (category, sector, F&O eligibility), the evidence sentences, missing inputs, reference close + liquidity, the history Phase 2 note; provenance: signal id, data as of, model, rules, session, expiry, workflow and task ids; "Open approval ›" goes to /autodesk/approvals/{approval_id}; clicking the row again closes it |
| AD-UI-44 | E | Filters | Direction (All / Bullish / Bearish), Segment (All / Cash / Fut / Opt / Idx), Min score (Any / 60 / 70) narrow the rows on screen; no match → "No signal matches these filters." |
| AD-UI-45 | E+C | Run session cycle | POST /desk/workflows with exactly `{kind: "SESSION_CYCLE", account_id}` (contract `scanner.run_session_cycle`); 202 RUNNING → "running" status and the AI Trader pill shows scanning; the UI polls GET /desk/workflows/{id} until the state leaves RUNNING, then shows the outcome (state, result, proposed count) and reloads the signals |
| AD-UI-46 | E | Run session cycle failures | 409 `{"detail": "already running"}` → the API's message in an alert; 422 `{"error": "INVALID", …}` → its message; a 202 that returns an already finished cycle → "already ran for this session" note; the rows on screen do not change |
| AD-UI-47 | E | No account, no cycle, Stop new entries | no desk account → the button is disabled with the reason; no cycle for the account → empty state saying a person starts the cycle; STOP_NEW_ENTRIES active → the design's red banner and a note that the cycle still scans while proposals are held back; workbench actions (plan in revision / risk review) read "Entries stopped" and are disabled, "Open approval" stays enabled; without the stop "Revise in workbench ›" opens /autodesk/workbench |
| AD-UI-48 | E | API errors and honesty | signals 500 → error box in place of the rows; cycles 500 → error box; plans 500 → status column "Status unavailable" plus an error box; signal history shows the Phase 2 note and no hit rates; none of the prototype's sample ids or figures (SIG-10251, APR-3106, TRD-1189, "712", "99.1%", "0.57", "n = 412", signal-v1.4) appear |
| AD-UI-49 | E | Phone 390×844 | rows become cards (rank, instrument, score, direction, entry → invalidation, levels, calibrated P, age · expiry, status); tapping a card shows the dimensions and the action; the run button is reachable; no horizontal overflow |
