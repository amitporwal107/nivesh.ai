# Deal ingest coverage repair — 2026-10-22

Test cases authored up front in `test_reports/deal_ingest_repair_TESTCASES.md`.
Scope: data-completeness repair of the bulk/block deal ingest. No feature design, no parameter,
no frozen configuration changed. The study evaluator and the frozen contracts were read only.

Files changed (left in the working tree, not committed):
- `backend/nidp/services/trendlyne_ownership/deals.py`
- `backend/nidp/migrations/181_trendlyne_deal_fetch_log.sql` (new)
- `backend/nidp/tests/services/test_trendlyne_deals_resume.py` (new)

---

## Step 1 — root cause, verified independently

### The feed really is truncated at A-G

```
=== BEFORE: trendlyne_deals totals ===
 legs  | symbols | min_sym |  max_sym
-------+---------+---------+-----------
 19787 |     328 | 360ONE  | GSPLTRANS
(1 row)

=== BEFORE: first-character histogram ===
 first_char | symbols | legs
------------+---------+------
 3          |       2 |   98
 6          |       1 |  197
 A          |      97 | 5562
 B          |      48 | 3587
 C          |      63 | 3660
 D          |      26 | 1738
 E          |      31 | 1550
 F          |      15 |  870
 G          |      45 | 2525
(9 rows)

=== BEFORE: any symbol outside 0-9 / A-G ? ===
 symbols_outside_0_9_a_g
-------------------------
                       0
(1 row)
```

### The frontier, and the job log

```
=== alphabetical position of the fetch frontier in the 984-candidate list ===
 last_fetched_position | first_unfetched_position | fetched | candidates
-----------------------+--------------------------+---------+------------
                   338 |                       16 |     328 |        984
(1 row)

=== retrieved_at dates present (is the skip-set day-scoped?) ===
 retrieved_on | symbols | legs
--------------+---------+-------
 2026-10-22   |     328 | 19787
(1 row)

=== attempted vs landed, from job_log metadata ===
 attempted | with_deals | calls_used
-----------+------------+------------
       341 |        328 |        341
(1 row)
```

### What I actually found, and where the diagnosis needed correcting

The job-log table is `nidp.job_log` (written by `nidp/shared/storage/job_log.py`); per-run figures
live in its `metadata` jsonb. **There was no `last_fetched_position` column or stored marker
anywhere.** `grep -rn last_fetched_position` over the repo hits exactly one file — another agent's
report — so that figure is *derived* (candidate list position of the last fetched symbol), not
read from a cursor. I reproduced it as 338 above. Stating this precisely matters, because it
means the old code had **no durable progress marker at all**; the only "resume" was the
day-scoped skip in `_symbols()`.

Reading `_symbols()` and `run()`, the truncation is the combination of **two** faults, not one:

- **D1 — the progress marker was day-scoped.** `_symbols()` skipped symbols whose
  `nidp.trendlyne_deals` rows carried `retrieved_at::date = current_date`, and ordered the rest
  `ORDER BY 1`. Within one day that does resume correctly (40 + 300 attempts are disjoint). But on
  a new day the skip-set is empty, so the alphabetical walk restarts at 'A' and re-pays for the
  same prefix. `retrieved_on` above shows a single date: there is nothing older to carry over.
- **D2 — the marker only recorded symbols that PRODUCED ROWS.** 341 attempted vs 328 landed means
  13 symbols were queried, legitimately had no deals, wrote nothing, and were therefore invisible
  to the skip-set — re-queried out of the shared budget on *every* run, forever.

There was also a latent third landmine: the `--refresh` branch in `run()` replaced the symbol list
with its own `ORDER BY 1` query, re-introducing alphabetical order even if `_symbols()` were fixed.

### The 6,873 figure, recomputed not copied

Recomputed from study 001's own frozen `universe_rule` (`turnover_lookback_sessions` 20,
`min_price_inr` 10, `min_trailing_median_turnover_inr` 1e8, series EQ) plus the evaluator's
`base`/`fwd` requirements, over the 9 formation dates:

