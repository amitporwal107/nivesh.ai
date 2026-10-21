# Functionality Verification Report — Desk results expectation (backend)

- **Branch:** feat/desk-results-expectation (from dev dc0852af)
- **Date:** 2026-10-21
- **Author:** Claude (full-stack + domain analyst, expectation backend fork)
- **Environment:** staging warehouse (nidp_staging) read-only; unit tests in the nivesh/backend:staging image
- **Changed areas:** backend routes/services: yes · frontend src: no

## Summary
`GET /v1/desk/events-calendar/expectation?symbol=&date=` (DaaS) and `GET /api/markets/events-calendar/expectation` (app).
An EXPECTATION for a results event from the company's own published quarters (same quarter last year x (1 + median of the last two
YoY growth rates)), a band from a point-in-time backtest of the same method over the whole universe, the filed result next to it for
declared events (computed from data known BEFORE the filing), and filings evidence (NSE announcements, no sentiment).
No consensus and no LLM text: neither exists in the warehouse and neither is invented.

## Design decisions fixed before coding (from checked data, 2026-10-21)
- (Revised after the first real run) The band is stratified by company size (last year's quarterly revenue, 4 buckets) as well as growth stability: real errors fall steeply with size.
- Quarterly history in nidp.nse_financials_quarterly is 8 quarters per stock (Dec-2024..Sep-2026; max 9; 1,704 of 2,156 symbols have 8). So the
  method needs: same quarter last year (t-4) and two YoY rates (t-1, t-2) = 7 quarters, and a per-stock backtest has only 2 points (targets t-1, t-2 of the
  latest). The band therefore comes from the UNIVERSE backtest (all stocks, point-in-time), by metric and by an instability bucket; the stock's own 2 errors are shown but flagged as too few.
- Reporting period is read from the calendar's purpose text ("period ended September 30, 2026"); event_calendar.period is unreliable (TCS Jun-2026 is labelled Q1 FY26).
- Known-at for a stored quarter = broadcast_at, else period_end + 60 days (conservative). Values are the latest stored, not as first filed (restatements are not tracked): stated in gaps.
- audited is NULL on all 16,886 rows (rows come from trendlyne_mcp / screener_in, which carry no audit flag; the NSE parser would read it, the xbrl_url is NULL too).
  FINDING during the build: the company's own board-meeting notice (nidp.event_calendar.purpose) often states it ("…Unaudited Standalone and Consolidated Financial Results…"),
  so audit_status is taken from that wording only (unaudited / audited / mixed), with audit_basis naming the source; 'not recorded' when the notice is silent. Never inferred.
- EPS is not comparable across bonus/split (HDFCBANK 21.23 -> 12.78): expected EPS = expected PAT x (latest EPS / latest PAT), share base held at the latest quarter, flagged derived.
- Basis: one basis (consolidated preferred, else standalone) for every quarter used; stated.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | period | parse "period ended September 30, 2026" / "quarter ended Jun 30, 2026" / Dec 31 | unit | period_end 2026-09-30 / 2026-06-30 / 2025-12-31 | PASS |
| TC-2 | period | no date in purpose: last quarter-end before the event date, note says inferred | unit | 2026-09-30 for 2026-10-23 | PASS |
| TC-3 | math | expected = last-year quarter x (1 + median of last two YoY growth rates) | unit | exact value | PASS |
| TC-4 | leakage | declared event: a later-known row (broadcast after cutoff) is ignored; target row never used | unit | expected identical with/without the future rows | PASS |
| TC-5 | leakage | known-at falls back to period_end + 60 days when broadcast_at is null | unit | row after cutoff dropped | PASS |
| TC-6 | reliability | PAT near zero or <= 0 base: expected null, reliable false, note | unit | null + note | PASS |
| TC-7 | reliability | fewer than 7 comparable quarters: no number | unit | null + note naming the count | PASS |
| TC-8 | basis | consolidated incomplete, standalone complete: standalone used and named | unit | basis standalone | PASS |
| TC-9 | banks | revenue missing in needed quarters: revenue unreliable, PAT still computed | unit | reliable false only for revenue | PASS |
| TC-10 | eps | expected EPS from expected PAT and the latest share base; null when latest PAT <= 0 | unit | exact value / null | PASS |
| TC-11 | band | band from universe backtest errors (quantiles), widened to a minimum | unit | low < mid < high, min width | PASS |
| TC-12 | backtest | universe backtest uses only data known before each target (no leakage); counts n | unit | n and median error reproducible on a fixture | PASS |
| TC-13 | declared | filed value vs mid: vs_mid_pct and inside/outside band | unit | exact | PASS |
| TC-14 | audit | audit_status never 'audited'/'unaudited' when audited is NULL | unit | 'not recorded' | PASS (revised: see audit finding) |
| TC-15 | evidence | announcements: window, category filter, dedupe, newest first, limit, no sentiment key | unit | list shape | PASS |
| TC-16 | api | symbol / date validation: 400 bad date, 400 bad symbol, 404-style empty when no results event | api | 400 / gaps | PASS |
| TC-17 | api | app route forwards, 422 on bad params, 502 upstream_unavailable | api | codes | PASS |
| TC-18 | data | real staging data: an upcoming result, a declared one, a bank, a thin-history stock | data | real output below | PASS (read-only staging data, code run offline) |
| TC-19 | data | universe backtest on real data: n, median abs error, share inside the band | data | real numbers below | PASS (numbers below; the baseline is weak, stated) |

## API / Endpoint Tests
- **pytest (nivesh/backend:staging image, branch checked out read-only):**
  `python -m pytest nidp/tests/services/test_daas_desk_expectation.py nidp/tests/services/test_daas_desk_events.py nidp/tests/services/test_daas_desk_macro.py tests/test_events_calendar_routes.py tests/test_macro_calendar_routes.py -q`
  -> `185 passed, 1 warning in 7.98s` (the new file alone: `55 passed`; 5 new route tests in tests/test_events_calendar_routes.py)
- **Registration:** `GET /v1/desk/events-calendar/expectation` is registered in the DaaS app; `GET /api/markets/events-calendar/expectation` in server.py (printed from both apps).
- **HTTP on staging: NOT RUN.** The branch is not deployed and this fork has no session token. See test_reports/OVERRIDE_desk_results_expectation_backend.md.

## Data Correctness (staging, read-only; real code run offline on rows exported with COPY ... TO STDOUT)
Rows: 15,257 quarterly rows, 2,156 symbols (nidp.nse_financials_quarterly), announcements and calendar rows for 8 symbols. `today` = 2026-10-21.

### Universe backtest (every stock, every testable quarter, point-in-time) — the baseline is WEAK; this is what the API reports
| metric | n tests | median abs error | 90th pct abs error | within ±10 % | "last year's quarter unchanged" median / p90 |
|---|---|---|---|---|---|
| revenue | 3,199 | 10.3 % | 41.7 % | 48.8 % | 18.2 % / 57.5 % |
| profit | 1,926 | 27.7 % | 121.9 % | 22.4 % | 33.8 % / 113.2 % |
Band coverage (a 10th–90th band should cover about 80 %): in-sample revenue 79.7 %, profit 79.5 %; held-out stocks (band calibrated on half the stocks, tested on the other half) revenue 76.9 % (n 1,534), profit 76.1 % (n 926); latest quarter only (n 21): revenue 90.5 %, profit 71.4 % — too few to mean anything.
Error falls with size (revenue, first run, 3 buckets, ₹ cr a quarter): small (<=157) median 16.5 % / mid 9.8 % / large (>653) 7.1 %; profit 35.2 % / 26.2 % / 22.0 %. Hence the size × stability bands.
Not source mixing: single-source stocks median 11.3 % (revenue), mixed-source 9.9 %. Signed median error +2.9 % revenue / +5.7 % profit (actuals tend to beat the baseline: 60 % / 56 % above).
Benchmarks tried on the same tests: "latest growth rate only" median 9.7 % revenue (about level) but profit 30.5 % median and p90 180.7 %: the two-rate average was kept.

### Real answers (excerpt; band = low–high, ₹ crore unless EPS)
| stock / meeting | status, basis, audit | revenue | profit |
|---|---|---|---|
| TCS 2026-10-08, Q2 FY27 | declared, consolidated, audit not recorded (notice silent) | expected 69,106–85,518 (mid 73,556), filed 73,188, −0.5 % vs mid, inside | expected 9,484–27,304 (mid 13,092), filed 13,934, +6.4 %, inside |
| AXISBANK 2026-10-17 | declared, consolidated | no number: only 4 of 5 needed quarters have revenue | expected 4,672–13,451 (mid 6,449), filed 7,666, +18.9 %, inside |
| COFORGE 2026-10-23 | upcoming, consolidated | expected 3,993–7,373 (mid 5,588), trend +40.2 % (growth 49.9 % and 30.5 %) | no number: growth 101 % is beyond ±100 % |
| KOTAKBANK 2026-10-24 | upcoming, audit **unaudited** (from the board notice) | no number: missing revenue quarter | expected 3,763–10,833 (mid 5,194); EPS expected 3.78–10.89; last-year EPS hidden (bonus/split) |
| HINDUNILVR 2026-10-28 | upcoming, unaudited (notice) | expected 15,972–19,765 (mid 17,001), trend +4.7 % | expected 1,952–5,865 (mid 2,936) |
| HAVELLS 2026-10-22 (5 quarters) | upcoming | no number: only 4 of 5 needed quarters | no number; stock's own backtest 0 points |
Evidence: 4–8 NSE filings per stock, e.g. TCS: Press Release / Analysts-Investor Meet / Acquisition (all before the meeting day); kinds come from the filing's subject, not a sentiment.
Declared answers use data known before the filing's broadcast_at (TCS: as of 2026-10-08T22:07 IST).

## Inputs required from user
- To run HTTP on staging: merge to dev (this fork cannot push) and a staging session token.

## Verdict: BLOCKED
<!-- HTTP on staging not run; see OVERRIDE. Units and offline real-data runs passed. -->
