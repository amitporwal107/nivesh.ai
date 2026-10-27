# Results This Week (P1.5) — backend functionality report

- **When:** 2026-10-27 23:58 IST · **Branch:** feat/results-week-file (from origin/dev 18b4870d) · **Spec:** docs/EARNINGS_SURPRISE_TRACKER.md §9 (contract committed e0553edf before implementation)
- **What:** `GET /api/desk/results-week/stock/{symbol}` (the per-stock results file) and `fno_track` {before, after} on the list's F&O rows.

## Test cases
| TC | What | Result |
|---|---|---|
| TC-R1 | snapshots: one session's own build-up; a span without an expiry reads the state | PASS |
| TC-R2 | a span across a monthly expiry is NOT read either way (rising or falling OI); the standard rollover % vs the stock's own past expiries is used (staging BAJAJ-AUTO 79.8 % vs 86.0 %) | PASS |
| TC-R3 | fno_track: declared before/after with the expiry carry; upcoming = positioning so far; non-F&O = null | PASS |
| TC-R4 | track window rel −5…latest, holidays skipped, upcoming anchored on the meeting session; volume ×, vs Nifty | PASS |
| TC-R5 | PCR and next-month premium | PASS |
| TC-R6 | commentary split pre / the result / post by the results filing time, latest analysis per filing, factors heaviest first, links, sentiment from the best-confidence results analysis; earnings calls classified as such | PASS |
| TC-R7 | no results analysis → no sentiment, coverage says so | PASS |
| TC-R8 | preview lines from data only, "baseline, not analyst consensus", no buy/sell/recommend/pick/beat | PASS |
| TC-R9 | route: 401 signed out; 422 bad symbol / date / future; 200 for a listed stock (incl. M&M); 404 no_results_meeting; past day from the stored snapshot (404 not_stored) | PASS |
| TC-S6 | staging dry run (read-only overlay, real data) | PASS (below) |

