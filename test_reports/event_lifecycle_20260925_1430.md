# Functionality Verification Report — Corporate transaction lifecycle (Phase 1, buyback-first)

- **Branch:** feat/event-lifecycle-engine (off dev @43643094)
- **Date:** 2026-09-25
- **Author:** Claude (full-stack-developer + qa-engineer)
- **Environment:** staging (nidp_staging on nidp-stack-vm)
- **Changed areas:** backend services: **yes** (`nidp/services/event_lifecycle/`, migration 155) · frontend src: **no**

## Summary

PRD v1.1 §3/§5.1 require one `transaction_id` spanning a deal's filings, with sample sizes counted
in transactions and never in filings. A repo-wide grep for `transaction_id | event_group |
parent_event | deal_id` returned nothing; `stock_events` is one row per filing. One real buyback
(MATRIMONY, 2026-01-20..02-26) is 12 filings across both exchanges — counting those as 12 events
would inflate a cohort twelvefold.

Built buyback-first, with persistence shaped so QIP/preferential arriving later is a **data
backfill, not a schema change**. Three properties were required and are each tested below:
classification stored separately from filings with provenance; the unreadable case explicit as
`UNRESOLVED` rather than disguised as data; and a **family-level** `lifecycle_ready` gate.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | data | Both families persisted; gate set per family | data | BUYBACK ready, QIP not | PASS |
| TC-2 | data | Cohort view excludes QIP and unreadable txns | data | buyback only | PASS |
| TC-3 | data | Provenance recorded per filing | data | subject/description/none | PASS |
| TC-4 | data | UNRESOLVED ⇔ source `none`, nothing else | data | clean partition | PASS |
| TC-5 | e2e | MATRIMONY 12 filings → one transaction_id | data | full lifecycle | PASS |
| TC-6 | service | Rebuild is idempotent | e2e | identical hash | PASS |
| TC-7 | service | Document stage survives a metadata re-run | failure | guard holds | **FAIL→FIXED** |
| TC-8 | unit/data | SQL rank fn agrees with Python SOURCE_RANK | unit | identical | PASS |
| TC-9 | unit | Classifier rules (families, stages, grouping) | unit | 21 passed | PASS |
| TC-10 | data | filing_count/unresolved_count match reality; no orphans | data | 0 mismatches | PASS |

## Unit tests

```
$ /app/research/tpd3_forward/venv/bin/python -m pytest nidp/tests/services/test_event_lifecycle.py -q
.....................                                                    [100%]
21 passed in 0.05s
```

## Migration 155 (staging)

```
$ docker exec -i nidp-postgres-staging psql -U nidp_staging -d nidp_staging \
    -v ON_ERROR_STOP=1 < nidp/migrations/155_corporate_transactions.sql
NOTICE:  relation "idx_corp_txn_filings_symbol" already exists, skipping
CREATE INDEX
CREATE INDEX
NOTICE:  relation "idx_corp_txn_filings_unresolved" already exists, skipping
CREATE VIEW
COMMENT
```

## Service run (staging)

```
$ PYTHONPATH=... /opt/nidp-staging/venv/bin/python -m nidp.services.event_lifecycle --build
2026-09-25 14:25:26,549 INFO corporate_transactions: 176 transactions, 396 filings (lifecycle-v1)
{
 "candidates_scanned": 434, "transactions": 176, "filings": 396,
 "filings_unresolved_stage": 185, "filings_staged": 211, "confounded": 9,
 "readiness": [
  {"family": "BUYBACK",  "lifecycle_ready": true,  "transactions": 34,
   "filings": 151, "unresolved": 27,  "confounded": 5, "txns_with_no_readable_stage": 1},
  {"family": "QIP_PREF", "lifecycle_ready": false, "transactions": 142,
   "filings": 245, "unresolved": 158, "confounded": 4, "txns_with_no_readable_stage": 72}
 ]
}
```

A first `--build` raised `asyncpg TimeoutError`: the query scanned all 219,538 announcements
through view 154's LATERAL join. Fixed with a coarse SQL prefilter (~450 candidate rows); the
prefilter is deliberately **wider** than the classifier, which still makes every accept/reject
decision — 434 scanned, 396 accepted, 38 rejected as debt buybacks, Reg-32 deviation statements
and warrant conversions.

## TC-1/2/3/4 — the three required properties (staging)

```
  family  | lifecycle_ready | txns | filings | unresolved | confounded
----------+-----------------+------+---------+------------+------------
 BUYBACK  | t               |   34 |     151 |         27 |          5
 QIP_PREF | f               |  142 |     245 |        158 |          4

 family  | in_cohort          <- v_corporate_transactions_ready
---------+-----------
 BUYBACK |        33          QIP absent by the family gate; 1 buyback txn
                              dropped for having no readable stage at all

  family  | stage_source | count
----------+--------------+-------
 BUYBACK  | subject      |   101
 BUYBACK  | none         |    27
 BUYBACK  | description  |    23
 QIP_PREF | none         |   158
 QIP_PREF | subject      |    71
 QIP_PREF | description  |    16

 is_unresolved | stage_source | count
---------------+--------------+-------
 f             | description  |    39
 f             | subject      |   172
 t             | none         |   185
```

