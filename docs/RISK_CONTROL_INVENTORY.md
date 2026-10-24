# Risk control — execution path inventory

> Step 1 of the Risk Control Center initiative: locate the real execution paths, the risk engine and
> the existing kill-switch code **before** writing a line of enforcement. Every claim below carries a
> file:line or a command output. Written 2026-10-22 against `origin/dev` @ `718a4469`.

## The finding that changes the plan

**There is no order placement in this system.** A repository-wide search for a call that submits,
modifies or cancels an order returns exactly one hit, and it is a comment saying the opposite:

```
grep -rniE "place_order|placeOrder|place_gtt|modify_order|cancel_order" --include=*.py services routes
services/brokers/zerodha.py:4:  we never call `place_order` / `modify_order` / `cancel_order`.
```

The Kite wrapper is read-only *by construction* — `services/kite_live_feed/gateway.py:3` states that
`ReadOnlyKite` exposes "exactly instruments(), quote(), historical_data() and profile(); there is no
order, GTT, margin or session method on it". The broker adapters under `services/brokers/` read
holdings and positions only.

**Consequence for the proposed design.** A "central authorization gate before the broker adapter",
an "order intent bound to policy version / instrument / quantity / expiry", and a "broker adapter
that must not accept an unverified order" all describe a component that does not exist yet. Building
that gate now would be building a door frame with no door: nothing would pass through it, nothing
would be tested by real traffic, and its correctness would be unfalsifiable until execution is
written — at which point it would be rewritten anyway.

What *does* exist is a set of paths that create **positions in the simulator** and **actionable
tickets**. Those are the paths worth governing today, and governing them is genuinely valuable:
they feed the promotion gates that would one day authorise live trading.

## The real paths

Not four execution paths — four **position-creating writes**, of which the risk governor covers one.

| # | Path | Write | Governed? |
|---|---|---|---|
| 1 | AI-trader ticket creation | `routes/ai_trader.py:616` `db[TICKETS].insert_one` | **Yes** — `evaluate()` at `:612` |
| 2 | AI-trader → desk paper trade | `routes/ai_trader.py:667` `db[desk.TRADES].insert_one` | Yes, via the same flow |
| 3 | **Desk paper trade (what users click)** | `routes/desk_trading.py:111` `db[svc.TRADES].insert_one` | **No gate of any kind** |
| 4 | Positional journal trade | `routes/positional_journal.py:189` `db[COL].insert_one` | **No** |

The governor's `evaluate()` has exactly **two** call sites, both in `routes/ai_trader.py` (`:612`,
`:732`). `routes/desk_trading.py` contains no reference to it; its only limits are count caps —
`409 open_trade_limit` at 100 open trades (`:110`, `:115`).

