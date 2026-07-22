# Verification — embeddings switched to self-hosted bge-base-768

- **Date:** 2026-07-18
- **Branch / commits:** `dev` @ `8e4ef4a7` (switch + sharded drain), `6fe5476b` (ORDER BY fix)
- **Environment:** STAGING — `nidp-stack-vm`, DB `nidp_staging`
- **Changed areas:** `nidp/shared/embeddings.py`, `nidp/shared/embeddings_local.py`,
  `nidp/services/document_parser/db.py`, `nidp/deploy/vm/embed_drain.py`,
  `nidp/migrations/125_document_chunks_embedding_bge_base.sql`

## Why the switch

The corpus grew to ~1.72M chunks. Two facts forced it off OpenAI:
1. **1536-dim no longer fits the disk.** ~9.9GB of vectors + a comparable HNSW index
   (~20GB total) against ~17GB free on the NFS share holding Postgres. This VM's known
   failure mode is a disk-full crash-looping Postgres. 768-dim is ~5GB (~10GB with index).
2. **OpenAI ran out of credit twice**, the second time after 208k chunks (~$2.13).

## TC1 — bge-base parity with OpenAI, proven on THIS corpus for $0  ✅ PASS

Used the 216k OpenAI vectors already in the DB as the reference — no new API spend.

```
loaded 400 real chunks with OpenAI vectors
OpenAI matrix: (400, 1536)   bge matrix: (400, 768)

NEIGHBOUR AGREEMENT (top-10, 40 probes)
  mean overlap: 0.458   (band 0.35-0.60 set BEFORE running = strong agreement)
  min=0.10 p50=0.40 max=0.90

QUALITATIVE RETRIEVAL (real filing queries)
  "quarterly net profit and revenue"     -> 0.649  "Net Profit for the Year ... 24,586.69"
  "board approves declaration of dividend"-> 0.641  "Board of Directors ... dividend of Rs 75 per share"
  "resignation or appointment of director"-> 0.680  "the proposed appointee shall ..."
  "earnings conference call transcript"   -> 0.576  (weak)
  "credit rating assigned or revised"     -> 0.549  (weak)
```
The two weak queries are a **sampling artifact**, not a model failure: only 400 random
chunks were loaded and no transcript/rating chunk was among them. Note bge-base scored
those *lower* (0.54-0.58 vs 0.65-0.68) — correct calibration, not false confidence.

## TC2 — model spec verified from source, not memory  ✅ PASS
From each model's own `1_Pooling/config.json`: `pooling_mode_cls_token=true`,
`pooling_mode_mean_tokens=false`; dims small=384 / base=768 / large=1024;
`max_position_embeddings=512`. CLS (not mean) pooling matters — mean pooling would
produce plausible vectors in the wrong space with no error, just degraded retrieval.

## TC3 — migration 125 applied  ✅ PASS
```
BEGIN / SET / SET / ALTER TABLE / ALTER TABLE / COMMENT / INSERT 0 1 / COMMIT
COLUMN_NOW=vector(768)      PSQL_EXIT=0
```
Column is `vector(768)`, migration recorded, the 216k OpenAI vectors discarded (no
1536->768 projection exists; mixing spaces in one index yields meaningless similarity).

## TC4 — embed fetch no longer times out  ✅ PASS
The unembedded fetch sorted every matching row by `ingested_at` to return the top LIMIT:
```
BEFORE: Sort (575,036 rows) -> Limit    Execution Time: 63,329 ms
```
63s exceeded the asyncpg pool's 30s `command_timeout`, so every embed batch died with a
bare `asyncio.TimeoutError` (which stringifies to `''`). Embedding is order-independent,
so the ORDER BY was removed:
```
AFTER:  Limit -> Parallel Seq Scan (actual rows=139 loops=3)   -- no Sort node, early stop
```

## TC5 — embedding actually progressing  ❌ NOT VERIFIED / BLOCKED
3 sharded bge-base workers were launched and the count moved 0 -> 200, but then **stopped
rising**. Working hypothesis (untested): a `CREATE INDEX CONCURRENTLY` on the embedding
column was launched at the same time as the write-heavy backfill, so each 400-row write
must maintain a half-built HNSW index and the batch stalls/rolls back — the workers burn
CPU embedding and commit nothing.

**Next action:** kill the concurrent index build, confirm the count climbs across all
three shards, and build the HNSW index once at the END of the backfill.

Currently blocked: the GCP token in `/app/.gcp-token` is rejected by Google
(`invalid_token`), including freshly-minted ones — the credential issuing them needs
re-authentication. No VM access until then.

## Known limitations
1. **The corpus is a moving target.** The Ray parse backfill keeps adding chunks, so
   "complete" means the backlog drains faster than it grows.
2. **Measured single-process bge-base throughput is 6.7 chunks/sec** (~24k/hr; ~3 days for
   1.72M). More ONNX threads did NOT help (identical at 2 and 4) — process-level
   parallelism is the only lever, hence 3 sharded workers (~1 day) if they run.
3. **Retrieval parity is measured on 400 chunks**, and the neighbour-agreement metric is a
   similarity-structure proxy, not a labelled relevance benchmark.
4. **UNVERIFIED on prod.** Staging only.

## Verdict: IN PROGRESS — schema + parity verified, embedding not yet flowing
