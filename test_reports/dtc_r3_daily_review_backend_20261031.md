# Functionality Verification Report — Daily Trader Copilot visual answer: Q15 daily review (backend, Release 3)

- **Branch:** feat/dtc-r3-daily-review (based on feat/dtc-r2-answers, PR #422)
- **Date:** 2026-10-31
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** unit tests in a `nivesh/backend:staging` container (`--network none`); the real-data capture ran in-process
  inside the running `nivesh-staging-app-backend` container (no restart, every database write dropped)
- **Changed areas:** backend routes/services: yes (`backend/services/copilot_visual/`: intents, readers, builders, payload,
  `__init__`) · frontend src: yes, small (a `₹` unit for `bars`; see `dtc_r3_daily_review_frontend_20261031.md`)

## Summary
Release 3's Q15 "What did I learn from today's trades?" is a new visual-answer intent, `daily_review`. It reads the
paper book's closed trades (`desk_paper_trades`, a plain read, not the GET route that runs the exit rule) and the risk
decisions log (`risk_decisions`) for the day asked about, or the ISO week when the question says so. It shows the
record (closed, wins/losses, win rate, net realised P&L, average R), plan vs actual per trade, how the trades ended
(the plan's rules vs closed by the user, gaps through the stop), what the risk checks refused, a cumulative-P&L `₹`
bars curve, and a notice that no live signal hit-rate exists. When nothing was recorded on the day asked about it
reviews the latest day with activity and names both dates; its `as_of` is that day, so an old day carries the stale
notice. Verified here: the backend, with unit tests on MOCK data and a real read-only capture. **Not verified on real
data: the populated branches**, because the staging account has 0 closed paper trades (below).

## Test Cases
> Authored up front (after reading the data the answer reads, before the implementation).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| R18 | intents | "What did I learn from today's trades?", "How did I do today?", "…this week?", "my mistakes today", "mistakes this week", "Review my trades today", "Weekly review of my trading", "How did I do on the TCS trade today?" | unit | `daily_review`; `period` = week when the question names the week; no stock, no thread read | PASS (8 cases) |
| R19 | intents | "What should I avoid today?", "How is my portfolio doing?", "What is my overall P&L?", "How did I do in my portfolio this year?" | unit | still None (Q14 and the CAS portfolio stay out) | PASS (in `test_r9_…`) |
| R20 | intents | "How are my trades going today?", "Review my open trades", "Is my trade in TCS still valid?", market view | unit | unchanged (open_trades stays open_trades) | PASS |
| B28 | daily_review | 2 trades closed today (target, gapped stop) + 1 not entered, decisions today | unit | KPIs, plan-vs-actual with R, exits list, curve, hit-rate notice, fresh sources | PASS |
| B29 | daily_review | nothing today, activity on 28 Oct | unit | the latest session; both dates in the headline; `as_of` 2026-10-28; stale notice | PASS |
| B30 | daily_review | "this week" | unit | the ISO week 26–30 Oct named; counts over the week | PASS |
| B31 | daily_review | no trades and no decisions ever | unit | empty-state notices only; no KPIs, table or curve | PASS |
| B32 | daily_review | the closed-trades read fails | unit | listed as missing; no trade figure; the decisions still shown; headline says so | PASS |
| B33 | daily_review | the decisions read fails | unit | listed as missing; trades still shown | PASS |
| B34 | daily_review | allowed / reduced / refused rows, one superseded row | unit | counted once (5 requests, not 6); top refusal reason with its message | PASS |
| B35 / B35b | daily_review | F&O structure, stop at/above the fill, no stop at all | unit | R shown as —, left out of the average; the KPI says how many had a stop | PASS |
| B36 | daily_review | `entry_not_reached` close | unit | "1 not entered", no P&L, not a win or loss | PASS (in B28) |
| B37 | daily_review | wording | unit | none of buy now / strong buy / recommended / pick / you should (the frontend's own regex); every follow-up resolves to an existing intent | PASS |
| B38 | facts | the review payload | unit | `facts()` carries the KPIs, table, curve and risk checks | PASS |
| B39 | readers | closed_trades / risk_decisions | unit | filters `{user_id, status: closed}` and `{user_id, at ≥ since}`; the GET route (a write) is never called | PASS |
| C2 | contract | real staging capture, 13 intents | contract | `validate()` = [] for each; the capture holds exactly the 13 builders | PASS |
| CI | regression | full CI allowlist | unit | no FAILED name that origin/dev does not also have | PASS |

## API / Endpoint Tests (staging)
No new route: the answer is reached through the existing chat pre-step (`routes/chat.py` → `copilot_visual.prepare`),
covered by `test_copilot_visual_chat.py`. Verified by building every intent in-process against real staging data.

- **pytest (targeted), re-run after the last code change:**
  `python -m pytest tests/test_copilot_visual.py tests/test_copilot_visual_chat.py tests/test_copilot_trade_idea.py -q`
  - Output: `184 passed, 2 warnings in 8.06s` (Release 2's branch: `162 passed, 1 skipped`)
  - Result: PASS
- **pytest (full CI allowlist, 284 files), branch and `origin/dev` @ 4a9cdef7 run the same way:**
  - branch: `17 failed, 7447 passed, 34 skipped, 15 warnings in 224.46s`
  - origin/dev: `20 failed, 7195 passed, 33 skipped, 15 warnings in 247.26s`
  - FAILED names diffed: the branch's 17 are all among dev's 20. Dev's three extra:
    `test_market_data_source.py::test_ms11_committed_file_is_current`,
    `test_truedata_client.py::test_nr7_cron_line_runs_after_the_last_fno_file`,
    `test_truedata_client.py::test_sw7_shipped_switch_keeps_truedata_off` (they fail on dev; this branch's base is older
    than the change that broke them). **No new failure.** The 17 shared are cron/fixture tests unrelated to this work
    (cas_api_client, chartink and desk cron lines, desk_redesign, move_odds, nidp_stamp, watchlist expiry).
  - Result: PASS

## Real staging capture (read-only, in-process inside `nivesh-staging-app-backend`)
13 intents built against the real NIDP warehouse, Mongo and app Postgres for one real staging account (hash `a5530afb31`).
Overlay `/tmp/ov_r3review` (`copilot_trade_idea.py` and the `copilot_visual` package), removed afterwards
(`ls /tmp/ov_r3review` → no such file). Auth stubbed. **Every database write was dropped**: each module's `db` was a proxy
whose write methods only counted calls. Output (user data as counts only):

```
write-proxy on 5 modules / auth stub on 6 modules
this user's closed paper trades: 0 | risk decisions: 31
open paper trades on this account: 3
== market_view … position_size   (the 12 earlier intents)   contract_problems=[]
== daily_review  (0.0s)  contract_problems=[]
  as_of 2026-10-30 | headline: Nothing was recorded on 31 Oct 2026; the latest session with activity is 30 Oct 2026. No paper trade closed; the risk checks refused 3 of 3 entry requests.
  source fresh   2026-10-30  Your closed paper trades (desk_paper_trades)
  source fresh   2026-10-30  Your entry risk checks (risk_decisions)
  notice[info]: No closed paper trades are on record yet.
  list risk_checks: ['3 entry requests checked: 0 allowed, 0 reduced, 3 refused.', 'Refused for plan levels mismatch (3×).']
  notice[info]: There is no live hit-rate for the desk's signals yet: no signal outcome has been recorded (positional_outcomes is empty) …
top_opportunities plan ids already stored in trade_plans: 5 of 5
fno_setups plan ids already stored in trade_plans: 5 of 5
writes blocked (nothing written): {'desk_paper_trades.create_index': 4, 'desk_price_alerts.create_index': 2, 'target_allocations.update_one': 1}
```
Rows touched on staging in the 40 minutes before the check: `desk_paper_trades` 0, `risk_decisions` 0, `paper_accounts` 0,
`paper_account_ledger` 0, `trade_plans` 4, `target_allocations` 1. The last two are not from this capture: its attempted
writes were all dropped (list above), and those rows are stamped 00:00–00:05 UTC, before the capture script was copied
(00:11 UTC), under the same account hash. Who wrote them is not established (another session using that account is the
likeliest reading).

## Data Correctness (staging)
- The staging account has **0 closed paper trades**, so on real data `daily_review` shows only its empty-trades branch plus
  the 3 refused entry requests dated 30 Oct. That agrees with an aggregate read made before the build: 3 `risk_decisions`
  rows dated 2026-10-30 across all users, so none belong to the other account that has decisions.
- The populated branches (KPIs, plan vs actual, R, exits, curve) are covered by unit tests on invented MOCK numbers
  (B-28 … B-36), not by real data. **UNVERIFIED on real data:** the figures for an account that has closed trades. It
  needs a staging account with at least one closed paper trade (a trade that hits its stop or target, or is closed by hand).
- Not checked on real data: an F&O structure close (kind `strategy`); B-35 covers the shape.

## Inputs required from user
- A staging account with a closed paper trade (or a closed trade on the existing one), and a signed-in session, to see
  the populated review on real data and to walk the deployed app.

## Verdict: PASS
Scope: the backend builder, resolver and readers on MOCK data, plus the contract on a real capture. All 17 test cases
passed with the output above; the full allowlist adds no failure beyond origin/dev's. The populated branches on real
data and a signed-in walk of the deployed app are open (Data Correctness; `OVERRIDE_dtc_r3_daily_review.md`).
