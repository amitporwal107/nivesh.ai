# Functionality Verification Report — AI Trader Phases 1 to 5 on STAGING

- **Branch:** dev (PR #265 merged as 3a184901, PR #266 merged as 5bdf1229)
- **Date:** 2026-10-21
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** staging (staging.niveshcopilot.com), real API over HTTPS, session token supplied by the user
- **Changed areas:** backend routes/services: yes · frontend src: no

## Summary
Both PRs were merged to dev on the user's explicit authorization, CI redeployed the app VM, and the backend container
now mounts `/app/research` (verified inside the container). Every endpoint below was called over real HTTPS against
the deployed code, as the signed-in user. A full strategy lifecycle ran: create, backtest on real warehouse data,
promote, and refuse to promote further. All output below is unedited.

## Test Cases

| ID | Scenario | Expected | Result |
|----|----------|----------|--------|
| TC-2 | GET evidence inside data coverage | items OK, schema valid | PASS, 16 of 16 OK |
| TC-3 | GET evidence for a sealed date | UNAVAILABLE/SEALED_GAP, no number | PASS, 16 of 16, no data leaked |
| TC-7a | missing/invalid as_of, bad symbol, no auth | 422/422/422/401 | PASS |
| TC-7b | unknown symbol | 404 | NOT VERIFIABLE here, see below |
| TC-11 | evidence p95 under 2 s | < 2 s | PASS, 0.29 to 0.49 s over 5 runs |
| CAL | POST calibration, hand-checked | Brier 0.16, bin 0.8 observed 0.8 | PASS |
| SYM | symbol evidence with no Kite bars | UNAVAILABLE/BARS_SOURCE_MISSING | PASS, and `notes` says so |
| P2-A | POST strategies, BEAR regime | accumulation template, DSL-valid, stage draft | PASS |
| P2-B | sealed backtest window, no holdout | 422 sealed_window | PASS |
| P2-C | holdout as a strategy's first run | 409 holdout_before_backtest | PASS |
| P2-D | real backtest on a clean window | runs, metrics stored | PASS, 30 trades |
| P2-E | promote a draft whose run measured nothing | 409 gate_not_met | PASS |
| P2-F | promote draft to paper (stage skip) | 409 stage_skip | PASS |
| P2-G | promote backtested to paper, weak strategy | 409 with every unmet criterion | PASS, 6 refusals |
| P4-A | a draft or backtested strategy signalling | 409 stage_cannot_signal | PASS |
| P5-A | mode=live, target_stage=live | 422, no live path exists | PASS, both 422 |
| X-1 | another user's strategy id | 404 | PASS |
| JRN | journal with nothing closed | n=0, stats None not zero | PASS |
| P4/P5 | paper trade, ticket, confirm, reject | per PRD | NOT RUN, unreachable, see below |

## API results (real, unedited)

Deployment check:
```
sudo docker inspect nivesh-staging-app-backend --format '{{range .Mounts}}{{.Destination}} {{end}}'
/app/backend /app/data /app/research
sudo docker exec nivesh-staging-app-backend sh -c 'ls /app/research' -> charting corporate_actions costs ...
```

Evidence, inside coverage (`as_of=2026-09-18`), HTTP 200 in 0.34 s, 16 of 16 OK:
```
market | NIFTY 500 regime is BEAR (close vs SMA200 and its slope).
market | NIFTY 500 20-session trend is BEAR (OLS slope and ADX 14).
market | India VIX closed at 11.39.
market | Advance/decline ratio 1.87 across the breadth universe.
20d | NIFTY PHARMA is rank 1 of 12 sectors; 20-session return minus NIFTY 500: +3.97 pts.
20d | NIFTY METAL is rank 2 of 12 sectors; 20-session return minus NIFTY 500: +2.80 pts.
```
Timing, 5 runs: 0.332 s, 0.487 s, 0.335 s, 0.286 s, 0.326 s, all HTTP 200.

Sealed block (`as_of=2023-06-01`):
```
statuses: {('UNAVAILABLE', 'SEALED_GAP')} | items: 16
any numeric data leaked: False
```

Errors: `GET evidence` -> 422, `as_of=bad` -> 422, `symbol=bad sym` -> 422, no cookie -> 401.

Calibration, 8 hits and 2 misses at 0.8 (hand calc (8*0.04 + 2*0.64)/10 = 0.16):
```
n= 10 brier= 0.16 calibration_error= 1.11e-16  bin 0.8 observed= 0.8
```

Strategy created (HTTP 201, 131 ms), real regime driving the choice:
```
id d526fd03-af68-415b-85be-f116bdb37d04  stage draft  template accumulation  regime BEAR
version 28a714665e489efe  universe {"type":"index","ref":"NIFTY500"}
config {schema_version 1, symbols [RELIANCE, TCS], initial_capital 1000000.0, commission_pct 0.05,
        pyramiding 0, short_margin_pct 100.0}
provenance.universe.note present: the backtest runs the template's index, the requested symbols constrain
        NiveshConfig only (the open question recorded for the owner)
orders: "Nothing is sent to any broker. A paper trade is a record Nivesh keeps; you place real orders yourself."
```

The three critical sealed-window and live-mode guards, on the deployed code:
```
sealed window, no holdout   -> 422 sealed_window
holdout as first run        -> 409 holdout_before_backtest
mode=live                   -> 422
target_stage=live           -> 422
draft signalling            -> 409 stage_cannot_signal
draft -> paper              -> 409 stage_skip
GET another user's id       -> 404
```

A REAL backtest on a window with no warehouse coverage (2025-01-01..2025-06-30), HTTP 200 in 2.5 s:
```
metrics: {"reason": "no_data"}   folds: 4, all empty
then promote draft -> backtested -> 409
  UNMET backtest_run  value=None  threshold=1
```
This is the build-time defect the suites found, caught on real data: before it was tightened, a run that measured
nothing satisfied "needs a stored backtest run" and would have promoted the strategy.

A REAL backtest with real trades (2026-06-01..2026-09-18), HTTP 200 in 13.5 s:
```
metrics: {"trade_count": 30, "win_rate": 30.0, "avg_win_pct": 4.73, "avg_loss_pct": -4.1,
          "profit_factor": 0.08, "max_drawdown_pct": -0.36, "total_return_pct": -0.36,
          "starting_capital": 1000000.0, "ending_capital": 996370.03, "avg_holding_days": 17.5,
          "price_basis": "corp_action_adjusted", "universe_basis": "latest_snapshot"}
folds: 4 -> trades 0, 0, 21, 16; returns None, None, -0.32, -0.17
promote draft -> backtested -> 200, stage backtested
  GATE backtest_run passed=True value=30 threshold=1
  evidence_run {run_id 3bfda134-cc90-4810-92cc-3c3b826b5d7e, window 2026-06-01..2026-09-18}
```

Then the gate that matters, backtested -> paper, HTTP 409:
```
code: gate_not_met
  REFUSED BY trade_count                 value=30              threshold=100
  REFUSED BY profit_factor               value=0.08            threshold=1.3
  REFUSED BY max_drawdown_pct            value=-0.36           threshold=-25.0
  REFUSED BY total_return_pct            value=-0.36           threshold=0.0
  REFUSED BY walk_forward_positive_folds value=0               threshold=3
  REFUSED BY universe_basis              value=latest_snapshot threshold=('point_in_time', 'custom_universe')
```
Two of those six are review fixes proving themselves on real data:
- **universe_basis = `latest_snapshot`.** The original gate banned only `present_day_fallback`, so this biased
  universe would have passed. The allowlist catches it. The DaaS provider staging and production use applies one
  constituent snapshot across the whole window, which is survivorship bias.
- **max_drawdown_pct = -0.36 fails against a -25.0 floor**, which looks wrong until you read the label: the row
  fails closed because the run declares no portfolio sizing basis. Which is correct, because -0.36 per cent is not a
  portfolio drawdown at all, see below.

## Data correctness (staging)

- Index files on the app VM end **2026-09-22** (breadth 2026-09-18). A request for today returns `AFTER_COVERAGE` on
  every item rather than a number. Correct behaviour, but the evidence endpoint is about a month stale: whatever job
  refreshes `research/index_history/data` has not run. This is a data-pipeline gap, not a code defect.
- The Kite daily bars are not on the app VM, so symbol-level evidence returns `BARS_SOURCE_MISSING` and the response
  says so in `notes`. Market, sector, VIX and breadth evidence all work.
- **The 30-trade run confirms the position-sizing finding with real numbers.** 30 trades moved a ten lakh account by
  0.36 per cent in total, because the engine computes profit on ONE share. A real 30-trade run of a 5 per cent-stop
  strategy at portfolio size could not produce a 0.36 per cent total move. So `total_return_pct` and
  `max_drawdown_pct` from this engine are not portfolio figures, exactly as predicted from reading the code.

## Inputs required from user

- Session token: supplied, used, and the local cookie file deleted after the run. It is in the conversation, so
  rotate it if that matters.
- **Decision needed (PRD section 10c, open question 4): position sizing in the shared backtester.** Until it is
  resolved no strategy can pass the paper gate, so Phases 4 and 5 cannot be exercised end to end.

## Not verified, and why

- **TC-7b, unknown symbol 404.** The route returns the bars-source note before it can check whether a symbol exists,
  so `symbol=NOPEXYZ` answers 200 with `BARS_SOURCE_MISSING` instead of 404. Correct, since without bars the route
  cannot know the symbol is unknown, but the 404 branch is unverifiable on this host. Verified at unit level only.
- **The sealed-date guard on /signals.** On staging the stage check fires first, so a sealed `as_of` answered
  `stage_cannot_signal`. The sealed refusal itself is verified at unit level (the test asserts zero provider calls),
  not end to end, because reaching stage paper requires passing the gate above.
- **Phases 4 and 5 (paper trades, tickets, confirm, reject, the governor in the live path).** Unreachable on real
  data until the sizing question is answered. Verified at unit level: 454 tests pass.
- **No real concurrency was exercised**, so the atomic holdout claim and the lost-update fix are proven against an
  in-memory collection and two sequential stale-snapshot requests, not interleaved tasks against mongod.

## Verdict: BLOCKED
<!-- Phases 1, 2 and 3 are VERIFIED on staging with the evidence above, including all five critical safety
     properties. The verdict stays BLOCKED because TC-7b and the /signals sealed guard are not verifiable on this
     host, and Phases 4 and 5 cannot be reached until the position-sizing decision is made. -->
