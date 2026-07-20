# Verification — layout-preserving extraction for numeric table pages (generic)

- **Date:** 2026-07-20  **Branch:** `dev` @ `6134e729`  **Env:** STAGING (`nidp-stack-vm`)
- **Changed:** `nidp/services/document_parser/pdf_extractor.py` — `_pdftotext_layout`,
  `_looks_tabular`, `_apply_layout_tables`, wired into `extract_text_from_pdf`.

## Problem
pypdf reads a multi-column financial table as two jumbled streams — the row labels
separated from their numbers — so EVERY digital results table in the corpus was stored
unusable. The DaaS `/documents/search` API (and the copilot on top of it) therefore
returned garbled figures for headline P&L. Distinct from the vision fix (which cleans
SCANNED tables); this cleans DIGITAL tables (good text layer, wrong reading order) at
zero OpenAI cost.

## Test Cases
- **TC1** — digital results tables extract with columns intact (TCS, HCL).
- **TC2** — prose pages are NOT switched to layout mode (no 2-column interleave regression).
- **TC3** — graceful on a bad/truncated PDF (falls back, never crashes worse than pypdf).

## TC1 — table pages now clean ✅
Real output, new `extract_text_from_pdf` on the live filings:
```
TCS  16p (tabular=3):  Revenue from operations   72,275  70,698  63,437  2,67,021
                       PROFIT BEFORE TAX          17,944  18,362  16,979    65,487
HCL  20p (tabular=8):  Revenue from operations   34,579  33,981  30,349  1,30,144
                       Profit before tax           6,108   5,702   5,189    22,102
```
Columns = [Q1 FY27 | Q4 FY26 | Q1 FY26 | FY26], confirmed against the period-header
row. Before the fix these were stored as label/number soup ("Revenue from operations"
in one chunk, the digits scattered elsewhere).

## TC2 — prose untouched ✅
```
TCS page 1 (cover letter, "9th Floor Nirmal Building Nariman Point Mumbai…")
   _looks_tabular = False  -> keeps pypdf
```
Only 3 of 16 TCS pages and 8 of 20 HCL pages hit the tabular gate (the actual table
pages); the rest keep pypdf. Narrative/2-column prose can't reach 4 lines of 3+ number
columns, so `-layout` (which would interleave columns) is never applied to it.

## TC3 — graceful ✅
Wipro's PDF arrived truncated in the harness; `extract_text_from_pdf` raised
`PdfStreamError` exactly as stock pypdf does — the layout pass added no new failure
mode. `pdftotext` missing/erroring → silent fall back to pypdf.

## Scope / how it reaches production
- **New parses** get it automatically (also the */15 cron, once dev-repo syncs — it's
  already at 6134e729). The cleaned text flows into `document_chunks`, which the DaaS
  documents API serves.
- **Existing docs** get it on re-parse (`reparse_docs.py`). Notably this needs **no
  OpenAI** — so even with the embedding/vision quota exhausted, a re-parse backfill
  would fix the DIGITAL table garble for the whole corpus now; only SCANNED tables
  (SSWL-type) still await the vision tier + restored quota.

## Verdict: PASS
