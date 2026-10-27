# Functionality Verification Report — F&O idea "Paper trade" request (Phase 0 item 0.1, gate 7) + provisional idea levels (D4)

- **Branch:** `fix/fno-idea-paper-trade` (off `origin/dev` 5b6b3cfd; commits b31227f6, 6da6f71d)
- **Date:** 2026-10-27
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DESIGN_ENGINEER)
- **Environment:** unit/contract tests in the `nivesh/backend:staging` image; Playwright on a production build with mocked
  API; read-only checks against staging (`nivesh-staging-app-backend`, newest stored watchlist day 2026-10-26).
- **Changed areas:** backend services: yes (`services/ai_watchlist_build.py`, `scripts/build_ai_watchlist.py`; no route
  changed, the validator is unchanged) · frontend src: yes
- **Test cases:** `test_reports/fno_idea_paper_trade_TESTCASES.md` (written before the implementation)

## Summary

Every F&O idea "Paper trade" was refused (422 `invalid_signal`) because `paperTradeBodyFor` sent no `signal`. It now
sends `signal {signal_at: chain date, rule_version: board rules_version, source_refs, evidence_summary}` and, when the
levels engine answered for the idea in the idea's own direction, the underlying stop and target 1 the row shows. A shared
fixture (`frontend-v5/e2e/fixtures/contract-fno-idea-paper-trade.json`) pins the exact body: Playwright asserts the browser
sends it, pytest sends it through the real route. Idea rows show display-only levels from `strategy_levels`, labelled
"Provisional · research levels" with the data date; the nightly watchlist job stores them per F&O idea.

## Before (reproduced first)

The body the old `paperTradeBodyFor` built for the real captured BANKNIFTY idea, through the real validator:

```
$ docker run ... nivesh/backend:staging python /probe/repro.py
REFUSED code = invalid_signal
```

The new Playwright cases run against the untouched base source (5b6b3cfd) with only the new specs and fixtures copied in:
see "UI / Playwright Tests — before" below.

## Test Cases

| ID | Scenario | Type | Result |
|----|----------|------|--------|
| B-1 | `body_with_levels` → POST /api/desk/paper-trades (real route, fakes) | api | PASS |
| B-2 | `body_without_levels` → same route | api | PASS |
| B-3 | pre-fix body (no signal) → 422 `invalid_signal`, nothing stored | api/regression | PASS |
| B-4 | mocked levels reply == real `strategy_levels.compute` answer | unit | PASS |
| B-5 | body's stop/target == the levels the row shows | unit | PASS |
| B-6 | nightly job's levels request == the browser's | unit | PASS |
| B-7 | `shape_day` stores the engine's answer per F&O entry | unit | PASS |
| B-8 | unpriced idea / engine exception keeps the day, says why, logs | edge/failure | PASS |
| B-9 | existing suites (desk strategy trades, desk trading, watchlist, levels, regime fit) | unit/api | PASS |
| F-1 | levels request == contract `levels_request` (Top by regime) | e2e | PASS |
| F-2 | Paper trade body == contract `body_with_levels` | e2e | PASS |
| F-3 | levels route fails → body == contract `body_without_levels` | e2e | PASS |
| F-4 | levels block: label, date, engine figures, full plan, no new entry control (+F-4b engine warning shown) | e2e | PASS |
| F-5 | Paper trade waits while the levels load | e2e | PASS |
| F-6 | neutral idea records no stop/target | e2e | PASS |
| F-7 | Top 10 BANKNIFTY row: levels block; body == contract (L-1, L-2), lab focus same (L-4) | e2e | PASS |
| F-8 | Top 10 stock row: scanner entry/stop/target in the row, label, scan date (L-3) | e2e | PASS |
| F-9 | AI watchlist stored levels shown; body == contract (L-1) | e2e | PASS |
| F-10 | AI watchlist day without levels: "not stored", no levels request, no stop/target (L-2) | e2e | PASS |
| F-11 | wording: no picks/suggested/recommended (F-4 + existing F-16, F-9) | e2e | PASS |
| F-12 | 390px no sideways scroll (existing F-26, F-10, with levels rendered) | e2e | PASS |
| F-13 | `copilot-app-desk-lab` still green | e2e | PASS |
| S-1 | staging read-only: real stored ideas get valid levels; bodies pass the deployed validator; branch job dry run in memory | data | PASS |
| S-2 | signed-in click of Paper trade on staging → 201 | e2e (manual) | **UNVERIFIED** — needs a session token, and it writes a paper trade |