```
 formation_date | eligible | eligible_queried | pct_visible
----------------+----------+------------------+-------------
 2026-01-12     |      650 |              187 |        28.8
 2026-02-12     |      704 |              196 |        27.8
 2026-03-12     |      681 |              194 |        28.5
 2026-04-13     |      784 |              223 |        28.4
 2026-05-12     |      797 |              219 |        27.5
 2026-06-12     |      801 |              217 |        27.1
 2026-07-13     |      827 |              226 |        27.3
 2026-08-12     |      798 |              219 |        27.4
 2026-09-15     |      831 |              229 |        27.6
                |     6873 |             1910 |        27.8
(10 rows)
```

6,873 eligible symbol-dates and 1,910 visible (27.8%) reproduce the diagnosis exactly.
I did **not** reproduce the contamination (unexplained-move) exclusion, which would shave a small
number off `eligible`; noted as a deviation below.

---

## Step 2 — the fix, and why this option

**Chosen: order candidates by staleness (least-recently-attempted first), backed by a new durable
per-symbol attempt log `nidp.trendlyne_deal_fetch_log` (migration 181).** Rejected: a persisted
positional cursor. A position into an `ORDER BY 1` list is only meaningful while the list is
unchanged — any listing/delisting shifts every later index, and a "last symbol done" cursor
permanently skips newly-added symbols that sort earlier. Staleness ordering needs no
reconciliation: a symbol new to the candidate list simply has no log row, so it sorts first.

Three properties the task asked for:

- **Durable marker.** An *attempt* is recorded for every symbol asked about, with status
  `OK` / `EMPTY` / `ERROR`. Recording `EMPTY` is what closes D2. Nothing is recorded for symbols a
  budget break never reached, so the next run starts exactly there.
- **Cannot silently regress.** Progress is no longer inferred from the fact table, so absence of a
  deal row can never again be confused with absence of a question.
- **Reportable coverage.** `run()`'s summary now carries `candidates`, `attempted_ever`,
  `never_attempted`, `attempted_pct`, and those land in `job_log.metadata`.

Two deliberate details:

- The tie-break among never-attempted symbols is `md5(symbol)`, not `symbol`. Alphabetical order
  would still make any *partial* ingest an alphabetically biased sample — which is the defect
  itself. md5 is stable, so a resumed run continues the same order rather than reshuffling.
- The `--refresh` list override in `run()` was removed (`_symbols()` now honours `refresh`
  itself), because that branch was a second, independent route back to `ORDER BY 1`.

One adjacent change, in the same function: a run that attempted symbols but found no deals used to
finalize `FAILED` ("no deal rows"). That is now `OK`, keyed on `symbols_attempted`. Justification:
once coverage reaches genuinely deal-free names a zero-row run is *normal*, and `FAILED` climbs
`source_registry.consecutive_failures` and freezes `v_feed_status`. This run already produced 17
such symbols.

---

## Step 3 — the run, and the shared budget

