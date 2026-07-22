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

---
## Update 2026-07-21 — OpenAI multi-query expansion (semantic variations)

Per user direction ("don't pass the exact query — fire semantic variations so we don't miss
anything; use OpenAI to build the queries"):
- `classify_theme` now uses OpenAI (gpt-4o-mini) to expand the query into 5–8 SEMANTIC
  VARIATIONS, whose pivot+context terms are UNIONed into one broad `(pivots)&(contexts)`
  tsquery (union, not per-variation clauses — the LLM's variation set varies run-to-run;
  union is stable). Prompt is exhaustive about real cost-driver nouns (raw material,
  packaging, fuel, freight, forex, wages). The endpoint returns the variations it fired.
- Candidate SQL now hands the LLM the top-2 passages per company (a company's flag isn't
  always its top-ranked chunk); the endpoint dedups the extraction to one row per company.

Verified on staging DaaS 8084: 8 variations fired (margin/cost, gross/raw-material,
ebitda/energy, margin/wage, cost/packaging, margin/logistics, …) → 933 candidates scanned,
52 curated companies. **Recall improved**: Heritage Foods now surfaces (was missed pre-
expansion) — confirmed BOTH direct and via the live copilot (sources: Heritage Foods annual
report p.76; answer cites Somany Ceramics ₹1.25–1.50/sq.ft input-cost rise, All Time
Plastics, EID Parry margin compression).

Residual limits (honest): Elecon/Bajaj/Nuvoco are now in the candidate net but not always
flagged by the extraction LLM — their top-2 keyword-dense passages aren't always the actual
flag, and gpt-4o-mini's judgement varies run-to-run; Elecon/Heritage have no concall in the
corpus (annual-report commentary only). Perfect recall of a hand-curated set is bounded by
extraction variance + corpus depth, not the query expansion.

## Verdict: PASS

---
## Update 2026-07-21 (2) — intensity + market-cap-tier ranking + show-all

Per user direction (rank by intensity of numbers / strong words; large-cap first then mid/
small unless explicitly asked; give a show-all option with pagination):
- **Intensity**: the extraction LLM scores each flagger 0-100 (magnitude of any number cited
  + strength of language) and returns the key metric. Verified live: metrics like "3.5-4% RM
  impact" (Bajaj Auto), "crude oil price +60%" (JM Financial), "price hike 4.35%" (Globus).
- **Cap tier**: join market_cap_bucket (nidp.v_v3_stock_scores_latest) by NSE symbol; sort
  LARGE→MID→SMALL→MICRO→unknown, intensity within tier. Verified: curated list leads with
  LARGE_CAP (UPL/Bajaj Auto/Dabur), then MID (KEI), SMALL (Vesuvius), unknown. Overridable —
  a query naming a segment ("smallcap …") filters to it (cap_filter in the response).
- **Show-all**: `?all=true` returns the full keyword-matched company list (no LLM curation),
  cap-ranked, paginated. Verified: matches=514, pagination.next_offset=8.
- Copilot end-to-end: sources now lead with large caps (Cholamandalam, Bajaj Auto, Hyundai,
  UPL) then smaller. DaaS @ e5e94efd.

Fixed in this pass: a SQL scoping bug (the cap-bucket LEFT JOIN sat after ', q' so table d
was out of scope → HTTP 500) — moved the tsquery CTE to an explicit CROSS JOIN. Also note a
transient staging-DB crash-recovery window (~205s checkpoint) that 500'd the endpoint until
Postgres finished WAL replay — infra, not code.

Known precision gap (honest): the extraction still occasionally flags a company that mentions
margins POSITIVELY (e.g. "margin improvements") as a flagger — the prompt should distinguish
"flagged PRESSURE" from "mentioned margins". Ranking is correct; extraction precision is the
next tuning lever.

---
## Update 2026-07-21 (3) — extraction precision (direction-aware)

Tightened the extraction prompt to require the theme's DIRECTION: qualify only when
management flags the theme as a concern in the direction implied (margins under pressure / a
cost rising), and EXCLUDE the opposite (margins improving/easing/fully-offset), generic
risk-factor boilerplate, bare word matches, and analyst questions ("when unsure, exclude").
Verified live (DaaS @ b4ca7194): the prior false positives (Lenskart "margin improvements",
Dabur "growth") are gone; the curated set is now genuine flaggers only — MRF "significant
headwinds", ITC "increased cost pressure", JK Lakshmi "concern over margin sustainability",
Jain Irrigation "sharp rise in polymer prices", Bajel "persistent supply chain".


## Verdict: PASS
