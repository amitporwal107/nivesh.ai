# Test cases — F&O risk foundation (PR A)

- **Branch:** feat/fno-risk-foundation (from origin/dev b74c7f4f)
- **Authored:** 2026-10-24, before implementation
- **Scope:** OpenAlgo removal + order-path guard, execution modes and live authorization, kill-switch authority and
  admin routes, the shared risk gate (`services/risk_gate/`), its wiring behind `fno_risk_gate`, and the journal
  `add_fill` security fix.
- **Where they run:** pytest in a throwaway container from `nivesh/backend:staging`, tree mounted read-only, no
  network. Staging API cases need a merge to dev, a backend restart and a session token (see
  `OVERRIDE_fno_risk_foundation.md`).

## OpenAlgo removal and the order-path guard

| ID | Type | Case | Expected |
|----|------|------|----------|
| OA-1 | unit | `server.py` and `routes/` after the removal | no `openalgo_proxy` module, no `/api/openalgo` mount |
| OA-2 | api | POST `/api/broker/connect`, POST `/api/broker/connect-hosted`, GET `/api/broker/openalgo-config` | not routed (404/405); nothing written |
| OA-3 | api | POST `/api/broker/accounts/{id}/sync` on a legacy OpenAlgo row | 400 `BROKER_READ_NOT_SUPPORTED`; holdings and the row untouched; no broker or OpenAlgo call |
| OA-4 | api | live holdings / positions / funds with a legacy OpenAlgo row present | that row listed as not supported, native rows read (existing suites) |
| OA-5 | api | DELETE an OpenAlgo row and a native row | 200 each; no instance stop is attempted; audit has no `instance_stopped` |
| OA-6 | unit | a native stub broker's error message | no longer points to `/api/broker/connect-hosted` |
| OA-7 | edge | OpenAlgo refusal of sync with `broker_hub` off or unreadable | same 400; the flag is not consulted |
| OA-8 | unit | tracked `openalgo_instances/ba_723fd208d615/*` | removed from git (checked with `git ls-files`) |
| G-1 | unit | AST scan of `backend/` (tests excluded) for calls to place_order / modify_order / cancel_order / place_gtt / modify_gtt / cancel_gtt | none outside `services/oms/adapters/` |
| G-2 | unit | the scanner on a planted snippet (`kite.place_order(...)`, `getattr(k, "cancel_gtt")(...)`) | both reported; the same snippet under `services/oms/adapters/` is allowed |
| G-3 | unit | AST scan for route decorators with a `{...:path}` catch-all | none, except the named admin Grafana proxy allowlist entry |
| G-4 | unit | the catch-all scanner on a planted `@router.api_route("/{path:path}")` | reported |
| G-5 | edge | the scan finds the files it claims to scan | a path typo fails the test instead of scanning nothing |

## Execution modes and live authorization (`services/execution_modes.py`)

| ID | Type | Case | Expected |
|----|------|------|----------|
| EM-1 | unit | constants | `MODES == ("paper","shadow","assisted","live")`, `LIVE_EXECUTION_AVAILABLE is False` |
| EM-2 | unit | `read_live_authorization` for a user with no row | `granted: False`, `stored: False` |
| EM-3 | unit | `set_live_authorization` with an empty / blank reason, either direction | refused, nothing written |
| EM-4 | unit | grant then revoke | each change appends to `risk_control_audit` with `field: "live_authorization"`, before, after, actor, reason; the row holds `{user_id, granted, granted_by, reason, at}` |
| EM-5 | unit | `is_live_allowed` with a granted row while `LIVE_EXECUTION_AVAILABLE` is False | False |
| EM-6 | unit | `is_live_allowed` with availability forced True | False without a grant, True with one |
| EM-7 | failure | `is_live_allowed` on an unreadable store (availability forced True) | False |
| EM-8 | edge | "restart": reload the module after a grant | still not live: the constant is back to False and nothing in memory grants it |

## Kill-switch authority, status, admin routes, indexes

| ID | Type | Case | Expected |
|----|------|------|----------|
| KS-1 | api | non-admin PUT `/api/risk/kill-switch` `{enabled: true, reason}` | 200, switch on, audit actor = the session user |
| KS-2 | api | non-admin PUT `/api/risk/kill-switch` `{enabled: false, reason}` | 403 `{"code": "admin_required"}`; state unchanged; no audit row |
| KS-3 | api | the same two cases on `/api/risk/halt` | on 200, clear 403 `admin_required` |
| KS-4 | api | admin clears their own switch on `/api/risk/kill-switch` | 200 |
| KS-5 | api | advisor impersonating a client (`_session_user_id` ≠ `user_id`) sets the switch | control stored on the client, audit actor = the advisor's session id |
| KS-6 | api | GET `/api/risk/status` | existing keys plus `can_reset`, `live_authorization`, `modes`, `live_execution_available`, `gate: {enabled, policy_version}` |
| KS-7 | api | non-admin on PUT `/api/admin/risk/{uid}/kill-switch`, `/halt`, `/live-authorization` | 403 for all three; nothing written |
| KS-8 | api | admin on the three admin routes | 200; control / authorization stored on the target user; audit actor = admin |
| KS-9 | api | admin routes without a reason, without `enabled`/`granted`, non-bool value, unknown user | 422, 422, 422, 404; nothing written |
| KS-10 | api | admin grants live authorization | status shows `granted: true` while `live_execution_available` stays false; the gate still blocks `live` |
| KS-11 | unit | `ensure_indexes` | risk_controls user_id unique; risk_control_audit (user_id, at); risk_decisions (user_id, at) and correlation_id; live_authorizations user_id unique; created once; a failure is logged and retried |
| KS-12 | api | GET `/api/risk/policy` | `{policy_version: "fno-risk-v1", limits, usage: {open_structures, capital_at_risk_rs}}` from the user's open desk structures |
| KS-13 | api | every `/api/risk/*` and `/api/admin/risk/*` route without a session | 401 |

