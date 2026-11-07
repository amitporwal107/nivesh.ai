# Functionality Verification Report — Market Intelligence "Market Update" ticker

- **Branch:** feat/intel-news-ticker (from origin/dev ea951dcb) · PR #498
- **Date:** 2026-11-06
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** production build of the branch (vite preview, Playwright 1.60, mocked routes) + real staging bodies captured
  read-only from the staging backend's own route handlers (6 Nov 09:18 IST) + nidp_staging SQL
- **Changed areas:** backend routes/services: **no** · frontend src: **yes**

## Summary
A Bloomberg-style band, MARKET UPDATE, on Market Desk › Market Intelligence above the AI Event Intelligence list. Owner asks:
5 Nov, a ticker with results today and tomorrow, fresh orders, M&A and the other important items; 6 Nov, "a summary of the
everything, need not to display every thing". Each item is one kind: a count line and a few names.
- **Results:** declared since the previous weekday, with Rev / PAT against the same quarter last year.
- **Meetings:** filed today with figures pending, due today, tomorrow.
- **Orders and M&A:** full counts from the feed's own per-category counts, plus the newest companies.
- **Market:** corporate-action counts, the latest deal day with its largest deals, FII / DII, SEBI circulars, and sector moves
  of 1 % or more.

A name opens its event below or the company's results panel in the Events calendar. "+n more" opens the full list. There is
no new route.

