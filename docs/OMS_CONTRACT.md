# OMS contract (`oms-contract-v1`)

The order lifecycle that every future execution path must use: the paper path first, and later the Kite Connect adapter for live execution. Code: `backend/services/oms/`. Tests: `backend/tests/test_oms_contract.py`.

**Status:** contract only. No route calls it yet, no broker adapter exists, and live orders are refused.

## States (PRD §12.1)
`CREATED → VALIDATED → AUTHORIZED → SUBMITTED → ACKNOWLEDGED → PARTIALLY_FILLED → FILLED`, plus `REJECTED`, `CANCEL_PENDING`, `CANCELLED`, `EXPIRED`, `UNKNOWN` and `RECONCILIATION_REQUIRED`.

- **Terminal states:** `FILLED`, `REJECTED`, `CANCELLED` and `EXPIRED`.
- **`UNKNOWN` → `RECONCILIATION_REQUIRED` only.** An order whose fate is unknown is reconciled against the broker, never resubmitted.
- **`CANCEL_PENDING` can still fill.** A cancel races the exchange.
- **Self-transitions:** only `PARTIALLY_FILLED → PARTIALLY_FILLED` (another fill) is allowed.
- **Everything else is refused** with `IllegalTransition`. The full table is `TRANSITIONS` in `states.py`.

## Order document (`oms_orders`)
| Field | Meaning |
|---|---|
| `_id` | Order id (uuid) |
| `user_id`, `client_order_id` | Idempotency key, unique per user |
| `mode` | `paper` or `shadow` when created; `live` is refused |
| `legs` | What was asked for |
| `fingerprint` | sha256 of mode and legs, used to tell a replay from a different request |
| `state`, `history[]` | Current state, and every change with time, actor and note |
| `correlation_id`, `risk_decision_id` | Links to the request and to the risk decision that allowed it |
| `broker_order_id` | Reserved for the broker adapter |
| `contract_version`, `created_at`, `updated_at` | |

## Rules
- **Idempotency:** the same `client_order_id` with the same request returns the first order (`created: false`). The same key with a different request raises `IdempotencyConflict`.
- **Compare-and-set:** `transition` writes only if the order is still in the state it read. Otherwise it raises `StaleOrderState` and writes nothing.
- **Indexes:** call `ensure_indexes(db)` before use. It creates a unique `(user_id, client_order_id)` index, `(user_id, created_at)`, and `correlation_id`.
