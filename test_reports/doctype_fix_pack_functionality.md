# Functionality Verification Report — Doc-Type Fix Pack + document_parser download recovery

- **Branch:** feat/copilot-backtest
- **Date:** 2026-07-16
- **Author:** Claude (Full-Stack Developer + Domain Expert)
- **Environment:** local unit/pytest + live BSE endpoints + read-only staging DB inspection
- **Changed areas:** backend routes/services: **yes** (nidp services) · frontend src: no

## Summary
Two things shipped on this branch:

1. **Content-based doc typing.** The document_parser now types each filing from its OWN
   first two pages (`doctype.classify`) — `concall_transcript` / `investor_presentation` /
   `annual_report` / `financial_results` / `press_release`, else `announcement_attachment` —
   instead of trusting BSE's self-reported, inconsistently-applied subcategory. Adds the
   missing **annual-report feed** (`nidp.services.annual_reports`, live-verified BSE
   `AnnualReport_New`, ~20-30yr depth/scrip), a Postgres **backfill**, and
   `doc_type_confidence` (migration 123) for the weekly QA loop.

2. **document_parser download recovery** (discovered while verifying #1 — bigger than #1).
   Staging's RAG corpus is dead: **18,574 of 18,579 documents stuck `parse_status='failed'`**
   because ANY download failure was marked terminal and `fetch_pending_docs` never re-queued
   `'failed'`. Fixes: browser UA + per-host Referer in `_download`, and bounded retry
   (`parse_attempts`, migration 124).

## Test Cases
> Authored up front (after design, before implementation).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1..7 | classifier | positive typing: transcript (explicit + body-only), deck (w/ + w/o subcat), annual report, Reg-33 results, press release | unit | correct doc_type, score ≥ THRESHOLD | **PASS** |
| TC-8 | classifier | analyst-meet **intimation** (a notice) | unit/trap | untyped | **PASS** |
| TC-9 | classifier | **notice of upcoming** concall (found as a real false-positive; fixed w/ intimation guard) | unit/edge | untyped | **PASS** |
| TC-10 | classifier | order-win PDF | unit/trap | untyped | **PASS** |
| TC-11 | classifier | trading-window closure | unit/neg | untyped | **PASS** |
| TC-12 | classifier | subcategory hint ALONE (design invariant) | unit | untyped, score < THRESHOLD | **PASS** |
| TC-13 | classifier | first page outweighs conflicting headline | unit | investor_presentation | **PASS** |
| TC-14 | AR feed | live `AnnualReport_New` fetch+parse (real service code) | api (live) | rows w/ Year/PDF/date | **PASS** |
| TC-15 | e2e | **REAL filing PDFs**: download → real pypdf extract → classify | e2e (live) | 5/5 correct | **PASS** |
| TC-16 | regression | existing nidp suite unaffected | unit | no new failures | **PASS** |
| TC-17 | download fix | bot UA vs browser UA+referer on a real BSE PDF | api (live) | 403 → 200 %PDF | **PASS** |
| TC-18 | recovery | are the 18.5k failed URLs actually recoverable? | data (staging) | high 200 rate | **PASS** (30/30) |
| TC-19 | migration | 123 + 124 apply; columns present | data (staging) | columns exist | **BLOCKED** (needs deploy) |
| TC-20 | parser e2e | doc_type flips off announcement_attachment in `nidp.documents` | data (staging) | real typed rows | **BLOCKED** (needs deploy) |
| TC-21 | backfill | `backfill_doctypes --dry-run` retypes existing rows | data (staging) | non-zero, no writes | **BLOCKED** (needs deploy) |
| TC-22 | AR feed e2e | `annual_reports --latest-only --limit 5` inserts pending AR docs | data (staging) | rows land | **BLOCKED** (needs deploy) |

## Evidence — real output

**pytest (TC-1..13 — new durable suite `nidp/tests/test_doctype.py`):**
```
$ python3 -m pytest nidp/tests/test_doctype.py -q
...................                                                      [100%]
19 passed in 0.28s
```

**pytest regression (TC-16):**
```
$ python3 -m pytest nidp/tests -q --ignore=.../test_daas_api.py --ignore=.../test_failing_feeds_golden.py
2 failed, 199 passed, 6 skipped in 3.28s
```
The 2 failures are `services/test_mf_amc_robustness.py` (imports `nidp.services.mf_holdings.amc_dispatch`;
**0** references to any module I changed) — pre-existing, unrelated to this work. The 2 ignored modules
fail to *collect* locally on missing `fastapi` / `fastavro` — a local env gap, not a code change.

**REAL filing PDFs end-to-end (TC-15)** — real BSE download via `_download_headers` → real
`extract_text_from_pdf` (pypdf) → `classify`:
```
[Earnings Call Transcript] HCL Technologies Ltd   485KB 29p  48,714 chars -> concall_transcript (30)
[Earnings Call Transcript] Tata Consultancy Svcs  695KB 25p  46,403 chars -> concall_transcript (48)
[Investor Presentation]    Dhampur Bio Organics  3224KB 26p  22,416 chars -> investor_presentation (26)
[Investor Presentation]    Emmvee Photovoltaic   4393KB 36p  34,923 chars -> investor_presentation (18)
[Reg. 34 (1) Annual Report] TCS LTD.            17019KB 361p 1,082,522 chars -> annual_report (13)
```
Every page-1 was a cover letter (`'9th Floor Nirmal Building ...'`) — reading pages 1-2 is what makes
these classify. This validates the design against real-world filings, not synthetic strings.

**Download root cause + fix (TC-17):**
```
(A) parser's old headers  (nidp-document-parser/1.0, no referer): HTTP 403 Forbidden
(B) browser UA + bseindia referer:                                HTTP 200  first-bytes=b'%PDF-'
```

**Staging state + recoverability (TC-18, read-only):**
```
nidp_staging.nidp.documents: 18,579 rows | parse_status: failed=18,574, parsed=5
failed by host x error:  nsearchives.nseindia.com "download: " (timeout) = 16,482
                         www.bseindia.com "download: 403"                =  2,103
probe 30 random recent FAILED urls with browser UA + host referer:  30 -> 200
```

**Compile (all changed/new files):** `py_compile: ALL OK`

## Data Correctness (staging) — BLOCKED
TC-19..22 need this branch deployed to staging (`/opt/nidp/dev-repo`) + migrations 123/124 applied.
Blocked on a branch decision: my change depends on the user's **untracked** `taxonomy.py`,
`118_ann_subcategory.sql`, `120_widen_document_ingest_window.sql`, `vision_extractor.py`
(352 uncommitted files; local 15 commits ahead of origin). User elected to curate + push the
branch themselves; I verify after. Also note staging's `document_parser` cron is commented out
(`nidp.staging.cron:69`) — it must be run manually or re-enabled.

## Inputs required from user
- Curate + push the branch (see the dependency list above — omitting them = ImportError on staging).
- A fresh `/app/.gcp-token` (the ~1h token expired mid-session) + explicit authorization to SSH
  into `nidp-stack-vm`.

## Verdict: BLOCKED
<!-- Unit/pytest/live/e2e layers PASS (19 tests + 5/5 real PDFs + 30/30 recovery probe). The staging
     DATA layer (TC-19..22) is BLOCKED pending the branch push + deploy. See
     test_reports/OVERRIDE_doctype_fix_pack.md. Not PASS. -->
