# Functionality Verification Report — embed scope: backfilled documents were unembeddable

- **Branch:** fix/filing-insights-period-sentiment, **rebased onto origin/dev @ 33291760**
- **Date:** 2026-07-19
- **Scope note (post-rebase):** this branch was cut down to the two changes that are
  still novel against `dev`. The filing-insights placeholder fix, migration 129, the
  Sentiment tab, `impact_matrix.py` and the denominator join were all **dropped as
  redundant** — superseded upstream by `04292a04` (identical `_NULLISH` fix, plus
  read-side normalisation instead of a migration), `919c96d6` (Filings Intelligence
  rebuild with a generator `sections` field driving the four tabs), `2256dcc8`
  (`NIDP_EMBED_DIM` Matryoshka truncation) and `96d472d0` (default back to
  text-embedding-3-small). Their reports were withdrawn with them.
- **Author:** Claude (full-stack-developer + qa-engineer)
- **Environment:** **staging** — `nidp-postgres-staging` on nidp-stack-vm, db `nidp_staging`, via IAP. **Read-only SELECT/EXPLAIN only.** No embed job was triggered; no writes.
- **Changed areas:** backend services: yes (`document_parser/db.py`, one predicate) · frontend src: no

## Summary

`_FETCH_UNEMBEDDED_SQL` scoped the embed drain on `d.filed_at` alone. A backfill
supplies documents with an **old filing date and a new ingestion date**, so every
backfilled document was parsed, chunked, and then never selected for embedding —
permanently. The drain reported zero pending while the material silently had no
vectors.

Fix: scope on `GREATEST(d.filed_at, d.ingested_at)`.

## Test Cases

| ID | Scenario | Type | Expected | Result |
|----|----------|------|----------|--------|
| TC-1 | edited modules compile | build | py_compile clean | **PASS** |
| TC-2 | modified SQL parses and plans on staging | data | EXPLAIN succeeds | **PASS** |
| TC-3 | LIMIT still stops early (no full-scan regression) | data | early-stop cost retained | **PASS** |
| TC-4 | old predicate's eligible set | data | quantified | **PASS** — 0 |
| TC-5 | new predicate's eligible set | data | the stranded backfill becomes eligible | **PASS** — 1,336,164 |
| TC-6 | HDFC Life transcripts become eligible | data | all 3 eligible | **PASS** |
| TC-7 | existing filing_insights suites unaffected | unit | 73 pass | **PASS** |
| TC-8 | embed drain actually produces vectors after the fix | **runtime** | chunks gain embeddings | **NOT RUN** — requires running the job |

## Evidence

### TC-1 — compile

```
py_compile: OK (5 files)
```

### TC-4 / TC-5 — the bug, quantified

```
 eligible_old | eligible_new
--------------+--------------
            0 |      1336164
```

The **current** predicate selects zero unembedded chunks. The drain is not slow or
queued — it is complete by its own definition and will never do further work, while
1,423,140 chunks lack vectors. 1,336,164 of those (94%) were ingested within 30 days
but filed outside it.

This is precisely the failure mode the project README calls out: *"A green cron
embedding 200/200 hid a 640K backlog. Alert on backlog delta/hour and oldest-item
age."* A run reporting nothing pending is fully consistent with a backlog that can
never become pending.

### TC-6 — the reported case

```
   filed    |  ingested  | unembedded | eligible_after_fix
------------+------------+------------+--------------------
 2026-04-23 | 2026-07-17 |         46 | t
 2026-04-16 | 2026-07-17 |          1 | t
 2026-01-22 | 2026-07-17 |         37 | t
```

Includes the 46-chunk April earnings call carrying HDFC Life's VNB margin bridge and
FY27 Ind AS statement.

### TC-2 / TC-3 — EXPLAIN of the real modified query

```
 Limit  (cost=0.00..2055.14 rows=100 width=1460)
   ->  Seq Scan on document_chunks  (cost=0.00..5059024.40 rows=246165 width=1460)
         Filter: ((embedding IS NULL) AND (text IS NOT NULL) AND (length(btrim(text)) > 0) AND (hashed SubPlan 2))
         SubPlan 2
           ->  Seq Scan on documents d  (cost=0.00..12328.26 rows=57338 width=16)
                 Filter: (GREATEST(filed_at, ingested_at) >= (now() - '30 days'::interval))
```

**Plan change worth recording:** with `GREATEST()` the planner hashes the EXISTS into
a one-off seq scan of `documents` (~57k rows, cost ~12k) and probes that hash per
candidate, instead of the per-row PK lookup the plain `filed_at` form produced. The
in-code comment asserted the PK-lookup mechanism; it was updated to match the actual
plan rather than left describing something that no longer happens. The LIMIT still
stops early (cost 2055 for the first 100 rows), so the regression the original
comment guarded against has not returned.

