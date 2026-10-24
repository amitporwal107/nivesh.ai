# OVERRIDE: F&O risk foundation (`feat/fno-risk-foundation`)

REASON: Staging verification of the new and changed endpoints is not done yet. It needs three things: this PR merged to `dev`, a backend restart on staging, and a staging session token for a normal user and for an admin (the admin endpoints and the admin-only reset). The risk gate also stays inert until the `fno_risk_gate` flag is moved from `off` to `allowlist`. Local evidence is below. This file is not a pass.

## Test cases
`test_reports/fno_risk_foundation_TESTCASES.md`, written before implementation.

## Local evidence (rebased onto dev f10c3e6f, throwaway container, `--network none`)
```
# new: test_execution_modes, test_order_path_guard, test_risk_gate, test_risk_gate_ai_trader,
#      test_risk_gate_desk_journal, test_risk_routes
164 passed, 3 warnings in 15.93s

# existing neighbours: test_risk_controls, test_desk_trading, test_desk_paper_sim, test_honesty_safety_pass,
#   test_ai_trader_execution, test_ai_trader_config_risk, test_paper_account, test_desk_strategy_trades,
#   test_fno_margin, test_fno_forward, test_broker_*, test_feature*
1407 passed, 1 skipped, 4 warnings in 19.25s

python -m compileall -q .   ->  compile_ok
```

## To verify on staging after merge and restart
1. `GET /api/risk/status` as a user: the new fields `can_reset`, `live_authorization`, `modes`, `live_execution_available: false` and `gate`.
2. `PUT /api/risk/kill-switch {enabled:false, reason}` as a non-admin → 403 `admin_required`; as an admin, through `PUT /api/admin/risk/{user_id}/kill-switch` → 200, with an audit row whose actor is the admin.
3. `GET /api/risk/policy` → limits and usage.
4. With `fno_risk_gate` set to allowlist for a test user:
   - an F&O paper trade with a wrong lot size → 409 `risk_blocked`;
   - a valid defined-risk structure → 201;
   - both write a `risk_decisions` row carrying a `correlation_id` (data test: query `risk_decisions`).
5. `/api/openalgo/...` → 404.