Budget checked **before** running. The account cap is about 1,000 calls/day shared across NIDP
jobs (`DEFAULT_DAILY_BUDGET = 700` in `trendlyne_fundamentals/service.py`, commented "the
account's cap is about 1,000 a day and is shared").

Consumed today (IST) before my work: **589** — `trendlyne_deals` 341 + `trendlyne_ownership` 248,
from `job_log.metadata`. The daily `trendlyne_fundamentals` job (cron `10 6 * * *`, VM is IST) had
already had its slot at 06:10 IST and **consumed 0 budgeted calls**: it failed `HTTP 403 on
initialize` because it resolves its URL from `TRENDLYNE_MCP_URL` in `/opt/nidp-staging/nidp.env`,
which holds a revoked token. Its next scheduled run is tomorrow 06:10 IST, on a fresh budget day.
So today's remainder was not owed to a scheduled job.

I spent **250** calls (3 smoke + 247 main), taking the day to **839** and leaving roughly **161**
headroom. I did not raise `--max-calls` beyond that and did not touch the shared allowance
accounting.

```
=== shared Trendlyne budget consumed today (IST), all ingesters ===
 calls_today_joblog
--------------------
                839
(1 row)
```

Main run, tail of real output (piped through a token redactor):

```
msg":"trendlyne_deals: 984 candidate(s), 331 ever attempted (33.6%), 653 never attempted; 653 due this run"
msg":"trendlyne_deals: 25/653 symbols, 976 rows, budget 222 left"
msg":"trendlyne_deals: 100/653 symbols, 5458 rows, budget 147 left"
msg":"trendlyne_deals: 225/653 symbols, 12704 rows, budget 22 left"
severity":"WARNING","msg":"trendlyne_deals: budget spent after 247 of 653 symbol(s); re-run to continue from JPPOWER (progress is durable)"
msg":"job_log[trendlyne_deals] 93122117-8bbb-4fbd-b9c6-afc24082a8a6 status=OK fetched=13838 inserted=13838 skipped=0 duration=190769ms"
msg":"trendlyne_deals done: {'symbols_attempted': 247, 'symbols_with_deals': 230, 'rows_written': 13838, 'errors': 0, 'budget_limit': 247, 'calls_used': 247, 'candidates': 984, 'attempted_ever': 578, 'never_attempted': 406, 'attempted_pct': 58.7}"
```

**The ingest is NOT complete.** 406 of 984 candidates remain unqueried. At roughly 250 spare calls
a day that needs **two more days**, and it will resume by itself — the next run starts at JPPOWER,
not at 'A'.

---

## Step 4 — verification

### TC-11 — migration idempotent, backfill seeded

Applied twice; the second application emitted only skip notices:

```
=== apply #2 (idempotency) ===
NOTICE:  relation "trendlyne_deal_fetch_log" already exists, skipping
NOTICE:  relation "idx_tl_deal_fetch_log_attempt" already exists, skipping
```

```
=== TC-11: backfill seeded the already-fetched symbols ===
 log_rows |       oldest        |       newest        | legs_accounted
----------+---------------------+---------------------+----------------
      328 | 2026-10-22 04:05:57 | 2026-10-22 04:10:02 |          19787
(1 row)

=== every symbol with deal rows now has a log row (0 = good) ===
 deal_symbols_missing_from_log
-------------------------------
                             0
(1 row)
```

Without that seed the first post-fix run would have seen all 984 as never-attempted and started at
'A' again.

### TC-12 — the alphabetic range broke out of A-G

```
=== AFTER: trendlyne_deals totals ===
 legs  | symbols | min_sym |  max_sym
-------+---------+---------+-----------
 33290 |     561 | 360ONE  | ZYDUSWELL
(1 row)

=== AFTER: first-character histogram (was 0-9 and A-G only) ===
 first_char | symbols | legs
------------+---------+------
 3          |       2 |   98
 6          |       1 |  197
 A          |      97 | 5562
 B          |      48 | 3587
 C          |      63 | 3660
 D          |      26 | 1738
 E          |      31 | 1550
 F          |      15 |  870
 G          |      49 | 2788
 H          |      12 | 1020
 I          |      12 |  784
 J          |       9 |  607
 K          |      18 |  799
 L          |      11 |  470
 M          |      22 | 1012
 N          |      11 |  799
 O          |       4 |  188
 P          |      25 | 1645
 Q          |       1 |   51
 R          |      18 | 1115
 S          |      42 | 1921
 T          |      23 | 1475
 U          |       5 |  189
 V          |       5 |  437
 W          |       5 |  153
 Y          |       3 |  318
 Z          |       3 |  257
(27 rows)

=== AFTER: symbols beyond G (was exactly 0) ===
 symbols_beyond_g | legs_beyond_g
------------------+---------------
              229 |         13240
(1 row)
```

Every letter that exists in the candidate universe is now represented. The X gap is not a defect:

```
=== is there any X-initial candidate at all? (explains the X gap) ===
 x_initial_candidates
----------------------
                    0
(1 row)
```

### TC-13 — candidates queried at least once

```
=== candidate coverage: queried at least once, from the durable log ===
 candidates | queried_at_least_once | never_queried | pct_queried
------------+-----------------------+---------------+-------------
        984 |                   578 |           406 |        58.7
(1 row)

=== attempt-log status mix (EMPTY rows are the leak the old code re-paid for) ===
 last_status | count
-------------+-------
 EMPTY       |    17
 OK          |   561
(2 rows)
```

Those 17 `EMPTY` rows are D2 closed on real data: 17 stocks that genuinely have no disclosed deals
are now recorded as answered instead of being re-bought from the shared budget every run.

### The defect test on real data — a budget break no longer restarts at 'A'

The actual production ordering query from `deals.py`, run against the real DB after the budget
break:

```
=== DURABLE CURSOR PROOF: real production ordering SQL, next 12 up ===
 next_up |   symbol   | last_status
---------+------------+-------------
       1 | JPPOWER    |
       2 | JNKINDIA   |
       3 | LAXMIDENTL |
       4 | TRAVELFOOD |
       5 | VSTTILLERS |
       6 | OMNI       |
       7 | OSWALPUMPS |
       8 | KIMS       |
       9 | HDBFS      |
      10 | QUADFUTURE |
      11 | TATVA      |
      12 | SIEMENS    |
(12 rows)

=== and it is NOT the alphabetical head of the unqueried set ===
 alphabetical_head_would_have_been
-----------------------------------
 AGL
 BHARTIHEXA
 BRIGHOTEL
(3 rows)
```

`JPPOWER` is exactly where the run's own warning said it stopped. The old code would have offered
`AGL, BHARTIHEXA, BRIGHOTEL`.

### TC-8 on real data — a partial run reports its own coverage

```
=== coverage reached job_log.metadata (TC-8 on real data) ===
       started       | status | rows_inserted | calls | cand | attempted | never | pct
---------------------+--------+---------------+-------+------+-----------+-------+------
 2026-10-22 09:22:42 | OK     |           208 | 3     | 984  | 331       | 653   | 33.6
 2026-10-22 09:23:04 | OK     |         13838 | 247   | 984  | 578       | 406   | 58.7
(2 rows)
```

### TC-14 — the headline: what the overlay can now see

Recomputed, same query as before the run:

```
 formation_date | eligible | eligible_queried | pct_visible
----------------+----------+------------------+-------------
 2026-01-12     |      650 |              305 |        46.9
 2026-02-12     |      704 |              318 |        45.2
 2026-03-12     |      681 |              321 |        47.1
 2026-04-13     |      784 |              363 |        46.3
 2026-05-12     |      797 |              366 |        45.9
 2026-06-12     |      801 |              362 |        45.2
 2026-07-13     |      827 |              376 |        45.5
 2026-08-12     |      798 |              369 |        46.2
 2026-09-15     |      831 |              380 |        45.7
                |     6873 |             3160 |        46.0
(10 rows)
```

Separating "has a deal row" from "has been asked" (a stock asked about with no deals is a known
zero, not a blind spot):

```
 eligible_symbol_dates | asked_ever | pct_asked | has_deal_row | pct_with_deal_row
-----------------------+------------+-----------+--------------+-------------------
                  6873 |       3221 |      46.9 |         3160 |              46.0
(1 row)
```

**Headline: the overlay can now see 3,221 of 6,873 eligible symbol-dates — 46.9%, up from 27.8%.**
The "never asked" population fell from 4,963 symbol-dates to 3,652.

### Before / after

| Measure | Before | After |
|---|---|---|
| Legs in `nidp.trendlyne_deals` | 19,787 | 33,290 |
| Distinct symbols | 328 | 561 |
| Alphabetic range | `360ONE`..`GSPLTRANS`, nothing past G | `360ONE`..`ZYDUSWELL`, every letter present bar X (no X candidate exists) |
| Symbols past G | 0 | 229 (13,240 legs) |
| Candidates queried ≥ once | 341 attempted / 328 landed, of 984 | 578 of 984 (58.7%) |
| Eligible symbol-dates asked about | 1,910 / 6,873 (27.8%) | 3,221 / 6,873 (46.9%) |
| Durable progress marker | none (inferred from facts, day-scoped) | `nidp.trendlyne_deal_fetch_log`, 578 rows |
| Trendlyne calls used today | 589 | 839 (~161 headroom) |

### TC-1..TC-10 — unit tests

```
nidp/tests/services/test_trendlyne_deals_resume.py::test_budget_break_does_not_restart_at_a PASSED [ 10%]
nidp/tests/services/test_trendlyne_deals_resume.py::test_never_attempted_sorts_before_attempted PASSED [ 20%]
nidp/tests/services/test_trendlyne_deals_resume.py::test_zero_deal_symbol_is_recorded_and_not_requeried PASSED [ 30%]
nidp/tests/services/test_trendlyne_deals_resume.py::test_errored_symbol_is_recorded_and_does_not_block PASSED [ 40%]
nidp/tests/services/test_trendlyne_deals_resume.py::test_new_candidate_jumps_the_queue PASSED [ 50%]
nidp/tests/services/test_trendlyne_deals_resume.py::test_tie_break_among_never_attempted_is_not_alphabetical PASSED [ 60%]
nidp/tests/services/test_trendlyne_deals_resume.py::test_refresh_includes_todays_symbols PASSED [ 70%]
nidp/tests/services/test_trendlyne_deals_resume.py::test_partial_run_reports_coverage PASSED [ 80%]
nidp/tests/services/test_trendlyne_deals_resume.py::test_unreached_symbols_are_not_marked_attempted PASSED [ 90%]
nidp/tests/services/test_trendlyne_deals_resume.py::test_zero_row_run_is_not_a_feed_failure PASSED [100%]

============================== 10 passed in 0.14s ==============================
```

### TC-16 — regression gate

Baseline, captured this session before any change:

```
51 failed, 1281 passed, 5 skipped, 23 warnings in 10.62s
```

After the change (same command, same container):

```
51 failed, 1291 passed, 5 skipped, 23 warnings in 10.30s
```

Same 51 pre-existing failures; +10 passed, which are exactly the new tests. Not made worse.

---

## UNVERIFIED / deviations / out of scope

- **UNVERIFIED: the ingest is not complete.** 406 of 984 candidates have never been queried. I ran
  as far as the shared budget safely allowed and stopped; completion needs about two more days at
  ~250 spare calls/day. Resume is proven to work, but I have not observed the final run.
- **UNVERIFIED: my eligible-universe recompute omits the contamination filter.** The evaluator also
  drops symbol-days with an unexplained ≥35% move (`_UNEXPLAINED_MOVE_SQL`). My 6,873 excludes that
  step, so the true `eligible` denominator is slightly lower. Since the figure reproduces the
  diagnosis exactly, the diagnosis appears to have used the same three conditions. The
  before/after percentages use an identical query, so the *change* is unaffected.
- **UNVERIFIED: the vendor's real remaining quota.** ~1,000/day is the figure recorded in the
  codebase, not something the API reports. I inferred today's usage from `job_log.metadata`; I did
  not probe the vendor for its own counter.
- **UNVERIFIED: the per-stock 200-row vendor cap.** Study 002's contract records that the feed
  returns at most 200 rows per stock, so heavily-dealt names remain truncated in *history* even at
  full symbol coverage. Unchanged by this repair and not measured here.
- **The unit tests stub the warehouse**, so they prove the ordering *semantics* and assert against
  the real SQL text (no `ORDER BY 1`, `NULLS FIRST` present). The real SQL itself is exercised
  against the staging DB in the cursor proof above.
- **Not touched:** `smart_money_study/evaluator.py` and its outputs (owned elsewhere; the rerun is
  deliberately left until the price-history backfill also lands), and the frozen contracts
  `NIDP-SM-VALIDATION-001.json` / `-002.json`, which were read only. Study C stays in shadow mode.
- Changes are left in the working tree. Nothing committed or pushed.

## Two findings outside my scope, reported not fixed

1. **A credential is leaking into a log file.** `/opt/nidp-staging/logs/trendlyne_fundamentals/trendlyne_fundamentals.log`
   contains httpx `INFO` lines with the full MCP URL including the `token=` query parameter.
   `trendlyne_ownership/client.py` silences the httpx loggers at import precisely to stop this, but
   `trendlyne_fundamentals` uses its own client module and does not. The token is on disk on the
   staging VM and would also reach Loki. I did not reproduce the value anywhere, and I piped every
   command's output in this session through a redactor. Fixing it means either silencing those
   loggers there too or moving the token out of the URL.
2. **The shared budget ledger is incomplete.** `trendlyne_fundamentals` checks its daily allowance
   by counting `nidp.trendlyne_call_log`, but `trendlyne_deals` and `trendlyne_ownership` never
   write to that table — today they spent 839 calls that the ledger reports as 0. The daily job can
   therefore believe it has 700 calls available when the account has far fewer. I deliberately did
   not change this: making the deals job write to that ledger would alter accounting another
   service reads and could starve the daily job. It needs a decision, not a drive-by fix.

## Verdict: PASS