Path 3 is the one a user actually reaches, including from the new "Paper trade" button on the Top-5
board (PR #288). It performs no risk evaluation whatsoever.

## The kill switch is not "unwired" — it is unreachable

`services/ai_trader/risk_governor.py:69-70` declares the fields with the comment "set by a person",
and `:112-115` enforces them correctly. They are never set:

```
routes/ai_trader.py:366
    return Portfolio(capital=capital, positions=positions, realized_pnl_today=round(realized, 2))
```

`kill_switch`, `halted` and `drawdown_pct` are **not passed**, so they hold their dataclass defaults
(`False`, `False`, `None`) on every evaluation. The only other construction, `:635`, copies those
same values forward while adding a position. There is no store, no route and no setter: a
repository-wide search for `kill_switch` finds the dataclass, the two enforcement lines and that one
copy, and nothing else.

So the enforcement logic is correct and can never fire. That is worse than absent, because the field
makes it look present.

## Drawdown has no baseline to measure against

`_portfolio()`'s own docstring admits it (`routes/ai_trader.py:329`): *"The desk keeps no equity
curve either, so drawdown is None and the governor says the drawdown halt could not be checked."*

An equity curve exists only inside the **backtest** engine — `services/strategy_engine/backtest.py:280`
`_build_equity_curve(...)` producing `[{date, equity, drawdown}]` per run. Nothing produces one for
live or paper positions. P0-2 therefore needs a baseline built first; it is not a wiring task.

## Audit

No trading path records anything. `grep -rn "audit" routes/ai_trader.py routes/desk_trading.py
routes/strategy_plan.py` returns **no hits**. Risk decisions live on mutable ticket documents and are
overwritten in place, so a decision cannot be reconstructed, nor proved to have been made.

## Corrected sequence

The proposed order assumed live execution. Re-ordered for what exists, hardest-value first:

1. **Make the kill switch reachable.** A `risk_limits`-style store, `GET/PUT` routes with elevated
   authorization, and three lines in `_portfolio()` so the fields carry real values. Small, and it
   removes a field that currently lies about itself.
2. **Route paths 3 and 4 through the governor.** This is the real "1 of 4" fix, and path 3 is the one
   users touch.
3. **Append-only audit events** for every risk decision, denial, limit change and kill-switch action.
   Needed before anything can be proved, and a precondition for the SEBI-facing surface.
4. **An equity baseline for paper positions**, then wire `drawdown_pct`. Do not enforce a threshold
   that cannot be computed.
5. **Screen 10** against those contracts, showing real state, timestamps, policy version and failures.
6. **Execution authorization and the broker gate** — only when order placement is actually being
   built, and designed together with it.

## What should NOT be built yet

- An order-intent authorization token bound to policy version, instrument, quantity and expiry.
  There is no order intent to bind it to.
- A broker-adapter gate. The adapters cannot place orders; the Kite wrapper has no order method.
- "Cancel working orders / flatten positions" halt policies. There are no working orders. The
  distinction the plan rightly insists on (block new vs. handle existing) currently has only one
  side.

Keeping these out is not deferral for its own sake: each would be unfalsifiable today, and would
encode assumptions about an execution layer whose shape is not yet decided.

## Still-open P0s not covered above

From the AI Trading Bot PRD gap analysis: derivatives were invisible to the risk book (**fixed**, PR
#284), the paper fill model could not lose to a gap (**fixed**, PR #284), PII reached the model
provider in text (**fixed**, PR #285). Remaining: three look-ahead leaks in the backtest engine, no
execution authorization model, and market data with no bid/ask or depth.

## Update 2026-10-24 — F&O risk foundation (PR A, branch `feat/fno-risk-foundation`)

Live execution will go through Kite Connect in the user's own session (product decision 2026-10-24). This change
lays the controls that execution must pass through. It still places no order.

- **OpenAlgo removed.** `routes/openalgo_proxy.py` was an unauthenticated reverse proxy mounted at `/api/openalgo/*`.
  It is gone, together with POST `/api/broker/connect`, POST `/api/broker/connect-hosted`, GET
  `/api/broker/openalgo-config`, the instance manager, the provisioner and the tracked `openalgo_instances/` data. A
  legacy OpenAlgo row can still be listed and disconnected. Its sync is refused with 400 `BROKER_READ_NOT_SUPPORTED`.
  `services/openalgo_client.py` stays because `broker_connect` still reads its `SUPPORTED_BROKERS` display names.
- **Order-path guard.** `tests/test_order_path_guard.py` AST-scans `backend/` and fails on any call to
  place/modify/cancel_order or place/modify/cancel_gtt outside `services/oms/adapters/`. It also fails on any new
  pass-through catch-all route. Four existing admin-only data-platform proxies are allowlisted by name, and each
  handler must start with `await require_admin(...)`.
- **Execution modes** (`services/execution_modes.py`): paper, shadow, assisted, live. `LIVE_EXECUTION_AVAILABLE = False`
  is a code constant. A per-user live grant (`live_authorizations`) is recorded by an admin with a reason and audited.
  `is_live_allowed` needs both the constant and the grant.
- **Kill-switch authority.** Anyone can turn their kill switch or halt on. Clearing either needs an admin (403
  `admin_required`). The audit actor is the signed-in person, not the client an advisor is acting for. New admin
  routes: `PUT /api/admin/risk/{user_id}/kill-switch | /halt | /live-authorization`. `GET /api/risk/status` now also
  reports `can_reset`, `live_authorization`, `modes`, `live_execution_available` and `gate`. The new
  `GET /api/risk/policy` reports the limits and the user's usage against them. Indexes are created lazily.
- **Shared risk gate** (`services/risk_gate/`, policy `fno-risk-v1`, conservative defaults that are not calibrated):
  - Checks, in a fixed order: controls, mode, structure, defined risk, exchange lot, listed expiry, caps, open
    structures. An unknown or unverifiable input blocks with a specific code.
  - Every decision is written to `risk_decisions` with correlation_id, path, mode and inputs_hash. If that write fails,
    the route answers 503 `risk_decision_unrecorded` and writes nothing. The legacy `record_decision` still fails open
    for its existing callers.
  - It sits behind the `fno_risk_gate` flag (default off) on the desk paper trade (cash and strategy), the journal
    entry, journal ENTRY fills, and AI-trader signals and confirm. The AI trader keeps its governor.
  - With the flag off, behaviour is unchanged.
- **Security fix, regardless of the flag:** the journal's `add_fill` now writes only to the owner's OPEN trade (the
  filter includes `user_id` and `status`). Any other trade gets 409 `trade_not_open`.

Not done in PR A: staging verification (needs a merge to dev, a backend restart and a session token), any frontend
(the legacy `frontend/src/components/BrokerConnectButton.jsx` still calls the removed OpenAlgo routes; frontend-v5
does not), and the order adapter itself.
