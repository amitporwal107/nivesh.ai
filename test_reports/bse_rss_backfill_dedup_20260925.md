# Functionality Verification Report — BSE RSS backfill: correctness fixes + automatic de-duplication

- **Branch:** fix/bse-rss-backfill-dedup (off origin/dev 28823803)
- **Date:** 2026-09-25
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** staging (nidp_staging Postgres on nidp-stack-vm)
- **Changed areas:** backend routes/services: yes (nidp/services/corporate_announcements) · frontend src: no

## Summary
api.bseindia.com has refused every cloud IP (HTTP 403) since 2026-09-23 20:00 IST, so the live BSE
announcement feed writes nothing. `backfill_bse_from_cie.py` fills the gap from the CIE's copy of
www.bseindia.com's RSS through the production parser and writer. Two adversarial reviews found real
defects; this change fixes them:

- bare `AttachLive/` directory links stored as attachment_url → now NULL, as production stores them;
- new listings dropped by scope → equity-ISIN scrips added;
- the feed_reconciler would duplicate every backfilled filing once the API recovers → **the writer now
  retires an RSS row, and its dependants in tables without a foreign key, in the same transaction its
  NEWSID twin is written**;
- a replaced PDF would be inserted as a second filing → collapsed to the latest file;
- `compare()` counted weekends, and its docstring mis-explained the gap.

It also adds the off-VM history fetcher/replay (Cloud Run + residential proxy; proxy leg UNVERIFIED) and
its deploy script. No HTTP endpoint changed, so verification is unit + integration against staging
Postgres + data checks.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | writer | API row written for a filing held as an RSS row (same PDF) | integration | RSS row deleted | PASS |
| TC-2 | writer | attachment-less notice, API 90 s after RSS submission | integration | RSS row deleted | PASS |
| TC-3 | writer | same PDF filed 3 days earlier (a different filing) | edge | kept | PASS |
| TC-4 | writer | attachment-less notice 490 s before the API row | edge | kept | PASS |
| TC-5 | writer | retired id in corporate_transaction_filings / corporate_event_signals (no FK) | integration | dependants removed, unrelated kept | PASS |
| TC-6 | writer | NSE rows or RSS-only batches | unit | no DELETE issued | PASS |
| TC-7 | writer | batch DELETE uses idx_ann_filed_at, not a scan of every BSE row | perf | index scan on r | PASS |
| TC-8 | backfill | bare directory link → NULL; AttachHis link kept; id independent of attachment | unit | as stated | PASS |
| TC-9 | backfill | replaced PDF (same scrip, second, text) | unit | one filing, latest file | PASS |
| TC-10 | backfill | fidelity vs production on 09-15..09-22 | data | recall ≥ 0.99, lag never negative | PASS |
| TC-11 | backfill | write 09-23..09-25 then re-run | data | idempotent (to_insert 0), 0 bare links | PASS |
| TC-12 | off-VM | fetcher URLs/headers/page caps/stop rules == production; replay parse == production | unit | identical | PASS |
| TC-13 | deploy | one-day Cloud Run job args have no repeated token (gcloud rejects them) | unit | unique tokens | PASS |
| TC-14 | regression | every existing announcements-related test | unit | all pass | PASS |

## API / Endpoint Tests (staging)
No HTTP route changed. Service-level evidence:

- **pytest, this branch:** `pytest nidp/tests/services/test_bse_backfill_from_cie.py nidp/tests/services/test_bse_offvm.py -q`
  - Output: `52 passed in 0.37s`
- **pytest, regression (every test touching corporate_announcements / upsert_announcements):**
  - Output: `112 passed in 0.65s`
- **Mutation check:** disabling the writer's supersede step → `1 failed`; old `--flag@@value` deploy args → `1 failed`.
- **TC-1..5, real `upsert_announcements` on staging Postgres, inside an outer transaction ALWAYS rolled back:**
  ```
  upserted: 2
  announcements left: ['t-api-bare', 't-api-pdf', 't-rss-far', 't-rss-late']
  txn filings left: ['t-rss-far'] | signals for retired t-rss-bare: 0
  after rollback TEST01 rows: 0 | t-txn filings: 0
  ```
- **TC-7, EXPLAIN ANALYZE of the batch DELETE with the 1,126 real API ids of 2026-09-22 (rolled back):**
  ```
  ->  Index Scan using idx_ann_filed_at on corporate_announcements r (actual rows=1324 loops=1)
        Rows Removed by Filter: 3813
  Execution Time: 179.402 ms
  ```
  Before the fix the same statement read the r side via `Bitmap Index Scan on corporate_announcements_pkey
  (actual rows=114079)` with `Rows Removed by Filter: 109188`.

## UI / Playwright Tests
Not applicable — no frontend change.

## Data Correctness (staging)
- `--compare 2026-09-15 2026-09-22` (read-only): `recall_of_production 0.9965`, `precision_vs_production 0.9624`,
  lag production-minus-backfill `min 0.0 / median 0.53 / max 40.083` s, `subject_agrees 0.0524`,
  `raw_category_agrees 0.0`, `subcategory_agrees 0.0` (the RSS carries no NEWSSUB/category — documented).
  The 190 unmatched items are production's own sweep gaps: `their attachments found anywhere in table: 0 of 184`,
  `unmatched filed before 12:00 IST: 104 of 190`.
- Writes (runs `8c01cfd1…`, `ad3b8b82…`, `c5ec9b05…`): 09-15..09-22 gap + weekend fill 686 rows, 09-23..09-25 outage
  197 + 143 rows. Per-day RSS rows: 09-19 Sat 456, 09-20 Sun 40, 09-23 1,324, 09-24 1,638, 09-25 2,072 (partial).
- `bare-dir links|0`; the one `nidp.documents` row pointing at the bare directory (0 chunks, pending) deleted: `deleted|1`,
  `bare-dir documents left|0`.
- Re-run `--dry-run 2026-09-15 2026-09-25` → `"to_insert": 0` (idempotent).
- `dup (scrip,attachment) pairs since 09-15|8` — all 8 are API-vs-API rows from BSE serving renamed companies under
  both names (HEG / HEG Advanced Materials; Sarda / Fresita Proteins; Sharp India / Smaart Tech); none involve a
  backfilled row. Pre-existing production behaviour, out of scope here.

## UNVERIFIED
- The live path of the writer change (a real API row retiring a real RSS row) cannot run while api.bseindia.com
  returns 403; it is verified only through the rolled-back integration test above. The change is not deployed.
- 2026-09-25 is partial until a `--write` after the RSS's nightly reset (~00:15 IST).
- The Cloud Run fetcher's proxy leg needs the owner's residential proxy secret `bse-proxy-url`; image, GCS mount
  and GCS write were verified (job-printed sha256 8587dec3…ae243 matched the object read back).

## Inputs required from user
- Residential proxy URL as Secret Manager secret `bse-proxy-url` (only for the off-VM history fetch).

## Verdict: PASS
