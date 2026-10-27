# Macro ingest fix: test cases (written before the code), 2026-10-27

**Owner approval:** "approve regime fix" (27 Oct): the code part (a) of `regime_staleness_diagnosis.md`.
**Defect:**
- The macro job's `CronTrigger(hour=18, minute=35)` has no timezone. In the UTC backend container it runs at 00:05 IST,
  when yfinance often leaves out the session that just closed.
- `macro_daily` therefore lagged: 21 and 26 Oct were never stored, and the risk service's regime read "as of 23 Oct".
- `latest_state` logged the lag as "likely NSE holiday".

| # | Case | Expected |
|---|---|---|
| MI-1 | The macro job's trigger | `macro_intelligence_daily` runs Mon–Fri at **19:30 Asia/Kolkata** (next run prints `19:30 +0530`), one instance at a time |
| MI-2 | The retry | `macro_intelligence_retry` runs Mon–Fri at **21:30 Asia/Kolkata**, the same function, one instance |
| MI-3 | The benchmark job | `benchmark_index_daily` keeps 18:30 but **in Asia/Kolkata** (next run `18:30 +0530`) |
| MI-4 | Warehouse has the session | Nifty and India VIX come from `nidp.index_eod` (`source = nidp.index_eod NSE_IND_CLOSE`, confidence 1.0). The row is dated by the **warehouse session**. yfinance is not asked for those two. |
| MI-5 | Warehouse read fails or is empty | Nifty and VIX fall back to yfinance as before (`^NSEI`, `^INDIAVIX`) |
| MI-6 | The warehouse is a session behind (today not ingested yet) | The row is dated by the warehouse's latest session, never by today's date; `market_open_today` False. The 21:30 retry picks up today. |
| MI-7 | A past `target_date` | The warehouse read ends at that date, so Nifty and VIX are that session's (no longer the latest bar) |
| MI-8 | India VIX from a different session than Nifty | Rejected (`session_mismatch`), never stored against the wrong day |
| MI-9 | `latest_state` falls back | The log says "not ingested yet, or not a session"; "likely NSE holiday" is gone |
| MI-10 | Regression | The existing macro, broker-hub scheduler and desk-regime tests still pass, and the full CI allowlist has no new failures vs dev |
