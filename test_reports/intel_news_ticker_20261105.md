# Functionality Verification Report — Market Intelligence news ticker

- **Branch:** feat/intel-news-ticker (from origin/dev ea951dcb)
- **Date:** 2026-11-05
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** production build of the branch (vite preview, Playwright 1.60, mocked routes) + real staging bodies captured
  read-only from the staging backend's own route handlers + nidp_staging SQL
- **Changed areas:** backend routes/services: **no** · frontend src: **yes**

## Summary
A Bloomberg-style ticker band on Market Desk › Market Intelligence, above the AI Event Intelligence list (owner ask 5 Nov 2026).
On the tape: declared quarterly results (today and the previous weekday) with revenue and PAT against the same quarter last
year; today's results filed but not yet loaded; today's meetings still due; tomorrow's results meetings; fresh orders; M&A,
buyback, dividend, capex, fundraise and rating filings; the largest deals of the latest deal day; FII / DII; SEBI circulars;
and sector moves of 1 % or more. Controls: Pause, a results universe switch (F&O · Nifty 50 · All NSE), and a Show switch
(Everything · Results · Orders · M&A · Corporate actions · Deals & flows) with counts. A click opens the item where it lives:
a filing, deal or flow in the event list below (`?in_chip=&in_ev=`), or a company's results panel in the Events calendar
(`?ev_open=&ev_uni=`, new and consumed once). There is no new route: the ticker composes existing reads and shares their caches.