Files: `tabs/market-desk/NewsTicker.tsx`, `tabs/market-desk/news-ticker-data.ts` (new); `MarketDesk.tsx` (mount), `intel-data.ts`
(optional refetch interval; the limit constants are now exported), `events-data.ts` (the board's `universe` flags), `EventsTab.tsx` (`?ev_open=&ev_uni=`),
`desk-nav.ts` (VIEW_PARAMS). Spec `e2e/tests/copilot-app-desk-news-ticker.spec.ts`; three neighbouring assertions were adjusted
(below).

Revised from the 5 Nov build, which listed every filing (149 items, ~16 min per pass on real data) with caps, a Show switch
and a coverage line. Per the owner, those are replaced by this summary: 9 items, ~117 s per pass on today's real data. The
counts are now complete without raising any row limit. The 5 Nov report was removed from the branch; this one replaces it.

## Test Cases
`test_reports/intel_news_ticker_TESTCASES.md` (design, NT-1…22, NT-R, NT-B, D-1…5).

| ID | Scenario | Result |
|----|----------|--------|
| NT-1 | band above the list, intel only, MARKET UPDATE | PASS |
| NT-2 | item order; counts read `days=1&sort=latest&limit=1` | PASS |
| NT-3 | results count, order, YoY, losses in words | PASS |
| NT-4/5 | filed / due / tomorrow counts, 12 names + "+6 more" | PASS |
| NT-6/7/8 | orders 27 + 6 names + "+21 more"; M&A names a company once, "+59 more"; corporate actions counts | PASS |
| NT-9 | counts read fails → names counted, note says so | PASS |
| NT-10–13 | deals (both sides of a deal = one name), flows, SEBI window, sectors | PASS |
| NT-14 | one `universe=all` board read; switch filters | PASS |
| NT-15/16 | clicks: event, chip, count, deal, flows, results panel, link consumed | PASS |
| NT-17 | pause / hover / focus, `aria-hidden` copy, spoken names | PASS |
| NT-18 | partial, all failed, nothing new, loading | PASS |
| NT-19 | no advice words | PASS |
| NT-20 | re-read every minute (orders and counts) | PASS |
| NT-21 | reduced motion | PASS |
| NT-22 | phone 390 px, sheet in the right list, "Back to F&O" | PASS |
| NT-R | 8 neighbouring specs | PASS |
| NT-B | tsc + vite build | PASS |
| D-1…5 | data checks below | PASS |

## API / Endpoint Tests (staging)
No backend route or service changed. The routes the band reads were called read-only through the staging backend's own
handlers (`nivesh-staging-app-backend`, routers on a throwaway FastAPI app, session check replaced by a stub user, no cookie or
secret read), with exactly the frontend's queries, on 6 Nov 09:18 IST (scratchpad `ticker_capture2.py`):
```
board_all        HTTP 200   0.6s items=146 total=None
feed_orders      HTTP 200   1.0s items=40 total=68
feed_mna         HTTP 200   1.0s items=20 total=204
feed_dividend    HTTP 200   0.9s items=20 total=159
feed_buyback     HTTP 200   0.9s items=20 total=22
feed_management  HTTP 200   0.9s items=20 total=542
feed_capex       HTTP 200   1.0s items=20 total=107
feed_qip         HTTP 200   1.0s items=20 total=93
feed_rating      HTTP 200   0.9s items=20 total=55
counts_d1        HTTP 200   0.1s items=1 total=961
board_prev       HTTP 200   0.2s items=252 total=None
deals            HTTP 200   0.1s items=200 total=464
fii_dii          HTTP 200   0.1s items=None total=None
circulars        HTTP 200   0.0s items=0 total=None
sector_returns   HTTP 200   0.2s items=None total=None
facets days=1: {'earnings': 285, 'management': 78, 'dividend': 22, 'mna': 21, 'qip': 17, 'capex': 15, 'litigation': 14, 'rating': 10, 'orders': 9, 'buyback': 1} total 961
backend date.today 2026-11-06 ('UTC', 'UTC')
```

## UI / Playwright Tests
Production build (`VITE_BASE=/v5/ npx vite build` + `vite preview`), `npx playwright test --config pw.copilot-app.config.ts`,
container `mcr.microsoft.com/playwright:v1.47.0-jammy`, `--network none`.

Typecheck `npx tsc --noEmit -p tsconfig.json` → `TSC_EXIT=0`.

Final run: the Market Update spec (16), the real-data render (2, scratch, not committed) and the 8 specs that open Market
Intelligence or the Events calendar (market-desk, events, results-today, desk-market, shell, top10, audit-wave1, macro):
```
✓ built in 25.12s
  153 passed (1.9m)
EXIT=0
```
Real-data render (6 Nov 09:18 IST bodies, F&O, desktop and phone, no page errors):
```
desktop F&O: 9 items
  RESULTS 6 declared since Thu 5 Nov MOTHERSON Rev ▲26.9% YoY PAT ▲47.3% YoY · BHARTIARTL Rev ▲16.7% YoY PAT ▲57.7% YoY · UNOMINDA Rev ▲38.2% YoY PAT ▲45.1% YoY · BHARATFORG Rev ▲20.8% YoY PAT ▼6.8% YoY · TIINDIA Rev ▲32.7% YoY PAT ▲125.5% YoY · M&M …
  DUE TODAY 7 meetings today BOSCHLTD · COROMANDEL · DATAPATTNS · HINDALCO · JUBLFOOD · SIEMENS · VOLTAS
  RESULTS TOMORROW Sat 7 Nov · 2 meetings DIVISLAB · TATASTEEL
  ORDERS 9 since Thu 5 Nov ASHOKA · MANAKCOAT · KNRCON · JASH · LOKESHMACH · STLNETWORK +3 more ›
  M&A 21 since Thu 5 Nov SUNTECK · CPPLUS · EIEL · ASHOKLEY · DEEPAKFERT · IIFLCAPS +14 more ›
  CORPORATE ACTIONS 65 since Thu 5 Nov Dividend 22 · Buyback 1 · Capex 15 · Fundraise 17 · Rating 10
  DEALS 93 bulk / block deals on 5 Nov, the largest PIIND ₹216 cr · MONEYVIEW ₹59 cr · RBA ₹57 cr +88 more ›
  FII / DII 5 Nov, cash market, provisional FII net +₹14,975 cr DII net −₹10,445 cr
  SECTORS moved 1% or more on 5 Nov Nifty Auto ▲4.14% · Nifty Financial Services ▲3.99% · Nifty Realty ▲3.52% · Nifty Private Bank ▲3.44% +7 more ›
desktop one pass: 6995 px ≈ 117 s at 60 px/s
```
Earlier (5 Nov), the full `copilot-app-desk*` suite on this branch had only the 32 failures in
`copilot-app-desk-strategy-graphs.spec.ts`, which also fail on an origin/dev build (`payoff-svg` not found): pre-existing and
unrelated. The 6 Nov rework touches only the band's own files and one desk-market assertion, so the eight specs above that
share its page were re-run.

Neighbouring assertions adjusted (the band now shares their page; intent kept):
- `copilot-app-desk-market.spec.ts` §6 frame: All's filings request is the one without a category or family that asks for rows
  (the band's counts read is `limit=1`).
- `copilot-app-desk-results-today.spec.ts` TC-17: the board's own request excludes the band's two `universe=all` reads. TC-20b
  switches to Nifty 50 via `events-universe-n50` ("ALL NSE" by role also matched the band's switch, and the band already
  reads `universe=all`).

## Data Correctness (staging)
- **D-1 board vs SQL** (`nidp.event_calendar`, quarterly_results): 6 Nov 118 meetings, 7 Nov 28. Captured board: due today 118
  (all NSE), 7 Nov 28. 5 Nov 252 meetings = `board_prev` items 252. Declared with figures on 5 Nov: 66 (F&O 6:
  BHARATFORG, BHARTIARTL, M&M, MOTHERSON, TIINDIA, UNOMINDA), which is what the tape shows. **PASS**
- **D-2 YoY vs `nidp.nse_financials_quarterly`** (5 Nov check, consolidated 2026-09-30 vs 2025-09-30): APOLLOHOSP +20.8 % / +38.3 %,
  BIOCON +2.2 % / −32.5 %, ZYDUSLIFE +29.2 % / −26.3 %, equal to the board's filed and same-quarter-last-year figures the tape
  computes from. **PASS**
- **D-3 counts read vs SQL**, filings since 5 Nov 00:00 IST (DB timezone Asia/Kolkata):
  ```
   event_category | since_date_cast | since_ist_midnight | since_utc_midnight
   buyback        |               1 |                  1 |                  1
   capex          |              15 |                 15 |                 15
   dividend       |              22 |                 22 |                 22
   earnings       |             285 |                285 |                279
   mna            |              21 |                 21 |                 21
   orders         |               9 |                  9 |                  9
   qip            |              17 |                 17 |                 17
   rating         |              10 |                 10 |                 10
  ```
  These equal the route's facets. The route counts from 00:00 IST of its (UTC) server date minus N days, so from 00:00 to 05:30
  IST the count starts a day earlier; the count line then names its own start. **PASS**
- **D-4 deals** (`as_of_date = 2026-11-05`): bulk 93, block 0 = "93 bulk / block deals on 5 Nov". **PASS**
- **D-5 real render**, desktop + phone: as above, no page errors. **PASS**

## Not verified / open
- UNVERIFIED on the deployed staging app with a signed-in session: the frontend image is built after a merge to dev. After the
  merge, open /v5/app/trader/desk?tab=market&view=intel.
- Staging has zero SEBI circulars, and 0 of today's results were filed at 09:18, so the SEBI and "Results filed" items were
  exercised with mocks only.

## Inputs required from user
- none

## Verdict: PASS