## API / Endpoint Tests

No route was added or changed. `POST /api/desk/paper-trades` was exercised through the real FastAPI route and validator
with the repo's in-memory fakes (not staging):

```
$ docker run --rm --network none -v /home/deploy/nivesh-idea-levels:/work:ro -w /work/backend ... nivesh/backend:staging \
    python -m pytest tests/test_fno_idea_paper_trade_contract.py tests/test_ai_watchlist.py::<3 new> -v -p no:cacheprovider
tests/test_fno_idea_paper_trade_contract.py::test_the_body_the_idea_button_sends_opens_a_strategy_trade_with_its_signal[body_with_levels] PASSED [ 10%]
tests/test_fno_idea_paper_trade_contract.py::test_the_body_the_idea_button_sends_opens_a_strategy_trade_with_its_signal[body_without_levels] PASSED [ 20%]
tests/test_fno_idea_paper_trade_contract.py::test_with_levels_the_trade_carries_the_engines_underlying_stop_and_target_1 PASSED [ 30%]
tests/test_fno_idea_paper_trade_contract.py::test_the_pre_fix_body_without_a_signal_is_refused_and_nothing_is_stored PASSED [ 40%]
tests/test_fno_idea_paper_trade_contract.py::test_the_levels_reply_the_browser_specs_use_is_the_real_engine_answer PASSED [ 50%]
tests/test_fno_idea_paper_trade_contract.py::test_the_body_records_the_levels_the_row_shows_and_none_without_them PASSED [ 60%]
tests/test_fno_idea_paper_trade_contract.py::test_the_nightly_job_builds_the_same_levels_request_as_the_browser PASSED [ 70%]
tests/test_ai_watchlist.py::test_each_fno_entry_stores_the_levels_engines_answer_for_that_idea_on_the_list_day PASSED [ 80%]
tests/test_ai_watchlist.py::test_an_idea_that_cannot_be_priced_or_an_engine_failure_keeps_the_day_and_says_why PASSED [ 90%]
tests/test_ai_watchlist.py::test_the_dry_run_summary_names_each_entrys_levels_or_why_there_are_none PASSED [100%]
======================== 10 passed, 2 warnings in 6.72s ========================
```

All related suites:

```
$ ... python -m pytest tests/test_fno_idea_paper_trade_contract.py tests/test_desk_strategy_trades.py tests/test_desk_trading.py \
    tests/test_ai_watchlist.py tests/test_strategy_levels.py tests/test_regime_fit.py tests/test_regime_fit_distinct.py -q -p no:cacheprovider
233 passed, 3 warnings in 9.78s
```

## UI / Playwright Tests

