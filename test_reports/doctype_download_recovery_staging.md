# Functionality verification — document corpus recovery + content-based doc_type

- **Date:** 2026-07-16
- **Branch / commits:** `dev` @ `e39b144d` (fix pack), `74caf606` (migration-chain fix), `bf11d7e1` (NUL fix)
- **Environment:** STAGING — `nidp-stack-vm`, DB `nidp_staging`, container `nidp-postgres-staging`
- **Changed areas:** `nidp/services/document_parser/{db.py,pdf_extractor.py,service.py}`,
  `nidp/services/corporate_announcements/doctype.py`, `nidp/cli.py`,
  migrations `123_documents_doc_type_confidence.sql`, `124_documents_parse_attempts.sql`

---

## Baseline (measured on staging BEFORE the fix)

```
parse_status:  failed 18655 | pending 35 | parsed 5          -- 99.8% dead
doc_type:      announcement_attachment 18624 | investor_presentation 58 | concall_transcript 13
top errors:    download: (empty) 16551 | download: 403 Forbidden bseindia 2103
```

Failure-category split — **100.0% of 18,655 failures were DOWNLOAD failures, 0 were parse failures.**
Only 5 documents ever had bytes stored. The parser was never the bottleneck; it succeeded on
5/5 of everything it was ever handed.

---

## Test cases and results

### TC1 — Migration chain applies (was blocking every deploy)
Every NIDP staging deploy failed at dev's `122_...sql` with a blank reason since `f8d0c802`.
Root cause proven on the CLI's exact asyncpg path (rolled back, nothing persisted):

```
RESULT: EXCEPTION after 30.0s
  type   = builtins.TimeoutError
  str(e) = ''                      <-- why the CI reason printed empty
RESULT: 122 APPLIED OK in 24.2s with timeout=600 override
```

Cause: `cmd_migrate` ran through the shared pool's `command_timeout=30`; 122 needs ~24-34s.
Fix: bounded 600s per-command timeout for migrations + always print the exception type.

Real CI output after the fix (run 29496713384, conclusion **success**):
```
✅ 122_fix_pat_yoy_data_quality_guards.sql applied
✅ 123_documents_doc_type_confidence.sql applied
✅ 124_documents_parse_attempts.sql applied
✅ Migrations done.
```
**PASS**

### TC2 — NUL bytes in extracted text do not fail the parse
First real parse run after downloads recovered died immediately:
```
asyncpg.exceptions.CharacterNotInRepertoireError:
invalid byte sequence for encoding "UTF8": 0x00   (store_parse_result, db.py:171)
```
Latent since the extractor was written — unreachable while every download failed.
Fixed in `ExtractedDoc.__post_init__` (the one point pypdf/OCR/vision converge on).
```
nidp/tests/parsers/test_pdf_extractor.py ... 3 passed
nidp/tests/test_doctype.py .............. 19 passed
```
**PASS**

### TC3 — Downloads recover (the 403 bot-block)
Pilot, 60 docs, concurrency 4, no discovery, no OpenAI spend:
```json
{ "discovered": 0, "parsed": 52, "failed": 7, "skipped_non_text": 1, "embedded": 0 }
```
52/60 parsed against a corpus whose lifetime total was 5.
Errors on all docs attempted under the new code:
```
download: 404, message='Not Found'                 128
format: not a PDF (first 4 bytes: b'PK\x03\x04')     2
parse: PdfReadError: Cannot find Root object in pdf  1
```
**Zero 403s.** The bot-block is gone; residual failures are legitimately unrecoverable
(absent upstream, a ZIP mislabelled as PDF, a corrupt PDF).
**PASS**

### TC4 — doc_type is typed from content (feeds the UI toggles)
```
announcement_attachment  62
financial_results        13
annual_report             5
investor_presentation     4
concall_transcript        3
press_release             2
```
Was: 100% generic. Live parse log line:
```
parsed doc=265bc2b1... pages=19 chars=10710 chunks=7 type=investor_presentation(15)
```
`doc_type_confidence` populated (21, 20, 18, 16…) via migration 123.
**PASS**

### TC5 — Retry counter bounds retries (migration 124)
`parse_attempts` increments per attempt (observed = 1) and gates re-fetch at
`parse_status='failed' AND parse_attempts < 5`. Transient failures are no longer terminal;
permanent ones stop after 5.
**PASS**

### TC6 — Real text lands in the RAG corpus
```
chunks 1066 | docs_with_chunks 89
```
**PASS**

---

## Known limitations (honest scope)

1. **~2,103 BSE `AttachLive` docs are permanently gone.** They are exactly the 403-blocked
   slice; `AttachLive` URLs expire, and they now 404. Not recoverable from stored URLs —
   would need BSE's archival `AttachHis` equivalents. Separate work.
   The other **16,637 (89%)** are `nsearchives.nseindia.com` and ARE recovering.
2. **Full 18,655-doc backfill is IN PROGRESS**, detached (pid 1771337), not complete at
   time of writing. Progress at last read: `parsed 173+`, climbing.
3. **UNVERIFIED: staging `OPENAI_API_KEY` is invalid** (`401 Incorrect API key provided`).
   Vision + embeddings are graceful-by-contract, so the pipeline is unaffected, but the
   vision tier is silently degraded (on prod too). Backfill run with `OPENAI_API_KEY=""`
   to avoid ~6h of wasted 401 round-trips; embeddings deliberately skipped (`--embed-limit 0`),
   so chunks are keyword-searchable but not yet semantically searchable.
4. **UNVERIFIED on prod.** All evidence above is staging-only. Prod tracks `main` and still
   carries both the download bug and the NUL bug.

## Verdict: PASS