TC-4 is the one that matters for honesty: `UNRESOLVED` appears with source `none` and **never**
with a real source, and no resolved stage carries `none`. The partition is clean, so a consumer
cannot mistake "could not read" for "read as nothing happened".

## TC-5 — MATRIMONY: 12 filings, one transaction

```
  filed_on  | source  |    stage     | stage_source
------------+---------+--------------+--------------
 2026-01-20 | BSE_ANN | RECORD_DATE  | subject
 2026-01-20 | NSE_ANN | UNRESOLVED   | none
 2026-01-22 | BSE_ANN | APPROVED     | subject
 2026-01-22 | BSE_ANN | ANNOUNCED    | subject
 2026-01-22 | NSE_ANN | ANNOUNCED    | subject
 2026-02-03 | BSE_ANN | OFFER_OPEN   | subject
 2026-02-03 | NSE_ANN | UNRESOLVED   | none
 2026-02-06 | NSE_ANN | UNRESOLVED   | none
 2026-02-20 | BSE_ANN | OFFER_CLOSED | subject
 2026-02-20 | NSE_ANN | OFFER_CLOSED | subject
 2026-02-26 | BSE_ANN | COMPLETED    | subject
 2026-02-26 | NSE_ANN | UNRESOLVED   | none
```

This is the argument for transaction-level grouping in one table. NSE files the bare subject
`"Buyback"` for four different steps — unreadable in isolation. BSE carries the readable lifecycle.
Grouped, the transaction reconstructs record date → approval → announcement → offer → close →
extinguishment. Per-filing analysis would have discarded the NSE rows or, worse, counted them as
four separate events.

## TC-6 — idempotency

```
before: 696abfb7bc563790e50a161642aa874a   (176 transactions)
after : 696abfb7bc563790e50a161642aa874a   (176 transactions)
```

## TC-7 — provenance guard: a real defect, found and fixed

The guard is what makes the QIP backfill safe. Tested by writing a document-derived stage onto an
UNRESOLVED QIP filing, then re-running the metadata build that would otherwise reclaim it.

**First run — FAILED:**

```
before_rerun:  OFFER_OPEN | document | lifecycle-v1+doc
after_rerun :  OFFER_OPEN | document | lifecycle-v1        <- attribution lost
```

`stage` and `stage_source` were guarded but `classifier_version` was not, so the row kept a
document-derived stage while claiming a classifier that did not produce it. That is the same
silent-wrong-answer shape as the `UPDATE` fallback: a field that looks like data but is not.

Root cause was that the rank ordering existed **twice** — `lifecycle.SOURCE_RANK` in Python and an
inline `CASE` repeated in the writer's SQL. Fixed by defining it once as
`nidp.stage_source_rank()` in migration 155, making all three fields move together under one
condition, and adding TC-8 to pin the two definitions to each other.

**After fix — PASS:**

```
before_rerun:  OFFER_OPEN | document | lifecycle-v1+doc
after_rerun :  OFFER_OPEN | document | lifecycle-v1+doc
doc_rows_downgraded_to_none: 0
```

Probe row restored to `UNRESOLVED | none | lifecycle-v1`; `doc_rows_remaining: 0`.

## TC-8 — the two rank definitions agree

```
 stage_source | sql_rank
--------------+----------
 none         |        0
 subject      |        1
 description  |        2
 document     |        3
 bogus        |        0
 (NULL)       |        0
```

The Python test parses the migration and compares. It initially failed for the right reason — a
non-greedy regex matched the opening `$$` and compared an empty dict — so a guard assertion was
added that the parse yields 4 entries, preventing a vacuous pass.

## TC-10 — denormalised counters match reality

`filing_count` and `unresolved_count` are denormalised onto `corporate_transactions`, and cohort
sample sizes are counted off them. Nothing in the schema constrains them, so they were checked
against the filings directly:

```
 orphan_filings | count_mismatches | unresolved_mismatches
----------------+------------------+-----------------------
              0 |                0 |                     0

 stage_source | count        <- probe restored; no simulated document rows remain
--------------+-------
 none         |   185
 subject      |   172
 description  |    39
```

## Not verified

- QIP/preferential stage quality is **not** claimed. 158 of 245 QIP filings are UNRESOLVED; the
  family is gated out of cohorts by `lifecycle_ready = false`.
- The buyback **gold set is not yet labelled**, so the PRD §15.2 ≥97% accuracy gate is untested.
  Nothing here should be read as evidence that classification is accurate — only that it is
  persisted, provenanced, idempotent and honest about what it could not read.
- Not wired into any scheduler.

## Verdict: PASS