## Shared risk gate (`services/risk_gate/`)

| ID | Type | Case | Expected |
|----|------|------|----------|
| RG-1 | unit | a bull call spread, 1 lot, exchange lot and expiry verified, paper mode | `allow`; every check `pass`; one `risk_decisions` row with correlation_id, path, mode, inputs_hash, reasons, policy_version |
| RG-2 | unit | kill switch on / halt on | `block` `kill_switch_on` / `trading_halted` |
| RG-3 | failure | controls store unreadable | `block` `controls_unreadable` |
| RG-4 | unit | mode `shadow`, `live`, `nonsense` | `block` `mode_not_allowed`, `live_execution_unavailable`, `mode_unknown` |
| RG-5 | unit | structure with no legs; unknown leg kind; fractional lots; option without strike; unknown path / action / instrument; cash with fractional quantity | `block` with the specific `structure` code each time |
| RG-6 | unit | naked short call; naked short put; futures only; long future + short call; options on two expiries | `block` `naked_short_call`, `naked_short_put`, `futures_only`, `unhedged_future`, `mixed_expiries` |
| RG-7 | unit | long future + long put of the same size and expiry | defined-risk check `pass` |
| RG-8 | failure | exchange lot unknown; lot differs from the exchange lot | `block` `lot_size_unverified`; `lot_size_mismatch` |
| RG-9 | failure | expiry unverifiable; not listed on the latest day; in the past | `block` `expiry_unverified`; `expiry_not_listed`; `expiry_past` |
| RG-10 | unit | 5 legs; 11 lots on a leg; capital at risk above ₹2,00,000; cash request with no capital figure | `block` `too_many_legs`, `lots_per_leg_exceeded`, `capital_at_risk_exceeded`, `capital_at_risk_unknown` |
| RG-11 | unit | 10 open structures already; open-structure count unreadable | `block` `open_structures_exceeded`; `open_structures_unverified` |
| RG-12 | failure | the decision write fails | `DecisionUnrecorded` raised, no decision returned (route answers 503) |
| RG-13 | unit | allow and block both persisted | one row per call, outcome `allowed` / `blocked` |
| RG-14 | unit | capital at risk: bull call spread, long straddle, iron condor (worked by hand in the test) | debit × qty; both premiums (not 0); wing width − credit |
| RG-15 | unit | inputs_hash | same inputs → same hash, correlation_id excluded, any input change → different hash |
| RG-16 | unit | contract reference: in-process Kite NFO list loaded today; DaaS bhavcopy fallback; bhavcopy older than the age limit; DaaS error; DaaS not configured | Kite list used without a network call; bhavcopy lot read; stale → unverified; error → unverified; not configured → unverified |
| RG-17 | unit | check order | `checks[]` in the fixed order controls, mode, structure, defined_risk, lot_size, expiry, caps, open_structures |
| RG-18 | unit | legacy `record_decision` | signature unchanged and still returns None on a failed write (other callers) |

## Wiring behind `fno_risk_gate`

| ID | Type | Case | Expected |
|----|------|------|----------|
| W-1 | api | flag off: desk create, journal create, AI-trader signals and confirm | behaviour unchanged (existing suites pass); no gate decision row; no correlation fields on documents |
| W-2 | api | flag on: desk cash paper trade | 201; document carries `correlation_id` (the X-Correlation-ID sent) and `risk_decision_id`; the decision row exists with path `desk_paper_trade` |
| W-3 | api | flag on: desk strategy trade that the desk accepts but the gate refuses (futures only) | 409 `{code: "risk_blocked", reasons, decision_id, correlation_id}`; no trade, no paper reservation |
| W-4 | api | flag on: kill switch on | 409 in the gate's shape; the decision row exists |
| W-5 | failure | flag on: decision write fails | 503 `{code: "risk_decision_unrecorded"}`; no trade, no reservation |
| W-6 | api | flag on: strategy trade with an unverifiable lot | 409 with `lot_size_unverified` |
| W-7 | api | flag on: journal create allowed / above the capital cap | 200 with `correlation_id` and `risk_decision_id` / 409 `capital_at_risk_exceeded`, nothing written |
| W-8 | api | flag on: journal ENTRY fill gated (blocked → 409, nothing pushed); EXIT fill not gated | as stated |
| W-9 | api | flag on: AI-trader signals allowed / kill switch on | tickets and trades carry both ids / 409, no ticket, no trade |
| W-10 | api | flag on: AI-trader confirm allowed / blocked | trade carries both ids / 409, ticket stays `awaiting_confirmation`, no trade |
| W-11 | unit | `enabled_for` | allowlist per user; under impersonation the session owner's email decides; a failed flag refresh keeps this worker's copy |
| W-12 | unit | correlation id with no middleware | a fresh uuid hex |
| W-13 | unit | `fno_risk_gate` in KNOWN_FEATURES | modes off / allowlist / everyone, default off |

## Security fix (regardless of the flag)

| ID | Type | Case | Expected |
|----|------|------|----------|
| S-1 | api | `add_fill` on another user's trade | 404; nothing written |
| S-2 | api | `add_fill` on a CLOSED or STOPPED trade | 409 `trade_not_open`; nothing written |
| S-3 | unit | the update filter `add_fill` sends | contains `user_id` and `status: "OPEN"` |