## Real output
```
pytest tests/test_results_stock.py tests/test_results_week.py tests/test_results_signal.py tests/test_positional_engine.py tests/test_positional_desk_fields.py
168 passed, 2 warnings in 7.84s
```
Staging dry run (branch code overlaid read-only in nivesh-staging-app-backend; nothing written):
```
week 2026-10-27 built in 9.2s; gaps: ['results calendar: no analyst consensus is available (nidp.earnings_estimates is empty): this is a baseline, not a consensus', 'results calendar: no news feed is 
  list MANKIND    declared  before=('2026-10-26', 'long build-up', 4.49, 9.6) after=('2026-10-26', '2026-10-27', 'rollover 92.6 % vs its usual 93.6 % (normal)', 8.24, -6.08, True)
  list SONACOMS   declared  before=('2026-10-26', 'no clear signal', 3.86, -1.22) after=('2026-10-26', '2026-10-27', 'rollover 92.2 % vs its usual 86.0 % (higher than usual)', 8.95, -20.11, True)
  list BAJAJ-AUTO declared  before=('2026-10-26', 'no clear signal', -0.01, 3.5) after=('2026-10-26', '2026-10-27', 'rollover 79.8 % vs its usual 86.0 % (lower than usual)', 3.17, 18.52, True)
  list TATACONSUM declared  before=('2026-10-26', 'long unwinding', -2.84, -2.57) after=('2026-10-26', '2026-10-27', 'rollover 96.0 % vs its usual 94.8 % (normal)', 6.78, -5.36, True)
  list HEROMOTOCO upcoming  before=('2026-10-27', 'no clear signal', 0.38, -12.04) after=None
  list SUNPHARMA  upcoming  before=('2026-10-27', 'no clear signal', 0.64, -1.45) after=None
== FILE MANKIND (declared, first reaction 2026-10-27) built in 0.2s; gaps []
  commentary pre 3 · results 3 · post 0 · sentiment ('moderately_positive', 88.0) · coverage: 6 of 18 exchange filings since 2026-10-06 have a stored analysis; the others are not summarised here.
    rel -5 2026-10-19 close 2253.2 chg -0.98 vsN 0.13 vol× 2.0 | OI 1.17 px -0.98 no clear signal prem None exp False carry None pcr None
    rel -4 2026-10-21 close 2285.5 chg 1.43 vsN 1.77 vol× 0.4 | OI -2.17 px 1.43 short covering prem None exp False carry None pcr None
    rel -3 2026-10-22 close 2275.6 chg -0.43 vsN 0.11 vol× 1.0 | OI -1.32 px -0.43 no clear signal prem None exp False carry None pcr None
    rel -2 2026-10-23 close 2212.6 chg -2.77 vsN -2.38 vol× 1.1 | OI -1.83 px -2.77 no clear signal prem None exp False carry None pcr None
    rel -1 2026-10-26 close 2312.0 chg 4.49 vsN 3.81 vol× 1.6 | OI 9.6 px 4.49 long build-up prem 0.22 exp False carry None pcr 0.43
    rel +0 2026-10-27 close 2502.5 chg 8.24 vsN 8.25 vol× 4.9 | OI -6.08 px 8.24 short covering prem 1.06 exp True carry -1.0 pcr 1.03
  before: {'date': '2026-10-26', 'state': 'long_buildup', 'text': 'long build-up', 'price_pct': 4.49, 'oi_pct': 9.6, 'span': '1 session'}
  after: {'date': '2026-10-27', 'since': '2026-10-26', 'state': None, 'text': 'rollover 92.6 % vs its usual 93.6 % (normal)', 'price_pct': 8.24, 'oi_pct': -6.08, 'span': '2026-10-26 close → 2026-10-
== FILE BAJAJ-AUTO (declared, first reaction 2026-10-27) built in 0.1s; gaps []
  commentary pre 0 · results 0 · post 0 · sentiment None · coverage: 0 of 10 exchange filings since 2026-10-06 have a stored analysis; the others are not summarised here. The results filing itself
    rel -5 2026-10-19 close 10287.0 chg -1.13 vsN -0.02 vol× 0.4 | OI -1.71 px -1.13 no clear signal prem None exp False carry None pcr None
    rel -4 2026-10-21 close 10072.0 chg -2.09 vsN -1.75 vol× 0.5 | OI 2.45 px -2.09 short build-up prem None exp False carry None pcr None
    rel -3 2026-10-22 close 10155.0 chg 0.82 vsN 1.37 vol× 0.7 | OI -1.58 px 0.82 no clear signal prem None exp False carry None pcr None
    rel -2 2026-10-23 close 10072.0 chg -0.82 vsN -0.43 vol× 0.8 | OI 2.33 px -0.82 short build-up prem None exp False carry None pcr None
    rel -1 2026-10-26 close 10071.0 chg -0.01 vsN -0.69 vol× 0.6 | OI 3.5 px -0.01 no clear signal prem 0.25 exp False carry None pcr 1.17
    rel +0 2026-10-27 close 10390.0 chg 3.17 vsN 3.18 vol× 1.1 | OI 18.52 px 3.17 long build-up prem 0.63 exp True carry -6.2 pcr 0.8
  before: {'date': '2026-10-26', 'state': 'no_clear_signal', 'text': 'no clear signal', 'price_pct': -0.01, 'oi_pct': 3.5, 'span': '1 session'}
  after: {'date': '2026-10-27', 'since': '2026-10-26', 'state': None, 'text': 'rollover 79.8 % vs its usual 86.0 % (lower than usual)', 'price_pct': 3.17, 'oi_pct': 18.52, 'span': '2026-10-26 close �
== FILE HEROMOTOCO (upcoming, first reaction None) built in 0.1s; gaps []
  commentary pre 0 · results 0 · post 0 · sentiment None · coverage: 0 of 7 exchange filings since 2026-10-07 have a stored analysis; the others are not summarised here.
    rel -5 2026-10-21 close 5153.5 chg -1.46 vsN -1.12 vol× 0.8 | OI 3.02 px -1.46 short build-up prem None exp False carry None pcr None
    rel -4 2026-10-22 close 5128.0 chg -0.49 vsN 0.05 vol× 1.0 | OI 0.84 px -0.49 no clear signal prem None exp False carry None pcr None
    rel -3 2026-10-23 close 5047.0 chg -1.58 vsN -1.19 vol× 1.0 | OI 3.43 px -1.58 short build-up prem None exp False carry None pcr None
    rel -2 2026-10-26 close 5199.0 chg 3.01 vsN 2.33 vol× 0.8 | OI 3.88 px 3.01 long build-up prem None exp False carry None pcr None
    rel -1 2026-10-27 close 5218.5 chg 0.38 vsN 0.39 vol× 1.1 | OI -12.04 px 0.38 no clear signal prem -0.16 exp True carry -8.9 pcr 0.95
  before: {'date': '2026-10-27', 'state': 'no_clear_signal', 'text': 'no clear signal', 'price_pct': 0.38, 'oi_pct': -12.04, 'span': '1 session'}
  after: None
== FILE ITCHOTELS (declared, first reaction 2026-10-27) built in 0.1s; gaps []
  commentary pre 0 · results 0 · post 0 · sentiment None · coverage: 0 of 5 exchange filings since 2026-10-06 have a stored analysis; the others are not summarised here. The results filing itself 
    rel -5 2026-10-19 close 158.5 chg -2.45 vsN -1.34 vol× 0.6 | OI None px None None prem None exp None carry None pcr None
    rel -4 2026-10-21 close 156.18 chg -1.46 vsN -1.12 vol× 0.7 | OI None px None None prem None exp None carry None pcr None
    rel -3 2026-10-22 close 161.83 chg 3.62 vsN 4.16 vol× 2.0 | OI None px None None prem None exp None carry None pcr None
    rel -2 2026-10-23 close 156.25 chg -3.45 vsN -3.06 vol× 1.5 | OI None px None None prem None exp None carry None pcr None
    rel -1 2026-10-26 close 164.31 chg 5.16 vsN 4.48 vol× 11.1 | OI None px None None prem None exp None carry None pcr None
    rel +0 2026-10-27 close 166.3 chg 1.21 vsN 1.23 vol× 11.0 | OI None px None None prem None exp None carry None pcr None
  before: None
  after: None
```

## UNVERIFIED
- The live route over HTTP and the screens need this PR (and the frontend PR from feat/results-week-watchlist-ui) merged and deployed.
- Analyst views: no source is connected (Trendlyne MCP returns corporate events only) — the API says so.
- Commentary coverage is what the filing-analysis pipeline has analysed (e.g. MANKIND 6 of 18 filings; BAJAJ-AUTO 0 — scanned results PDF).
- The nightly snapshot job (cron) is still not installed; past dates answer only once a day is stored.

## Verdict: PASS
