# Test cases — Risk Control Center (Desk › More › Risk controls), PR D

- **Branch:** feat/risk-control-center (from origin/dev b74c7f4f)
- **Date:** 2026-10-24
- **Authored:** before implementation, after the API contract and UI layout were fixed.
- **Changed areas:** frontend only (frontend-v5). The backend routes (`/api/risk/status`, `/kill-switch`, `/halt`,
  `/policy`, `/audit`, `/decisions` and the 409 gate) come from the parallel backend PR (feat/fno-risk-foundation).
- **How they run:** `frontend-v5/e2e/tests/copilot-app-desk-risk-controls.spec.ts` against a production build with
  every `/api/*` route mocked (MOCK — not real data). The writeProblem case (TC-13) runs in
  `copilot-app-desk-scanner.spec.ts` beside the existing 409 test, because that spec already mocks the Chart tab's
  paper action.

## Contract under test (mocked)
- `GET /api/risk/status` → `{user_id, kill_switch, halted, reason, set_by, set_at, policy_version, scope, not_in_scope,
  can_reset, live_authorization{granted, granted_by, granted_at, reason}, modes[], live_execution_available, gate{enabled, policy_version}}`
- `PUT /api/risk/kill-switch`, `PUT /api/risk/halt` ← `{enabled, reason}`; 403 `{detail:{code:"admin_required"}}`; 422 `invalid_input`
- `GET /api/risk/policy` → `{policy_version, limits{max_legs, max_lots_per_leg, max_open_structures, max_capital_at_risk_rs, require_defined_risk}, usage{open_structures, capital_at_risk_rs}}`
- `GET /api/risk/audit?limit=` → `{events[], count, append_only}`; `GET /api/risk/decisions?limit=` → `{decisions[], count}`
- Paper write blocked: 409 `{detail:{code:"risk_blocked", reasons[{code,message}], decision_id, correlation_id}}`; legacy 409 `{detail:{code:"risk_blocked", reason, set_by, message}}`

## Test cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | Nav | More lists "Risk controls"; clicking it opens `?tab=more&view=risk`; the chip is pressed; the Copilot chip is not | e2e | `desk-panel-risk` (tabpanel "Risk controls") renders `risk-controls`; URL carries `view=risk` |
| TC-2 | Status off | kill_switch false, halted false | e2e | "Off" / "Not halted" in words and pills; "Paper" active; "Shadow / Assisted / Live: not available"; live authorization "Not authorized" |
| TC-3 | Status on | kill_switch true with reason, set_by, set_at; live authorization granted | e2e | "On" with the reason, who set it and when (IST); "Authorized by <granted_by>" |
| TC-4 | Trip | "Turn kill switch on" → reason → confirm → yes | e2e | exactly one `PUT /api/risk/kill-switch` with `{enabled:true, reason}`; Cancel at either step sends nothing; status re-read after success |
| TC-5 | Reset | can_reset true → "Turn kill switch off" → reason → confirm | e2e | one `PUT …/kill-switch` `{enabled:false, reason}`; with can_reset false the button is absent and "Only an admin can turn the kill switch off" is shown |
| TC-6 | Halt | same pattern on the halt | e2e | `PUT /api/risk/halt` `{enabled:true, reason}`; can_reset false → "Only an admin can lift the halt" |
| TC-7 | Policy | limits with usage | e2e | rows for legs, lots per leg, open structures (limit, used, remaining), capital at risk (₹ limit, used, remaining), defined risk only (Yes/No); gate.enabled false → "Gate off for your account" |
| TC-8 | Decisions | three rows given oldest-first, one with string reasons, one with an old outcome value | e2e | newest first; outcome in words (Allowed / Blocked / the old value as given); path, symbol, reasons; correlation id in a monospace element |
| TC-9 | Audit | two events | e2e | newest first; actor, "Kill switch: off → on", reason, policy version; append-only said |
| TC-10 | Trust | status and policy loaded | e2e | TrustLine "Risk controls · … · risk-controls-v1" |
| TC-11 | Scope | not_in_scope present | e2e | the route's `not_in_scope` sentence is visible |
| TC-12 | Header pill | status kill_switch true | e2e | "Kill switch on" pill in the desktop top bar and the phone header; clicking opens `view=risk`; a body without a boolean kill_switch (the catch-all `{}`) shows no pill |
| TC-13 | Gate 409 | a paper add answers 409 risk_blocked (gate shape), then the legacy kill-switch shape | e2e | the reasons in plain words, pointing to "Desk › More › Risk controls", code shown; legacy: the message and the stored reason |
| TC-14 | Empty | no decisions, no audit events | edge | "No risk decisions yet" / "No control changes yet"; nothing invented |
| TC-15 | Unknown shape | status `{}`; policy without usage | edge | status card says the state is unknown (never "Off"); trip/reset controls not offered; used/remaining "—" |
| TC-16 | Long text | 500-character reason and a long correlation id at 390px | edge | text wraps; no sideways page scroll |
| TC-17 | Old outcomes | outcome "allowed" / "reduced" | edge | shown in words / as given, neutral tone, not coerced to Blocked |
| TC-18 | Status 503 | `GET /api/risk/status` 503 | failure | error block with Retry; no controls; never claims the switch is off |
| TC-19 | Status 500 | `GET /api/risk/status` 500 | failure | same as TC-18 |
| TC-20 | 403 | reset answers 403 `admin_required` | failure | "Only an admin can turn this off. (admin_required)" in the confirm's error; confirm stays open |
| TC-21 | 422 | empty reason; server 422 `invalid_input` | failure | empty reason is refused in the form with no PUT; a server 422 shows the server's words with `(invalid_input)` |
| TC-22 | Part failure | policy / audit / decisions 500 | failure | each card shows its own error; the status card still works |
| TC-23 | Keyboard | Tab to "Turn kill switch on", Enter, type, Enter on Continue, Enter on confirm | a11y | the whole trip flow works from the keyboard; focus moves into the reason field |
| TC-24 | Labels | reason field, buttons, states | a11y | the reason textarea has a label; outcomes are words, not colour only; done/error use role status/alert |
| TC-25 | Phone | 390px risk view | e2e | panel renders with Widgets; no sideways scroll |
| TC-26 | Types | `tsc --noEmit` | unit | 0 errors |
| TC-27 | Regression | desk specs (lab, scanner, portfolio-fno, strategy-builder, desk) | regression | pass, or failures proven pre-existing on an untouched origin/dev copy |

## DONE-GATE
TC-1…TC-27 pass locally (real tsc and Playwright output in the report). Staging render is blocked on the backend PR
being merged and deployed plus a user session; that is recorded in `test_reports/OVERRIDE_risk_control_center.md`.

## Results (local, mocked APIs; see OVERRIDE_risk_control_center.md for the run lines)
TC-1…TC-12, TC-14…TC-25: PASS in copilot-app-desk-risk-controls.spec.ts (RC-1…RC-15, 17 tests). TC-13: PASS in
copilot-app-desk-scanner.spec.ts ("TC-23 a 409 risk_blocked names what blocked it…"). TC-26: tsc exit 0. TC-27: 326
passed, 16 skipped, 0 failed across the affected desk specs; baseline on untouched origin/dev 255 passed, 0 failed.
Staging: not run (backend PR not deployed, no session) — recorded as an override.
