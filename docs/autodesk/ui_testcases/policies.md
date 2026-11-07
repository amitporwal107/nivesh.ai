# Policies & permissions (screen 12) — UI test cases AD-UI-70..79

Design: `docs/autodesk/design/prototype/TDPolicies.dc.html`. Screen: `frontend-v5/src/autodesk/screens/Policies.tsx`.
Spec: `frontend-v5/e2e/tests/autodesk-policies.spec.ts` (route mocks shaped like the real API; fixtures in
`autodesk-fixtures-policies.ts`, marked MOCK). Request contracts: `frontend-v5/e2e/fixtures/autodesk/requests/policies.json`
(posted to the real FastAPI app by `backend/tests/autodesk/test_ui_request_contracts.py`). Written before the screen code.

Layers: **E** = Playwright against the production build with route mocks · **C** = request contract.

Data sources (Phase 1): `GET /policies`, `GET /policies/{id}` (+ `?version=n` for history), `GET /accounts`,
`GET /desk/status` (STOP_NEW_ENTRIES), `GET /api/auth/me` (role). Writes: `POST /accounts/{id}/mode`,
`POST /policies/{id}/versions`, `POST /desk/controls/STOP_NEW_ENTRIES`. Live trading is out of scope: every live
control is shown locked with no action.

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-UI-70 | E | Header | eyebrow "12 · Policies & permissions"; one mint pill per policy "{name} · v{current_version} active"; headline "The most restrictive rule always wins. *Autonomous live* stays locked …"; sub-line computed from the policies (versioned, every change audited, who may loosen) |
| AD-UI-71 | E | "Operating mode by account" | one card per desk account (name, its policy name + version); four options Research / Assisted / Autonomous paper / "Autonomous live · locked"; current mode highlighted mint; note describes what the current mode lets the Middle Office do; Autonomous live has no action; the "AUTONOMOUS LIVE · LOCKED" box lists broker permission, simulator certification, compliance approval and kill-switch drill as not available (owner decision pending) |
| AD-UI-72 | E+C | Switch Desk A from Autonomous paper to Assisted | confirm dialog with a required reason; Confirm sends `POST /accounts/{account_id}/mode` = contract `set_mode_assisted`; the card then shows Assisted highlighted and an "audited" note; the API's 409/422 message is shown in the dialog on failure and the card keeps the old mode |
| AD-UI-73 | E | "Effective policy" table for the selected account | one row per policy limit (risk per trade, open risk, daily/weekly loss, drawdown, instrument and sector caps, margin, reward:risk, credit, signal score, proposals, days to expiry, legs, lots, traded value, data age, traded legs, segments, strategies) with the policy's values; the account's policy in its scope column ("Tenant · v{n}"), other levels "—"; Effective column = the values the risk engine applies; binding level marked; note that the pre-market check narrows the allowed segments to its own list |
| AD-UI-74 | E+C | Edit limits: tighten "Max risk per trade" 0.5 → 0.4 | `POST /policies/{policy_id}/versions` = contract `tighten_limit` (only the changed field, Decimal as string, plus the reason); then v2 is ACTIVE and v1 RETIRED in Version history with the change "Max risk per trade 0.5% → 0.4%" |
| AD-UI-75 | E+C | Loosen as a non-admin / invalid value / nothing changed | 0.5 → 1 sends contract `loosen_limit_needs_admin`; the API's 403 message ("looser than the default needs an admin: per_trade_risk_pct") is shown verbatim in the dialog and no new version appears; a 422 message is shown the same way; Save is disabled while no field differs |
| AD-UI-76 | E+C | Switch off automatic approval | the body carries the WHOLE `autonomy` object (the API merges top-level keys) = contract `autonomy_auto_approve_off`; "What agents may do" then shows APPROVAL for in-rules plans in Auto paper |
| AD-UI-77 | E | "What agents may do on their own", "Who must approve", "Roles and permissions" | matrix rows from the Middle Office rules and the policy's autonomy (auto_approve, max_risk_pct, min_signal_score, strategy list) with AUTO / APPROVAL / NEVER per mode and Auto live LOCKED; position actions shown as a Phase 2 note; thresholds list the real figures (e.g. "Plan risk above 0.5% of equity"); roles table has Account owner and Administrator (the code's two roles) with the signed-in person's role highlighted from `/api/auth/me`, other roles noted as not in Phase 1 |
| AD-UI-78 | E+C | "Emergency controls" | "Stop new entries" card shows OFF / ACTIVE from desk status; Activate… → inline reason → Confirm activate sends contract `stop_entries`; card turns ACTIVE and the shell's banner appears; Lift this control → Confirm lift sends contract `lift_entries`; a failed POST shows the API's message; the other seven controls are shown "NOT AVAILABLE" with no action |
| AD-UI-79 | E | Version history, errors, phone | versions newest first from `GET /policies/{id}?version=n` with ACTIVE / RETIRED pills, dates, the stored reason and the computed field changes; `GET /policies` 500 → ErrorBox with the message; at 390×844 the layout is one column, wide tables scroll inside their box and the page has no horizontal overflow |

| AD-UI-74b | Edit limits: the refreshed list reaches the screen before the save has finished | The dialog closes and does not come back offering the next version; exactly one POST |
