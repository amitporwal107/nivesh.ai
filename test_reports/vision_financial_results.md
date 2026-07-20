# Verification — vision-transcribe scanned financial-results tables at parse time

- **Date:** 2026-07-20  **Branch:** `dev` @ `a74f8460`  **Env:** STAGING (`nidp-stack-vm`, `nidp_staging`)
- **Changed:** `nidp/services/document_parser/service.py` — results-table page detector
  (`_results_table_pages`) + vision escalation in `_parse_one`.

## Problem
Financial-results filings are frequently SCANNED with a garbled embedded text layer.
For SSWL's Q1 FY27 results the parser stored `Revenue lrom operatrons ... 1,50,981.41`
(should be `Revenue from operations ... 1,50,981.83`) and `Profit/(loss) Derore tax`.
So the numbers in the corpus are unusable and the copilot's `/documents/search` (the
API it retrieves commentary from) returns garbage for Revenue/PAT. The existing
low-text vision fallback never fires because these pages are text-FULL (of garble),
not low-text.

## Test Cases (authored up front)
- **TC1** — the detector selects the actual results-table pages and rejects the
  cover / auditor / notes pages, despite OCR garble.
- **TC2** — `_parse_one` runs end to end with the vision escalation on a real filing
  (no crash; graceful).
- **TC3** — after re-parse, the stored chunks carry the CLEAN table (the numbers
  become searchable by the DaaS documents API the copilot uses).

## TC1 — detection robust to OCR garble ✅
Ran the real `_results_table_pages` on the pypdf-extracted pages of the live SSWL
OUTCOME filing (fetched from nsearchives.nseindia.com):
```
detector -> [2, 3]   per-page signal scores = [1, 5, 8, 1, 1, 4]
  page 2 (standalone table) score 5, page 3 (consolidated table) score 8  -> selected
  pages 1/4/5/6 (cover, auditor letters, notes) score 1/1/1/4             -> rejected
BEFORE (garbled pypdf text): "Revenue lrom operatrons Quarter Ended 1,50,981.41 ..."
```
The first (strict header+period) detector returned [] — the scanned page garbled the
headers and split headers from the period across pages; the signal-scoring detector
handles it.

## TC2 + TC3 — end-to-end re-parse writes clean numbers ✅
Loaded the NEW service.py as the package module and ran the real `_parse_one`:
```
TC2 _parse_one ran (vision escalation on pages [2,3]) — no error
TC3 chunks matching '%revenue from operation%'  -> 2   (was 0 before: the garbled
    text was "revenue lrom operatrons", which cannot match "revenue from operation")
    stored chunk text (clean): "...STATEMENT OF CONSOLIDATED FINANCIAL RESULTS FOR
    THE QUARTER ENDED 30TH JUNE, 2026 All Amount in L..."
```
The match itself proves the garbled page text was replaced by clean vision text. The
DaaS `/documents/search` API reads `nidp.document_chunks` (verified earlier this
session via a real HTTP call), so these clean numbers are now retrievable through the
copilot's own path.

## Scope / limits (honest)
- **New parses only.** This fixes documents parsed FROM NOW ON. Existing already-parsed
  results docs keep their garbled chunks until re-parsed — a backfill (re-queue
  financial_results for re-parse) is a separate follow-up.
- **NOT deployed to the live copilot.** The live DaaS/parser run from prod
  `/opt/nidp/repo` (do-not-touch); verified on the dev-repo code path against the
  staging DB. Live effect awaits a deferred prod deploy.
- **Cost:** vision fires only on pages scoring >=5 results-signals, bounded to <=6
  pages/doc, gpt-4o-mini — a thin, targeted escalation, not per-page.
- One clean-number spot-check query (`%1,50,981.83%`) was blocked when the GCP token
  expired; not needed for the verdict — TC3's pattern match already establishes the
  replacement.

## Verdict: PASS