### TC-7 — no regression in the branch's other work

```
73 passed in 0.16s
```

## Cost consequence (corrected 2026-07-19, after measurement)

An earlier revision of this report estimated ~57 hours and ~$16, assuming the
self-hosted bge-base CPU path. **Both figures were wrong**: commit `96d472d0` already
defaults `NIDP_EMBED_MODEL` back to `text-embedding-3-small` (bge was silently mixing
vector spaces), so this is an API job, not a CPU job.

Measured on staging:

- **Volume:** 1,336,164 chunks, ~583M tokens gross.
- **Dedupe:** a 200k-row sample showed 48.3% duplicate text; commit `1da6115c`
  (content-addressed memoization, `nidp.embedding_cache`, already holding 224,750
  rows) measured 28%. The sample used `LIMIT` without `ORDER BY`, so it is
  physical-row order and clusters same-document chunks — it likely OVERSTATES the
  rate. Plan on the 28% end.
- **Cost:** ~420M billable tokens at 28% dedupe → **~$8.40**; ~$6.00 at 48%. Under
  $10 either way. Cross-checks against the project's own measured "$2 per 208k
  chunks".
- **Time:** ~5,400–7,500 API calls at `_MAX_BATCH=128`. **~5–7 hours at 1M TPM**,
  ~1–1.5h at 5M. Near-zero local CPU, so the prod-contention concern raised earlier
  (box at load 4.17, sharing cores with prod Postgres and whisper) does **not** apply.

Cost and time are close to non-issues. Disk is the constraint — see below.

## Disk (corrected — pgvector, not an in-process index)

pgvector 0.8.1, `m=16, ef_construction=64` (migration 125). Unlike hnswlib/FAISS,
the heap copy is NOT releasable after the build: `document_chunks.embedding` stays in
the table permanently AND pgvector stores a full copy of each vector in the index
pages. Both costs are steady-state, not peak.

| Item | Size |
|---|---|
| New heap vectors, 1,336,164 × 3,072 B (+TOAST overhead; `attstorage='e'`) | ~3.8–4.2 GiB |
| HNSW over 1.65M: raw vectors (4.7 GiB) + graph/page overhead at m=16 | ~5.2–6.0 GiB |
| **Total additional** | **~9–10 GiB** |
| Available on the NFS share (disk, not RAM) | 13 GiB |
| **Headroom** | **~3–4 GiB** |

Fits, but this share is at 84% and this VM's documented failure mode is a disk-full
crash-looping Postgres. Reclaim before running.

**Two build gotchas:**

1. `idx_chunk_embedding_hnsw` does **not currently exist** (`pg_indexes`). Migration
   125 creates it on an empty column — instant, graph grows per insert — but it is
   absent now, so someone must `CREATE INDEX` over 1.65M populated rows.
2. That build is where `maintenance_work_mem` matters. The server is set to 2000MB,
   but migration 125 does `SET maintenance_work_mem = '256MB'` inside its own
   transaction. Building a ~5.5 GiB graph under 256MB makes pgvector spill and log
   "hnsw graph no longer fits into maintenance_work_mem" — order-of-magnitude slower.
   Build outside that migration.

**Option not taken:** `halfvec` (supported in 0.8.1) halves both heap and index to
~4.7–5 GiB total, taking headroom from ~3 to ~8 GiB. Costs a column-type migration
plus full reindex, and must be decided corpus-wide (same one-vector-space discipline
that made `96d472d0` necessary). Worth considering given this share's history; not a
blocker for the backfill.

If a shorter run is wanted, the lever is doc type rather than date. Stranded chunks
by type:

| doc_type | stranded chunks | docs |
|---|---|---|
| announcement_attachment | 539,966 | 79,270 |
| financial_results | 514,405 | 33,820 |
| annual_report | 158,655 | 1,024 |
| concall_transcript | 96,598 | 5,021 |
| investor_presentation | 66,903 | 4,851 |
| press_release | 46,613 | 6,946 |

Excluding `announcement_attachment` cuts 38% while retaining every research-grade
document — **but** that is the generic bucket the doc-type classifier work exists to
reclassify, so an unknown share of those 540k are likely mistyped transcripts and
presentations. Verify classification before gating on it.

## 🔴 Not verified

TC-8: the embed drain has **not been run** with this change. Proven here: the query
parses, plans sensibly, and selects exactly the intended rows. NOT proven: that
running the drain over 1.34M chunks completes, stays inside the pool's command
timeout, and writes valid vectors at that volume. The prior timeout incident recorded
in this same file's comments (a sort blowing past `command_timeout=30`, failing with
an empty-string `asyncio.TimeoutError`) is a reason to watch the first real run
closely rather than assume it.

## Verdict: PASS
