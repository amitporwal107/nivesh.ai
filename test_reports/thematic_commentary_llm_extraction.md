# Functionality Verification Report — Thematic commentary (LLM-curated "who flagged X?")

- **Branch:** feat/filings-intelligence-design (shipped to `dev`)
- **Date:** 2026-07-21
- **Author:** Claude (Full-Stack + QA)
- **Environment:** staging (nidp_staging · DaaS 8084 · nivesh-staging-app-backend)
- **Changed areas:** backend routes/services: **yes** (daas_api intelligence.py + new thematic_search.py; copilot daas_client.py, stocks_insights.py, symbol_resolver.py, node) · frontend: no

## Summary
A cross-company commentary ask ("which companies flagged margin pressure in Q1 concalls?")
returned "only Sai Silks results" — the copilot resolved a period token ("Q1") to a ticker
and its document search ranked the right companies below its candidate pool. Root-caused and
rebuilt: (1) the resolver never treats Q1/FY27/2026 as a ticker; (2) a NEW
`/v1/intelligence/thematic-commentary` endpoint casts a wide GIN-indexed keyword net over the
chunk corpus (deduped by suffix-stripped company, ranked by breadth of discussion), then an
LLM (gpt-4o-mini) reads the candidate passages and keeps ONLY companies whose management
genuinely flagged the theme, with a grounded statement + page citation; (3) the copilot's
thematic path calls it. Verified end-to-end through the live copilot.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | resolver | "Q1"/"FY27"/"2026" not resolved to a ticker | unit | None | PASS |
| TC-2 | candidate SQL | GIN keyword net, deduped, ranked by breadth | api | fast, dedups Ltd/Limited | PASS |
| TC-3 | endpoint | /thematic-commentary depth=1200 returns curated companies | api | LLM-filtered list + statements | PASS |
| TC-4 | grounding | statements trace to real chunks (not hallucinated) | data | grounded | PASS |
| TC-5 | copilot e2e | live copilot "who flagged margin pressure" | e2e | curated commentary + citations | PASS |
| TC-6 | honesty | answer doesn't claim concall when source is annual report | e2e | honest caveat | PASS |

## API / Endpoint Tests (staging DaaS 8084)
- `GET /v1/intelligence/thematic-commentary?q=which companies flagged margin pressure…&depth=1200`
  → curated list incl. Raymond Lifestyle (p.137), Mahindra Logistics ("flagged inflation and
  rising input costs may impact margins"), Dr. Reddy's, Jyothy Labs, Harsha Engineers
  ("near-term margin pressure"), Bombay Dyeing, Patanjali Foods, NOCIL, KRBL — each with a
  grounded statement + doc_type + page. Latency ~19s at depth=1200. → PASS
- Candidate SQL (breadth-ranked, suffix-deduped): merges "Elecon … Ltd/Limited"; runs ~9–13s
  over the GIN index (idx_chunk_text_fts). → PASS

## Live Copilot Test (POST /api/chat/stream, session_token 7bde1212…)
- "which companies flagged margin pressure or rising input costs in their Q1 concalls" →
  `mode=thematic`; sources = LLM-curated companies with page citations (Raymond Lifestyle
  annual report p.137, Harsha Engineers p.46, Bombay Dyeing p.7, …); answer grounded and
  honest ("I don't have Q1 concall transcripts … the available annual-report text flags:
  Harsha Engineers 'near-term margin pressure' [5], GHCL Textiles 'volatility in global
  energy prices' [7], Sejal Glass 'Raw Material…'"). Total round-trip ~41s. → PASS

## Data Correctness (staging)
- The 4 companies the user hand-picked (Heritage/Elecon/Bajaj/Nuvoco) ARE in the corpus, but
  by chunk-count rank at 32 / 119 / 668 / 949 among 1,228 margin-discussing companies —
  Nuvoco flags it in only 4 chunks, so no keyword/vector ranking isolates it in a small pool.
  Verified via real DB queries. The LLM pass surfaces companies we DO have commentary for;
  Heritage & Elecon have NO concall_transcript in the corpus (their Q1 concall isn't
  ingested), so their specific quotes cannot be surfaced — a depth/ingestion gap, not a
  retrieval bug.

## Known limitations (honest)
- **Latency ~41s** end-to-end (candidate SQL + LLM batches). Acceptable for a "deep" query,
  slow for instant chat; belongs behind a deep-search mode / progress state. Tunable via
  `depth` (lower = faster, less recall).
- **One passage per company** to the LLM: a company whose flag is in a non-top chunk can be
  missed. More passages/company would raise recall at higher LLM cost.
- Corpus depth: companies without an ingested concall can't surface their concall quote.
- prod / `main` untouched per standing instruction.

## Inputs required from user
- session_token for the live fire (provided: 7bde1212-…).

## Verdict: PASS
