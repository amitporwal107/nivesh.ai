# Test cases — bulk/block deal ingest coverage repair

Authored BEFORE implementation, per `.claude/VERIFICATION_PROTOCOL.md`.
Target: `backend/nidp/services/trendlyne_ownership/deals.py` + migration for a durable
per-symbol attempt log. Evidence lands in `test_reports/deal_ingest_repair_20261022.md`.

## The defect under test

`_symbols()` ordered its candidate list `ORDER BY 1` (alphabetical) and inferred "already done"
from the FACT table (`nidp.trendlyne_deals WHERE retrieved_at::date = current_date`). Two
independent faults combine into the observed truncation:

- **D1 — the progress marker is day-scoped.** On a new day the skip-set is empty, so the
  alphabetical walk restarts at 'A'. With a per-run budget smaller than the candidate list, the
  same prefix is re-paid for every day and the tail is never reached.
- **D2 — the marker only records symbols that PRODUCED ROWS.** A symbol queried with no deals
  writes nothing, is never recorded as attempted, and is re-queried on every run forever.

A test that merely asserts "rows arrived" would pass on the broken code. The tests below target
the resume behaviour itself.

## Unit / behavioural cases (pytest, no API calls)

| ID | Case | Pass condition |
|----|------|----------------|
| TC-1 | Never-attempted candidates sort before already-attempted ones | `_symbols()` returns all never-attempted symbols ahead of every symbol carrying a `last_attempt_at` |
| TC-2 | **A budget break does not restart at 'A'** (the actual defect, D1) | With candidates A..J and budget 3: run 1 takes 3 symbols; run 2 takes 3 *different* symbols; the two sets are disjoint and run 2's first symbol is not run 1's first symbol. Asserted across a simulated day boundary, not just within one day |
| TC-3 | A zero-deal symbol is still recorded as attempted (D2) | After a call that parses 0 deals, the symbol has a fetch-log row with status `EMPTY`; the next run does not re-query it |
| TC-4 | An errored symbol is recorded and does not block the queue | After `TrendlyneError`, the symbol has status `ERROR` and a fresh `last_attempt_at`; the next run proceeds to other symbols instead of re-paying for it |
| TC-5 | Ordering is robust when the candidate list changes between runs | A symbol added to the candidate list after earlier runs is fetched before any already-attempted symbol is re-fetched; a symbol dropped from the list is simply absent. No positional index is stored that could go stale |
| TC-6 | The tie-break among never-attempted symbols is not alphabetical | Ordering of a never-attempted set is stable across calls but is not `sorted(symbols)`, so a permanently-partial ingest is not alphabetically biased |
| TC-7 | `--refresh` re-attempts today's symbols, still staleness-ordered | With `refresh=True` a symbol attempted today is included, and the emitted SQL contains no `ORDER BY 1` |
| TC-8 | A partial run's coverage is reportable | `run()`'s summary carries `candidates`, `attempted_ever`, `never_attempted`, `attempted_pct`, and those reach `job_log.metadata` |
| TC-9 | Budget exhaustion is not recorded as an attempt | When the budget break stops the loop, the unreached symbols have no fetch-log row, so the next run still sees them as never-attempted |
| TC-10 | A zero-row run is not reported as a feed FAILURE | A run that attempted symbols but found no deals finalizes `OK`, not `FAILED` (otherwise `source_registry.consecutive_failures` climbs and `v_feed_status` freezes once coverage reaches genuinely deal-free names) |

## Data cases (real staging DB, real output required)

| ID | Case | Pass condition |
|----|------|----------------|
| TC-11 | Migration is idempotent and backfills known history | Applying it twice succeeds; afterwards every symbol already in `nidp.trendlyne_deals` has a fetch-log row, so the first post-fix run does not re-walk A-G |
| TC-12 | Alphabetic range breaks out of A-G | After the real run, `nidp.trendlyne_deals` contains at least one symbol whose first character is > 'G' |
| TC-13 | Candidate coverage rises | Count of the 984 candidates attempted at least once is strictly greater after than before, measured from the durable log |
| TC-14 | Study-eligible coverage recomputed, not copied | The eligible symbol-date total is recomputed from the study's own `universe_rule`; before/after visibility percentages shown |
| TC-15 | Shared call budget respected | Calls consumed today, before and after the run, shown from `nidp.job_log` metadata; the run leaves documented headroom under the ~1,000/day account cap |

## Regression gate

| ID | Case | Pass condition |
|----|------|----------------|
| TC-16 | Test suite no worse than baseline | `python -m pytest nidp/tests -q -p no:cacheprovider` in `nidp-daas-api-staging` is no worse than the recorded baseline of 51 failed, 1281 passed, 5 skipped |

## Out of scope (explicitly not touched)

- The study evaluator and its outputs (`smart_money_study/evaluator.py`) — owned elsewhere; the
  rerun happens after this repair and a separate price-history backfill.
- The frozen contracts `NIDP-SM-VALIDATION-001.json` / `-002.json` — read only.
- No feature design, parameter or frozen configuration changes. This is a data-completeness repair.
