# OMS contract — test cases (written before implementation)

Scope:
- `backend/services/oms/states.py`: the order state machine from PRD §12.1.
- `backend/services/oms/orders.py`: an idempotent order store.

Nothing calls a broker, and no route is added. Live mode is refused.

| ID | Type | Case | Expected |
|---|---|---|---|
| OMS-1 | unit | Every PRD §12.1 state exists | 13 states: CREATED … RECONCILIATION_REQUIRED |
| OMS-2 | unit | Happy path CREATED → VALIDATED → AUTHORIZED → SUBMITTED → ACKNOWLEDGED → PARTIALLY_FILLED → FILLED | each step allowed |
| OMS-3 | unit | Terminal states (FILLED, REJECTED, CANCELLED, EXPIRED) have no way out | every transition from them refused |
| OMS-4 | unit | UNKNOWN can only go to RECONCILIATION_REQUIRED, never back to SUBMITTED | no blind resubmission (PRD §14.3) |
| OMS-5 | unit | CANCEL_PENDING can still see a fill (PARTIALLY_FILLED / FILLED) | allowed: cancel races fill |
| OMS-6 | unit | Skipping states (CREATED → SUBMITTED) | `IllegalTransition` |
| OMS-7 | unit | PARTIALLY_FILLED → PARTIALLY_FILLED (another fill) allowed; any other self-transition refused | as stated |
| OMS-8 | unit | Unknown state name | `IllegalTransition` |
| OMS-9 | integration | `create_order` stores state CREATED, a history entry, correlation id, risk decision id, mode and `broker_order_id = None` | doc as stated |
| OMS-10 | integration | Same `client_order_id` and same payload sent twice | the second call returns the first order with `created=False`; one doc stored |
| OMS-11 | integration | Same `client_order_id`, different payload | `IdempotencyConflict` |
| OMS-12 | integration | Same `client_order_id` for two different users | two orders (the key is per user) |
| OMS-13 | edge | `client_order_id` missing, blank, or longer than 64 characters; legs empty | `InvalidOrder` |
| OMS-14 | edge | mode `live` | `InvalidOrder` (`live_not_available`); nothing stored |
| OMS-15 | edge | mode not in the vocabulary | `InvalidOrder` |
| OMS-16 | integration | `transition` moves state, appends history, and sets `broker_order_id` when given | doc updated |
| OMS-17 | failure | `transition` when another writer changed the state first (compare-and-set misses) | `StaleOrderState`; doc untouched |
| OMS-18 | failure | `transition` to an illegal state | `IllegalTransition`; doc untouched |
| OMS-19 | failure | `transition` on another user's order | `OrderNotFound` |
| OMS-20 | integration | `ensure_indexes` declares a unique `(user_id, client_order_id)` index | index recorded as unique |
