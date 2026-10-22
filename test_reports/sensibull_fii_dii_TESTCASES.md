# Test cases — Sensibull FII/DII ingest (authored BEFORE implementation)

**Service** `backend/nidp/services/sensibull_fii_dii/` → `nidp.fii_dii_flows`
**Authored** 2026-10-22, before any implementation code was written, per
`.claude/VERIFICATION_PROTOCOL.md`.

## Design decisions these cases lock in

`nidp.fii_dii_flows` PK is `(as_of_date, category, segment, source)`. `source` is already in the
key, so provenance separation needs **no migration**.

| Decision | Value | Why |
|---|---|---|
| Daily source tag | `SENSIBULL` | |
| Monthly source tag | `SENSIBULL_MONTHLY` | A *distinct source* keeps monthly and daily un-mixable: every query filters `source`, so an accidental sum across granularities cannot happen silently. `as_of_date` always being the 1st is a second, independent signal. |
| Existing NSE rows | `NSE_FII_DII`, untouched | The overlap is a free daily reconciliation check, so NSE rows are never overwritten. |
| Categories | `FII`, `DII`, `PRO`, `CLIENT` | The feed carries all four for F&O; cash carries FII/DII only. |
| Segments | `EQUITY_CASH`, `INDEX_FUTURES`, `INDEX_OPTIONS`, `FUT_NIFTY`, `FUT_BANKNIFTY`, `FUT_FINNIFTY`, `FUT_MIDCPNIFTY`, `FUT_NIFTYNXT50` | Index-specific F&O without a schema change. |
| Deliberately NOT ingested | `net_view` / `net_view_strength` / `net_action` strings, call/put long-short legs, `amount-wise` duplicates of `quantity-wise` | They are the vendor's *interpretation*, not observations. We do not store another party's opinion as if it were data. |

## Cases

| # | Case | Expected |
|---|---|---|
| T1 | Anonymous token mint | `GET /v1/pluto/auth/web/session/a/platform/identify` yields `access_token=pa:<JWT>`. If absent, the service aborts loudly and writes **no** rows. |
| T2 | Month discovery, not guessing | The no-param daily call is made first and `key_list` drives which months are fetched. Hard-coded month lists are a defect. |
| T3 | Month-name parameter | `year_month` is sent as `2026-September`. The numeric form `2026-09` must never be sent (it returns `Internal Calculation Error`). |
| T4 | Origin header required | Both data calls send `Origin: https://web.sensibull.com`. Without it the API returns `access denied`. |
| T5 | Daily cash rows land correctly | For each trading date in each month: 2 rows (FII, DII) at `segment=EQUITY_CASH`, `source=SENSIBULL`, with `buy_value_cr`, `sell_value_cr`, `net_value_cr` populated and `net ≈ buy − sell`. |
| T6 | Net is internally consistent | `abs(net_value_cr − (buy_value_cr − sell_value_cr)) < 0.01` on every cash row. Catches a field-mapping error silently producing plausible numbers. |
| T7 | Monthly rows land under their own source | 98 months × 2 categories at `source=SENSIBULL_MONTHLY`, `as_of_date` = 1st of month, earliest 2018-09-01. |
| T8 | Granularity cannot be mixed | No `as_of_date` carries both a `SENSIBULL` and a `SENSIBULL_MONTHLY` row for the same (category, segment) **unless** the date is a 1st — and even then the two are separable by `source`. A guard query must fail loudly if an aggregate spans both sources. |
| T9 | Idempotency | A second full run leaves row count unchanged and **no** `net_value_cr` altered. Only `ingested_at` / `source_run_id` may move. |
| T10 | Existing NSE rows survive byte-identical | The 16 `NSE_FII_DII` rows have the same `net_value_cr` before and after. |
| T11 | Cross-source agreement on the overlap | On dates where `SENSIBULL` and `NSE_FII_DII` both have an `EQUITY_CASH` row, nets agree within tolerance. A real disagreement is reported, not smoothed. |
| T12 | Coverage and missing sessions reported | The service reports, per source, its date range and **which trading sessions inside that range are missing** (calendar from `prices_eod`). The flows panel must not be enabled before this is clean. |
| T13 | F&O OI captured | `INDEX_FUTURES` / `INDEX_OPTIONS` rows exist for all four categories with `open_interest` and `net_contracts` populated; per-index `FUT_*` rows carry `net_contracts`. |
| T14 | Politeness | Sequential month requests with a deliberate gap; this is a public app's internal endpoint, not a documented API. |
| T15 | Partial failure is not silent | If a month fetch fails, the service logs it, counts it, and still finalises its job row — it does not write a partial month and claim success. |

## Out of scope for this run, stated so it is not mistaken for coverage

- **No evaluator rerun.** `nidp.fii_dii_flows` is **not** an input to
  `smart_money_study/evaluator.py` (verified by grep: no match). Market-wide flows cannot extend
  the formation-date sample, which is bound by `stock_features_daily` starting 2025-12-29. The
  B-vs-C gate stays **INCONCLUSIVE** on the same 9 dates.
- **1Y daily remains short.** Daily depth is a ~7-month rolling window (~145 sessions) vs 248
  needed. The 1Y chart uses the monthly series as a clearly-labelled lower-frequency fallback.
- **ScanX is not ingested here.** It stays an independent reconciliation feed.
