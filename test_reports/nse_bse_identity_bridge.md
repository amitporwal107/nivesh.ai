# Verification — NSE/BSE identity bridge in daas_api /documents/search

- **Date:** 2026-07-20  **Branch:** `dev`  **Env:** STAGING (`nidp-stack-vm`, `nidp_staging`)
- **Changed:** `nidp/services/daas_api/routers/documents.py` (identity bridge +
  widened hybrid/FTS filters), `nidp/migrations/129_documents_norm_company_idx.sql`.

## Problem
The copilot could not quote SSWL's Q1 FY27 concall commentary. Root cause (proven on
live data, NOT embeddings): a company's NSE filings carry `ticker_symbol='SSWL'`; its
BSE filings carry only `scrip_code='513262'` with `ticker_symbol`/`isin` NULL. The
current-quarter transcript + results are BSE-sourced, and `/documents/search` filtered
on `ticker_symbol` only. No populated key links the two identities
(`ref.security_master.bse_code` is empty for all 4,924 equities).

## TC1 — bridge surfaces the previously-invisible BSE content ✅
Ran the ACTUAL route SQL (`_HYBRID_SQL`) and `_resolve_scrips()` from the edited module
against the real staging DB:
```
_resolve_scrips('SSWL') -> ['513262']
BEFORE (ticker-only, scrips=[]): 5 rows, ALL [SSWL], NO BSE transcript
AFTER  (bridge, resolved):       concall_transcript [BSE-scrip] + investor_presentation
                                 [BSE-scrip] now returned (the 15-Jul Q1 material)
AFTER, doc_type=concall_transcript: 3 rows incl. ticker=None (BSE) transcripts
```

## TC2 — resolution latency fixed (was a hard blocker) ✅
First implementation resolved in ~8.9s (seq-scan of 94,942 scrip rows applying the
normalizer). Fix = functional index `idx_documents_norm_company` + ANALYZE. EXPLAIN
ANALYZE on staging:
```
BEFORE index+ANALYZE: Index Scan idx_doc_scrip, Filter norm(...), 6,974 ms
AFTER  index+ANALYZE: Index Scan idx_documents_norm_company (Index Cond), 0.348 ms
end-to-end _resolve_scrips('SSWL'): 39 ms  (step1 5ms + step2 0.3ms)
```
The ANALYZE is essential (index alone left the planner mis-estimating and ignoring it)
— documented in migration 129.

## TC3 — collision safety of the normalizer ✅
Bridges 1,460 NSE/BSE split identities corpus-wide with ZERO real cross-company
collisions (the only normalized-name/multi-ISIN pairs are one issuer's partly-paid
'IN9…' vs fully-paid 'INE…' series). LIMIT 25 caps any pathological fan-out.

## NOT verified / explicitly out of scope
- **Live HTTP endpoint + the copilot were NOT exercised.** The live DaaS service runs
  from `/opt/nidp/repo` (the PROD checkout), which is under a do-not-touch instruction.
  Verification was done at the route-SQL + index level against the staging DB, one layer
  below the HTTP/auth/routing surface. A transient dev-repo DaaS instance was started to
  close that gap but stopped at the user's request.
- **NOT deployed.** The staging copilot will keep using the prod `/opt/nidp/repo` DaaS
  until prod is updated (deferred). So the copilot's SSWL answer is unchanged in the live
  app right now — this change is verified-correct, not live.
- Durable follow-up still open: source a BSE scrip↔symbol master and backfill
  `ticker_symbol`/`isin` onto BSE docs at ingestion, after which this bridge is dead code.

## Verdict: IN PROGRESS — route-SQL + index verified on staging; real HTTP endpoint
## output NOT yet captured (see OVERRIDE_nse_bse_bridge.md). Not a PASS.
