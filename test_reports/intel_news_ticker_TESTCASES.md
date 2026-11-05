# Test cases — Market Intelligence news ticker (authored up front, 2026-11-05)

Owner ask (5 Nov 2026, with a screenshot of Market Desk › Market Intelligence): "In the market intelligence section have a
bloomberg style news ticker where user can see latest quarterly results for today and waiting for tomorrow, fresh order books,
M&A and all other important aspects."

## Design (API + UI, before implementation)

**Where:** Market Desk › Market Intelligence only, between the view head and the AI Event Intelligence panel
(`tabs/market-desk/MarketDesk.tsx`, intel case). No other view gets it.

**Data: no new backend route.** The ticker composes reads the view already makes, with the same React Query keys, so the
caches are shared with the Intel list and the Events calendar:

| Segment (tag) | Source (existing route) | Window / rule |
|---|---|---|
| RESULTS (declared, figures) | `GET /api/markets/events-calendar/expectations?from=today&to=tomorrow&universe=all`, plus the same route for the previous weekday alone | today's AND the previous weekday's meetings with loaded figures: Revenue and PAT filed, % vs the same quarter last year (both figures from the route). Added during implementation after real data showed 0 of today's 189 filed results had figures at 19:08 IST (figures load ~20:30), while 88 of the previous day's did |
| RESULTS FILED (figures pending) | same | today, `filed_state = pending`: filed time, "figures not loaded yet" |
| DUE TODAY | same | today, upcoming: one grouped item, each symbol clickable |
| RESULTS TOMORROW | same | tomorrow: one grouped item with the count, first 15 symbols, "+N more" |
| ORDER | `GET /api/filings/feed?category=orders` (Intel "Orders" chip query) | filings published from 00:00 IST of the previous weekday |
| M&A · DIVIDEND · BUYBACK | Intel "M&A & actions" chip queries (mna, dividend, buyback) | same window |
| CAPEX · FUNDRAISE (qip) · RATING | Intel "Announcements" chip queries (management is left out: appointments are noise in a ticker) | same window |
| BLOCK / BULK DEAL | `GET /api/markets/deals` (Bulk & block chip) | latest deal date only, 6 largest by value; existing wording "acquired / disposed of" |
| FII / DII | `GET /api/markets/fii-dii` | latest session; existing wording "net inflow / net outflow" |
| SEBI | `GET /api/markets/circulars` | issued in the window, at most 3 |
| SECTOR | `GET /api/markets/sector-returns` | last session, |1-day| ≥ 1 %, at most 4 |

Rules:
- A filing whose exchange subject is a board-meeting outcome / financial results, from a company with results today, is NOT
  listed under ORDER / M&A / CAPEX … (the classifier labels many results filings mna/capex; the RESULTS item covers them).
- YoY % = filed ÷ same quarter last year − 1, only when last year's figure is positive; a filed loss against a profit reads
  "turned to a loss", a profit against a loss "from a loss", no % otherwise. Never "beat", "miss", "above/below estimate".
