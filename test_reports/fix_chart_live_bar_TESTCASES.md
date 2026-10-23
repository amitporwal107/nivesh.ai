# Chart tab candles: Kite's session as the last bar: test cases

Ask (user, 2026-10-23): the desk charts still end at 22 Oct; live quotes should show in market hours and the latest snapshot after it.
Cause: the daily candles come from the adjusted series (prices_eod_adjusted), which is built later than the raw bars; the header already used Kite's quote, the candles did not.
Rule: Kite live while the feed is live; after the close its final snapshot only for a day NEWER than the adjusted series; once the series has the day, nothing is overlaid.

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-L1 | closed + final snapshot newer than the last bar: that session is the last candle; the footnote says "from Kite (the close), not yet in the adjusted series" and gives the adjusted session | e2e | data-day, text |
| TC-L2 | live: the forming bar is the last candle; footnote says live, still forming | e2e | data-day, text |
| TC-L3 | the series already has that day: no extra candle, footnote is the end-of-day one | e2e | absent |
| TC-L4 | existing header and chip live/close tests still pass (80 scanner/chart tests) | e2e | pass |
| TC-L5 | tsc exit 0 | tsc | exit 0 |
