# OVERRIDE — Doc-Type Fix Pack (content classifier + AR feed + download-retry fix)

REASON (updated 2026-07-16, after real staging access): The final DB-write layer is DEFERRED
because deploying this branch to staging would require committing a large slice of the user's
UNCOMMITTED work-in-progress that my change depends on — `taxonomy.py`, `118_ann_subcategory.sql`,
`120_widen_document_ingest_window.sql` and `vision_extractor.py` are all **untracked** (not in
local HEAD, not on origin), and origin's `db.py` does not even import `taxonomy` yet. The branch
has **352 uncommitted files** and local is **15 commits ahead** of origin. Committing/pushing that
WIP to trigger a staging deploy is a consequential call that belongs to the user, not me. Awaiting
their direction. This is a loud, recorded deferral — NOT a claim of end-to-end verification.

## What IS verified (real evidence, this session)
1. **Classifier unit battery — 12/12** incl. all traps + the intimation false-positive fix + the
   design invariant (a subcategory hint alone, score 3, cannot cross THRESHOLD=4).
2. **REAL filing PDFs end-to-end — 5/5** (real BSE download via the new `_download_headers` →
   real pypdf `extract_text_from_pdf` → `classify`):
   - HCL Technologies transcript (485KB/29p) → `concall_transcript` (30)
   - TCS transcript (695KB/25p) → `concall_transcript` (48)
   - Dhampur Bio Organics deck (3.2MB/26p) → `investor_presentation` (26)
   - Emmvee Photovoltaic deck (4.4MB/36p) → `investor_presentation` (18)
   - TCS Annual Report (17MB/**361p**/1.08M chars) → `annual_report` (13)
   Note: every page-1 was a cover letter — reading pages 1-2 is what makes these classify.
3. **Live BSE `AnnualReport_New`** via the real `annual_reports.service` code: TCS 23 rows,
   Reliance 30 rows; field names Table/Year/PDFDownload confirmed; ~20-30yr AR depth per scrip.
4. **py_compile + import** clean on all changed modules; `_download_headers` emits correct
   per-host referers; fetch SQL re-queues 'failed'; update SQL increments `parse_attempts`.

## MAJOR FINDING (bigger than doc-typing) — staging RAG corpus is dead
`nidp_staging.nidp.documents`: 18,579 rows, **only 5 parsed — 18,574 `failed`**
(16,482 `nsearchives.nseindia.com` timeouts + 2,103 `bseindia` 403s; all inside the 180-day window).
Root cause: `_parse_one` marks ANY download failure terminal `'failed'`, and `fetch_pending_docs`
never re-queued `'failed'` — so one transient blip killed thousands permanently. **Proven
recoverable: 30/30 sampled failed URLs return HTTP 200 now.** Fixes on this branch:
- `_download` now sends a browser UA + per-host Referer (bseindia/nseindia) — kills the 403 class.
- Migration `122` + `fetch_pending_docs` bounded retry (`parse_attempts < NIDP_MAX_PARSE_ATTEMPTS`,
  default 5): transient failures self-heal; permanently-gone URLs (BSE purges old AttachLive → 404)
  stop after the cap. Existing rows default to 0 attempts → the 18.5k backlog becomes retry-eligible
  with **no bulk UPDATE required**.

## Still BLOCKED (needs the deploy decision)
- Apply migrations 123 + 124 to `nidp_staging` (staging DB is on VM port 5434;
  `/opt/nidp-staging/venv/bin/python -m nidp.cli migrate`).
- Run `document_parser` on staging and show the doc_type distribution flip off
  `announcement_attachment` (NOTE: staging's document_parser cron is **commented out** at
  `nidp.staging.cron:69` — it must be run manually or re-enabled).
- `backfill_doctypes --dry-run`; `annual_reports --latest-only --limit 5`.

Until those run with real output, this is IN PROGRESS, not DONE.
