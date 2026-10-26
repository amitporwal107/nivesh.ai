# Test report — AI scanner watchlist: F&O chain date gate, cron after the F&O ingest, board expiry rule

- **Date:** 2026-10-27 (run 02:48–03:15 IST) · **Branch:** `fix/watchlist-fno-chain-expiry` (worktree
  `/home/deploy/nivesh-watchlist-fix`, off `origin/dev` 5b6b3cfd)
- **Test cases (authored first):** `test_reports/watchlist_fno_chain_expiry_TESTCASES.md`
- **Scope:** backend + one repo cron file. No frontend change, so no Playwright run: the desk board specs stub the API
  from fixtures and assert no expiry text this change alters.
- **Not done here (by instruction):** no deploy, no staging writes, no cron install, no push, no PR.

## 1. Unit tests (container `nivesh/backend:staging`, `--network none`, worktree mounted read-only)

Command:

```
sudo docker run --rm --network none -v /home/deploy/nivesh-watchlist-fix:/work:ro -w /work/backend -e PYTHONDONTWRITEBYTECODE=1 \
  -e MONGO_URL=mongodb://localhost:27017 -e DB_NAME=unit_test -e OPENAI_API_KEY=unit-test-placeholder nivesh/backend:staging \
  python -m pytest tests/test_watchlist_fno_chain_expiry.py tests/test_regime_fit.py tests/test_regime_fit_distinct.py \
  tests/test_ai_watchlist.py tests/test_strategy_ideas.py tests/test_fno_routes.py -q -p no:cacheprovider
```

Output (tail, unedited):

```
........................................................................ [ 31%]
........................................................................ [ 63%]
........................................................................ [ 95%]
...........                                                              [100%]
...
227 passed, 2 warnings in 11.14s
```

New cases, `-v` (unedited):

```
tests/test_watchlist_fno_chain_expiry.py::test_j1_chain_of_the_list_date_builds_and_stores_once PASSED [  4%]
tests/test_watchlist_fno_chain_expiry.py::test_j2_previous_sessions_chain_is_refused_with_exit_4_and_nothing_written PASSED [  9%]
tests/test_watchlist_fno_chain_expiry.py::test_j3_no_chain_at_all_is_refused_with_the_boards_reasons PASSED [ 14%]
tests/test_watchlist_fno_chain_expiry.py::test_j4_one_idea_on_the_previous_chain_refuses_the_whole_day PASSED [ 19%]
tests/test_watchlist_fno_chain_expiry.py::test_j5_a_retry_after_the_chain_arrives_builds_once_and_then_skips PASSED [ 23%]
tests/test_watchlist_fno_chain_expiry.py::test_j6_skip_if_done_with_the_day_stored_builds_nothing PASSED [ 28%]
tests/test_watchlist_fno_chain_expiry.py::test_j7_dry_run_applies_the_same_check_and_never_writes PASSED [ 33%]
tests/test_watchlist_fno_chain_expiry.py::test_j8_every_chain_day_is_recorded_and_the_cash_half_is_unchanged PASSED [ 38%]
tests/test_watchlist_fno_chain_expiry.py::test_e1_sessions_to_expiry_counts_weekdays_after_the_chain_day[2026-10-27-2026-10-27-0] PASSED [ 42%]
tests/test_watchlist_fno_chain_expiry.py::test_e1_sessions_to_expiry_counts_weekdays_after_the_chain_day[2026-10-27-2026-10-26-0] PASSED [ 47%]
tests/test_watchlist_fno_chain_expiry.py::test_e1_sessions_to_expiry_counts_weekdays_after_the_chain_day[2026-10-26-2026-10-27-1] PASSED [ 52%]
tests/test_watchlist_fno_chain_expiry.py::test_e1_sessions_to_expiry_counts_weekdays_after_the_chain_day[2026-10-23-2026-10-26-1] PASSED [ 57%]
tests/test_watchlist_fno_chain_expiry.py::test_e1_sessions_to_expiry_counts_weekdays_after_the_chain_day[2026-10-22-2026-10-27-3] PASSED [ 61%]
tests/test_watchlist_fno_chain_expiry.py::test_e1_sessions_to_expiry_counts_weekdays_after_the_chain_day[2026-10-26-2026-11-24-21] PASSED [ 66%]
tests/test_watchlist_fno_chain_expiry.py::test_e2_e3_a_chain_dated_an_expiry_day_uses_the_next_expiry_and_records_the_skipped_one PASSED [ 71%]
tests/test_watchlist_fno_chain_expiry.py::test_e4_no_qualifying_expiry_drops_the_underlying_with_the_reason PASSED [ 76%]
tests/test_watchlist_fno_chain_expiry.py::test_e5_a_requested_expiry_on_the_chain_day_is_refused_without_a_chain_read PASSED [ 80%]
tests/test_watchlist_fno_chain_expiry.py::test_e6_a_chain_that_moved_to_the_expiry_day_between_the_reads_is_refused PASSED [ 85%]
tests/test_watchlist_fno_chain_expiry.py::test_e7_the_constant_is_the_one_control PASSED [ 90%]
tests/test_watchlist_fno_chain_expiry.py::test_e8_the_rule_is_stated_with_the_boards_notes_and_tells_no_one_to_trade PASSED [ 95%]
tests/test_watchlist_fno_chain_expiry.py::test_c1_the_job_runs_after_the_last_fno_bhavcopy_ingest_with_retries_under_a_lock PASSED [100%]
======================== 21 passed, 2 warnings in 6.51s ========================
```

