# Verification — filtered HNSW search returned zero rows; benchmark vs external ground truth

- **Date:** 2026-07-19  **Branch:** `dev` @ `197b11e4`  **Env:** STAGING (`nidp-stack-vm`, `nidp_staging`)
- **Changed:** `nidp/shared/storage/pg.py` (new `prepare_vector_search`),
  `nidp/services/daas_api/routers/documents.py`, `services/feed_rag/retrievers/vector.py`

## Trigger
User supplied an external ground truth (news-sourced Q1 FY27 AI commentary for TCS,
HCLTech, Wipro, Tech Mahindra, Reliance) and asked how our system compares. Running
that comparison exposed the bug.

## TC1 — filtered vector search returned 0 rows ✅ FIXED
Company-scoped semantic query, 311,868 embedded chunks in the index:
```
                        DEFAULT (ef_search=40)   iterative_scan=relaxed_order   ef_search=1000
Tata Consultancy        0 rows / 176ms           3 rows / 181ms                 3 rows / 1092ms
HCL Tech                0 rows /   7ms           3 rows /  40ms                 3 rows /   26ms
```
TCS has 195 embedded chunks and HCLTech 299 — the data was there. HNSW collects
ef_search candidates and applies WHERE afterwards, so a selective filter eliminates
all of them. No error is raised. iterative_scan is ~6x cheaper than brute-forcing
ef_search for the same rows.

## TC2 — production hybrid path ⚠️ NO OBSERVED CHANGE
Running the real `_HYBRID_SQL` from daas_api, with and without the fix, returned
**byte-identical results** for both test queries. The FTS leg already found these,
and RRF masked the dead vector leg.

This is honest evidence that:
1. The fix does NOT improve keyword-rich queries (the FTS leg carries them), and
2. the bug was invisible precisely because of this — the endpoint looked healthy
   while contributing nothing from the vector half. It presents as "retrieval is
   mediocre", never as "retrieval is broken".

The fix's value is on paraphrased/conceptual queries with no keyword overlap, and on
the pure-vector feed_rag retriever. That benefit is NOT demonstrated here — UNVERIFIED.

## TC3 — corpus coverage vs external ground truth ✅
Keyword scan, per company, July 2026 filings — 10 of 12 cited facts present:
```
FOUND  TCS $2.6bn AI run rate  (9)   TCS $9.5bn order book (5)   TCS TPG JV (1)
FOUND  TCS SKF deal (15)             HCL $171mn Advanced AI (3)  HCL 62.1% YoY (4)
FOUND  HCL $2.4bn bookings (8)       TechM 14.4% margin (15)     TechM $1.66bn rev (15)
FOUND  "agentic" AI (15)
  --   RIL Jamnagar (0)              RIL Rs10tn AI plan (0)
```
Retrieved verbatim from the TCS 2026-07-09 press release: *"scaling our AI business to
a $2.6 billion annualized revenue run rate"*, and the 2026-07-15 concall: *"our AI
services revenue continues to accelerate... $2.6 billion in annualized revenue."*

The two misses are AGM/analyst-meet material, which is not exchange-filed — out of
scope by construction, not a pipeline failure.

## Findings NOT fixed
1. **Boilerplate outranks substance.** For "HCL Advanced AI revenue growth", the top
   pure-vector hit (0.647) was forward-looking-statement legalese, scoring HIGHER
   than the genuinely relevant TCS concall answer (0.590) and HCL concall (0.573).
   Similarity is therefore NOT thresholdable, and callers must not treat a high score
   as relevance. Boilerplate should probably be filtered at chunk time.
2. **Duplicate results** (carried from the prior report) — identical chunks tie for
   top rank; 311,868 vectors represent 223,809 unique texts.
3. **Entity resolution.** A `company_name ILIKE '%Reliance%'` probe returned *Reliance
   Power* (unrelated group) for a Reliance Industries question. Product paths must
   scope by ticker/scrip_code, never by name substring.

## Correction to the previous report
`c1680a17` establishes that the "311,461/311,461 = 100.00%" claim in
`embeddings_openai_768_complete.md` held only within a predicate that scoped on
`filed_at` alone. Backfilled documents (old filed_at, new ingested_at) could never be
selected: 1,336,164 chunks / 125,648 documents. The corpus is NOT fully embedded; that
backlog is now reachable and undrained.

## Verdict: PASS
