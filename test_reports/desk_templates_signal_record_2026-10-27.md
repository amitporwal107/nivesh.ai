# Functionality Verification Report — desk first-wave templates + signal record route

- **Branch:** feat/desk-templates-signal-record (base origin/dev 18b4870d)
- **Date:** 2026-10-27
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** unit tests in Docker `nivesh/backend:staging`, `--network none`; read-only data check inside
  `nivesh-staging-app-backend` (SELECT only). Not deployed: staging HTTP only after merge (see OVERRIDE).
- **Changed areas:** backend routes/services: yes · frontend src: no
- **Test cases:** test_reports/desk_templates_signal_record_TESTCASES.md (written before implementation)

## Summary

1. `services/strategy_plan/templates.py`: five new templates — `covered_call`, `bull_put_spread`, `bear_call_spread`,
   `protective_put`, `collar` — on the existing leg builders, the payoff engine's numbers and payoff-v2 costs. The
   underlying is cash shares (lots × lot_size, at the chain's spot). The catalog (`GET /api/desk/strategy/templates`)
   now has 13 entries, each with a per-leg `instrument` and a `risk` block (`max_loss`: defined / to_zero / unbounded,
   plus a note).
2. `GET /api/positional/signals/{symbol}/record?date=`: the live revision, every revision in
   positional_signals_history with `changes`, and the stored outcomes as `state`. Signed-in, SELECT only, 404 / 503.

## Results by case

| ID | Result | Evidence |
|----|--------|----------|
| T-1…T-11 | PASS | test_strategy_templates_first_wave.py (hand-worked figures below) |
| T-12, T-13 | PASS | test_strategy_plan_templates_route.py (7 tests) |
| P-1…P-3 | PASS | payoff route 200 valid for all five; naked shorts still `undefined_risk_not_supported`; paper `clean_leg` + `check_defined_risk` accept all five |
| R-1, R-2 | PASS | `defined_risk` pass and `fno_additional` pass for all five; `gate.defined_risk_failures` = [] |
| R-3 | PASS | covered call on a long future → `unhedged_future` (why shares are used) |
| R-4 | PASS | naked short call / put / under-covered call still fail `defined_risk` |
| R-5 | PASS (recorded) | see "Risk service findings" |
| S-1…S-10 | PASS | test_positional_signal_record.py (17 tests) |
| S-11 | PASS | staging read below |

Hand-worked template figures (MOCK chain, spot 1215, lot 50), as asserted by the tests and produced by the engine:

| Template | Legs | Max profit | Max loss | Breakeven |
|---|---|---|---|---|
| covered_call 1250 | +50 sh @1215, −1250C @14 | 2,450 | −60,050 (price 0) | 1201 |
| bull_put_spread 1100/1150 | +1100P @5, −1150P @15 | 500 | −2,000 | 1140 |
| bear_call_spread 1250/1300 | −1250C @14, +1300C @4 | 500 | −2,000 | 1260 |
| protective_put 1150 | +50 sh @1215, +1150P @15 | unbounded | −4,000 | 1230 |
| collar 1150/1250 | +50 sh, +1150P @15, −1250C @14 | 1,700 | −3,300 | 1216 |

## Risk service findings (rules NOT changed)

`svc.decide` on a MOCK snapshot, default profile, `fno_additional` on, equity Rs 1 crore:

| Structure | Outcome | Reasons |
|---|---|---|
| covered_call | block | `min_lot_exceeds_budget` (max loss = the shares to zero; even at Rs 1 crore) |
| bull_put_spread | block | `reward_risk_too_low` (500 : 2,000 < 1.5) |
| bear_call_spread | block | `reward_risk_too_low` |
| collar | block | `reward_risk_too_low` |
| protective_put | allow | — |

None is a defined-risk refusal. The sizing checks (per-trade budget, min reward:risk 1.5) will refuse most covered
calls, credit spreads, condors and collars at the default profile. That is a policy question for the owner.

## Real output

New and changed test files:
```
71 passed, 2 warnings in 8.01s
     17 tests/test_positional_signal_record.py
      7 tests/test_strategy_plan_templates_route.py
     47 tests/test_strategy_templates_first_wave.py
```

New + related (strategy_payoff, payoff_cost_card, templates route, risk_gate*, risk_service, positional_*):
```
439 passed, 1 skipped, 2 warnings in 13.75s
```

Full CI allowlist, this branch (253 files):
```
FAILED tests/test_cas_api_client.py::test_sandbox_parse_and_map - AssertionEr...
FAILED tests/test_cas_api_client.py::test_convenience_helper_returns_list - a...
FAILED tests/test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches - a...
3 failed, 6721 passed, 28 skipped, 15 warnings in 205.54s (0:03:25)
```

Full CI allowlist, origin/dev (251 files, same image, same flags):
```
FAILED tests/test_cas_api_client.py::test_sandbox_parse_and_map - AssertionEr...
FAILED tests/test_cas_api_client.py::test_convenience_helper_returns_list - a...
FAILED tests/test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches - a...
3 failed, 6656 passed, 28 skipped, 15 warnings in 199.01s (0:03:19)
```
+65 tests, the same 3 network-only failures, no new failure.

Staging data, read only (the branch's routes/positional.py loaded under another module name in
`nivesh-staging-app-backend`, handler called directly, SELECT only; temp files removed afterwards):
```
direct SELECT: CORONA 2026-10-27 history rows 0 {'revision': '1', 'entry_price': '2175.2700', 'stoploss': '2078.4900', 'target_price': '2368.8500', 'risk_reward': '2.00', 'stage': 'EARLY_BREAKOUT', 'stop_method': '{"atr": 64.53, "rule": "the tighter of the 20-session swing '}
route current: {"revision": 1, "levels": {"entry": 2175.27, "stop": 2078.49, "target": 2368.85, "risk_reward": 2.0}} stage EARLY_BREAKOUT
route stop_method: {"atr": 64.53, "rule": "the tighter of the 20-session swing low x 0.995 and entry - 1.5 x ATR(14)", "method": "atr", "swing_ref": 1941.5, "atr_multiple": 1.5, "
route revisions: 0 revision_count: 1 state: {"live": true, "stage": "EARLY_BREAKOUT", "outcomes": [], "outcomes_error": null}
route note: No earlier revision is stored: the levels have not changed since the signal was first written.
no date -> signal_date 2026-10-27 symbol CORONA
unknown symbol -> 404 No scanner signal for NOSUCHSYMBOLX on 2026-10-27
```
Staging facts read the same session: `positional_signals_history` exists with **0 rows** (no re-run has changed a
signal since migration 025), `positional_signals.revision > 1`: 0 rows, `positional_outcomes`: 0 rows. So the
multi-revision path (S-1) is proven only on MOCK rows.

## UNVERIFIED

- Both routes over HTTP on staging (not deployed; needs merge + backend restart).
- A real multi-revision signal: staging has no history rows yet.
- The Trade Desk UI showing the new templates (branch feat/desk-trade-desk-b reads the catalog by name; not run here).
  The F&O lab Programs library's `legText` labels a share leg "BUY option" because it falls back to the template kind;
  it ignores the new `instrument` field (frontend follow-up, not changed here).

## Verdict: PASS
