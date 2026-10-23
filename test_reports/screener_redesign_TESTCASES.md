# Screener redesign — test cases (authored before implementation, 2026-10-23)

Scope: POST /api/screeners/run gains mutual-fund metrics; the Screener screen gets lens tabs, live Kite
price/day columns, sortable results and a click-to-chart panel that reuses Research's StockResearch.

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | api | run with `mfAmcsUp over 3` joins scanner rows by symbol and keeps only stocks that pass | unit (pytest, scanner mocked) | matched rows all carry amcsUp >= 3 |
| TC-2 | api | a stock outside the scanner's universe has no MF value and FAILS an MF rule | unit | not in matches; coverage for the key is filled < total |
| TC-3 | api | scanner answers non-200 / raises: run still answers ok:true for non-MF rules, MF coverage 0/total | failure | no 500; MF columns null |
| TC-4 | api | scanner failure + an MF rule: matches nothing, coverage says 0 filled (a gap, not a verdict) | failure | matched 0, coverage[key].filled 0 |
| TC-5 | api | unknown metric still 422; each new MF key accepted | edge | 422 names it / 200 |
| TC-6 | api | existing 29 test_screeners_run cases still pass | regression | all pass |
| TC-7 | api (staging) | real run with an MF rule returns rows whose MF values match GET /api/markets/smart-money/scanner for the same symbol | data | values equal |
| TC-8 | e2e | clicking a result row opens the stock panel with the Research price chart (same component) and the stock name | e2e | dialog visible, research-stock-price shown |
| TC-9 | e2e | Esc / close button closes the panel and returns focus to the row | e2e | dialog gone |
| TC-10 | e2e | lens tabs switch the visible columns (Overview / Fundamentals / Technicals / Ownership & funds) | e2e | header text differs per lens |
| TC-11 | e2e | clicking a column header sorts; second click reverses; null values always sort last | e2e | row order |
| TC-12 | e2e | live Kite LTP + Day % columns show while feed LIVE, "—" otherwise; no column of zeros | e2e | cell text |
| TC-13 | e2e | all existing screener states (idle, loading, error, nodata, nomatch, partial, saved run, template) keep their testids and copy | regression | existing spec passes |
| TC-14 | e2e | ready-made (strategy-builder) screen rows also open the chart panel | e2e | dialog visible |
| TC-15 | e2e | mobile width: panel is full-screen sheet, table scrolls horizontally, no page-level overflow | e2e | no horizontal page scroll |
| TC-16 | e2e | MF-metric coverage note is shown ("Nifty 500 only") when an MF rule is used | e2e | coverage line text |
| TC-17 | static | tsc --noEmit clean | static | exit 0 |
