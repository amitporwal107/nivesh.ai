# Test cases: F&O lab backend core (`feat/fno-lab-backend-core`)

Written before implementation. This is backend B1, which makes screens 09 Live and 12 Audit read computed state instead of fixed text.

## Decision snapshot (P0.3, first part)

| ID | Case | Expected |
|---|---|---|
| D-1 | The gate decides any request | The `risk_decisions` row gains `snapshot` with these fields: `request` (the full RiskRequest), `references` (the exchange lot and listed-expiry lookups the decision used, with source and as_of), `controls` (kill switch, halt and reason, or null when unreadable), `live_allowed` (null unless the mode is live), `open_structures` (the count used, null when unreadable, or "n/a"), `today`, plus `snapshot_version: "decision-snapshot-v1"` and `snapshot_hash` (SHA-256 of the snapshot). Every value is BSON-safe: dates are stored as ISO strings. |
| D-2 | Behaviour unchanged | Every existing gate test passes unchanged: the same checks in the same order, the same reasons, and fail-closed on every unreadable input. |
| D-3 | Decision list | `GET /api/risk/decisions` does not return `snapshot` (the list stays small). |

## Replay (P0.3)

| ID | Case | Expected |
|---|---|---|
| R-1 | `POST /api/risk/decisions/{id}/replay` on the user's own decision | 200 with `{replayable: true, match, outcome_then, outcome_now, reasons_then, reasons_now, checks_then, checks_now, inputs_hash_match, snapshot_hash_match, policy_version_then, policy_version_now}`. It writes nothing: the decision count is unchanged. |
| R-2 | The same policy and code | `match: true`; outcomes and reason codes are equal. |
| R-3 | A tampered snapshot | `snapshot_hash_match: false`, and `match` cannot be true. |
| R-4 | A decision recorded before snapshots | `{replayable: false, reason: …}`, not an error. |
| R-5 | Someone else's decision | 404 for a non-admin. An admin may replay any decision. |
| R-6 | Unknown id or no auth | 404 for an unknown id; 401 without a session. |

## Lineage

| ID | Case | Expected |
|---|---|---|
| L-1 | `GET /api/risk/decisions/{id}/lineage` | 10 steps in order: market_snapshot, instrument_master, regime, agent_proposal, schema_check, pricing_margin, risk_decision, certification, oms, audit_record. Each step has a status (recorded, not_recorded or not_reached), a ref and a detail. Instrument master is recorded when the snapshot has references. Schema check and pricing come from the stored checks. OMS is recorded when an `oms_orders` row carries this risk_decision_id. Certification is not recorded (none exists). The market price snapshot is not recorded (P0.3). |
| L-2 | Access | The same rules as R-5 and R-6. |

## Live readiness (PRD §21)

| ID | Case | Expected |
|---|---|---|
| G-1 | `GET /api/risk/live-readiness` | 12 conditions in PRD order, each with `{id, label, status (pass/fail), evidence, backlog}`, plus `enforceable` (the count of passes) and `live_execution_available`. With no order adapter and no certification, every row is `fail` and `enforceable: 0`. |
| G-2 | Live state | Row 5 states whether the gate is on for the user; row 6 states the feed session and data time; row 9 states whether live authorization is granted; row 11 states the kill switch. These are read from the same sources as `/api/risk/status` and the live feed status. |
| G-3 | Unreadable state | Any read failure gives `fail` with "could not be read", never pass. 401 without a session. |

## Screens

| ID | Case | Expected |
|---|---|---|
| UI-1 | Live Desk | The rows come from `/api/risk/live-readiness`. If it fails, the error says so; the rows are not filled with fixed text. |
| UI-2 | Audit lineage | Each step's status comes from `/lineage`. |
| UI-3 | Audit replay | "Replay from snapshot" is shown for decisions with a snapshot. It shows match or mismatch, and the then/now outcome and reasons. A decision without a snapshot shows the route's reason. |

## Verification plan
- Backend: pytest covering D, R, L and G, plus the existing gate and risk route suites, in a throwaway container.
- Frontend: tsc, plus the governance Playwright spec updated for UI-1 to UI-3.
- Staging, after the merge and a restart: G-1 and G-2 with the admin and normal sessions. For R and L: with `fno_risk_gate` on the allowlist for the admin, create one paper structure (as in the Sprint 1 check), then call lineage and replay on that decision. Restore the flag afterwards.