Runner: `scratchpad/run-fe.sh` (tsc, production build, `vite preview`, Playwright `pw.copilot-app.config.ts`, mocked API —
MOCK, not real data; the board and the levels reply are a real capture and the real engine's answer, see the specs).

After (final run, all four specs):

```
== tsc
tsc: clean
== build
✓ built in 30.53s
== playwright
  2 skipped
  169 passed (2.4m)
exit 0
```

Per spec: desk-strategy-top 27 passed · desk-top10 31 passed · ai-watchlist 13 passed · desk-lab 98 passed, 2 skipped.

The first run of the same four specs had one failure, `copilot-app-desk-lab.spec.ts:2103 TC-7 … at 390px the table
scrolls inside its box` (`Expected: <= 1, Received: 153`). It is pre-existing and flaky, not caused by this branch: on the
untouched base export (5b6b3cfd) the same test alone gave `1 failed`; on this branch alone `--repeat-each=3` gave
`3 passed`; it passed in the final run.

Before (the new specs against the untouched base source):

```
$ run-fe.sh <export of 5b6b3cfd + the three new specs and two new fixtures> \
    copilot-app-desk-strategy-top copilot-app-desk-top10 copilot-app-ai-watchlist
  12 failed
  59 passed (1.5m)
exit 1
```

The 12 failures are exactly the new cases (strategy-top F-1…F-6 incl. F-4b, top10 L-1…L-4, ai-watchlist L-1, L-2); the 59
existing cases pass on the base. Example (F-1/F-2 on the base):

```
    Error: expect(locator).toHaveAttribute(expected) failed
    Locator: getByTestId('top-idea-BANKNIFTY-bear_put_spread').getByTestId('idea-levels')
    Expected: "ok"
    Error: element(s) not found
```

On the base the cases stop at the missing levels block, before the body comparison. The body defect itself is shown by
the reproduction above and the backend regression case B-3 (pre-fix body → 422 `invalid_signal`).

Visual check (mocked API, production build): the Top by regime BANKNIFTY card at 1280px and 390px shows the
"PROVISIONAL · RESEARCH LEVELS" pill, "end-of-day chain of 21 Oct 2026", Entry · net debit 292.30, Stop 204.61
(BANKNIFTY 55,271.88), Target 1 379.99 (BANKNIFTY 54,641.63), Target 2 467.68 (BANKNIFTY 54,362.19), Max loss ₹8,769
before costs, the totals line and the "Full plan" link; the card's controls are still only "Payoff chart" and "Paper
trade". Not rendered on the deployed staging build (not deployed).

## Data Correctness (staging, read only)

The validator and levels engine deployed on staging are byte-identical to this branch
(`diff -q` on `services/desk_strategy_trades.py`, `services/strategy_levels.py`, `services/desk_trading.py`: same). The
branch's `ai_watchlist_build.py` was piped on stdin and executed in memory inside `nivesh-staging-app-backend`; nothing was
written (no insert, no file). (A) the newest stored day's 10 F&O ideas: levels from the deployed engine, then a body built by
the same rule (a Python REPLICA of `paperTradeBodyFor`) through the deployed `new_strategy_trade` (pure; builds the document,
stores nothing). (B) `build_day("2026-10-26")` of the branch, dry run in memory.

```
stored day 2026-10-26: 10 F&O entries, 0 with stored levels
  BANKNIFTY   bear_put_spread   view down ref 54366.7 | levels valid True bearish stop 54555.15 target 54203.65 (34 ms) | body ACCEPTED stop 54555.15 target 54203.65 signal_at 2026-10-26
  INDUSTOWER  bear_put_spread   view down ref 388.99 | levels valid True bearish stop None target 375.65 (13 ms) | body ACCEPTED stop None target 375.65 signal_at 2026-10-26
  ... (10 rows, 13–34 ms each)
  accepted 10/10
== B dry-run build_day(2026-10-26) in 16.0 s: 10 F&O entries
  BANKNIFTY   as_of 2026-10-26 em 471.55 valid True error None
  ... (10 rows, all valid True, error None)
== B built ideas + stored levels: list 2026-10-26, rules 'regime-fit-v1 (2026-10-22)', 10 F&O ideas
  accepted 10/10
```

Finding (needs an owner decision, behaviour not changed): every idea on the 26 Oct list expires 27 Oct (1 day, engine flag
`expiry_week`). The engine's underlying stop sits +0.17 % to +0.81 % and target 1 −0.14 % to −3.43 % from the reference:

```
  BANKNIFTY   expiry 2026-10-27 dte 1 flags ['expiry_week'] ... underlying stop +0.35% target -0.30% target2 -0.59%
  PETRONET    expiry 2026-10-27 dte 1 flags ['expiry_week'] ... underlying stop +0.41% target -0.14% target2 -0.35%
  UNIONBANK   expiry 2026-10-27 dte 1 flags ['expiry_week'] ... underlying stop +0.17% target -0.18% target2 -0.31%
```

A daily bar will often touch both, which the strategy exit rule counts as the stop. The row now shows the engine's
expiry-week warning next to the levels.

## Inputs required from user

- A staging session token (or the owner clicking it) for S-2: one signed-in "Paper trade" on a staging F&O idea after the
  branch is deployed. It writes a paper trade and reserves paper cash, so it needs the owner's go-ahead.

## Verdict: BLOCKED
<!-- Not PASS: S-2 (signed-in staging click on the deployed build) is UNVERIFIED pending a session token. Every other
     case passed with the real output above. See test_reports/OVERRIDE_fno_idea_paper_trade.md. -->