| Case | Test | Result |
|------|------|--------|
| J-1 … J-8 | `test_j1` … `test_j8` (J-6 also existing `test_skip_if_done_with_the_day_stored_builds_nothing`) | PASS |
| E-1 … E-8 | `test_e1` … `test_e8` | PASS |
| C-1 | `test_c1` | PASS |
| existing | `test_regime_fit.py`, `test_regime_fit_distinct.py`, `test_ai_watchlist.py`, `test_strategy_ideas.py`, `test_fno_routes.py` | PASS (in the 227) |

`test_ai_watchlist.py` change: its `job_env` stub board had no chain at all, which the new gate correctly refuses; the
stub now reads a chain on the list date. `test_route_with_nothing_stored_yet_says_when_the_job_runs` now expects
"22:45 IST" (the route's empty-state text follows the cron).

### Mutation check: the new tests fail on the old behaviour

The new suite was run against two copies of the branch: (a) the job gate removed (`why = None`), and (b) the old
nearest-expiry choice restored (`chosen = rows[0]["expiry"]`, re-check removed). Output (unedited):

```
== mutant: gate
FAILED tests/test_watchlist_fno_chain_expiry.py::test_j2_previous_sessions_chain_is_refused_with_exit_4_and_nothing_written
FAILED tests/test_watchlist_fno_chain_expiry.py::test_j3_no_chain_at_all_is_refused_with_the_boards_reasons
FAILED tests/test_watchlist_fno_chain_expiry.py::test_j4_one_idea_on_the_previous_chain_refuses_the_whole_day
FAILED tests/test_watchlist_fno_chain_expiry.py::test_j5_a_retry_after_the_chain_arrives_builds_once_and_then_skips
FAILED tests/test_watchlist_fno_chain_expiry.py::test_j7_dry_run_applies_the_same_check_and_never_writes
5 failed, 16 passed, 2 warnings in 6.77s
== mutant: expiry
FAILED tests/test_watchlist_fno_chain_expiry.py::test_e2_e3_a_chain_dated_an_expiry_day_uses_the_next_expiry_and_records_the_skipped_one
FAILED tests/test_watchlist_fno_chain_expiry.py::test_e4_no_qualifying_expiry_drops_the_underlying_with_the_reason
FAILED tests/test_watchlist_fno_chain_expiry.py::test_e6_a_chain_that_moved_to_the_expiry_day_between_the_reads_is_refused
FAILED tests/test_watchlist_fno_chain_expiry.py::test_e7_the_constant_is_the_one_control
4 failed, 17 passed, 2 warnings in 6.48s
```

### Full backend suite, branch vs base

The whole `tests/` directory was run on the branch and on an export of base 5b6b3cfd (`git archive 5b6b3cfd backend
deploy`), both concurrently in the same sandbox, with `--continue-on-collection-errors`. Then any FAILED/ERROR id
present on the branch but not on base was listed. Output (unedited):

```
== branch
ERROR tests/test_v3_portfolio_has_api.py::TestPerFundHas::test_category_field_valid
ERROR tests/test_v4_endpoints.py::test_nsdl_fixture_loads - FileNotFoundError...
580 failed, 5960 passed, 577 skipped, 39 warnings, 166 errors in 401.12s (0:06:41)
== base
ERROR tests/test_v3_portfolio_has_api.py::TestPerFundHas::test_category_field_valid
ERROR tests/test_v4_endpoints.py::test_nsdl_fixture_loads - FileNotFoundError...
621 failed, 5692 passed, 580 skipped, 41 warnings, 169 errors in 363.36s (0:06:03)
== failing on branch but not on base:

```

No test fails on the branch that passes on base; the list is empty. Both runs carry many failures from the sandbox,
which has no network, a read-only mount and no database (for example `test_cas_benchmark.py` writes into the mount).
These failures are not caused by this change. Base fails more because its export holds only `backend/` and `deploy/`,
so tests that read `docs/` or `frontend-v5/` fail there.

## 2. Staging proof (read-only)

### S-1 — the stored 2026-10-26 list (Mongo `ai_watchlist_days`, allow-list projection, env not printed)

```
2026-10-26 built_at 2026-10-26T18:14:56.706700+00:00 chain_as_of 2026-10-26 rules regime-fit-v1 (2026-10-22)
  01 BANKNIFTY    bear_put_spread    expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27']
  02 INDUSTOWER   bear_put_spread    expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27']
  03 PETRONET     long_put           expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27']
  04 UNIONBANK    bear_put_spread    expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27']
  05 DRREDDY      bear_put_spread    expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27']
  06 NIFTY        bear_put_spread    expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27']
  07 COFORGE      long_put           expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27']
  08 LAURUSLABS   bear_put_spread    expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27']
  09 MPHASIS      bear_put_spread    expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27']
  10 FEDERALBNK   bear_put_spread    expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27']
```

Chain date = list date; all ten expire 2026-10-27, one session after the chain. It passes both new rules at the default
(`MIN_SESSIONS_TO_EXPIRY = 1`). It is the only stored day.

### S-2 — the new board replayed in memory against the live chain (2026-10-26)

Method: the worktree's `regime_fit.py` and `ai_watchlist_build.py` were streamed as source into a fresh `python -`
inside `nivesh-staging-app-backend` (`docker exec -i`), loaded as in-memory modules over the container's package, and
`build_top(limit=10, classes=[index_options, stock_fno], distinct=True)` was called inside `deps.system_caller` exactly
as the job does. Nothing was written (no insert, no file; the board path is read-only, only process-local caches).
Every other module on the path (`routes/fno.py`, `candidates.py`, `selection.py`, `engine.py`, `routes/macro.py`,
`deps.py`) is byte-identical on staging to the branch base, checked with `cmp`. Script:
`/tmp/claude-1002/-home-deploy-nivesh-ai/ed913e2a-3741-4fc5-b4b0-5ab7c9f24ea5/scratchpad/replay_board_body.py`.
A first attempt ran the two passes in two `asyncio.run` calls and the second pass failed on the container's asyncpg pool
(bound to the first loop: "another operation is in progress"); it was rerun with both passes in one loop. Output of
the rerun at 02:58:45 IST (unedited; alternative rows trimmed for length, their count and check are in the totals line):

```
===== shipped default: rules regime-fit-v1.1 (2026-10-27), MIN_SESSIONS_TO_EXPIRY=1
-- index_options: chain as_of 2026-10-26, considered 17, rows 2
   ctx NIFTY       expiry 2026-10-27
   ctx BANKNIFTY   expiry 2026-10-27
   01 BANKNIFTY   bear_put_spread   expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27'] OK
   02 NIFTY       bear_put_spread   expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27'] OK
-- stock_fno: chain as_of 2026-10-26, considered 98, rows 10
   01 INDUSTOWER  bear_put_spread   expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27'] OK
   02 PETRONET    long_put          expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27'] OK
   03 UNIONBANK   bear_put_spread   expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27'] OK
   04 DRREDDY     bear_put_spread   expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27'] OK
   05 COFORGE     long_put          expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27'] OK
   06 LAURUSLABS  bear_put_spread   expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27'] OK
   07 MPHASIS     bear_put_spread   expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27'] OK
   08 FEDERALBNK  bear_put_spread   expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27'] OK
   09 ICICIBANK   bear_put_spread   expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27'] OK
   10 INDHOTEL    long_put          expiry 2026-10-27 dte 1 chain 2026-10-26 legs ['2026-10-27'] OK
offered contracts (rows + alternatives): 36; expiring on or before their chain day: 0
job F&O top 10: 1.BANKNIFTY 2026-10-27, 2.INDUSTOWER 2026-10-27, 3.PETRONET 2026-10-27, 4.UNIONBANK 2026-10-27, 5.DRREDDY 2026-10-27, 6.NIFTY 2026-10-27, 7.COFORGE 2026-10-27, 8.LAURUSLABS 2026-10-27, 9.MPHASIS 2026-10-27, 10.FEDERALBNK 2026-10-27
job gate for list date 2026-10-26: fno_chain_dates ['2026-10-26'] -> STORE (exit 0)
job gate for list date 2026-10-27: fno_chain_dates ['2026-10-26'] -> REFUSE (exit 4): the F&O option chain is from 2026-10-26, not the list date 2026-10-27
===== rule raised to 2 in memory (stand-in for an expiry-day chain): rules regime-fit-v1.1 (2026-10-27), MIN_SESSIONS_TO_EXPIRY=2
-- index_options: chain as_of 2026-10-26, considered 16, rows 2
   ctx NIFTY       expiry 2026-11-03  | 2026-10-27 skipped (expiry 2026-10-27 is 1 session(s) after the chain date 2026-10-26; at least 2 needed)
   ctx BANKNIFTY   expiry 2026-11-23  | 2026-10-27 skipped (expiry 2026-10-27 is 1 session(s) after the chain date 2026-10-26; at least 2 needed)
   01 BANKNIFTY   bear_put_spread   expiry 2026-11-23 dte 28 chain 2026-10-26 legs ['2026-11-23'] OK
   02 NIFTY       bear_put_spread   expiry 2026-11-03 dte 8 chain 2026-10-26 legs ['2026-11-03'] OK
-- stock_fno: chain as_of 2026-10-26, considered 92, rows 10
   ctx ICICIBANK   expiry 2026-11-23  | 2026-10-27 skipped (expiry 2026-10-27 is 1 session(s) after the chain date 2026-10-26; at least 2 needed)
   [ … the same skip line for UNIONBANK, KOTAKBANK, MPHASIS, COFORGE, LAURUSLABS, FEDERALBNK, INDHOTEL, DRREDDY, INDUSTOWER, PETRONET, BHARTIARTL … ]
   01 COFORGE     bear_put_spread   expiry 2026-11-23 dte 28 chain 2026-10-26 legs ['2026-11-23'] OK
   02 PETRONET    bear_put_spread   expiry 2026-11-23 dte 28 chain 2026-10-26 legs ['2026-11-23'] OK
   03 LAURUSLABS  bear_put_spread   expiry 2026-11-23 dte 28 chain 2026-10-26 legs ['2026-11-23'] OK
   04 BHARTIARTL  bear_put_spread   expiry 2026-11-23 dte 28 chain 2026-10-26 legs ['2026-11-23'] OK
   05 MPHASIS     bear_put_spread   expiry 2026-11-23 dte 28 chain 2026-10-26 legs ['2026-11-23'] OK
   06 KOTAKBANK   bear_put_spread   expiry 2026-11-23 dte 28 chain 2026-10-26 legs ['2026-11-23'] OK
   07 UNIONBANK   bear_put_spread   expiry 2026-11-23 dte 28 chain 2026-10-26 legs ['2026-11-23'] OK
   08 ICICIBANK   bear_put_spread   expiry 2026-11-23 dte 28 chain 2026-10-26 legs ['2026-11-23'] OK
   09 DRREDDY     bear_put_spread   expiry 2026-11-23 dte 28 chain 2026-10-26 legs ['2026-11-23'] OK
   10 FEDERALBNK  bear_put_spread   expiry 2026-11-23 dte 28 chain 2026-10-26 legs ['2026-11-23'] OK
offered contracts (rows + alternatives): 36; expiring on or before their chain day: 0
job F&O top 10: 1.COFORGE 2026-11-23, 2.PETRONET 2026-11-23, 3.LAURUSLABS 2026-11-23, 4.BHARTIARTL 2026-11-23, 5.MPHASIS 2026-11-23, 6.KOTAKBANK 2026-11-23, 7.BANKNIFTY 2026-11-23, 8.UNIONBANK 2026-11-23, 9.NIFTY 2026-11-03, 10.ICICIBANK 2026-11-23
job gate for list date 2026-10-26: fno_chain_dates ['2026-10-26'] -> STORE (exit 0)
job gate for list date 2026-10-27: fno_chain_dates ['2026-10-26'] -> REFUSE (exit 4): the F&O option chain is from 2026-10-26, not the list date 2026-10-27
```

Readings:
- At the shipped default, no offered contract (36 rows + alternatives) expires on or before its chain day. The job's
  F&O top 10 is identical, row for row, to the stored 26 Oct list (S-1).
- The gate stores list date 2026-10-26 (its own chain) and refuses list date 2026-10-27 (exit 4). That is exactly what
  tonight's 20:15 run would have met.
- With the rule at 2 in memory, the 27 Oct expiry (one session out) is skipped with its reason and the next listed
  expiry is used: NIFTY's weekly 2026-11-03; BANKNIFTY and stocks 2026-11-23 (the listed monthly). This is the same
  path an expiry-day chain takes at the default of 1.
- On the failed first attempt, the regime could not be read, and the gate refused both list dates: "the F&O board read
  no option chain … (the market regime is unavailable, so fit cannot be scored)". That is case J-3 on real data.

### S-3 — chain 2026-10-27: not yet available

NIDP (`~/.config/nivesh/nidp-psql.sh`, SQL on STDIN, read-only) at 02:59:15 IST on 2026-10-27:

```
 as_of_date | rows  |  first_ingest_ist   |   last_ingest_ist   | rows_expiring_on_or_before_day 
------------+-------+---------------------+---------------------+--------------------------------
 2026-10-19 | 38485 | 2026-10-20 22:15:03 | 2026-10-20 22:15:14 |                            208
 2026-10-21 | 38777 | 2026-10-21 22:15:04 | 2026-10-21 22:15:16 |                              0
 2026-10-22 | 39343 | 2026-10-22 22:15:03 | 2026-10-22 22:15:15 |                              0
 2026-10-23 | 40212 | 2026-10-23 22:15:03 | 2026-10-23 22:15:17 |                              0
 2026-10-26 | 40976 | 2026-10-26 22:15:04 | 2026-10-26 22:15:16 |                              0
(5 rows)
```

The 27 Oct F&O bhavcopy is not in the warehouse; it lands at about 22:15 IST tonight. The chain-2026-10-27 replay
could not run. The data confirms the timing defect: every day since 19 Oct was ingested at 22:15:03–22:15:17 IST. The
19 Oct file arrived on 20 Oct (20 Oct had no session), so under the new rule 19 Oct would not have been built.

## 3. What is UNVERIFIED and why

- **S-3** (chain 2026-10-27, an expiry-day chain at the default rule) cannot run before the 27 Oct F&O bhavcopy lands
  at about 22:15 IST. To close it, run the replay script above after 22:15 IST. Expect every 2026-10-27 expiry to be
  skipped, and the gate to store list date 2026-10-27.
- **Deployed behaviour.** The code is not deployed and the cron is not installed (owner approval needed). The first
  real 22:45 run and its log line (`stored 2026-10-27` or `refused … exit 4`) are unverified.
- **Holidays.** Sessions are counted as weekdays. At the default of 1 this is exact for any weekday expiry. If the
  constant is raised, an exchange holiday between the chain day and the expiry counts as a session.

No `## Verdict: PASS` line. Every unit, mutation, S-1 and S-2 case above passed, but S-3 has not run and the change
is not deployed, so a PASS verdict for this test plan would be untrue today.