Files: `tabs/market-desk/NewsTicker.tsx`, `tabs/market-desk/news-ticker-data.ts` (new); `MarketDesk.tsx` (mount), `intel-data.ts`
(optional refetch interval; the limit constants are now exported), `events-data.ts` (the board's `universe` flags), `EventsTab.tsx` (deep link),
`desk-nav.ts` (VIEW_PARAMS). Spec `e2e/tests/copilot-app-desk-news-ticker.spec.ts`. Three neighbouring spec assertions were
adjusted because the ticker now shares their page (details below).

Design changes made during the build because of real data:
1. **Previous weekday's results.** At 19:08 IST none of today's 189 filed results had figures loaded (the warehouse loads them
   from ~20:30 IST). The previous day had 88 with figures, so the tape also reads the previous weekday's board.
2. **Show switch + caps.** The real F&O tape held 149 items (~16 min a pass). "Everything" now shows the newest few of each kind
   (68 items, ~345 s); choosing a kind shows all of that kind.
3. **Coverage line.** The shared Intel reads return the newest 20 filings per category (40 for orders). On 5 Nov, M&A had 61
   filings in the window but its read reached back only to 4 Nov 20:25 IST. The ticker now says so under the band rather than
   implying completeness.

## Test Cases
Authored up front: `test_reports/intel_news_ticker_TESTCASES.md` (design, NT-1…24, D-1…4; NT-23/24 added after the real-data runs).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| NT-1 | placement | Market Intelligence vs the other four views | e2e | ticker above `desk-panel-intel`, only on intel | PASS |
| NT-2/3/4 | results | YoY figures, losses in words, filed-pending, previous day, order | e2e | `Rev ₹1,100 cr ▲10.0% YoY`, `turned to a loss`, `from a loss`, `4 Nov` | PASS |
| NT-5 | results | due today, tomorrow 18 companies | e2e | grouped; 15 symbols + `+3 more ›` | PASS |
| NT-6/7 | filings | 7 kinds, old row, management, board outcome | e2e | one tag each; the three left out; tag order | PASS |
| NT-8/9/10 | deals/flows/SEBI/sector | latest day top 6, FII −1,234.5, old circular, 0.3 % move | e2e | `disposed of`/`acquired`, `−₹1,235 cr`, today's circular, 2 sector moves | PASS |
| NT-11 | universe | F&O → Nifty 50 → All NSE | e2e | two `universe=all` reads, the switch filters, no new read | PASS |
| NT-12/13 | click | order, deal, FII/DII | e2e | `in_chip`/`in_ev` set; Intel detail shows the filing | PASS |
| NT-14 | click | results item, tomorrow symbol | e2e | Events panel opens for the company; params consumed | PASS |
| NT-15/16 | motion, a11y | pause, hover, focus; second copy | e2e | paused; `aria-hidden`, 0 tab stops; named buttons | PASS |
| NT-15b | reduced motion | `prefers-reduced-motion` | e2e | no animation, one copy, scrolls sideways, no Pause | PASS |
| NT-17 | states | partial, all failed, empty, loading | e2e | note + retry; error + retry; empty line; loading line | PASS |
| NT-18 | phone | 390 px | e2e | no sideways scroll; results tap opens the sheet; "Back to F&O" | PASS |
| NT-19 | wording | all ticker text in All NSE | e2e | no buy/sell/target/stop loss/recommend/pick/suggest/beat/miss | PASS |
| NT-20 | refresh | 61 s on a fake clock | e2e | another orders read | PASS |
| NT-23 | Show | 10 orders; Orders; Deals & flows | e2e | 8 on Everything, 10 on Orders, counts `Orders10 M&A1 Results25` | PASS |
| NT-24 | coverage | M&A read at its 20-row limit | e2e | `M&A from 5 Nov, 09:00 IST`; no line under the limits | PASS |
| NT-21 | regression | market-desk, desk-events, results-today, desk-market, desk-shell | e2e | pass (3 assertions adjusted, below) | PASS |
| NT-21b | regression | every `copilot-app-desk*` spec | e2e | only failures are pre-existing on dev | PASS (32 strategy-graphs failures also fail on origin/dev) |
| NT-22 | build | tsc, vite build | build | clean | PASS |
| D-1 | data | board counts | data | = nidp.event_calendar SQL | PASS |
| D-2 | data | YoY of 3 stocks | data | = nse_financials_quarterly SQL | PASS |
| D-3 | data | orders/M&A vs SQL | data | orders complete; truncated kinds said on screen | PASS |
| D-4 | real render | captured staging bodies, desktop + phone | e2e | renders, no page errors | PASS |

## API / Endpoint Tests (staging)
No backend route or service changed. The routes the ticker reads were called read-only through the staging backend's own
handlers (`nivesh-staging-app-backend`, routers on a throwaway FastAPI app, session check replaced by a stub user, no cookie or
secret read), with exactly the frontend's queries (scratchpad `ticker_capture.py`):
```
board_all        HTTP 200   0.3s items=369 total=None
feed_orders      HTTP 200   1.0s items=40 total=77
feed_mna         HTTP 200   0.9s items=20 total=237
feed_dividend    HTTP 200   0.9s items=20 total=182
feed_buyback     HTTP 200   0.9s items=20 total=28
feed_management  HTTP 200   0.9s items=20 total=565
feed_capex       HTTP 200   0.9s items=20 total=128
feed_qip         HTTP 200   0.9s items=20 total=105
feed_rating      HTTP 200   1.0s items=20 total=62
deals            HTTP 200   0.1s items=200 total=371
fii_dii          HTTP 200   0.1s items=None total=None
circulars        HTTP 200   0.0s items=0 total=None
sector_returns   HTTP 200   0.1s items=None total=None
board_prev       HTTP 200   0.2s items=214 total=None
```

## UI / Playwright Tests
Production build (`VITE_BASE=/v5/ npx vite build` + `vite preview`), `npx playwright test --config pw.copilot-app.config.ts`,
container `mcr.microsoft.com/playwright:v1.47.0-jammy`, `--network none`.

Typecheck: `npx tsc --noEmit -p tsconfig.json` → `TSC_EXIT=0`.

Final run (latest code): ticker spec + real-data render + five neighbouring specs:
```
✓ built in 24.62s
…
  104 passed (1.4m)
EXIT=0
```
Full desk suite (`copilot-app-desk` + real-data render, code before the coverage line was added):
```
  32 failed
  84 skipped
  803 passed (21.1m)
```
All 32 failures are in `copilot-app-desk-strategy-graphs.spec.ts` (`getByTestId('payoff-svg')` not found). The same spec on an
**origin/dev** build (dev's `src`, no ticker code) gives:
```
✓ built in 24.38s
  32 failed
```
They are pre-existing and unrelated.

Neighbouring assertions adjusted (the ticker now shares their page; intent kept):
- `copilot-app-desk-market.spec.ts` §6 frame: All's filings request is the one without a category or family, not necessarily `feed[0]`.
- `copilot-app-desk-results-today.spec.ts` TC-17: the board's own request excludes the ticker's two `universe=all` reads.
  TC-20b: switches to Nifty 50 via `events-universe-n50`. The old `getByRole('button', {name: 'ALL NSE'})` now also matched
  the ticker's switch, and `universe=all` is already read (and cached) by the ticker.

## Data Correctness (staging)
- **D-1** SQL (`nidp.event_calendar`, quarterly_results): 5 Nov 252 meetings (F&O 17, N50 4), 6 Nov 117 (F&O 7). The captured
  board: `2026-11-05 all 252 fno 17 n50 4` / `2026-11-06 all 117 fno 7 n50 1`, 369 events. **PASS**
- **D-2** Board figures vs `nidp.nse_financials_quarterly` (consolidated, 2026-09-30 vs 2025-09-30):
  APOLLOHOSP 7615/6303.5 → +20.8 %, PAT 660/477.2 → +38.3 %; BIOCON 4389/4295.5 → +2.2 %, 57/84.5 → −32.5 %;
  ZYDUSLIFE 7910/6123.2 → +29.2 %, 928/1258.6 → −26.3 %. The ticker over the captured board shows exactly these
  (`ZYDUSLIFE Q2 FY27 results Rev ₹7,910 cr ▲29.2% YoY PAT ₹928 cr ▼26.3% YoY 4 Nov`). **PASS**
- **D-3** SQL, 4 Nov 00:00 → 5 Nov 19:08 IST: orders 27 records (all NSE), mna 61, dividend 74, capex 36, qip 37, rating 22,
  buyback 6. Captured reads: orders 27 rows in the window → 26 after consolidating the same company + subject + day = the
  tape's 26 (complete). The M&A read's newest 20 reach back to 4 Nov 20:25. The tape shows 17, after the board-outcome rule
  drops 3 (12 board outcomes tagged mna in the window by SQL). The coverage line on real data:
  `M&A from 4 Nov, 20:25 IST · Dividend from 4 Nov, 21:16 IST · Capex from 4 Nov, 18:52 IST · Fundraise from 4 Nov, 19:46 IST · Rating from 4 Nov, 11:13 IST.` **PASS** (truncation is said on screen)
- **D-4** Real render, desktop + phone: 68 items on Everything (F&O), Show counts `Results30 | Orders26 | M&A17 | Corporate actions71 | Deals & flows11`,
  All NSE 77 items, one pass ≈ 345 s, no page errors. **PASS**

## Not verified / open
- UNVERIFIED on the deployed staging app with a signed-in session: the frontend image is built only after a merge to dev,
  and no session token was used. After the merge: open /v5/app/trader/desk?tab=market&view=intel and check the band.
- Staging has zero SEBI circulars, so the SEBI segment was exercised only with mocks.
- Owner decision: raising the per-category read limit (LIMIT_GROUPED 20) would make M&A / dividend / capex … complete back to
  the previous weekday, but it also changes the Intel list's own chips.

## Inputs required from user
- none

## Verdict: PASS
