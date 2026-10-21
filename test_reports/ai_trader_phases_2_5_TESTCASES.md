# Functionality Verification Report — AI Trader Phases 2–5

- **Branch:** feat/ai-trader-phases-2-5 (worktree /home/deploy/nivesh-ai-trader)
- **Date:** 2026-10-21
- **Environment:** unit/route tests in a container from the staging image; staging NOT run
- **Changed areas:** backend routes/services: yes · frontend src: no

## Test Cases (authored before implementation, from docs/prd/AI_TRADER_PHASES_2_5.prd.md §5)
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| P2-1 | Config | defaults, initial_capital override, frozen, shadowing, serialisable, ranges | unit | per spec | PASS (unit, 192 passed, 0 xfail) |
| P2-2 | Architect | regime→template, DSL-valid, regime UNAVAILABLE → none | unit | as stated | PASS (unit) |
| P2-3 | Backtest | sealed window refused; holdout one-shot; config stored with run | unit/api | 422 / 409 | PASS (unit) |
| P2-4 | Gates | each criterion fail+pass; no stage skip; live→422 | unit/api | 409/422 | PASS (unit) |
| P2-5 | Walk-forward | 4 folds, boundaries, none in sealed block | unit | as stated | PASS (unit) |
| P3-1 | Governor | one test per reason code | unit | codes | PASS (all 30 reason codes, AST-enumerated) |
| P3-2 | Governor | precedence; reduce satisfies all limits; <1 share → reject; deterministic | unit | as stated | PASS (unit, 6,912-input invariant sweep) |
| P3-3 | Governor | independence (AST: no strategy/evidence/LLM import) | unit | none | PASS (AST) |
| P4-1 | Paper | backtested strategy cannot signal | api | 409 | PASS (TestClient, 409) |
| P4-2 | Paper | approved intent → exactly one paper trade matching decision | api | match | PASS (asserted on the real stored desk document) |
| P4-3 | Paper | rejected intent stored with reasons, no trade; idempotent repeat | api | as stated | PASS (incl. a simulated duplicate-key race) |
| P5-1 | Assisted | ticket awaits confirmation; expiry; confirm re-checks governor | api | as stated | PASS (TestClient) |
| P5-2 | Assisted | confirm text contains order fields and the "nothing sent" line | api | present | PASS (exact self-place line asserted) |
| P5-3 | Safety | AST: no broker import; mode=live → 422 | unit | none / 422 | PASS (AST over all 5 modules; no "live" value exists) |
| P5-4 | Journal | outcomes → (confidence, hit) → calibration | unit | match | PASS (Brier 0.26, calibration error 0.10, hand-checked) |
| X-1 | Auth | other user's strategy/ticket 404; no auth 401; bad body 422 | api | codes | PASS (404 never 403; 8 x 401; 8 x 422) |

## Evidence run 2026-10-21 (container from the staging image, tree mounted read-only, no network)
- `python -m pytest tests/test_ai_trader_strategy.py -q` -> `105 passed in 1.93s` (Phase 2 module)
- `python -m pytest tests/test_ai_trader_config_risk.py -q` -> `192 passed in 0.51s` (NiveshConfig + governor, 0 xfail,
  0 skipped; every defect below is now an ordinary regression guard)
- `python -m pytest tests/test_ai_trader_execution.py -q` -> `62 passed, 1 warning in 6.67s` (Phases 4 and 5)
- `python -m pytest tests/test_ai_trader{,_config_risk,_strategy,_execution}.py -q` -> `454 passed, 1 warning in
  44.19s` (ALL FOUR suites, Phases 1 to 5 together, after the 31 review fixes: 201 config/governor, 129 strategy,
  124 execution/routes with Phase 1, each fixed test-first and mutation-checked)
- `python -m pytest tests/test_desk_trading.py tests/test_desk_alerts.py tests/test_desk_paper_sim.py -q` ->
  `144 passed` (the desk engine the paper trades are written through; no regression)
- Direct probe of the critical fixes, all printed in this session's transcript: the signals route checks
  `is_sealed_gap` before any provider call; the holdout seal is claimed with a conditional write BEFORE the window is
  handed to the runner; a holdout cannot be a strategy's first run (`holdout_before_backtest`); the confirm path
  clamps to the signal-date quantity (`SIZE_CAPPED_AT_SIGNAL`); signals refuse with 503 while the idempotence index
  is missing; `stated_confidence` returns None rather than a sealed-block win rate when only a holdout run exists,
  and 0.55 from the ordinary run when both exist; an AST scan of all 13 files finds no broker, Kite, Angel One,
  Upstox, Dhan, Fyers or order-placing import, and `live` is in neither MODES nor STAGES.
- `python -c "import server"` registers all 13 /api/ai-trader paths, the 3 from Phase 1 plus the 10 new ones
- `python -m pytest tests/test_desk_trading.py tests/test_desk_alerts.py -q` -> `104 passed` (the desk engine the
  paper trades are written through; no regression)
- `python -m pytest tests/test_ai_trader_strategy.py tests/test_ai_trader.py -q` -> `148 passed, 1 warning in 41.41s`
  (Phase 2 plus the Phase 1 suite, after the fixes, so nothing regressed)

Defects found and fixed in this branch's own code: 10 by the test suites during the build, then 31 confirmed by the
adversarial review (45 agents, 39 findings, 8 refuted by the verifiers). 5 of the 31 were critical, including three
ways the sealed 2023-01-01..2024-07-31 block could be read: a failed holdout run never recorded that the seal was
opened, the signals route had no sealed check at all, and ticket confidence was read from the holdout run so the
sealed block would have become the basis of the system's own confidence claims. 3 of the 31 were deliberately not
fixed and are recorded as open items: scoping the governor's book to one strategy's sleeve (a product choice, not a
bug), a post-insert re-check whose suggested form would refuse nearly every confirm, and filtering informational
codes out of a rejection reason (cosmetic). The build-time ten follow. and re-checked by the printed probe in
this turn's transcript: the `symbols` write error did not point at the symbol picker; `validate()` accepted a custom
key that could never be read back; a KNOWN zero average traded value was treated as missing and approved full size
(now a zero cap, so the order is refused); the five size-cap reduce reasons carried no limit. A fifth defect was
introduced by my own first fix and caught by the probe: a non-string custom key raised `AttributeError` instead of a
validation error, because the shadow check read it as a string before the identifier check ran. A sixth: symbols
entries were never type-checked, so [1, 2] validated and would have been persisted with the run and reproduced it
wrongly forever. Four more came from the Phases 4 and 5 agent reviewing code it had to call: resolve() silently
dropped an unknown Bot details field, so a mistyped setting vanished and the run used a default the caller never
chose; the paper tally and the assisted gate agreed on four key names by coincidence, so a rename would have made the
gate read nothing and refuse a promotion for the wrong reason (the names are now declared once in strategy.py and the
producer raises if it stops providing one); and a refused order still carried a hedge suggestion for exposure it was
never going to add. Every one of the ten was found by an adversarial reviewer or a probe, not by the code's author.

Phase 4 and 5 rows stay NOT RUN: that agent is still working. Every staging row stays NOT RUN, see
OVERRIDE_ai_trader_phases_2_5.md.

## Verdict: BLOCKED
