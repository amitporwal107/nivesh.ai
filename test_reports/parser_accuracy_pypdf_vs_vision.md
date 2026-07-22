# Parser accuracy — pypdf (what we store) vs gpt-4o vision (reference)

- **Date:** 2026-07-16
- **Question:** `parse_status='parsed'` is a status, not a correctness claim. How accurate is the
  text we actually store — and does pypdf lose table values badly enough to justify replacing it
  (e.g. with Docling)?
- **Method:** 54 successfully-parsed NSE filings, stratified 9 per doc_type. For each: re-download
  the PDF, extract with pypdf (exactly what the pipeline stores), rasterise the same page
  (`pdftoppm -r 150`), transcribe it with **gpt-4o vision** (`temperature=0`, "transcribe verbatim,
  include EVERY number and all table values"), and compare.
- **Pages:** page 1 (cover) + the middle page (`n//2`, where tables live), max 2/doc.
- **Metric:** *material number recall* — of the financially-meaningful numeric tokens vision saw
  (decimal, or >=4 digits), what fraction did pypdf also capture? Raw all-token recall is noise:
  dates, page numbers and bullets dominate it.
- **Cost:** ~$1.70. Harness: `scratchpad/bakeoff.py` (not committed — throwaway).

---

## Result

| | pages | mean | median | perfect |
|---|---|---|---|---|
| page 1 (cover/letterhead) | 54 | 71% | 82% | 14/54 |
| **middle pages (content/tables)** | **20** | **99%** | **100%** | **18/20** |

Content pages by doc_type: concall_transcript 100% · press_release 100% · annual_report 99% ·
investor_presentation 100% · announcement_attachment 100% · financial_results 86% (1 page only).

**Total material misses across all 20 content pages: 2.**

## Where the loss actually is

Every low-recall page is **page 1**, and the missed tokens are the same shape every time:

```
'033417', '042363', '011854'   -> CIN fragments
'122002', '400070', '122050'   -> PIN codes
'1995', '1987', '1990', '2008' -> incorporation years
'1800', '7777', '6300'         -> phone / toll-free numbers
```

Classified across all misses: 30% phone/misc, 27% CIN/PIN-like, 9% year — **66% is letterhead
metadata**, which is rendered as an *image* in the letterhead block and therefore invisible to
pypdf by construction. Not one missed token was a reported financial figure.

`investor_presentation` — the strongest case for a layout/vision model — measured mean 73% /
median 90%, and all three worst pages were p1 letterheads (33%, 33%, 36%).

## Conclusion

**pypdf is ~99% faithful on content, and the table-fidelity concern is not supported.**
An earlier claim in this project's discussion — that flattened tables were the biggest unmeasured
accuracy risk and the best argument for Docling — was a plausible inference that the data refutes.
Recorded here so the decision rests on evidence rather than intuition.

**Recommendation: do NOT adopt Docling on this evidence.** It would add a multi-GB torch + model
stack to a 17-dependency service on a VM at 90% disk (5.1G free), to fix something measuring ~1%.
If the letterhead fields (CIN, registered office) are ever wanted, that is OCR on page 1 only.

**Do instead: install tesseract on the staging VM.** `pdftoppm` is present but `tesseract` is
MISSING, so `ocr_available()` is False and **387 scanned documents extract at 0%**. The code
already re-queues `skipped_non_text` automatically once OCR appears. One package, measured return.

## Limitations (do not over-read this)

1. **20 content pages is a modest sample.** Filings <=3 pages have no "middle" page, so per-type
   counts are thin — `financial_results` rests on a single page (86%).
2. **"Middle page" is a proxy for "table page"**, not verified page-by-page.
3. **Vision is a reference, not ground truth.** This measures agreement with gpt-4o, not
   correctness; vision can hallucinate or misread. A true accuracy number needs human checking.
4. **NSE only.** The expired BSE `AttachLive` slice is unrepresented.
5. Numbers-only. Says nothing about narrative text fidelity or reading order.

## Verdict: PASS
