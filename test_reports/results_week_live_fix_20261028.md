# Results This Week — fixes from the live check after #381/#384 (functionality report)

- **When:** 2026-10-28 01:05 IST · **Branch:** fix/results-week-live (from origin/dev 1d6546e8)
- **Found live on staging (28 Oct ~01:00 IST):** (1) the results file's "after" was empty after midnight — it read up to the
  calendar day (28 Oct, no data yet) instead of the latest loaded session; (2) the build hit the DaaS rate limit (HTTP 429), so
  the exchange-filings read failed and BAJAJ-AUTO's first reaction fell back to 28 Oct (labelled as a gap); (3) a cold results
  file took 9–13 s against the screen's default 15 s wait.

## Test cases
| TC | What | Result |
|---|---|---|
| TC-L1 | a 429 from DaaS is retried with back-off (1, 2, 4 s) and the answer returned | PASS |
| TC-L2 | after the retries a 429 is returned as before (the caller labels the gap) | PASS |
| TC-L3 | the results file reads up to the latest loaded session (prices) and the "after" uses the latest session with F&O rows | PASS (staging dry run) |
| TC-L4 | the screen waits up to 45 s for a results file | PASS (tsc; results specs) |

## Real output
```
pytest tests/test_results_stock.py tests/test_results_week.py tests/test_results_signal.py tests/test_desk_paper_safety.py
148 passed, 2 warnings in 8.99s
tsc: OK (no errors)
✓ built in 25.70s
2 skipped
17 passed (11.5s)
```
Staging dry run (read-only overlay, day 2026-10-28):
```
week 2026-10-28 in 9.8s; 429/exchange gaps: []  (only the standing "no news feed" note)
  MANKIND: first reaction 2026-10-26 | last track session 2026-10-27 | after: rollover 92.6 % vs its usual 93.6 % (normal) | 0.4s
  BAJAJ-AUTO: first reaction 2026-10-27 | last track session 2026-10-27 | after: rollover 79.8 % vs its usual 86.0 % (lower than usual) | 0.2s
```

## UNVERIFIED
- The deployed route after this merge (re-run the live checks).


## Addendum (01:13 IST): Results This Week moved to the top of the Watchlist page
The owner could not find the block: on Trade Desk › Watchlists it sat ~5,679 px down, under the AI scanner watchlist's plan cards
(live probe). It is now the first block of the Watchlist page (same page on the sidebar and on Trade Desk › Watchlists).
```
tsc: OK (no errors)
✓ built in 24.75s
2 skipped
78 passed (52.8s)
```

## Addendum (01:50 IST): left panel of watchlists; no overlapping text
Owner, 28 Oct: "the text is overlapping in the UI and distorted" and "a list of watchlists in the left panel; once a user clicks
the watchlist, its content is displayed in the rest of the screen".

Test cases (in `copilot-app-results-this-week.spec.ts`):
- TC-W15 at 1600 / 1440 / 1100 px: the block shows rows when it is ≥ 1080 px wide, cards when not; in rows, no cell's widest
  descendant ends past the next cell's left edge; no sideways page scroll.
- TC-W16 (1440): the panel lists every watchlist; a click shows that list alone, sets `?wl=` and `aria-current`; a link opens it.
- TC-W17 (390 phone): the panel is a row of chips; a chip switches the list; no sideways page scroll.
- Existing specs updated for the new URLs (`?wl=all`, `?wl=screens`) and the layout-agnostic date/reaction text.

Measured block width on the Watchlist page (temporary log, removed): 1100 px screen → 552 px (cards); 1440 → 892 px (cards);
1600 → 1052 px (cards). The page was capped at 1040 px, so the table could never show; it is now 1360 px, so screens ≈ 1700 px
and wider get rows. Screenshot at 1440 checked by eye: cards, no overlap.

Run (11 specs, Docker Playwright 1.47, build with VITE_BASE=/v5/):
```
tsc: OK (no errors)
✓ built in 24.37s
4 skipped
221 passed (2.8m)
```
The three new layout/panel tests:
```
✓  138 [copilot-app] › e2e/tests/copilot-app-results-this-week.spec.ts:679:5 › Results This Week — layout never overlaps › TC-W15 at 1600px: rows when the block is wide enough, cards when not; no cell runs into the next (1.1s)
✓  139 [copilot-app] › e2e/tests/copilot-app-results-this-week.spec.ts:679:5 › Results This Week — layout never overlaps › TC-W15 at 1440px: rows when the block is wide enough, cards when not; no cell runs into the next (1.1s)
✓  140 [copilot-app] › e2e/tests/copilot-app-results-this-week.spec.ts:679:5 › Results This Week — layout never overlaps › TC-W15 at 1100px: rows when the block is wide enough, cards when not; no cell runs into the next (1.1s)
✓  142 [copilot-app] › e2e/tests/copilot-app-results-this-week.spec.ts:736:3 › Watchlist page — left panel › TC-W17 phone: the panel is a row of chips; a chip switches the list; no sideways page scroll (1.1s)
✓  141 [copilot-app] › e2e/tests/copilot-app-results-this-week.spec.ts:713:3 › Watchlist page — left panel › TC-W16 the panel lists every watchlist; a click shows that list alone and puts it in the URL; a link opens it (2.6s)
```
The 4 skipped are the opt-in screenshot runs (`shots 1440`, `shots 390` in two specs).

## UNVERIFIED
- The deployed page after this merge (re-run the live checks on staging).

## Addendum (02:05 IST): management commentary before the results
Owner, 28 Oct: "management pre results commentary analysis if the results are not declared yet". The results file read
filing analyses from only 21 days before the meeting, so last quarter's call, presentations and business updates never showed.
Now analyses from up to 100 days before are kept when they are management's own material (call transcripts, presentations,
business updates); other older analyses are not. The coverage note counts them separately; links come from a 300-row
filings read, the filings count stays the 21-day window. Backend only (the page shows the note as sent).

Test cases (`backend/tests/test_results_stock.py`):
- older filings are kept only when they are management's own; one filing analysed twice counts once; order oldest first;
- filing links reach back 100 days, the count is the recent window only (DaaS mocked).
```
150 passed, 2 warnings in 8.97s      (test_results_stock, test_results_week, test_results_signal, test_desk_paper_safety)
```
Staging dry run (new code in a temporary copy inside the backend container, read-only, day 2026-10-28): 65 upcoming names
have older management analyses. Sample:
```
JSWENERGY (meeting 2026-10-28): 7 analysed management filings from 2026-07-20 on (General Updates ×6 …), links yes
RPGLIFE   (meeting 2026-10-29): 6 (Investor Presentation 2026-09-02, General Updates …), links yes
APARINDS  (meeting 2026-10-29): 4 (Investor Presentation 2026-07-24, General Updates …), links yes
DEEPAKNTR (meeting 2026-10-29): 3 (General Updates …), links yes
```
Known gap (not fixed here): earnings-call transcripts are never analysed. NSE files them under "Analysts/Institutional
Investor Meet/Con. Call Updates", which the analysis pipeline treats as routine; 237 of 412 upcoming names have a last-quarter
transcript in nidp.corporate_announcements (245 filings). Needs a guidance read per transcript (owner's call on cost).

## UNVERIFIED
- The deployed page after this merge (re-run the live checks on staging).

## Verdict: PASS
