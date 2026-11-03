# Macro ingest fix (timezone, warehouse first): results, 2026-10-27

**Test cases:** `test_reports/macro_ingest_fix_TESTCASES.md` (MI-1..MI-10, written before the code).
**Branch:** `fix/macro-ingest-timezone-warehouse` from origin/dev `c882e64c`.
**Run:** `nivesh/backend:staging` image, `--network none`.

| # | Result |
|---|---|
| MI-1..MI-9 | `tests/test_macro_ingest_schedule.py`: 8 tests (MI-1 and MI-2 share one), all pass |
| MI-10 | with the existing macro and broker-hub scheduler tests: **167 passed**. Full CI allowlist: **6,528 passed, 3 failed, 28 skipped** vs dev 6,520 passed with the same 3 network-only failures (`test_cas_api_client` ×2, `test_nidp_stamp_broadcast_at`). 6,528 = 6,520 + 8 new. |

**Staging data:** the 21 and 26 Oct backfill (`macro_regime_backfill_20261027.md`, PASS). The risk service now reads
BEAR as of 2026-10-26, with VIX 17.16.

**After merge:**
- The backend restarts with the new triggers.
- Check `macro_intelligence_daily` next run = 19:30 IST.
- Check that the 19:30 IST run writes 27 Oct from the warehouse (`source_nifty = nidp.index_eod NSE_IND_CLOSE`), and the
  risk service then reads as of 2026-10-27.

## Verdict: PASS
<!-- Scope: unit and regression tests above; the live 19:30 run is checked after deploy. -->
