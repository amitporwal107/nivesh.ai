# Verification — 30-day corpus embedded (OpenAI 768-dim) + HNSW index

- **Date:** 2026-07-19
- **Branch:** `dev` (embeddings @ `96d472d0`, cache @ `1da6115c`, scope @ `0f1c2169`)
- **Environment:** STAGING — `nidp-stack-vm`, DB `nidp_staging`

## Result

```
30-day scope     : 311,461 / 311,461 chunks embedded  (100.00%)
total embedded   : 311,868
model            : text-embedding-3-small @ dimensions=768  (single model, no mixing)
cache            : 223,809 unique texts
dedup            : 87,859 chunks served from cache = 28.2%
HNSW index       : idx_chunk_embedding_hnsw  valid=true  875 MB  (m=16, ef_construction=200)
```

## TC1 — dedup delivered as measured ✅
Predicted 28.0% before the run (289,628 chunks -> 208,437 unique); actual 28.2%
(311,868 embedded from 223,809 unique). ~$0.90 of tokens never bought, and the saving
is permanent: content-hash memoization means future Ray re-parses of the same source
hit the cache instead of re-paying.

## TC2 — end-to-end semantic search ✅
Query embedded on the read side, retrieved via HNSW. Proves write and read share one
vector space:
```
"resignation of a director"          -> 0.702  "request the Board to kindly take my resignation on record"
"earnings conference call transcript"-> 0.656  Precision Camshafts / HCL  (doc_type=concall_transcript)
"quarterly net profit and revenue"   -> 0.611  "STATEMENT OF UNAUDITED FINANCIAL RESULTS FOR THE QUARTER"
"board approved declaration of dividend" -> 0.653  annual_report, dividend payment
```
Latency 268-1,105 ms, dominated by the OpenAI query-embedding round trip; the ANN
search itself is sub-millisecond.

## TC3 — single-model corpus ✅
`embedding_model` distribution is 100% `text-embedding-3-small`. During the run the
*/15 cron briefly wrote 600 `bge-base-en-v1.5` vectors into the same vector(768)
column — same width, DIFFERENT vector space, so those rows returned meaningless
similarity with no error raised. Cleaned up, cron pinned via nidp.env, and the code
default corrected (`96d472d0`) so a redeploy cannot reintroduce it.

## KNOWN DEFECT — duplicate chunks dominate results ❌
The cache deduped what we *pay for*, not what is *in the index*. 311,868 vectors
represent only 223,809 unique texts, so identical text ties for top rank:
```
"resignation of a director" -> the SAME Photon Capital chunk 3x at 0.702
"quarterly net profit"      -> Dharti Proteins twice
"board approved dividend"   -> Rajratan twice
```
A user asking that question today gets one answer repeated instead of three distinct
ones. This is a retrieval-quality bug, not a cost bug.

Fix options (not yet implemented):
1. Dedup at query time — `DISTINCT ON (content_hash)` / group by hash before LIMIT.
   Cheapest, no schema change, but needs a hash available on the row.
2. Dedup at chunk level — store `content_hash` on document_chunks and keep one row
   per unique text per document, mapping duplicates back. Cleaner index, smaller
   HNSW graph (~224k instead of 312k vectors), better recall per query slot.

## Known limitations
1. **Scope is 30 days by design.** 1,422,934 older chunks are unembedded — the
   classifier only reaches filed_at >= now()-30d, so vectors there would serve
   material nothing downstream can classify. They remain keyword-searchable via the
   GIN FTS index.
2. **Query latency is API-bound.** An LRU/Redis cache on query embeddings would cut
   the 268-1,105 ms substantially for repeat queries; not implemented.
3. **Batch API not used.** Would have halved cost (~$1.50 vs ~$3) but is async with a
   24h SLA; sync finished in ~1h on a corpus that had been blocked for days.
4. **No quantization.** pgvector 0.8.1 has no native int8 vector type; `halfvec` (f16)
   would take 955MB -> 478MB against 17GB free. Not worth a migration at this scale.
5. **UNVERIFIED on prod.** Staging only.

## Verdict: PASS (with the duplicate-results defect recorded above)