- Universe switch F&O (default) · Nifty 50 · All NSE (the Events calendar's own three) applies to the results segments.
- Filings re-read every 60 s while the ticker is mounted; the board every 10 min (its existing interval).
- Wording: no buy / sell / target / stop loss / recommend / pick / suggest (owner 3 Nov compliance rule).

**Clicks:** a filing / deal / FII-DII / SEBI / sector item sets `?in_chip=<chip>&in_ev=<event id>` (IntelTab's existing deep
link) and scrolls to the Intel panel. A results item sets `?ev_open=<calendar event id>&ev_uni=<universe>`, which the Events
calendar (new, `EventsTab.tsx`) consumes once: right month, RESULTS type on, universe set, the stock's panel/sheet open; the
params are then removed. Both new params join `VIEW_PARAMS` (dropped on a view change).

**UI:** a dark band, mono type, a fixed left label ("MARKET WIRE" + latest filing time), the tape (two copies, the existing
`mkt-marquee` seamless loop; speed scales with length), right controls: Pause/Play and the universe switch. Hover and keyboard
focus pause it. `prefers-reduced-motion`: no animation, the tape scrolls sideways. The second copy is `aria-hidden` and its
buttons are `tabIndex=-1`. A one-line source note sits under the band.

## Test cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| NT-1 | placement | open Market Intelligence; open the other views | e2e | ticker visible above `desk-panel-intel` on intel only |
| NT-2 | results | declared row with figures (rev 1,100 vs 1,000; PAT 90 vs 100) | e2e | "Rev ₹1,100 cr ▲10.0% YoY", "PAT ₹90 cr ▼10.0% YoY", period label |
| NT-3 | results | PAT −5 vs 20; PAT 8 vs −3; last year missing | e2e | "turned to a loss"; "from a loss"; value only |
| NT-4 | results | filed, figures pending | e2e | "results filed 16:05 · figures not loaded yet" |
| NT-5 | results | due today (2) and tomorrow (18) | e2e | grouped items with counts and day label; 15 symbols + "+3 more" |
| NT-6 | filings | orders / mna / dividend / buyback / capex / qip / rating rows today, plus one 9 days old | e2e | one item each with tag, symbol, exchange subject, time; the old one absent; management absent |
| NT-7 | filings | "Outcome of Board Meeting" (mna) from a company with results today | e2e | not listed under M&A |
| NT-8 | deals | 8 deals on the latest date + 1 older | e2e | 6 largest of the latest date, "acquired"/"disposed of" |
| NT-9 | flows | FII −1,234.5 / DII +2,000 | e2e | "FIIs net outflow … · DIIs net inflow …" |
| NT-10 | SEBI / sector | circular today, one 20 days old; sector moves 2.1 %, −1.4 %, 0.3 % | e2e | today's circular only; the two ≥ 1 % moves |
| NT-11 | universe | default, then Nifty 50, then All NSE | e2e | board requests carry universe=fno, n50, all |
| NT-12 | click | an ORDER item | e2e | URL in_chip=orders & in_ev=<id>; the Intel detail shows that filing |
| NT-13 | click | a deal, the FII/DII item | e2e | in_chip=deals / flows with the event id |
| NT-14 | click | a results item (desktop) | e2e | ev_open/ev_uni set, then consumed; Events panel for that stock opens |
| NT-15 | motion | Pause button; hover; reduced motion | e2e | aria-pressed, animation paused; reduced motion: no animation, scrollable |
| NT-16 | a11y | duplicate copy, labels | e2e | second copy aria-hidden, its buttons tabindex -1; band named |
| NT-17 | states | loading; one source 500; all 500; nothing in window | e2e | loading line; partial note + rest; error + retry; empty line |
| NT-18 | phone | 390 px | e2e | no horizontal page scroll; ticker and controls visible |
| NT-19 | wording | all ticker text | e2e | no buy/sell/target/stop loss/recommend/pick/suggest |
| NT-20 | refresh | 61 s pass with the ticker mounted | e2e | another /api/filings/feed request |
| NT-23 | Show switch | 10 orders in the window; Everything, then Orders, then Deals & flows (added after the real-data run: 149 items ≈ 16 min per pass) | e2e | Everything: the newest 8 orders; Orders: all 10, nothing else; counts on the switches (Orders 10, M&A 1, Results 25) |
| NT-24 | coverage | the M&A read returns its 20-row limit, all from today 09:00 (added after D-3: 61 real M&A filings in the window, the shared read's 20 reached back only to 4 Nov 20:25) | e2e | line under the band: "M&A from 5 Nov, 09:00 IST"; no line when every read is under its limit |
| NT-21 | regression | market-desk, desk-events, results-today, desk-market specs | e2e | same results as dev |
| NT-22 | build | tsc --noEmit, vite build | build | clean |
| D-1 | data | real staging board today/tomorrow (fno, all) | data | counts match nidp.event_calendar SQL |
| D-2 | data | 3 declared stocks' YoY | data | equals nse_financials_quarterly SQL |
| D-3 | data | today's orders / M&A filings | data | ticker set ⊆ SQL list for the window, rule NT-7 applied |
| D-4 | real render | ticker over real staging bodies (captured read-only) | e2e | renders, no page errors; screenshot |
