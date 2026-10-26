# Test cases — AI scanner price history and adjusted prices (study N1, N2; plan 0.8 + adjusted prices; gates 5, 6)

Authored before implementation, 2026-10-27. Branch `fix/scanner-bar-integrity` (off origin/dev 5b6b3cfd).
Acceptance standard: `docs/NIVESH_AI_LAB_PHASE_SUCCESS_CRITERIA.md` §0.1 (Historical market data).

## Design the cases test against

- `bhavcopy_ingester.parse_bhavcopy_csv(blob, on_date)` reads every row's own `DATE1` (real NSE header:
  `SYMBOL, SERIES, DATE1, …`, value like ` 01-Oct-2026`) and raises `BhavcopyDateMismatch` unless the file's dates are
  exactly `{on_date}`. `bhavcopy_ingester.ingest(on_date)` returns an explicit result
  (`written | not_a_session | calendar_unavailable | not_published | date_mismatch | no_rows`) and writes nothing unless
  `written`. `ingest_for_date` keeps returning the row count (0 when refused) for the two admin routes.
- `session_calendar`: NSE CM holiday list (DaaS `/holidays`) decides whether a date is a session; a year with no CM
  rows, or an unreadable list, is `CalendarUnavailable` (never "assume a weekday trades"). Warehouse sessions
  (DaaS `/prices/eod?on=`) decide whether a past date was a session.
- Runner: refuses a non-session run date (exit 3) or an unverifiable one (exit 4) before any fetch or scoring;
  `--backfill-missing` ingests warehouse sessions the store lacks in a bounded window; `--require-clean` refuses scoring
  when the data-quality check finds missing/copied/non-session dates (exit 5).
- `pipeline.run_for_date` refuses a non-session date; features are computed on bars adjusted with the warehouse's
  `cumulative_adj_factor` (DaaS `/prices/adjusted/bulk`), then truncated at any residual ≥40% one-session break
  (the `research_chart._adjustment_break` rule). Factors unreadable → the run refuses (fail closed).
- `bar_quality`: missing sessions, non-session dates, copied sessions, duplicate bars, stale symbols, invalid OHLC,
  zero volume — counts plus sample symbols.
- `scripts/repair_scanner_bars.py`: `--dry-run` (default, read-only), `--apply --snapshot PATH`, `--restore PATH`.

## Cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | ingester (gate 5) | Real-format file for 01-Oct-2026 requested as 2026-10-02 (what NSE serves for the holiday URL) | unit | `parse_bhavcopy_csv` raises `BhavcopyDateMismatch` naming 2026-10-01; `ingest` → `date_mismatch`, upsert never called, 0 rows |
| TC-2 | ingester | Matching file (DATE1 = requested) | unit | rows parsed and stamped with the file's date; `ingest` → `written` with the upsert's count |
| TC-3 | ingester edge | File with mixed DATE1 values, or no DATE1 column, or blank DATE1 | edge | refused (`BhavcopyDateMismatch`), nothing written |
| TC-4 | ingester | Holiday requested (calendar says not a session) | unit | `not_a_session` with the holiday name; NSE never fetched; nothing written |
| TC-5 | ingester failure | Calendar unreadable | failure | `calendar_unavailable`; NSE never fetched; nothing written |
| TC-6 | ingester | NSE fetch fails / empty body | failure | `not_published`, nothing written; `ingest_for_date` returns 0 |
| TC-7 | calendar | Weekend, CM holiday, ordinary weekday | unit | (False,"weekend"), (False,"NSE holiday: …"), (True,…) |
| TC-8 | calendar edge | Holiday list empty for the year / HTTP error | edge | `CalendarUnavailable` |
| TC-9 | runner | Run date is a holiday | unit | exit 3, `skipped=not_a_session`; no ingest, no scans, no scoring |
| TC-10 | runner | Calendar unavailable | failure | exit 4, `skipped=calendar_unavailable`; nothing fetched or scored |
| TC-11 | pipeline | `run_for_date` on a holiday | unit | `{"ok": False, "error": "not_a_session"}`; nothing scored |
| TC-12 | back-fill | Store lacks two warehouse sessions in the window | unit | both ingested (via the DATE1-checked ingester), summary lists them |
| TC-13 | back-fill | Second run after TC-12 | unit | no-op: nothing fetched, nothing written |
| TC-14 | back-fill failure | Warehouse sessions unreadable | failure | back-fill step reports the error; no ingest attempted |
| TC-15 | adjusted (gate 6) | KOTAKBANK-style 5:1 split (raw 2133.30 → 421.00 on 2026-01-14), warehouse factor 0.2 before | unit | adjusted series has no ≥40% move; SMA20/50/200, ATR14, 20d return, swing levels, volume z-score match a natively continuous series; raw series shows the break |
| TC-16 | adjusted | No factors for the symbol (BE-only / not in warehouse) | edge | `raw_no_factors`; window truncated at the break (research_chart rule); bars before it dropped |
| TC-17 | adjusted | Ex-date is the run date (warehouse factors only through T-1) | edge | residual break at T → truncated → fewer than MIN_BARS → not scored that day (recorded) |
| TC-18 | adjusted | Symbol with factor 1 throughout | unit | bars unchanged (byte-identical values) |
| TC-19 | pipeline failure | Factor fetch fails | failure | `run_for_date` → `{"ok": False, "error": "adjustment_factors_unavailable"}`, nothing persisted |
| TC-20 | data quality | Store with a copied holiday date, a missing session, an invalid OHLC row, a zero-volume row, a stale symbol | unit | each check reports the exact count and sample symbols |
| TC-21 | repair dry-run | Fake store: 2 phantom dates (one 100% copy, one partial), 1 missing session | unit | plan lists exactly the 100% copy as phantom, the partial one as "unverified, not deleted", the missing session with its warehouse rows; the fake store records zero writes |
| TC-22 | repair apply | Apply on the fake store | unit | phantom rows + their derived rows deleted, missing session back-filled, recompute date replaced, snapshot written before any change |
| TC-23 | repair idempotency | Apply twice | unit | second run changes nothing (no deletes, no ingest, no recompute) |
| TC-24 | repair restore | Restore the snapshot after apply | unit | the fake store equals its pre-apply state; restore twice changes nothing more |
| TC-25 | repair guard | `--apply` without `--snapshot` | edge | refused before any read-write |
| TC-26 | regression | Existing engine tests | unit | `test_positional_engine.py`, `test_positional_runner_guards.py`, `test_positional_calibration.py`, `test_positional_scan_universe.py`, `test_positional_desk_fields.py`, `test_positional_scenario.py`, `test_ai_watchlist.py` pass (baseline on origin/dev run if any fail) |
| TC-27 | staging data (read-only) | Repair dry-run against staging | data | real counts: phantom dates + rows, missing sessions + warehouse rows, derived rows, CA symbols (reconciled with the study's 91), adjusted-vs-warehouse sample, DQ report, scanner rerun preview — and zero writes |

## Not covered here (stated, not hidden)

- No staging deploy, no `--apply`, no cron change: the code paths are verified by unit tests and the read-only dry-run
  only. Staging verification of the deployed code is a post-merge step listed in the report.
