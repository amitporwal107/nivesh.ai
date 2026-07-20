# OVERRIDE — NSE/BSE identity bridge in daas_api documents.search

REASON: Blocked awaiting a fresh GCP access token (1h TTL) to finish latency
diagnosis + verification on staging. The token expired mid-`EXPLAIN ANALYZE`.
Nothing is deployed to the live DaaS service; this is verification-in-progress,
not a shipped change.

## What is DONE and PROVEN (real staging output)
- Root cause of the copilot's "commentary unavailable" for SSWL is NSE/BSE
  identity split, NOT embeddings: the current quarter's concall transcript +
  results are BSE-sourced (scrip_code=513262, ticker_symbol=NULL, isin=NULL),
  and `/documents/search` filtered on `ticker_symbol` only.
- Bridge logic works: `_resolve_scrips('SSWL') -> ['513262']`, and the widened
  `_HYBRID_SQL` now returns the `[BSE-scrip]` concall_transcript + investor
  presentations that the ticker-only filter completely missed (shown live).
- Normalizer validated collision-safe: bridges 1,460 split identities corpus-wide
  with ZERO real cross-company collisions (only same-issuer partly/fully-paid
  ISIN pairs).

## The BLOCKER (why this is NOT PASS)
- `_resolve_scrips('SSWL')` takes ~8.9s (was ~12.9s pre-index). The functional
  index `idx_documents_norm_company` was created (valid, 1.3MB) but the plan is
  NOT using it — a per-request 8.9s resolution is unusable in the copilot hot path.
- Next step (needs a token): `EXPLAIN ANALYZE` both resolution steps to see why
  the index is skipped. Leading candidate fix is to REPLACE the on-the-fly
  normalized-name resolution with a small precomputed `nidp.scrip_ticker_map`
  (ticker_symbol, scrip_code) table (~1,460 rows, indexed on ticker) refreshed by
  cron — an indexed <1ms lookup with none of the functional-index-match fragility,
  and the same identity-map seam the durable BSE-scrip-master fix will populate.

## Status: IN PROGRESS — blocked on a fresh GCP token, latency unresolved
Do NOT read this as complete. The route edit + functional index exist on the
working branch and dev-repo but are unverified end-to-end and undeployed.
