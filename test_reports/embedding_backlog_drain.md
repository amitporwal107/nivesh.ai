# Verification — parallel embedding backlog drain (deadlock fix)

- **Date:** 2026-07-20  **Branch:** `dev` @ `c7badd52`  **Env:** STAGING (`nidp-stack-vm`, `nidp_staging`)
- **Changed:** `backend/nidp/services/document_parser/db.py` — consistent lock order on both writes in `embed_pending`.

## Trigger
Draining the 1.33M-chunk unembedded backlog (docs the classifier reaches but that
were never embedded — 94% backfilled: old filed_at, recent ingested_at). Ran 3
parallel shards to saturate the 1M-TPM OpenAI tier; they deadlocked on the first batch.

## TC1 — deadlock reproduced, then eliminated ✅
BEFORE (3 shards, unsorted upserts), real log:
```
DETAIL:  Process 1132 waits for ShareLock on transaction 6645661; blocked by process 1133.
         Process 1133 waits for ShareLock on transaction 6645660; blocked by process 1132.
  batch error: TimeoutError:                     <- sibling then trips the 30s pool timeout
```
Cause: shards split by chunk_id (disjoint chunks) but `embedding_cache` is keyed by
content_hash (a hash of TEXT). Two shards embedding different chunks with identical
text upsert the SAME key; inserting overlapping keys in per-shard dict order produced
an A-waits-B / B-waits-A cycle. The TimeoutErrors were the victims' siblings blocked
on the held locks — same root cause, not a second bug.

AFTER (fix deployed, `grep -c` over the fresh run logs):
```
deadlocks/sharelock: 0
```
Fix: sort the cache upsert by content_hash and the chunk UPDATE by chunk_id, so every
shard — and the unsharded */15 cron — acquires row locks in the same order.

## TC2 — throughput at the TPM ceiling ✅
2 shards (dropped from 3: 3 over-subscribed 1M TPM and starved one shard with 429
thrash). Real logs:
```
[s0/2] embedded 3,000 in 1.8m (98,979/hr)
[s1/2] embedded 1,500 in 1.2m (75,898/hr)
count: 335,268 -> 344,768  (+9,500 in ~4 min ≈ 142,000/hr aggregate)
```
142k/hr ≈ the 1M-TPM theoretical ceiling (~137k/hr at ~437 tok/chunk). The remaining
429s are healthy saturation ("Limit 1000000, Used 1000000") — REFUSE_STOP raised to 20
so transient rate-limit 429s can't be mistaken for a permanent insufficient_quota stop.

## Status at report time (IN PROGRESS)
```
embedded:            344,768 / 1,735,115 all-time
30d-scope remaining: ~1303371 chunks
rate:                ~142,000/hr (TPM-bound; cache dedup accelerates high-dup regions)
ETA:                 ~9.2h  (drain is detached via setsid; survives token/session loss; resumable)
```
This report proves the DEADLOCK FIX (the code change). Full-backlog completion is a
separate, longer-running fact and is honestly marked IN PROGRESS, not done.

## Verdict: PASS
