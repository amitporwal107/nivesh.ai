# Test cases — Market Intelligence "Market Update" ticker (authored up front 2026-11-05, revised 2026-11-06)

Owner asks:
- 5 Nov 2026 (with a screenshot of Market Desk › Market Intelligence): "have a bloomberg style news ticker where user can see
  latest quarterly results for today and waiting for tomorrow, fresh order books, M&A and all other important aspects."
- 6 Nov 2026, on the 20-filings-per-category limit: "we should [show] a summary of the everything, need not to display every
  thing — 'Market Update'."

## Design (API + UI, before implementation)

**Where:** Market Desk › Market Intelligence only, between the view head and the AI Event Intelligence panel
(`tabs/market-desk/MarketDesk.tsx`, intel case). No other view gets it.

**What:** a summary band labelled MARKET UPDATE. One item per kind: a count line and a few names. The full lists stay
below (the event list's chips and the Events calendar).

**Data: no new backend route.** The band composes existing reads, sharing their React Query caches where the keys match:

| Item | Source (existing route) | Rule |
|---|---|---|
| RESULTS | `GET /api/markets/events-calendar/expectations?from=today&to=tomorrow&universe=all`, plus the same route for the previous weekday | declared since the previous weekday, newest filing first, ≤ 8 names, each with Rev / PAT vs the same quarter last year |
| RESULTS FILED | same | today, figures not loaded yet |
| DUE TODAY | same | today's meetings not filed yet (≤ 12 names) |
| RESULTS TOMORROW | same | tomorrow's meetings (≤ 12 names, "+n more" → the results board) |
| ORDERS · M&A | count: `GET /api/filings/feed?days=N&sort=latest&limit=1` (`facets`, the whole window). Names: the Intel chips' reads | count since 00:00 IST of the previous weekday; the newest 6 distinct companies; "+n more" → the chip |
| CORPORATE ACTIONS | the same counts read | Dividend · Buyback · Capex · Fundraise · Rating counts, each → its chip |
| DEALS | `GET /api/markets/deals` | the latest deal day's count and its 3 largest (one name per company) |
| FII / DII | `GET /api/markets/fii-dii` | the latest session's net flows |
| SEBI | `GET /api/markets/circulars` | circulars issued in the window (≤ 2 titles) |
| SECTORS | `GET /api/markets/sector-returns` | last session's moves of 1 % or more (≤ 4) |

Rules:
- YoY % = filed ÷ same quarter last year − 1, only when last year's figure is positive. A filed loss against a profit reads
  "turned to a loss", a profit against a loss "from a loss". Never beat / miss.
- A board-meeting outcome or results filing from a company with results in the window is not named under M&A. The count is
  the classifier's own.
- Without the counts read, a kind counts the names read, with "+" when that read hit its row limit.
- Universe switch F&O (default) · Nifty 50 · All NSE filters the results items (one `universe=all` read).
- Re-read: filings and counts every 60 s; the board every 10 min (its existing interval).
- Wording: no buy / sell / target / stop loss / recommend / pick / suggest.

**Clicks:** a name opens its event in the list below (`?in_chip=&in_ev=`) or the company's results panel in the Events calendar
(`?ev_open=&ev_uni=`, new in `EventsTab.tsx`, consumed once; phone shows a "Back to F&O" note for other lists). "+n more"
opens the chip (`?in_chip=`, no event) or scrolls to the results board. Both new params join `VIEW_PARAMS`.

**UI:** a dark band with a fixed left label (MARKET UPDATE + the newest filing time), the tape (two copies on the existing
`mkt-marquee` loop, speed scaled to length, edge fade), and under it Pause, the universe switch and a one-line note. Hover and
keyboard focus pause it. With reduced motion: no animation, one copy, scrolls sideways. The second copy is `aria-hidden`
and its buttons have `tabIndex=-1`.

History: the 5 Nov build listed every filing (149 items, ~16 min per pass on real data), then added caps, a Show switch and a
coverage line. The 6 Nov owner instruction replaced all three with this summary.

## Test cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| NT-1 | placement | Market Intelligence vs other views | e2e | band above `desk-panel-intel`, intel only, label MARKET UPDATE |
| NT-2 | order, counts | default tape | e2e | results, filed, due, tomorrow, orders, mna, actions, deals, flows, sebi, sector; counts read `days=1&sort=latest&limit=1` |
| NT-3 | results | 4 declared (today + previous weekday) | e2e | "4 declared since Wed 4 Nov", newest first, `Rev ▲10.0% YoY`, `turned to a loss`, `from a loss`, `₹300 cr` |
| NT-4/5 | meetings | filed 1, due 2, tomorrow 18 | e2e | count lines; 12 names + "+6 more ›" |
| NT-6/7/8 | filings | counts 27 / 61 / actions; MNAA twice; OUTCO board outcome | e2e | "27 since Wed 4 Nov", 6 names, "+21 more"; M&A names MNAA once, "+59 more"; actions "Dividend 22 · …" |
| NT-9 | fallback | counts read fails | e2e | orders "10 since Wed 4 Nov", "+4 more"; no actions item; "Not loaded: filing counts." |
| NT-10–13 | market | 9 deals (both sides of DLB), flows, circulars, sectors | e2e | "9 bulk / block deals on 5 Nov", DLB once, "+5 more"; `−₹1,235 cr`; today's circular only; ▲2.10% / ▼1.40% |
| NT-14 | universe | F&O → Nifty 50 → All NSE | e2e | two `universe=all` reads only; the switch filters |
| NT-15 | clicks | order, "+ more", Capex count, deal, flows | e2e | `in_chip`/`in_ev` as designed; Intel detail shows the filing |
| NT-16 | clicks | results name, tomorrow name | e2e | Events panel for the company; params consumed |
| NT-17 | motion, a11y | pause, hover, focus; second copy; names | e2e | paused; `aria-hidden`, 0 tab stops; spoken names |
| NT-18 | states | partial, all failed, nothing new, loading | e2e | note + retry; error + retry; empty line; loading line |
| NT-19 | wording | all text in All NSE | e2e | no advice words |
| NT-20 | refresh | 61 s on a fake clock | e2e | orders and counts read again |
| NT-21 | reduced motion | `prefers-reduced-motion` | e2e | no animation, one copy, sideways scroll, no Pause |
| NT-22 | phone | 390 px | e2e | no sideways page scroll; results tap opens the sheet in the right list; "Back to F&O" |
| NT-R | regression | market-desk, events, results-today, desk-market, shell, top10, audit-wave1, macro | e2e | pass |
| NT-B | build | tsc, vite build | build | clean |
| D-1 | data | board counts | data | = nidp.event_calendar SQL |
| D-2 | data | YoY of 3 stocks | data | = nse_financials_quarterly SQL |
| D-3 | data | counts read vs SQL | data | facets = SQL since 00:00 IST |
| D-4 | data | deals count | data | = nidp.bulk_deals + block_deals for the day |
| D-5 | real render | captured staging bodies, desktop + phone | e2e | renders, no page errors |
